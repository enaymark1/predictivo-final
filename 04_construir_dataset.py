#!/usr/bin/env python3
"""
04_construir_dataset.py
Convierte el clima diario en features por campaña y lo une con el rendimiento.

La idea central: el rendimiento no depende del clima "del año" sino de qué pasó
en cada etapa del cultivo. Treinta milímetros en barbecho no valen lo mismo que
treinta milímetros en llenado de grano. Por eso el clima diario se agrega en
ventanas fenológicas y no en promedios anuales.

Ventanas para soja en Argentina, campaña YYYY/YYYY+1:
    barbecho    jul-sep YYYY        recarga de agua en el perfil
    siembra     oct - 15 dic YYYY   implantación
    vegetativo  16 dic - 15 ene     crecimiento
    floracion   16 ene - 10 feb     R1-R2, definición de vainas
    llenado     11 feb - 20 mar     R3-R6, define el peso del grano
    cosecha     21 mar - 10 may     lluvia acá es problema, no beneficio

Genera, por ventana: lluvia acumulada, temperaturas, días de calor extremo,
días de helada, radiación, evapotranspiración (Hargreaves), balance hídrico y
racha seca máxima. Y para cada una, la anomalía contra la normal del propio
departamento.

IMPORTANTE — la normal climática se calcula SOLO con campañas <= 2018, es decir
sin tocar el período de test (2020/21 en adelante). Si se calculara sobre toda
la serie, las anomalías filtrarían información del futuro al entrenamiento.

Uso:
    python 04_construir_dataset.py --cultivo "soja total"
"""

import argparse
import pathlib
import unicodedata

import numpy as np
import pandas as pd

CLIMA = pathlib.Path("data/raw/clima_power")
SALIDA = pathlib.Path("data/processed")
SALIDA.mkdir(parents=True, exist_ok=True)

ULTIMO_ANIO_NORMAL = 2018        # la normal climática no mira más allá de esto

# (nombre, mes-día de inicio, mes-día de fin, año relativo al inicio de campaña)
VENTANAS = [
    ("barbecho",   (7, 1),  (9, 30),  0, 0),
    ("siembra",    (10, 1), (12, 15), 0, 0),
    ("vegetativo", (12, 16), (1, 15), 0, 1),
    ("floracion",  (1, 16), (2, 10),  1, 1),
    ("llenado",    (2, 11), (3, 20),  1, 1),
    ("cosecha",    (3, 21), (5, 10),  1, 1),
    ("ciclo",      (10, 1), (4, 30),  0, 1),
]

UMBRAL_CALOR = 32.0     # °C: por encima, estrés térmico en soja
UMBRAL_HELADA = 3.0     # °C: riesgo de daño por frío
UMBRAL_SECO = 1.0       # mm: día considerado seco


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return "".join(c if c.isalnum() else "_" for c in s.upper()).strip("_")


def et0_hargreaves(tmax, tmin, tmed, lat_grados, doy):
    """
    Evapotranspiración de referencia por Hargreaves-Samani (FAO-56, ec. 52).
    Necesita la radiación extraterrestre Ra, que depende solo de latitud y día
    del año, así que se calcula en vez de medirse.
    """
    lat = np.radians(lat_grados)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)              # distancia tierra-sol
    dec = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)          # declinación solar
    x = np.clip(-np.tan(lat) * np.tan(dec), -1, 1)
    ws = np.arccos(x)                                            # ángulo horario del ocaso
    ra = (24 * 60 / np.pi) * 0.0820 * dr * (
        ws * np.sin(lat) * np.sin(dec) + np.cos(lat) * np.cos(dec) * np.sin(ws)
    )                                                            # MJ/m²/día
    delta_t = np.maximum(tmax - tmin, 0)
    return 0.0023 * (tmed + 17.8) * np.sqrt(delta_t) * ra / 2.45   # mm/día


def racha_seca_max(lluvia: np.ndarray) -> int:
    """Días consecutivos sin lluvia útil. El indicador de sequía que más pesa."""
    mejor = actual = 0
    for v in lluvia:
        actual = actual + 1 if v < UMBRAL_SECO else 0
        mejor = max(mejor, actual)
    return mejor


def features_de_ventana(sub: pd.DataFrame, pre: str) -> dict:
    if sub.empty:
        return {}
    return {
        f"{pre}_pp_mm":        sub.precipitation_sum.sum(),
        f"{pre}_tmax_med":     sub.temperature_2m_max.mean(),
        f"{pre}_tmin_med":     sub.temperature_2m_min.mean(),
        f"{pre}_tmed":         sub.temperature_2m_mean.mean(),
        f"{pre}_dias_calor":   int((sub.temperature_2m_max > UMBRAL_CALOR).sum()),
        f"{pre}_dias_helada":  int((sub.temperature_2m_min < UMBRAL_HELADA).sum()),
        f"{pre}_rad_med":      sub.shortwave_radiation_sum.mean(),
        f"{pre}_et0_mm":       sub.et0.sum(),
        f"{pre}_balance_mm":   sub.precipitation_sum.sum() - sub.et0.sum(),
        f"{pre}_racha_seca":   racha_seca_max(sub.precipitation_sum.values),
        f"{pre}_hr_med":       sub.humedad_relativa_media.mean(),
        f"{pre}_viento_med":   sub.viento_2m_medio.mean(),
    }


def clima_por_campania(df: pd.DataFrame, lat: float) -> pd.DataFrame:
    """De ~9.900 días a una fila por campaña."""
    df = df.copy()
    df["et0"] = et0_hargreaves(
        df.temperature_2m_max, df.temperature_2m_min, df.temperature_2m_mean,
        lat, df.fecha.dt.dayofyear,
    )
    df = df.set_index("fecha").sort_index()

    filas = []
    for anio in range(df.index.year.min(), df.index.year.max()):
        fila = {"anio": anio}
        completa = True
        for nombre, (m0, d0), (m1, d1), off0, off1 in VENTANAS:
            ini = pd.Timestamp(anio + off0, m0, d0)
            fin = pd.Timestamp(anio + off1, m1, d1)
            sub = df.loc[ini:fin]
            f = features_de_ventana(sub, nombre)
            if not f:
                completa = False
                break
            fila.update(f)
        if completa:
            filas.append(fila)
    return pd.DataFrame(filas)


def agregar_anomalias(clima: pd.DataFrame) -> pd.DataFrame:
    """
    Anomalía = valor - normal del departamento, en desvíos propios.
    La normal usa solo campañas <= ULTIMO_ANIO_NORMAL para no filtrar el futuro.
    """
    cols = [c for c in clima.columns if c not in ("anio", "departamento_id")]
    base = clima[clima.anio <= ULTIMO_ANIO_NORMAL]
    med = base.groupby("departamento_id")[cols].mean()
    sd = base.groupby("departamento_id")[cols].std()

    idx = clima.departamento_id
    med_al, sd_al = med.loc[idx, cols].values, sd.loc[idx, cols].values

    # Desvío cero = la variable es constante en ese departamento (típico de
    # días_helada en el norte). La anomalía correcta ahí es 0, no NaN.
    constante = (sd_al == 0) | ~np.isfinite(sd_al)
    with np.errstate(invalid="ignore", divide="ignore"):
        anom = (clima[cols].values - med_al) / np.where(constante, 1.0, sd_al)
    anom = np.where(constante, 0.0, anom)

    anom = pd.DataFrame(anom, columns=[f"anom_{c}" for c in cols], index=clima.index)
    n_const = int(constante.all(axis=0).sum())
    if n_const:
        print(f"  ({n_const} columnas constantes en algún departamento -> anomalía 0)")
    return pd.concat([clima, anom], axis=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cultivo", default="soja total")
    ap.add_argument("--min-campanias", type=int, default=15)
    args = ap.parse_args()

    obj = pd.read_csv("data/raw/departamentos_objetivo.csv")
    print(f"Agregando clima de {len(obj)} departamentos en ventanas fenológicas...")

    piezas = []
    for i, r in enumerate(obj.itertuples(), 1):
        f = CLIMA / f"{slug(r.provincia)}__{slug(r.departamento)}.parquet"
        if not f.exists():
            continue
        c = clima_por_campania(pd.read_parquet(f), r.lat)
        c["departamento_id"] = r.departamento_id
        piezas.append(c)
        if i % 50 == 0:
            print(f"  {i}/{len(obj)}")

    clima = pd.concat(piezas, ignore_index=True)
    print(f"  clima agregado: {clima.shape[0]:,} filas (depto x campaña) "
          f"x {clima.shape[1]} columnas")

    clima = agregar_anomalias(clima)
    print(f"  con anomalías:  {clima.shape[1]} columnas "
          f"(normal calculada con campañas <= {ULTIMO_ANIO_NORMAL})")

    # --- Rendimiento ---
    est = pd.read_csv("data/raw/estimaciones_agricolas.csv")
    s = est[est.cultivo == args.cultivo].copy()
    s = s[(s.superficie_sembrada_ha > 0) & (s.rendimiento_kgxha.between(1, 7000))]
    s = s.dropna(subset=["departamento_id"])
    s["departamento_id"] = s.departamento_id.astype(int)

    # produccion_tm y superficie_cosechada_ha definen el target: se excluyen.
    s = s[["anio", "campania", "provincia", "departamento", "departamento_id",
           "superficie_sembrada_ha", "rendimiento_kgxha"]]

    df = s.merge(clima, on=["departamento_id", "anio"], how="inner")
    n = df.groupby("departamento_id").size()
    df = df[df.departamento_id.isin(n[n >= args.min_campanias].index)]

    # Features estructurales conocidas antes de la campaña
    df = df.merge(obj[["departamento_id", "lat", "lon", "area_km2"]],
                  on="departamento_id", how="left")
    df["sup_sembrada_log"] = np.log1p(df.superficie_sembrada_ha)

    df = df.sort_values(["anio", "departamento_id"]).reset_index(drop=True)
    destino = SALIDA / f"dataset_{slug(args.cultivo).lower()}.csv"
    df.to_csv(destino, index=False)

    print(f"\n=== DATASET FINAL ===")
    print(f"  {df.shape[0]:,} observaciones x {df.shape[1]} columnas")
    print(f"  {df.departamento_id.nunique()} departamentos | "
          f"{df.anio.nunique()} campañas ({df.anio.min()}/{df.anio.min()+1} a "
          f"{df.anio.max()}/{df.anio.max()+1})")
    print(f"  rendimiento medio {df.rendimiento_kgxha.mean():.0f} kg/ha "
          f"(sd {df.rendimiento_kgxha.std():.0f})")
    print(f"  faltantes: {df.isna().mean().max()*100:.1f}% en la peor columna")
    print(f"  -> {destino}")


if __name__ == "__main__":
    main()
