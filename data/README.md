# Datos

## Versionado en el repositorio

| Archivo | Qué es |
|---|---|
| `raw/centroides_departamentos_ar.csv` | 527 departamentos con lat/lon y superficie. Llave del join con clima. |
| `raw/departamentos_objetivo.csv` | Los 319 departamentos con soja/maíz/trigo/girasol y ≥15 campañas, con coordenadas ya matcheadas. |
| `raw/oni.csv`, `raw/oni_mensual.csv` | Índice ENSO de NOAA (Anexo A). |
| `processed/dataset_soja_total.csv` | **El dataset final**: 6.156 × 179. Se versiona para que el notebook corra sin descargar nada. |

## No versionado (regenerable)

| Ruta | Peso | Cómo se regenera |
|---|---|---|
| `raw/estimaciones_agricolas.csv` | 12 MB | `python3 01_descargar_magyp.py` |
| `raw/clima_power/` | 82 MB | `python3 02_descargar_clima.py` (~3 min) |
| `raw/clima_openmeteo_validacion/` | 5 MB | ver `descartados/README.md` |

O todo junto: `./run_all.sh`

## Fuentes

- **Estimaciones Agrícolas** — Ministerio de Agricultura, Ganadería y Pesca.
  https://datos.magyp.gob.ar/dataset/estimaciones-agricolas
  Actualización mensual durante la campaña, cierre anual.
- **NASA POWER** (MERRA-2, comunidad AG) — https://power.larc.nasa.gov/
  Clima diario, actualización diaria con unos días de rezago. Sin API key.
- **Oceanic Niño Index** — NOAA. https://psl.noaa.gov/data/correlation/oni.data
