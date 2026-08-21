#!/usr/bin/env python3
"""
05_descargar_enso.py
Descarga el Oceanic Niño Index (ONI) de NOAA y lo deja listo para unir al panel.

Por qué hace falta:
  El caso de negocio pone la decisión ANTES de la siembra. En ese momento no se
  observó nada del verano, y el modelo con solo barbecho y siembra apenas le gana
  al promedio histórico (+1,4%). El ONI es el único predictor conocido que
  informa sobre el verano que viene y que ya está publicado en noviembre.

  La Niña seca la Pampa húmeda en verano: es una de las teleconexiones mejor
  documentadas de la climatología argentina. Las tres sequías del panel
  (2008/09, 2017/18, 2022/23) ocurrieron en años Niña.

Qué genera: data/raw/oni.csv con una fila por año calendario y el ONI de cada
mes, más las features derivadas que se conocen al 15 de diciembre.

Uso:  python 05_descargar_enso.py
"""

import io
import sys

import numpy as np
import pandas as pd
import requests

FUENTES = [
    ("psl", "https://psl.noaa.gov/data/correlation/oni.data"),
    ("cpc", "https://origin.cpc.ncep.noaa.gov/products/analysis_monitoring/"
            "ensostuff/detrend.nino34.ascii.txt"),
]
MESES = ["ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic"]


def bajar(url: str) -> str:
    r = requests.get(url, timeout=90, headers={"User-Agent": "ITBA-AP/1.0"})
    r.raise_for_status()
    return r.text


def parse_psl(txt: str) -> pd.DataFrame:
    """Formato PSL: primera línea 'anio_ini anio_fin', luego año + 12 valores."""
    lineas = [l for l in txt.splitlines() if l.strip()]
    a0, a1 = (int(x) for x in lineas[0].split()[:2])
    filas = []
    for l in lineas[1:]:
        p = l.split()
        if len(p) != 13:
            continue
        anio = int(p[0])
        if not (a0 <= anio <= a1):
            continue
        filas.append([anio] + [float(v) for v in p[1:]])
    df = pd.DataFrame(filas, columns=["anio"] + MESES)
    return df.replace([-99.9, -99.90, -999.0], np.nan)


def parse_cpc(txt: str) -> pd.DataFrame:
    """Formato CPC: YR MON TOTAL ClimAdjust ANOM (la anomalía es NINO3.4)."""
    df = pd.read_csv(io.StringIO(txt), sep=r"\s+")
    df.columns = [c.strip().upper() for c in df.columns]
    col = "ANOM" if "ANOM" in df.columns else df.columns[-1]
    df = df.rename(columns={"YR": "anio", "MON": "mes", col: "v"})
    # ONI = media móvil de 3 meses de la anomalía NINO3.4
    df = df.sort_values(["anio", "mes"]).reset_index(drop=True)
    df["oni"] = df["v"].rolling(3, center=True).mean().round(2)
    ancho = df.pivot(index="anio", columns="mes", values="oni")
    ancho.columns = [MESES[int(c) - 1] for c in ancho.columns]
    return ancho.reset_index()


def main() -> None:
    oni = None
    for nombre, url in FUENTES:
        try:
            print(f"Probando {nombre}: {url}")
            txt = bajar(url)
            oni = parse_psl(txt) if nombre == "psl" else parse_cpc(txt)
            if oni is not None and len(oni) > 50:
                print(f"  OK — {len(oni)} años, {oni.anio.min()}–{oni.anio.max()}")
                break
        except Exception as e:
            print(f"  falló: {type(e).__name__}: {str(e)[:120]}")
            oni = None

    if oni is None:
        print("\nNinguna fuente respondió. Bajá a mano el ONI desde")
        print("  https://psl.noaa.gov/data/correlation/oni.data")
        print("y guardalo como data/raw/oni_crudo.txt; después volvé a correr esto.")
        sys.exit(1)

    # --- Features conocidas al 15 de diciembre del año YYYY ---
    # La campaña YYYY/YYYY+1 se siembra en YYYY, así que en diciembre ya se
    # publicaron los ONI hasta noviembre de ese mismo año.
    f = pd.DataFrame({"anio": oni.anio})
    f["oni_sep"] = oni["sep"]
    f["oni_oct"] = oni["oct"]
    f["oni_nov"] = oni["nov"]
    f["oni_son"] = oni[["sep", "oct", "nov"]].mean(axis=1)      # trimestre SON
    f["oni_tendencia"] = oni["nov"] - oni["ago"]                 # se enfría o calienta
    f["oni_jja"] = oni[["jun", "jul", "ago"]].mean(axis=1)

    # Fase ENSO según el umbral estándar de ±0,5 °C sobre el trimestre SON
    f["enso_fase"] = pd.cut(f.oni_son, [-9, -0.5, 0.5, 9],
                            labels=["nina", "neutral", "nino"]).astype(str)
    f["es_nina"] = (f.enso_fase == "nina").astype(int)
    f["nina_intensidad"] = np.where(f.oni_son < -0.5, -f.oni_son, 0.0)

    # Estas dos solo se conocen más tarde: quedan marcadas para no usarlas en T1
    f["T2_oni_dic"] = oni["dic"]
    f["T2_oni_ene_sig"] = oni["ene"].shift(-1)

    oni.to_csv("data/raw/oni_mensual.csv", index=False)
    f.to_csv("data/raw/oni.csv", index=False)

    print(f"\n-> data/raw/oni.csv  ({len(f)} años, {f.shape[1]-1} features)")
    print("\nCampañas del panel y su fase ENSO en el trimestre SON:")
    v = f[(f.anio >= 1999) & (f.anio <= 2024)][["anio", "oni_son", "enso_fase"]]
    for r in v.itertuples():
        marca = "   <-- SEQUÍA" if r.anio in (2008, 2017, 2022) else ""
        print(f"  {r.anio}/{str(r.anio+1)[2:]}  ONI(SON)={r.oni_son:+.2f}  "
              f"{r.enso_fase:8s}{marca}")


if __name__ == "__main__":
    main()
