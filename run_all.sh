#!/usr/bin/env bash
# Reconstruye el dataset de punta a punta desde las fuentes públicas.
# Tiempo total aproximado: 6 minutos.
set -e
pip install -r requirements.txt
python3 01_descargar_magyp.py        # estimaciones agrícolas -> data/raw/
python3 02_descargar_clima.py        # NASA POWER, 319 deptos -> data/raw/clima_power/
python3 05_descargar_enso.py         # índice ENSO (solo para el anexo A)
python3 04_construir_dataset.py      # ventanas fenológicas + join -> data/processed/
echo "Listo. Abrí notebooks/01_eda_soja.ipynb"
