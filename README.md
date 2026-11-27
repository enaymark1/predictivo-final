# Predicción de rendimiento de soja por departamento

**Examen Final — Análisis Predictivo (82.05) · ITBA**

Modelo que predice, **al 10 de febrero**, el rendimiento de soja (kg/ha) de cada
departamento argentino, para que una **aseguradora agrícola con seguro indexado por
rendimiento zonal** pueda constituir reservas dos meses antes de la cosecha.

---

## Resultados

**Modelo final:** promedio simple de **ElasticNet + CatBoost**, que predicen el desvío
del rendimiento **en % del nivel esperado** del departamento (su promedio histórico +
tendencia), usando solo el clima disponible al 10 de febrero.

| RMSE (kg/ha) | Baseline: media del depto | Modelo final | Mejora |
|---|---|---|---|
| Validación expansiva 2010–2019 | 651 | 511 | 21,5 % |
| **Test 2020/21 – 2024/25** | **665** | **541** | **18,6 %** |
| Test, sequía 2022/23 | 1.012 | 637 | 37 % |

- **Generaliza:** el error en test (541) es cercano al de validación (511).
- **En la sequía 2022/23** anticipa cerca de la mitad de la caída del rinde, pero
  **sobreestima** (sesgo +372 kg/ha): la sequía se agravó en el llenado de granos,
  después del 10/02, y eso el modelo no lo puede ver por diseño.
- **No gana todos los años:** empata con el baseline en 2021/22 y queda algo peor en 2024/25.
- **Uso recomendado:** herramienta de reservas al 10/02, con margen prudencial en años
  secos y actualización en marzo.

## Notebooks

| Notebook | Qué hace |
|---|---|
| [`01_eda_soja.ipynb`](notebooks/01_eda_soja.ipynb) | Caso de negocio, construcción del dataset y análisis exploratorio |
| [`02_seleccion_modelos.ipynb`](notebooks/02_seleccion_modelos.ipynb) | Compara baselines, targets, más de 20 familias de modelos, features, selección de variables, Optuna y ensambles con validación expansiva (~8 min) |
| [`03_entrenar_final.ipynb`](notebooks/03_entrenar_final.ipynb) | **Entrena y guarda** el modelo final con 1999/00–2019/20 en `models/modelo_final.joblib` |
| [`04_aplicar_test.ipynb`](notebooks/04_aplicar_test.ipynb) | **Aplica** el modelo guardado al test 2020/21–2024/25 (única vez que se toca) |

El código compartido (reglas anti-fuga, validación temporal y definición del modelo)
está en [`notebooks/comun.py`](notebooks/comun.py).

La presentación está en [`presentacion/presentacion_final.pdf`](presentacion/presentacion_final.pdf).

## Selección del modelo

Se eligió con **validación expansiva**: para cada campaña de 2010 a 2019 se entrena con
todas las anteriores y se valida en esa (10 folds, incluye la sequía 2017/18). El test
no se usó para elegir nada.

| Etapa | Resultado (RMSE de validación, kg/ha) |
|---|---|
| Baselines | promedio general 803 · campaña anterior 729 · **media del depto 651** · depto + tendencia 608 |
| Target | predecir el desvío **en %** del nivel esperado le gana a predecir el rinde crudo (519 vs 529, mismo Lasso) |
| Familias | lineales regularizados y boosting arriba (517–527 tras Optuna); KNN, SVR, red neuronal y lineal sin regularizar no compiten (568–619) |
| Features | las anomalías climáticas traen la señal; los rezagos del propio depto suman un poco |
| Ensamble | ElasticNet + CatBoost: **511**, el mejor RMSE y MAE, y menos error en sequía que el ElasticNet solo |

Métricas reportadas: RMSE (principal), MAE, sesgo, RMSE en sequía y mejora % sobre el baseline.

## El dataset

**6.156 observaciones · 255 departamentos · 26 campañas (1999/00 – 2024/25) · 14 provincias · sin faltantes**

Construido cruzando dos fuentes públicas, ambas regenerables por script:

| Fuente | Aporta | Actualización |
|---|---|---|
| Estimaciones Agrícolas (MAGyP) | superficie sembrada y rendimiento por departamento y campaña | mensual durante la campaña |
| NASA POWER (MERRA-2, comunidad AG) | clima diario en el centroide de 319 departamentos | diaria, con días de rezago |

El clima diario se agrega en **ventanas fenológicas** con 12 indicadores por ventana,
en valor absoluto y como anomalía contra la normal del propio departamento. La varianza
del rendimiento se reparte en 37 % departamento, 23 % campaña y 40 % interacción
departamento × campaña: el mismo año no afecta igual a todos los departamentos.

## Decisiones metodológicas

1. **Sin fuga del target.** `rendimiento = produccion × 1000 / superficie_cosechada`
   (coincidencia exacta en el 99,84 % de los casos): ambas columnas excluidas.
2. **Solo información disponible al 10 de febrero:** ventanas de barbecho, siembra,
   vegetativo y floración. Llenado, cosecha y ciclo completo quedan afuera (hay un `assert`).
3. **Normal climática calculada solo con campañas ≤ 2018.**
4. **Partición temporal:** train ≤ 2019/20, test 2020/21–2024/25, evaluado una sola vez.
5. **Todo lo que aprende de los datos** (promedio del depto, tendencia, escalado) se
   calcula dentro de cada fold, solo con el pasado.

## Reproducir

```bash
pip install -r requirements.txt
jupyter notebook notebooks/
```

El dataset final está versionado, así que **los notebooks corren sin descargar nada**.
Orden: `02` (opcional, reproduce la selección) → `03` (entrena y guarda) → `04` (aplica a test).

Para reconstruir el dataset desde las fuentes públicas (~6 min):

```bash
./run_all.sh
```

## Estructura

```
Final/
├── README.md
├── DISEÑO.md                     decisiones metodológicas y bitácora de cambios
├── run_all.sh                    reconstruye el dataset desde las fuentes
├── requirements.txt
│
├── 01_descargar_magyp.py         estimaciones agrícolas por depto y campaña
├── 02_descargar_clima.py         clima diario NASA POWER (319 deptos, paralelo)
├── 03_perfilado_y_baseline.py    perfilado y feasibility sobre MAGyP solo
├── 04_construir_dataset.py       ventanas fenológicas, anomalías y join
├── 05_descargar_enso.py          Oceanic Niño Index (anexo del EDA)
│
├── notebooks/
│   ├── 01_eda_soja.ipynb         caso de negocio, dataset y EDA
│   ├── 02_seleccion_modelos.ipynb
│   ├── 03_entrenar_final.ipynb   ← entrena y guarda el modelo final
│   ├── 04_aplicar_test.ipynb     ← aplica el modelo a test
│   └── comun.py                  código compartido por 02–04
├── models/                       modelo_final.joblib + ficha modelo_final.json
├── resultados/                   métricas, predicciones de test y rondas de validación
├── presentacion/                 presentación final (PDF y PPTX) y guion
├── data/                         ver data/README.md
└── descartados/                  Open-Meteo: por qué no funcionó
```
