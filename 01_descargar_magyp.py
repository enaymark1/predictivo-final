#!/usr/bin/env python3
"""
01_descargar_magyp.py
Descarga las Estimaciones Agrícolas del MAGyP (superficie sembrada/cosechada,
producción y rendimiento por cultivo, campaña, provincia y departamento).

Uso:
    python 01_descargar_magyp.py

Salida:
    data/raw/estimaciones_agricolas.csv
    data/raw/_recursos_encontrados.json   (para auditoría / trazabilidad)

Si la descarga automática falla (el portal a veces bloquea clientes no-browser),
el script imprime las URLs exactas para que las bajes a mano y las dejes en
data/raw/. El resto del pipeline funciona igual.
"""

import io
import json
import pathlib
import sys
import zipfile

import pandas as pd
import requests

CKAN = "https://datos.magyp.gob.ar/api/3/action/package_show"
DATASET_ID = "estimaciones-agricolas"

RAW = pathlib.Path("data/raw")
RAW.mkdir(parents=True, exist_ok=True)

# El portal responde 403 a clientes sin User-Agent de navegador.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def listar_recursos() -> list[dict]:
    """Consulta la API CKAN del portal y devuelve los recursos del dataset."""
    r = requests.get(CKAN, params={"id": DATASET_ID}, headers=HEADERS, timeout=60)
    r.raise_for_status()
    recursos = r.json()["result"]["resources"]
    (RAW / "_recursos_encontrados.json").write_text(
        json.dumps(recursos, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return recursos


def descargar(url: str) -> bytes:
    r = requests.get(url, headers=HEADERS, timeout=300)
    r.raise_for_status()
    return r.content


def leer_tabular(contenido: bytes, nombre: str) -> pd.DataFrame:
    """Lee CSV/XLSX/ZIP probando encodings y separadores habituales del portal."""
    n = nombre.lower()

    if n.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            interno = [x for x in z.namelist() if x.lower().endswith((".csv", ".xlsx", ".xls"))]
            if not interno:
                raise ValueError(f"El zip {nombre} no contiene CSV ni Excel")
            with z.open(interno[0]) as fh:
                return leer_tabular(fh.read(), interno[0])

    if n.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(contenido))

    for enc in ("utf-8", "latin-1", "cp1252"):
        for sep in (";", ",", "\t"):
            try:
                df = pd.read_csv(io.BytesIO(contenido), encoding=enc, sep=sep)
                if df.shape[1] > 3:          # heurística: se parseó bien
                    return df
            except Exception:
                continue
    raise ValueError(f"No pude parsear {nombre}")


def main() -> None:
    print("Consultando el catálogo del MAGyP...")
    try:
        recursos = listar_recursos()
    except Exception as e:
        print(f"\n[!] No pude consultar la API CKAN: {e}")
        print("    Bajá el archivo a mano desde:")
        print("    https://datos.magyp.gob.ar/dataset/estimaciones-agricolas")
        print("    y guardalo como data/raw/estimaciones_agricolas.csv")
        sys.exit(1)

    print(f"  {len(recursos)} recursos publicados:\n")
    for i, rec in enumerate(recursos):
        print(f"  [{i}] {rec.get('name')}  ({rec.get('format')})")
        print(f"      {rec.get('url')}")

    # Preferimos el recurso tabular más pesado: suele ser la serie completa.
    candidatos = [
        r for r in recursos
        if str(r.get("format", "")).upper() in {"CSV", "XLSX", "XLS", "ZIP"}
    ]
    if not candidatos:
        print("\n[!] No hay recursos tabulares. Revisá _recursos_encontrados.json")
        sys.exit(1)

    candidatos.sort(key=lambda r: r.get("size") or 0, reverse=True)

    for rec in candidatos:
        url, nombre = rec["url"], rec.get("name", "recurso")
        print(f"\nDescargando: {nombre}\n  {url}")
        try:
            contenido = descargar(url)
            df = leer_tabular(contenido, url)
        except Exception as e:
            print(f"  [!] Falló: {e}")
            continue

        destino = RAW / "estimaciones_agricolas.csv"
        df.to_csv(destino, index=False, encoding="utf-8")
        print(f"\n  OK  {df.shape[0]:,} filas x {df.shape[1]} columnas -> {destino}")
        print(f"  Columnas: {list(df.columns)}")
        return

    print("\n[!] Ningún recurso se pudo descargar automáticamente.")
    print("    Usá las URLs de arriba en el navegador y dejá el CSV en data/raw/")
    sys.exit(1)


if __name__ == "__main__":
    main()
