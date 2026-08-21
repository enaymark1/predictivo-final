#!/usr/bin/env python3
"""
02_descargar_clima.py
Clima diario histórico desde NASA POWER (comunidad AG, agroclimatología).

Por qué se cambió de fuente:
  Open-Meteo pondera cada llamada por volumen (~7 días de datos = 1 llamada).
  27 años por departamento cuestan ~1.400 llamadas contra una cuota gratuita
  de 5.000/hora: 3 o 4 departamentos por hora. Inviable para 319.

  NASA POWER sirve el mismo tipo de dato (reanálisis MERRA-2), sin API key y
  sin cuota por volumen. Es además el producto que la NASA publica pensado
  para uso agronómico, así que la elección se defiende sola en la presentación.

Diferencia a declarar en el trabajo: POWER tiene resolución ~0,5° x 0,625°
frente a los 0,25° de ERA5. Para agregados departamentales es suficiente, y
el script el notebook (validación cruzada, pendiente) lo verifica contra los departamentos que
ya se bajaron de Open-Meteo.

Uso:
    python 02_descargar_clima.py --test
    python 02_descargar_clima.py --workers 6
"""

import argparse
import pathlib
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests

API = "https://power.larc.nasa.gov/api/temporal/daily/point"

# Nombres POWER -> nombres que ya usa el resto del pipeline
PARAMS = {
    "PRECTOTCORR": "precipitation_sum",          # mm/día, corregida
    "T2M_MAX": "temperature_2m_max",             # °C
    "T2M_MIN": "temperature_2m_min",             # °C
    "T2M": "temperature_2m_mean",                # °C
    "ALLSKY_SFC_SW_DWN": "shortwave_radiation_sum",  # MJ/m²/día
    "RH2M": "humedad_relativa_media",            # %
    "WS2M": "viento_2m_medio",                   # m/s
}

FALTANTE = -999.0

CLIMA = pathlib.Path("data/raw/clima_power")
CLIMA.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_estado = {"hechos": 0, "fallidos": 0, "t0": 0.0, "abortar": False, "motivo": ""}
_local = threading.local()


def sesion() -> requests.Session:
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": "ITBA-AnalisisPredictivo/1.0", "Accept": "application/json"})
        _local.s = s
    return _local.s


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in s.upper()).strip("_")


def pedir(lat: float, lon: float, d0: int, d1: int) -> pd.DataFrame:
    params = {
        "parameters": ",".join(PARAMS),
        "community": "AG",
        "latitude": lat,
        "longitude": lon,
        "start": f"{d0}0101",
        "end": f"{d1}1231",
        "format": "JSON",
    }
    r = sesion().get(API, params=params, timeout=300)
    r.raise_for_status()
    bruto = r.json()["properties"]["parameter"]

    df = pd.DataFrame({destino: pd.Series(bruto[origen]) for origen, destino in PARAMS.items()})
    df.index.name = "fecha"
    df = df.reset_index()
    df["fecha"] = pd.to_datetime(df.fecha, format="%Y%m%d")
    # POWER marca los faltantes con -999
    for c in PARAMS.values():
        df[c] = df[c].replace(FALTANTE, np.nan)
    return df.sort_values("fecha").reset_index(drop=True)


def diagnostico(row, d0: int, d1: int) -> bool:
    print("=" * 68)
    print("DIAGNÓSTICO — NASA POWER, un pedido de prueba")
    print("=" * 68)
    print(f"  {row.provincia} / {row.departamento}  ({row.lat}, {row.lon})")
    print(f"  {d0} a {d1} | {len(PARAMS)} variables\n")
    t = time.time()
    try:
        df = pedir(row.lat, row.lon, d0, d1)
    except Exception as e:
        print(f"  FALLA en {time.time()-t:.1f}s -> {type(e).__name__}: {str(e)[:200]}")
        return False
    seg = time.time() - t
    print(f"  OK en {seg:.1f}s: {len(df):,} días x {df.shape[1]} columnas\n")
    print("  Faltantes por variable:")
    for c in PARAMS.values():
        print(f"    {c:28s} {df[c].isna().mean()*100:5.1f}%")
    print(f"\n  Rango de fechas: {df.fecha.min().date()} a {df.fecha.max().date()}")
    print(f"  Ejemplo (últimos 3 días):")
    print(df.tail(3).to_string(index=False))
    print(f"\n  Ritmo: {seg:.1f} s/departamento.")
    print("=" * 68 + "\n")
    return True


def bajar_uno(row, d0: int, d1: int, total: int):
    nombre = f"{row.provincia} / {row.departamento}"
    destino = CLIMA / f"{slug(row.provincia)}__{slug(row.departamento)}.parquet"
    if destino.exists():
        with _lock:
            _estado["hechos"] += 1
        return nombre, None
    if _estado["abortar"]:
        return nombre, "abortado"

    error = None
    for intento in range(4):
        try:
            df = pedir(row.lat, row.lon, d0, d1)
            df["provincia"] = row.provincia
            df["departamento"] = row.departamento
            df["departamento_id"] = row.departamento_id
            tmp = destino.with_suffix(".tmp")
            df.to_parquet(tmp, index=False)
            tmp.rename(destino)
            error = None
            break
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:70]}"
            time.sleep(8 * (intento + 1))

    with _lock:
        if error:
            _estado["fallidos"] += 1
        _estado["hechos"] += 1
        n, t = _estado["hechos"], time.time() - _estado["t0"]
        ritmo = n / max(t, 1e-9)
        if error:
            print(f"  [{n}/{total}] FALLO {nombre:38.38s} -> {error[:55]}")
        else:
            print(f"  [{n}/{total}] ok    {nombre:38.38s} "
                  f"{ritmo*60:5.1f}/min  faltan ~{(total-n)/max(ritmo,1e-9)/60:4.1f} min")
        if n >= 10 and _estado["fallidos"] == n:
            _estado["abortar"] = True
            _estado["motivo"] = "los primeros 10 pedidos fallaron"
    return nombre, error


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=1999)
    ap.add_argument("--hasta", type=int, default=2025)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--objetivo", default="data/raw/departamentos_objetivo.csv")
    ap.add_argument("--provincias", default=None)
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    obj = pd.read_csv(args.objetivo)
    if args.provincias:
        quiero = {p.strip().lower() for p in args.provincias.split(",")}
        obj = obj[obj.provincia.str.lower().isin(quiero)]

    if not diagnostico(obj.iloc[0], args.desde, args.hasta):
        print("El diagnóstico falló, no lanzo las descargas.")
        sys.exit(1)
    if args.test:
        print("Modo --test: no descargo nada más.")
        return

    ya = sum(1 for r in obj.itertuples()
             if (CLIMA / f"{slug(r.provincia)}__{slug(r.departamento)}.parquet").exists())
    print(f"{len(obj)} departamentos | {ya} en caché | {len(obj)-ya} a bajar")
    print(f"{args.workers} en paralelo\n")
    if len(obj) - ya == 0:
        print("Ya está todo.")
        return

    _estado["t0"] = time.time()
    errores = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut = [pool.submit(bajar_uno, r, args.desde, args.hasta, len(obj))
               for r in obj.itertuples()]
        for f in as_completed(fut):
            nombre, err = f.result()
            if err:
                errores.append((nombre, err))

    print(f"\nTerminó en {(time.time()-_estado['t0'])/60:.1f} min. "
          f"{len(obj)-len(errores)} listos, {len(errores)} con error.")
    if _estado["abortar"]:
        print(f"  CORTADO: {_estado['motivo']}")
    if errores:
        pd.DataFrame(errores, columns=["departamento", "error"]).to_csv(
            "data/raw/clima_power_fallidos.csv", index=False)
        print("  Detalle en data/raw/clima_power_fallidos.csv")


if __name__ == "__main__":
    main()
