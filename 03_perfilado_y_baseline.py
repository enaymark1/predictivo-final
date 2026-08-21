#!/usr/bin/env python3
"""
03_perfilado_y_baseline.py
Perfilado del dataset de Estimaciones Agrícolas + feasibility check.

Responde tres preguntas antes de invertir en el modelo:
  1. ¿El dataset tiene la calidad y cobertura necesarias?
  2. ¿Cuánta varianza del rendimiento hay para explicar?
  3. ¿Qué RMSE alcanza un baseline honesto, y dónde falla?

Uso:
    python 03_perfilado_y_baseline.py --cultivo "soja total"
"""

import argparse

import numpy as np
import pandas as pd

RUTA = "data/raw/estimaciones_agricolas.csv"
CAMPANIAS_TEST = [2020, 2021, 2022, 2023, 2024]   # 2020/21 .. 2024/25
MIN_CAMPANIAS = 20                                # historia mínima por departamento
DESDE = 1990                                      # recorte de tecnología comparable


def rmse(a, b) -> float:
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def cargar(cultivo: str) -> pd.DataFrame:
    df = pd.read_csv(RUTA)
    s = df[df.cultivo == cultivo].copy()

    print(f"=== {cultivo.upper()} — crudo: {s.shape[0]:,} filas ===")

    # --- Consistencia interna: ¿rendimiento = producción / superficie cosechada? ---
    con_cosecha = s.superficie_cosechada_ha > 0
    calc = s.loc[con_cosecha, "produccion_tm"] * 1000 / s.loc[con_cosecha, "superficie_cosechada_ha"]
    err = (calc - s.loc[con_cosecha, "rendimiento_kgxha"]).abs()
    print(f"  rendimiento == producción/sup_cosechada  ->  error mediano {err.median():.2f} kg/ha")
    print("  => `produccion_tm` y `superficie_cosechada_ha` son el target disfrazado: NO son features.\n")

    # --- Calidad ---
    print("  Calidad:")
    print(f"    rendimiento = 0            {(s.rendimiento_kgxha == 0).sum():>5}   (pérdida total: es información real, no faltante)")
    print(f"    superficie cosechada = 0   {(s.superficie_cosechada_ha == 0).sum():>5}")
    print(f"    cosechada > sembrada       {(s.superficie_cosechada_ha > s.superficie_sembrada_ha).sum():>5}   (inconsistencias)")
    print(f"    duplicados campaña×depto   {s.duplicated(['campania', 'departamento_id']).sum():>5}")
    print(f"    rendimiento > 7000 kg/ha   {(s.rendimiento_kgxha > 7000).sum():>5}   (outliers)\n")

    # --- Filtros ---
    s = s[
        (s.superficie_sembrada_ha > 0)
        & (s.rendimiento_kgxha.between(1, 7000))
        & (s.anio >= DESDE)
    ]
    n = s.groupby("departamento_id").size()
    s = s[s.departamento_id.isin(n[n >= MIN_CAMPANIAS].index)]

    print(f"  Panel final: {s.shape[0]:,} filas | "
          f"{s.departamento_id.nunique()} departamentos | "
          f"{s.anio.nunique()} campañas ({s.anio.min()}/{s.anio.min()+1} a {s.anio.max()}/{s.anio.max()+1})\n")
    return s.sort_values("anio")


def descomponer_varianza(s: pd.DataFrame) -> None:
    """Cuánta varianza aporta el lugar, cuánta el año, cuánta la interacción."""
    y = s.rendimiento_kgxha
    gm = y.mean()
    ef_dep = s.groupby("departamento_id").rendimiento_kgxha.transform("mean") - gm
    ef_cam = s.groupby("anio").rendimiento_kgxha.transform("mean") - gm
    resid = y - gm - ef_dep - ef_cam
    tot = y.var()

    print("=== DESCOMPOSICIÓN DE VARIANZA ===")
    filas = [
        ("entre DEPARTAMENTOS (el lugar)", ef_dep.var(), "lo que captura el baseline"),
        ("entre CAMPAÑAS (el año)", ef_cam.var(), "clima regional, ENSO"),
        ("residual (depto × año)", resid.var(), "clima LOCAL de ese depto ese año"),
    ]
    for nombre, v, nota in filas:
        print(f"  {nombre:34s} {v/tot*100:5.1f}%   <- {nota}")
    print(f"  desvío total del rendimiento: {y.std():.0f} kg/ha")
    print(f"  => techo del baseline ~{filas[0][1]/tot*100:.0f}%. "
          f"El {100-filas[0][1]/tot*100:.0f}% restante es territorio del clima.\n")


def baselines(s: pd.DataFrame) -> None:
    tr = s[~s.anio.isin(CAMPANIAS_TEST)]
    te = s[s.anio.isin(CAMPANIAS_TEST)]
    print(f"=== BASELINES (split TEMPORAL: train {tr.anio.max()}/{tr.anio.max()+1} y anteriores) ===")
    print(f"    train {len(tr):,} filas | test {len(te):,} filas\n")

    # B1: media global
    p1 = np.full(len(te), tr.rendimiento_kgxha.mean())

    # B2: media histórica del departamento
    m = tr.groupby("departamento_id").rendimiento_kgxha.mean()
    p2 = te.departamento_id.map(m).fillna(tr.rendimiento_kgxha.mean()).values

    # B3: media del departamento + tendencia lineal propia
    coef = {
        d: np.polyfit(g.anio, g.rendimiento_kgxha, 1)
        for d, g in tr.groupby("departamento_id")
        if len(g) >= 8
    }
    b_glob, a_glob = np.polyfit(tr.anio, tr.rendimiento_kgxha, 1)
    p3 = np.array([
        np.clip(
            (lambda bb, aa: aa + bb * r.anio)(*coef.get(r.departamento_id, (b_glob, a_glob))),
            500, 6000,
        )
        for r in te.itertuples()
    ])

    resultados = {}
    for nombre, p in [
        ("B1  media global", p1),
        ("B2  media histórica del depto", p2),
        ("B3  depto + tendencia lineal", p3),
    ]:
        r = rmse(te.rendimiento_kgxha, p)
        resultados[nombre] = r
        print(f"  {nombre:32s} RMSE = {r:4.0f} kg/ha  ({r/te.rendimiento_kgxha.mean()*100:.1f}% del rendimiento medio)")

    mejor = min(resultados, key=resultados.get)
    print(f"\n  Baseline a vencer: {mejor.strip()} ({resultados[mejor]:.0f} kg/ha)\n")

    # Dónde falla el baseline: desagregado por campaña
    print("=== DÓNDE FALLA EL BASELINE (B2, por campaña de test) ===")
    te2 = te.copy()
    te2["pred"] = p2
    for a, g in te2.groupby("anio"):
        sesgo = g.pred.mean() - g.rendimiento_kgxha.mean()
        marca = "  <<< SEQUÍA" if sesgo > 800 else ""
        print(f"  {a}/{str(a+1)[2:]}   RMSE={rmse(g.rendimiento_kgxha, g.pred):5.0f}   "
              f"real={g.rendimiento_kgxha.mean():5.0f}   pred={g.pred.mean():5.0f}   "
              f"sesgo={sesgo:+5.0f}{marca}")
    print("\n  => El baseline no anticipa el año climático. Ese es exactamente")
    print("     el riesgo que la aseguradora necesita cubrir, y el hueco que")
    print("     las features climáticas tienen que llenar.\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cultivo", default="soja total")
    args = ap.parse_args()

    s = cargar(args.cultivo)
    descomponer_varianza(s)
    baselines(s)


if __name__ == "__main__":
    main()
