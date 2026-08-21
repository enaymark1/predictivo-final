#!/usr/bin/env python3
"""
00_test_api.py
Diagnóstico escalonado de Open-Meteo: pide payloads cada vez más grandes
hasta que algo se rompe. Dónde se rompe dice cuál es el problema.

  - Falla YA en el pedido mínimo   -> tu IP está bloqueada temporalmente.
  - Funciona chico y falla grande  -> es el tamaño de la respuesta.
  - Funciona todo                  -> el bloqueo ya se levantó, seguí.

Uso:  python 00_test_api.py
"""

import time

import requests

API = "https://archive-api.open-meteo.com/v1/archive"
LAT, LON = -35.5541, -60.2823          # 25 de Mayo, Buenos Aires

TODAS = [
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
    "temperature_2m_mean",
    "et0_fao_evapotranspiration",
    "shortwave_radiation_sum",
]

# (etiqueta, desde, hasta, variables)
PRUEBAS = [
    ("mínimo:  1 día,  1 variable",  "2024-01-01", "2024-01-02", TODAS[:1]),
    ("chico:   1 año,  1 variable",  "2024-01-01", "2024-12-31", TODAS[:1]),
    ("medio:   1 año,  6 variables", "2024-01-01", "2024-12-31", TODAS),
    ("grande:  5 años, 6 variables", "2020-01-01", "2024-12-31", TODAS),
    ("enorme: 27 años, 6 variables", "1999-01-01", "2025-12-31", TODAS),
]

# Un User-Agent de navegador: algunos CDN cortan el default de requests.
SESION = requests.Session()
SESION.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})


def probar(etiqueta, desde, hasta, variables) -> bool:
    params = {
        "latitude": LAT,
        "longitude": LON,
        "start_date": desde,
        "end_date": hasta,
        "daily": ",".join(variables),
        "timezone": "America/Argentina/Buenos_Aires",
    }
    print(f"  {etiqueta:32s} ", end="", flush=True)
    t = time.time()
    try:
        r = SESION.get(API, params=params, timeout=180)
        seg = time.time() - t
        if r.status_code != 200:
            razon = ""
            try:
                razon = r.json().get("reason", "")
            except Exception:
                razon = r.text[:120]
            print(f"HTTP {r.status_code} en {seg:5.1f}s  -> {razon}")
            return False
        kb = len(r.content) / 1024
        dias = len(r.json()["daily"]["time"])
        print(f"OK  {seg:5.1f}s  {kb:8.0f} KB  {dias:6,} días")
        return True
    except Exception as e:
        print(f"FALLA en {time.time()-t:5.1f}s  -> {type(e).__name__}: {e}")
        return False


def main() -> None:
    print("=" * 72)
    print("TEST ESCALONADO — Open-Meteo Archive")
    print("=" * 72 + "\n")

    resultados = []
    for p in PRUEBAS:
        resultados.append((p[0], probar(*p)))
        time.sleep(3)          # respiro entre pedidos

    print("\n" + "=" * 72)
    ok = [n for n, r in resultados if r]
    fail = [n for n, r in resultados if not r]

    if not ok:
        print("DIAGNÓSTICO: falla incluso el pedido mínimo.")
        print("  -> Open-Meteo te bloqueó la IP temporalmente (suele durar entre")
        print("     unos minutos y una hora). Esperá y volvé a correr este test.")
        print("  -> Si tenés cómo, probá desde otra red (datos del celular) para")
        print("     confirmar que es la IP y no tu conexión.")
    elif not fail:
        print("DIAGNÓSTICO: anda todo, incluso el pedido de 27 años.")
        print("  -> El bloqueo se levantó. Corré:")
        print("     python3 02_descargar_clima.py --workers 3")
    else:
        print(f"DIAGNÓSTICO: anda hasta '{ok[-1].split(':')[0]}' y se rompe en"
              f" '{fail[0].split(':')[0]}'.")
        print("  -> Es el tamaño de la respuesta, no un bloqueo.")
        print("  -> Corré la descarga partiendo el rango en tramos:")
        print("     python3 02_descargar_clima.py --workers 3 --tramos 5")
    print("=" * 72)


if __name__ == "__main__":
    main()
