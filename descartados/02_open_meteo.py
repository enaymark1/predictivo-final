#!/usr/bin/env python3
"""
02_descargar_clima.py
Clima diario histórico (Open-Meteo Archive / ERA5) por departamento agrícola.

Novedades respecto de la versión anterior:
  - User-Agent de navegador (algunos CDN cortan el default de requests).
  - Sesión HTTP reutilizada por hilo: menos handshakes, menos resets.
  - --tramos N parte el rango de años en N pedidos chicos y los concatena,
    para cuando el problema es el tamaño de la respuesta.
  - Backoff progresivo ante ConnectionReset, que es lo que aparece cuando
    te están limitando a nivel de conexión y no con un HTTP 429.

Uso:
    python 00_test_api.py                            # diagnosticar primero
    python 02_descargar_clima.py --workers 3
    python 02_descargar_clima.py --workers 3 --tramos 5
"""

import argparse
import pathlib
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests

API = "https://archive-api.open-meteo.com/v1/archive"

DIARIAS = [
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum",
]

CLIMA = pathlib.Path("data/raw/clima")
CLIMA.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_lock = threading.Lock()
_estado = {"hechos": 0, "fallidos": 0, "t0": 0.0, "abortar": False, "motivo": ""}
_local = threading.local()


def sesion() -> requests.Session:
    """Una sesión HTTP por hilo, reutilizada entre pedidos."""
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept": "application/json"})
        _local.s = s
    return _local.s


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in s.upper()).strip("_")


def razon_de(r: requests.Response) -> str:
    try:
        j = r.json()
        if isinstance(j, dict) and j.get("reason"):
            return str(j["reason"])
    except Exception:
        pass
    return (r.text or "")[:200]


def rangos(desde_anio: int, hasta_anio: int, tramos: int):
    """Parte [desde, hasta] en `tramos` sub-rangos de años."""
    anios = list(range(desde_anio, hasta_anio + 1))
    n = max(1, len(anios) // max(tramos, 1))
    for i in range(0, len(anios), n):
        bloque = anios[i:i + n]
        yield f"{bloque[0]}-01-01", f"{bloque[-1]}-12-31"


def pedir(lat, lon, desde, hasta) -> pd.DataFrame:
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": desde,
        "end_date": hasta,
        "daily": ",".join(DIARIAS),
        "timezone": "America/Argentina/Buenos_Aires",
    }
    r = sesion().get(API, params=params, timeout=180)
    if r.status_code == 429:
        raise RuntimeError(f"429 {razon_de(r)}")
    r.raise_for_status()
    return pd.DataFrame(r.json()["daily"]).rename(columns={"time": "fecha"})


def bajar_uno(row, d0: int, d1: int, tramos: int, total: int):
    nombre = f"{row.provincia} / {row.departamento}"
    destino = CLIMA / f"{slug(row.provincia)}__{slug(row.departamento)}.parquet"
    if destino.exists():
        with _lock:
            _estado["hechos"] += 1
        return nombre, None
    if _estado["abortar"]:
        return nombre, "abortado"

    error = None
    for intento in range(5):
        if _estado["abortar"]:
            return nombre, "abortado"
        try:
            partes = [pedir(row.lat, row.lon, a, b) for a, b in rangos(d0, d1, tramos)]
            df = pd.concat(partes, ignore_index=True).drop_duplicates("fecha")
            df["provincia"] = row.provincia
            df["departamento"] = row.departamento
            df["departamento_id"] = row.departamento_id
            tmp = destino.with_suffix(".tmp")
            df.to_parquet(tmp, index=False)
            tmp.rename(destino)
            error = None
            break

        except requests.exceptions.ConnectionError as e:
            # Reset de conexión: casi siempre limitación a nivel de red.
            error = f"ConnectionError: {str(e)[:80]}"
            time.sleep(20 * (intento + 1))
        except RuntimeError as e:                       # 429 con motivo
            error = str(e)
            if "daily" in error.lower():
                with _lock:
                    _estado["abortar"] = True
                    _estado["motivo"] = error
                return nombre, error
            time.sleep(25 * (intento + 1))
        except Exception as e:
            error = f"{type(e).__name__}: {str(e)[:80]}"
            time.sleep(6 * (intento + 1))

    with _lock:
        if error:
            _estado["fallidos"] += 1
        _estado["hechos"] += 1
        n, t = _estado["hechos"], time.time() - _estado["t0"]
        ritmo = n / max(t, 1e-9)
        if error:
            print(f"  [{n}/{total}] FALLO {nombre:38.38s} -> {error[:60]}")
        else:
            print(f"  [{n}/{total}] ok    {nombre:38.38s} "
                  f"{ritmo*60:5.1f}/min  faltan ~{(total-n)/max(ritmo,1e-9)/60:4.1f} min")
        # Si los primeros 10 fallan todos, no tiene sentido seguir.
        if n >= 10 and _estado["fallidos"] == n:
            _estado["abortar"] = True
            _estado["motivo"] = "los primeros 10 pedidos fallaron todos"
    return nombre, error


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=1999)
    ap.add_argument("--hasta", type=int, default=2025)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tramos", type=int, default=1,
                    help="partir el rango de años en N pedidos más chicos")
    ap.add_argument("--objetivo", default="data/raw/departamentos_objetivo.csv")
    ap.add_argument("--provincias", default=None)
    args = ap.parse_args()

    obj = pd.read_csv(args.objetivo)
    if args.provincias:
        quiero = {p.strip().lower() for p in args.provincias.split(",")}
        obj = obj[obj.provincia.str.lower().isin(quiero)]

    # Un pedido de prueba antes de lanzar el pool.
    print("Probando un pedido antes de empezar... ", end="", flush=True)
    try:
        r0 = obj.iloc[0]
        df0 = pd.concat([pedir(r0.lat, r0.lon, a, b)
                         for a, b in rangos(args.desde, args.hasta, args.tramos)])
        print(f"OK ({len(df0):,} días)\n")
    except Exception as e:
        print(f"FALLA\n  -> {type(e).__name__}: {str(e)[:160]}\n")
        print("  Corré primero:  python3 00_test_api.py")
        sys.exit(1)

    ya = sum(1 for r in obj.itertuples()
             if (CLIMA / f"{slug(r.provincia)}__{slug(r.departamento)}.parquet").exists())
    print(f"{len(obj)} departamentos | {ya} en caché | {len(obj)-ya} a bajar")
    print(f"{args.workers} en paralelo | rango partido en {args.tramos} tramo(s)\n")
    if len(obj) - ya == 0:
        print("Ya está todo.")
        return

    _estado["t0"] = time.time()
    errores = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        fut = [pool.submit(bajar_uno, r, args.desde, args.hasta, args.tramos, len(obj))
               for r in obj.itertuples()]
        for f in as_completed(fut):
            nombre, err = f.result()
            if err:
                errores.append((nombre, err))

    print(f"\nTerminó en {(time.time()-_estado['t0'])/60:.1f} min. "
          f"{len(obj)-len(errores)} listos, {len(errores)} con error.")
    if _estado["abortar"]:
        print(f"  CORTADO: {_estado['motivo']}")
        print("  Esperá un rato y volvé a correrlo: retoma donde quedó.")
    if errores:
        pd.DataFrame(errores, columns=["departamento", "error"]).to_csv(
            "data/raw/clima_fallidos.csv", index=False)
        print("  Detalle en data/raw/clima_fallidos.csv")


if __name__ == "__main__":
    main()
