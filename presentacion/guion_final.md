# Guion de la presentación final (15 minutos)

Tiempos aproximados entre corchetes. Total ≈ 14 min 30 s, con 30 s de margen: si vas justo de tiempo, acortá el slide de features.

---

### Portada [10 s]
Buenas. *(No leer la portada: pasar directo al slide siguiente.)*

### 1 · Caso de negocio [1 min 20 s]
**Arranco con un número.** En la campaña 2022/23 Argentina cosechó **25 millones de toneladas de soja**. La campaña anterior habían sido 44. **Se perdió casi la mitad.** El rinde cayó de 2.763 a 1.744 kg/ha, y el 10 % de lo que se sembró directamente no se cosechó.

*(Pausa.)* Mi pregunta es: **¿una aseguradora lo podría haber anticipado el 10 de febrero, dos meses antes de la cosecha?**

¿Por qué le importa a una aseguradora? Pensemos en una que vende un **seguro indexado por rendimiento zonal**. No hay peritos: el pago se activa cuando el rendimiento oficial del departamento cae debajo de un umbral. O sea que **ese rendimiento es la deuda de la aseguradora**, y tiene que reservar plata antes de saber cuánto se cosechó.

Entonces el objetivo es predecir el rendimiento en kg/ha de cada departamento **el 10 de febrero**.

¿Cuál es el error caro? **Sobreestimar el rinde en una sequía como la de 2022/23**, porque la aseguradora reserva de menos justo el año en que tiene que pagar. Eso lo vamos a mirar todo el tiempo.

### 1 · Contexto: el ciclo de la soja [45 s]
¿Por qué el 10 de febrero? La soja es el principal cultivo del país: se siembran entre 16 y 18 millones de hectáreas por campaña y, en un año normal, se cosechan entre 44 y 55 millones de toneladas.

El gráfico muestra la campaña de julio a mayo. Al 10 de febrero ya pasaron cuatro etapas: barbecho, siembra, vegetativo y **floración, que es la que define cuántas vainas va a haber**. Gran parte de la campaña ya está jugada, pero todavía faltan unos dos meses para la cosecha: hay tiempo de reservar.

Lo rayado, el llenado de granos y la cosecha, pasa **después** del corte. El modelo no lo usa: sería mirar el futuro. *(Esto se retoma en el slide de la sequía: justo ahí se agravó la de 2022/23.)*

### 2 · Dataset [1 min]
El panel lo construí cruzando dos fuentes públicas: el **MAGyP** (rendimiento y superficie sembrada) y **NASA POWER** (clima diario). Son 6.156 observaciones: 255 departamentos y 26 campañas.

El clima no entra crudo. Lo agrego en **ventanas fenológicas**, con 12 indicadores, y cada uno en dos versiones: el valor y la **anomalía** (cuánto se apartó de lo normal *para ese departamento*). Solo uso las 4 ventanas cerradas al 10/02.

Fuga: producción y superficie cosechada reconstruyen exactamente el rendimiento, así que las saqué. Y la normal climática se calcula solo con campañas hasta 2018.

### 3 · EDA [1 min]
Se ven dos cosas: una **tendencia creciente** (mejora genética y de manejo) y **caídas abruptas en sequía**: 2008/09, 2017/18 y 2022/23, que es la peor.

La descomposición de varianza dice que el departamento explica el 37 %, el año el 23 %, y el 40 % es la interacción: **el mismo año no afecta igual a todos los departamentos**. Ahí entra el clima local.

### 4 · Evaluación [1 min 15 s]
**Métrica principal: RMSE.** Castiga al cuadrado los errores grandes, y los errores grandes son los que le hacen daño a la aseguradora. También reporto MAE, sesgo (si predice de más o de menos) y el error en el año de sequía.

**Partición temporal**: entreno hasta 2019/20 y el test es 2020/21–2024/25. **El test lo toqué una sola vez**, al final.

Para elegir el modelo usé **validación expansiva**: para cada año entre 2010 y 2019, entreno con todos los años anteriores y valido en ese. Son 10 folds y uno incluye la sequía 2017/18. Nunca entreno con el futuro.

### 5 · Baselines [45 s]
El baseline de referencia es el **promedio histórico del departamento**: 651 kg/ha en validación. Es lo que se usaría sin modelo.

Promediar todo o usar la campaña anterior es peor. Sumarle una tendencia mejora el promedio, pero **en la sequía empeora**: la tendencia promete más rinde justo cuando cae.

### 6 · La idea clave [1 min]
Lo que más mejoró el modelo no fue el algoritmo, fue **qué le pido que prediga**.

Una sequía no te saca 500 kg en todos lados, te saca **un porcentaje**. Así que el modelo predice el **desvío en % respecto del rinde esperado del departamento** (promedio + tendencia) y después lo paso a kg/ha. Con el mismo Lasso, pasar de predecir el rinde crudo a predecir el % baja el error de 529 a 519.

De paso resuelve un problema de los árboles: no pueden extrapolar el año.

### 7 · Selección de modelos [1 min 30 s]
Probé más de 20 familias con la misma validación: lineales con y sin regularización, PLS, PCA, efectos fijos, KNN, SVR, red neuronal, Random Forest, Extra Trees y cuatro de boosting.

Arriba quedan los **lineales regularizados**. Hay ~100 variables climáticas muy correlacionadas, y el Lasso se queda con pocas y descarta las redundantes. La regresión sin regularizar es mucho peor (616) justamente por eso.

Los **boosting** quedan muy cerca después de ajustarlos con **Optuna**. KNN, SVR y la red neuronal no compiten: con ~5.000 filas no les alcanzan los datos.

### 7 · Features y ajuste fino [45 s]
Los rezagos (el rinde de las campañas anteriores) mejoran un poco. Las **anomalías traen toda la señal**: con solo valores crudos el error sube a 565. Las interacciones "seco y caliente" le sirven a CatBoost pero no al lineal. Y elegir variables a mano no le gana al Lasso, que ya hace su propia selección.

### 8 · Modelo final [1 min]
El elegido es el **promedio simple de ElasticNet y CatBoost**. El lineal capta el efecto promedio del clima; CatBoost capta combinaciones extremas. Se equivocan en cosas distintas, así que el promedio se equivoca menos.

**511 kg/ha en validación, 21,5 % mejor que el baseline**, y mejor que el ElasticNet solo en la sequía. Honestamente: le gana al ElasticNet solo en 6 de 10 años, así que la diferencia es chica. Lo que inclinó la balanza fue la sequía.

### 8 · ¿Qué mira el modelo? [45 s]
El ElasticNet usa **14 de 101 variables**. Más humedad en vegetativo y floración suma rinde; más radiación en siembra (año seco y soleado) resta. También pesa el rinde de la campaña anterior.

### 8 · Resultados en test [1 min 15 s]
**541 kg/ha contra 665 del baseline: 18,6 % mejor.** En validación había dado 511, así que generaliza: que el test dé un poco peor es lo esperable.

No gana todos los años: empata en 2021/22 y pierde en 2024/25. El valor está en los años extremos.

Comparado con el modelo del Examen 1: es mejor en general (541 contra 584), pero **en la sequía 22/23 es peor** (637 contra 585). Lo digo yo antes de que me lo pregunten.

### 8 · La sequía 2022/23 [1 min]
**Vuelvo a la pregunta del principio:** ¿se podía anticipar la sequía 2022/23 el 10 de febrero? La respuesta es: **la mitad sí.**

El error baja de 1.012 a 637. El modelo **vio venir la mitad de la caída**, pero igual **sobreestimó en 3 de cada 4 departamentos**.

¿Por qué? La sequía **se agravó después del 10 de febrero**: el llenado de granos tuvo la peor anomalía de calor del período (+2,9 desvíos). El modelo no lo puede ver por diseño, porque predice antes.

### 9 · Limitaciones y mejoras [1 min]
Limitaciones: pocas sequías para validar, la sobreestimación en sequía, el clima del centroide y no del lote, Optuna algo optimista, y una normal climática que envejece.

Mejoras: **actualizar la predicción en marzo** con el llenado ya observado, sumar NDVI satelital y suelo, recalibrar la normal, y usar modelos de cuantiles para dar un escenario pesimista para las reservas.

### 10 · Conclusiones [45 s]
- Con el clima al 10 de febrero se predice el rinde con un 19 % menos de error que el promedio histórico, y un 37 % menos en sequía.
- Lo que más aportó fue el planteo (predecir la caída en %), no el algoritmo.
- Se probaron más de 20 familias con validación temporal, y el test se tocó una sola vez.
- Recomendación: usarlo para reservar al 10/02, con margen prudencial si el año viene seco, y actualizarlo en marzo.

Gracias.

---

## Preguntas probables

**¿Por qué RMSE y no MAE?** Porque castiga más los errores grandes, que son los que comprometen la solvencia de la aseguradora.

**¿Por qué no validación cruzada común (k-fold)?** Porque mezclaría años: entrenaría con 2018 para predecir 2015, y eso es usar el futuro.

**¿Qué es el Lasso / ElasticNet?** Una regresión lineal que penaliza el tamaño de los coeficientes. El Lasso pone en cero los que no aportan, así que selecciona variables. ElasticNet mezcla Lasso y Ridge; el nuestro quedó casi en Lasso (l1_ratio 0,93).

**¿Qué es CatBoost?** Boosting de árboles: muchos árboles chicos, cada uno corrige el error de los anteriores. CatBoost usa árboles simétricos, que regularizan bien con pocos datos.

**¿Qué hace Optuna?** Busca hiperparámetros probando combinaciones de forma inteligente: después de cada prueba propone combinaciones parecidas a las que mejor anduvieron.

**¿Por qué promedio y no stacking?** Probé stacking con pesos aprendidos solo con años anteriores y no le ganó al promedio: con 10 años, estimar pesos agrega ruido.

**¿Los rezagos son fuga?** No. El rinde de la campaña anterior ya se conoce al 10 de febrero porque esa cosecha terminó en mayo del año anterior.

**¿Tocaste el test más de una vez?** No para decidir nada. El modelo se eligió y se guardó antes; el notebook de test solo lo carga y lo aplica.
