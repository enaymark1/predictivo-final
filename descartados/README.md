# Scripts descartados

Se conservan porque documentan una limitación operativa real, que se discute en
la sección 2 del notebook y en el Anexo A.

## `02_open_meteo.py` — clima desde Open-Meteo (ERA5)

Primera implementación de la descarga climática. **Inviable con la cuota gratuita.**

Open-Meteo no cuenta pedidos sino volumen: una llamada equivale a unos 7 días de
datos. Los 27 años de serie diaria por departamento cuestan ~1.400 llamadas,
contra 5.000/hora y 10.000/día de cuota. Son 3 o 4 departamentos por hora: los
319 habrían tardado semanas.

Se migró a NASA POWER (`../02_descargar_clima.py`), sin cuota por volumen: los
319 departamentos en 3 minutos y sin valores faltantes.

**Contrapartida a declarar:** MERRA-2 (POWER) tiene resolución ~0,5° x 0,625°
contra 0,25° de ERA5. Aceptable para agregados departamentales.

## `00_test_api_open_meteo.py` — diagnóstico escalonado

Hace pedidos de tamaño creciente para distinguir un bloqueo de IP de un límite
por tamaño de respuesta. Fue la herramienta que permitió identificar el problema
de cuota.

## `data/raw/clima_openmeteo_validacion/`

33 departamentos de Buenos Aires que alcanzaron a descargarse de Open-Meteo antes
del corte. Sirven para validación cruzada entre dos productos de reanálisis
independientes (ERA5 vs MERRA-2) sobre las mismas unidades.
