# Predicción de rendimiento de soja por departamento

**Trabajo Práctico 1 — Análisis Predictivo (82.05) · ITBA**

Modelo de rendimiento de soja a nivel departamento×campaña, construido para
alimentar la **constitución de reservas de una aseguradora agrícola** que vende
cobertura por índice de rendimiento zonal.

📓 **El trabajo está en [`notebooks/01_eda_soja.ipynb`](notebooks/01_eda_soja.ipynb)** —
caso de negocio, construcción del dataset, análisis exploratorio y conclusiones.

---

## El dataset

**6.156 observaciones × 179 columnas · 255 departamentos · 26 campañas (1999/00 – 2024/25) · sin faltantes**

Construido cruzando dos fuentes públicas, ambas regenerables por script:

| Fuente | Aporta | Actualización |
|---|---|---|
| Estimaciones Agrícolas (MAGyP) | superficie sembrada y rendimiento por departamento y campaña | mensual durante la campaña |
| NASA POWER (MERRA-2, comunidad AG) | clima diario en el centroide de 319 departamentos | diaria, con días de rezago |

El clima diario no entra crudo: se agrega en **ventanas fenológicas** (barbecho,
siembra, vegetativo, floración, llenado, cosecha), con 12 indicadores por ventana
más su anomalía contra la normal del propio departamento.

## Resultados principales

| | |
|---|---|
| **Descomposición de varianza** | 37% departamento · 23% campaña · **40% interacción** (clima local) |
| **Baseline** (promedio histórico del depto) | RMSE 665 kg/ha |
| **Modelo al 10 de febrero** | RMSE 584 kg/ha — **12% mejor** |
| **En la sequía 2022/23** | de 1012 a 585 kg/ha — **42% mejor** |
| **En unidades del negocio** | la sobrestimación de producción cae de 15,0 a 6,8 Mt |

**El hallazgo que ordena el trabajo:** el modelo *no* sirve para tarifar antes de
la siembra (mejora 1,6%, ni el índice ENSO lo cambia — Anexo A). El valor aparece
recién con la floración. Es una herramienta de gestión de reservas, no de
tarifación.

## Reproducir

```bash
./run_all.sh          # ~6 min: descarga las fuentes y reconstruye el dataset
```

O paso a paso:

```bash
pip install -r requirements.txt
python3 01_descargar_magyp.py      # estimaciones agrícolas
python3 02_descargar_clima.py      # NASA POWER, 319 deptos (~3 min)
python3 05_descargar_enso.py       # índice ENSO (solo Anexo A)
python3 04_construir_dataset.py    # ventanas fenológicas + join
jupyter notebook notebooks/01_eda_soja.ipynb
```

El dataset final está versionado, así que **el notebook corre sin descargar nada**.

## Estructura

```
TP/
├── README.md
├── DISEÑO.md                     decisiones metodológicas y bitácora de cambios
├── run_all.sh                    pipeline completo
├── requirements.txt
│
├── 01_descargar_magyp.py         estimaciones agrícolas por depto y campaña
├── 02_descargar_clima.py         clima diario NASA POWER (319 deptos, paralelo)
├── 03_perfilado_y_baseline.py    perfilado y feasibility sobre MAGyP solo
├── 04_construir_dataset.py       ventanas fenológicas, anomalías y join
├── 05_descargar_enso.py          Oceanic Niño Index (Anexo A)
│
├── notebooks/
│   └── 01_eda_soja.ipynb         ← el trabajo
├── data/                         ver data/README.md
├── descartados/                  Open-Meteo: por qué no funcionó
└── entregables/                  presentación
```

## Decisiones metodológicas

1. **Leakage removido y demostrado.** `rendimiento = produccion × 1000 / superficie_cosechada`
   con coincidencia exacta en el 99,84% de los casos (sección 2.3 del notebook).
   Ambas columnas excluidas.
2. **Normal climática calculada solo con campañas ≤ 2018**, sin tocar el período
   de evaluación.
3. **Solo ventanas cerradas al 10 de febrero** entran al modelo de producción.
4. **Partición temporal**, nunca aleatoria: train ≤ 2019/20, test 2020/21–2024/25.
