# Diseño metodológico y bitácora de decisiones

Complementa al notebook: acá están las decisiones y **por qué** se tomaron,
incluidas las que se revirtieron.

---

## 1. Caso de negocio

Aseguradora agrícola con cobertura por **índice de rendimiento zonal**: el pago
se dispara si el rendimiento promedio del departamento cae bajo un umbral, sin
peritaje individual. Eso convierte al rendimiento departamental en el activo
subyacente del contrato.

**Decisión alimentada:** constitución de reservas y activación de reaseguro,
revisada mensualmente entre enero y marzo. **No** la tarifación — ver §5.

## 2. Unidad, respuesta y evaluación

| | |
|---|---|
| Unidad observacional | departamento × campaña |
| Variable respuesta | `rendimiento_kgxha` (regresión) |
| Momento de predicción | 10 de febrero de la campaña en curso |
| Métrica | RMSE en kg/ha |
| Partición | temporal: train ≤ 2019/20, test 2020/21–2024/25 |
| Baseline | promedio histórico del departamento |

**Por qué RMSE y no MAE:** penaliza cuadráticamente los errores grandes. Para una
aseguradora un error de 1.000 kg/ha en un departamento es peor que dos de 500 en
dos departamentos — la cola es donde está la insolvencia.

## 3. Lo que no puede ser feature

- `produccion_tm` y `superficie_cosechada_ha` — reconstruyen el target de forma
  exacta (99,84% de coincidencia bajo 1 kg/ha). Verificado, no supuesto.
- Cualquier ventana fenológica posterior al 10 de febrero: llenado y cosecha.
- La normal climática calculada sobre la serie completa: se calcula solo con
  campañas ≤ 2018 para no filtrar el futuro hacia el entrenamiento.

`superficie_sembrada_ha` **sí** se conserva: se declara al inicio de la campaña.

## 4. Enriquecimiento climático

El rendimiento no responde al clima "del año" sino a qué pasó en cada etapa del
cultivo. Por eso el clima diario se agrega en ventanas fenológicas:

| Ventana | Período (campaña YYYY/YYYY+1) | Rol |
|---|---|---|
| barbecho | jul – sep YYYY | recarga de agua en el perfil |
| siembra | oct – 15 dic YYYY | implantación |
| vegetativo | 16 dic – 15 ene | crecimiento |
| floración | 16 ene – 10 feb | R1–R2, define vainas |
| llenado | 11 feb – 20 mar | R3–R6, define peso del grano |
| cosecha | 21 mar – 10 may | acá la lluvia es problema |

12 indicadores por ventana (lluvia, temperaturas, días de calor >32 °C, días de
helada, radiación, ET0 por Hargreaves-Samani, balance hídrico, racha seca,
humedad, viento) más la anomalía de cada uno contra la normal del departamento.

---

## 5. Bitácora: qué cambió respecto del diseño inicial

Tres decisiones se revirtieron durante el trabajo. Se dejan asentadas porque las
tres son defendibles y dos aparecen en la presentación.

### 5.1 La fuente climática: de Open-Meteo a NASA POWER

**Diseño inicial:** Open-Meteo Archive (ERA5), 0,25° de resolución.

**Qué pasó:** Open-Meteo pondera las llamadas por volumen — una llamada ≈ 7 días
de datos. Los 27 años por departamento cuestan ~1.400 llamadas contra 5.000/hora
de cuota gratuita: 3 o 4 departamentos por hora. Inviable para 319.

**Resolución:** NASA POWER (MERRA-2, comunidad AG). Sin cuota por volumen, 3,3 s
por departamento, cero faltantes en las 7 variables. Contrapartida declarada:
resolución ~0,5° × 0,625°, más gruesa que ERA5.

Detalle en `descartados/README.md`.

### 5.2 El momento de predicción: de septiembre a febrero

**Diseño inicial:** predecir antes de la siembra, para que la aseguradora
tarifara con el modelo.

**Qué pasó:** medido honestamente, un modelo que solo usa barbecho y siembra
mejora **1,4%** sobre el promedio histórico. En la sequía 2022/23 baja de 1012 a
955 kg/ha: nada. Es coherente con la agronomía — en diciembre no ocurrió todavía
nada de lo que define el rendimiento.

**Resolución:** la corrida principal se fija al 10 de febrero, cuando cerró la
floración. Ahí la mejora es 12% general y 41% en sequía. El caso de negocio pasa
de tarifación a gestión de reservas.

### 5.3 El índice ENSO: hipótesis descartada

**Hipótesis:** si el problema es que en noviembre no hay información del verano,
el ENSO la aportaría — se publica antes de la siembra y las tres sequías del
panel fueron años Niña.

**Qué pasó:** la relación existe pero es débil (r = +0,43 entre ONI y efecto-año,
p = 0,029, ~18% explicado) y tiene contraejemplos que la destruyen: 2010/11 tuvo
la Niña más intensa del panel con rendimientos normales; 2016/17 fue Niña y
resultó el segundo mejor año. Con selección de modelo honesta (validación
2015-19, test tocado una vez) **ENSO no queda seleccionado**. Reformularlo como
clasificación tampoco funciona: el AUC global de 0,671 se desarma al desagregar
por campaña (0,25 / 0,39 / 0,59 / 0,58 / 0,26).

**Resolución:** se documenta como resultado negativo en el Anexo A del notebook.
La tarifación pre-siembra no se puede mejorar con datos públicos.

---

## 6. Limitaciones a declarar

- **Granularidad.** El departamento es la unidad mínima publicada; el clima se
  toma del centroide, que representa peor a los departamentos grandes del norte.
- **Resolución climática.** MERRA-2 a ~0,5°, no apto para nivel de lote.
- **Sin suelo ni manejo.** No hay tipo de suelo, agua útil, fecha de siembra real,
  variedad, fertilización ni plagas. Es la ausencia más importante.
- **Las estimaciones del MAGyP se revisan** después de publicadas.
- **El clima empieza en 1999**, así que se pierden las campañas 1990/91–1998/99.
- **La normal climática envejece:** el ciclo se calienta ~0,37 °C/década y la
  anomalía media del test corre en +1,26 desvíos. Producción necesita una
  política de recalibración, no solo de reentrenamiento.
