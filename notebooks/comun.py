"""Funciones compartidas por los notebooks del final (02, 03 y 04).

Acá vive todo lo que tiene que ser IDÉNTICO en selección, entrenamiento y
aplicación a test: qué columnas se pueden usar, cómo se arma la validación
temporal y cómo se construyen las features que dependen del train.
"""
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, RegressorMixin, clone

RAIZ = Path(__file__).resolve().parent.parent
DATASET = RAIZ / "data" / "processed" / "dataset_soja_total.csv"

TARGET = "rendimiento_kgxha"
ULTIMO_TRAIN = 2019                       # train: campañas 1999/00 – 2019/20
TEST = [2020, 2021, 2022, 2023, 2024]     # test: 2020/21 – 2024/25 (se toca UNA vez)
ANIOS_VALIDACION = list(range(2010, 2020))  # folds de la validación expansiva
ANIOS_SEQUIA_VAL = [2017]                 # sequía dentro de la validación (2017/18)

# ── Reglas anti-fuga ─────────────────────────────────────────────────────────
VENT_FEB = ("barbecho", "siembra", "vegetativo", "floracion")   # cerradas al 10/02
PROHIBIDAS = ("llenado_", "anom_llenado_", "cosecha_", "anom_cosecha_",
              "ciclo_", "anom_ciclo_")    # ocurren (o terminan) después del 10/02
FUGA_TARGET = ("produccion_tm", "superficie_cosechada_ha")      # reconstruyen el target
ESTRUCT = ("lat", "lon", "area_km2", "sup_sembrada_log", "anio")


def rmse(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    return float(np.sqrt(np.mean((y - p) ** 2)))


def agregar_rezagos(d):
    """Rezagos del propio departamento. Usan SOLO campañas anteriores (shift),
    así que no filtran el futuro: al 10/02 la campaña anterior ya se cosechó."""
    d = d.sort_values(["departamento_id", "anio"]).copy()
    g = d.groupby("departamento_id")
    consecutiva = g.anio.shift(1) == d.anio - 1
    d["rend_lag1"] = g[TARGET].shift(1).where(consecutiva)
    d["rend_prom3"] = g[TARGET].transform(lambda s: s.shift(1).rolling(3, min_periods=1).mean())
    d["sup_cambio"] = (d.sup_sembrada_log - g.sup_sembrada_log.shift(1)).where(consecutiva).fillna(0.0)
    return d.sort_index()


def cargar():
    d = pd.read_csv(DATASET)
    assert not [c for c in FUGA_TARGET if c in d.columns], "columnas con fuga en el dataset"
    return agregar_rezagos(d)


def features_clima(df, ventanas=VENT_FEB, tipo="ambos"):
    """Columnas climáticas de las ventanas pedidas.

    tipo: "ambos" (absolutas + anomalías), "anom" (solo anomalías), "crudo" (solo absolutas).
    Descarta las que no varían en `df` (p. ej. días de helada en floración).
    """
    cols = []
    for v in ventanas:
        if tipo in ("ambos", "crudo"):
            cols += [c for c in df.columns if c.startswith(v + "_")]
        if tipo in ("ambos", "anom"):
            cols += [c for c in df.columns if c.startswith("anom_" + v + "_")]
    cols = [c for c in cols if df[c].nunique() > 1]
    assert not [c for c in cols if c.startswith(PROHIBIDAS)], "ventana posterior al 10/02"
    return cols


# ── Componente "lugar + tendencia" ───────────────────────────────────────────
class Tendencia:
    """rendimiento ≈ efecto del departamento + b · año.

    `b` es una única pendiente (kg/ha por año) estimada *dentro* de cada
    departamento, así la expansión hacia zonas nuevas no la contamina.
    Departamentos sin historia caen al intercepto promedio.
    """

    def fit(self, df):
        g = df.groupby("departamento_id")
        t_c = df.anio - g.anio.transform("mean")
        y_c = df[TARGET] - g[TARGET].transform("mean")
        self.b_ = float((t_c * y_c).sum() / (t_c ** 2).sum())
        self.a_ = (g[TARGET].mean() - self.b_ * g.anio.mean())
        self.a_global_ = float(self.a_.mean())
        return self

    def predict(self, df):
        a = df.departamento_id.map(self.a_).fillna(self.a_global_)
        return (a + self.b_ * df.anio).to_numpy(float)


# ── El modelo completo ───────────────────────────────────────────────────────
class ModeloRendimiento(BaseEstimator, RegressorMixin):
    """Envuelve cualquier regresor de sklearn con las features que dependen del train.

    objetivo (qué se le pide al estimador):
      "media_global" -> sin estimador: predice el promedio general (baseline)
      "media_dep"    -> sin estimador: promedio histórico del depto (baseline)
      "anterior"     -> sin estimador: rendimiento de la campaña anterior (baseline)
      "tendencia"    -> sin estimador: depto + tendencia (baseline)
      "crudo"        -> el estimador predice el rendimiento directamente
      "desvio_media" -> predice el desvío respecto del promedio del depto
      "residuo"      -> predice el desvío respecto de depto + tendencia (sin tendencia)
      "relativo"     -> predice ese desvío en % del nivel esperado del depto
    usar_dep: agrega media, desvío y n de campañas del depto (calculados con el train).
    tipo_clima: "ambos" | "anom" | "crudo".
    corr_max: si se da, descarta features climáticas con |r| mayor a ese umbral
              contra otra ya elegida (correlación medida en el train).
    extras: subconjunto de {"acum", "region", "cuadrados", "provincia", "rezagos",
            "interac", "prov_te", "dummies_dep"}.
    """

    def __init__(self, estimador=None, objetivo="residuo", usar_dep=True,
                 usar_estruct=True, ventanas=VENT_FEB, suavizado=0.0, extras=(),
                 tipo_clima="ambos", corr_max=None):
        self.estimador = estimador
        self.objetivo = objetivo
        self.usar_dep = usar_dep
        self.usar_estruct = usar_estruct
        self.ventanas = ventanas
        self.suavizado = suavizado
        self.extras = extras
        self.tipo_clima = tipo_clima
        self.corr_max = corr_max

    # -- piezas que dependen del train ------------------------------------
    def _stats_dep(self, df):
        g = df.groupby("departamento_id")[TARGET]
        n, media, sd = g.size(), g.mean(), g.std()
        k = self.suavizado      # contracción hacia la media global si hay pocas campañas
        media = (n * media + k * self.media_global_) / (n + k)
        return pd.DataFrame({"dep_media": media, "dep_sd": sd.fillna(sd.median()),
                             "dep_n": n})

    def _media_dep(self, df):
        return (df.departamento_id.map(self.stats_dep_.dep_media)
                .fillna(self.media_global_).to_numpy(float))

    def _escala(self, df):
        """Nivel esperado del depto (nunca menor a 300 kg/ha), para pasar a %."""
        return np.maximum(self.tend_.predict(df), 300.0)

    def _sin_correlacionadas(self, df, cols):
        if self.corr_max is None:
            return cols
        c = df[cols].corr().abs().to_numpy()
        elegidas = []
        for i in range(len(cols)):
            if all(c[i, j] <= self.corr_max for j in elegidas):
                elegidas.append(i)
        return [cols[i] for i in elegidas]

    def _extras(self, df):
        """Variables derivadas, todas con información disponible al 10/02."""
        E = pd.DataFrame(index=df.index)
        vs = list(self.ventanas)
        ex = self.extras
        if "acum" in ex:      # la sequía se acumula de ventana en ventana
            for ind in ("pp_mm", "balance_mm", "dias_calor"):
                E[f"acum_{ind}"] = df[[f"{v}_{ind}" for v in vs]].sum(axis=1)
                E[f"acum_anom_{ind}"] = df[[f"anom_{v}_{ind}" for v in vs]].sum(axis=1)
            E["racha_max"] = df[[f"{v}_racha_seca" for v in vs]].max(axis=1)
            E["veg_flor_anom_balance"] = df.anom_vegetativo_balance_mm + df.anom_floracion_balance_mm
        if "region" in ex:    # mismo año, promedio de la provincia: suaviza el centroide
            clave = ["anom_vegetativo_balance_mm", "anom_floracion_balance_mm",
                     "anom_vegetativo_dias_calor", "anom_floracion_dias_calor",
                     "anom_floracion_pp_mm", "anom_vegetativo_pp_mm"]
            reg = df.groupby(["provincia", "anio"])[clave].transform("mean")
            E[[f"prov_{c}" for c in clave]] = reg.to_numpy()
        if "cuadrados" in ex:  # exceso y falta de agua dañan: relación en U
            for v in ("vegetativo", "floracion"):
                for ind in ("balance_mm", "pp_mm", "dias_calor"):
                    E[f"sq_anom_{v}_{ind}"] = df[f"anom_{v}_{ind}"] ** 2
        if "provincia" in ex:
            for p in self.provincias_:
                E[f"prov_is_{p}"] = (df.provincia == p).astype(float).to_numpy()
        if "rezagos" in ex:    # campaña anterior y últimas 3, en % del nivel esperado
            esc = self._escala(df)
            E["lag1_rel"] = (df.rend_lag1.to_numpy() / esc - 1)
            E["lag1_falta"] = df.rend_lag1.isna().astype(float).to_numpy()
            E["lag1_rel"] = E.lag1_rel.fillna(0.0)
            E["prom3_rel"] = pd.Series(df.rend_prom3.to_numpy() / esc - 1, index=df.index).fillna(0.0)
            E["sup_cambio"] = df.sup_cambio.to_numpy()
        if "interac" in ex:    # floración seca Y caliente: el peor escenario
            seca = (-df.anom_floracion_pp_mm).clip(lower=0)
            calor = df.anom_floracion_dias_calor.clip(lower=0)
            E["flor_seca_x_calor"] = seca * calor
            E["flor_pp_x_calor"] = df.anom_floracion_pp_mm * df.anom_floracion_dias_calor
            E["veg_seca_x_calor"] = ((-df.anom_vegetativo_pp_mm).clip(lower=0)
                                     * df.anom_vegetativo_dias_calor.clip(lower=0))
            E["balance_siembra_a_flor"] = (df.anom_siembra_balance_mm + df.anom_vegetativo_balance_mm
                                           + df.anom_floracion_balance_mm)
        if "prov_te" in ex:    # target encoding de provincia con el train (no con el año evaluado)
            E["prov_media"] = df.provincia.map(self.prov_media_).fillna(self.media_global_).to_numpy()
        if "dummies_dep" in ex:  # efectos fijos: una columna por departamento del train
            D = pd.get_dummies(pd.Categorical(df.departamento_id, categories=self.deptos_),
                               prefix="dep", dtype=float)
            D.index = df.index
            E = pd.concat([E, D], axis=1)
        return E

    def _X(self, df):
        X = df[self.cols_].copy()
        if self.usar_dep:
            st = self.stats_dep_.reindex(df.departamento_id)
            X["dep_media"] = st.dep_media.fillna(self.media_global_).to_numpy()
            X["dep_sd"] = st.dep_sd.fillna(self.stats_dep_.dep_sd.median()).to_numpy()
            X["dep_n"] = st.dep_n.fillna(0).to_numpy()
            X["base_tend"] = self.tend_.predict(df)
        if self.extras:
            X = pd.concat([X, self._extras(df)], axis=1)
        return X

    def _base(self, df):
        o = self.objetivo
        if o == "media_global":
            return np.full(len(df), self.media_global_)
        if o in ("media_dep", "desvio_media"):
            return self._media_dep(df)
        if o == "anterior":
            return df.rend_lag1.fillna(pd.Series(self._media_dep(df), index=df.index)).to_numpy(float)
        if o in ("tendencia", "residuo", "relativo"):
            return self.tend_.predict(df)
        return np.zeros(len(df))

    # -- API sklearn -------------------------------------------------------
    def fit(self, df, y=None):
        self.media_global_ = float(df[TARGET].mean())
        self.tend_ = Tendencia().fit(df)
        self.stats_dep_ = self._stats_dep(df)
        self.provincias_ = sorted(df.provincia.unique())
        self.prov_media_ = df.groupby("provincia")[TARGET].mean()
        self.deptos_ = sorted(df.departamento_id.unique())
        clima = self._sin_correlacionadas(df, features_clima(df, self.ventanas, self.tipo_clima))
        self.cols_ = (list(ESTRUCT) if self.usar_estruct else []) + clima
        if self.estimador is not None:
            X = self._X(df)
            self.features_ = list(X.columns)
            y = df[TARGET].to_numpy(float) - self._base(df)
            if self.objetivo == "relativo":      # desvío en % del nivel esperado
                y = y / self._escala(df)
            self.est_ = clone(self.estimador).fit(X, y)
        return self

    def predict(self, df):
        p = self._base(df)
        if self.estimador is not None:
            f = self.est_.predict(self._X(df))
            if self.objetivo == "relativo":
                f = f * self._escala(df)
            p = p + np.ravel(f)
        return p


class SelectorPermutacion(BaseEstimator, RegressorMixin):
    """Se queda con las k features más importantes por permutación, medidas en las
    últimas `anios_hold` campañas DEL TRAIN (nunca en el año que se valida)."""

    def __init__(self, estimador=None, k=20, anios_hold=3, n_repeats=3):
        self.estimador = estimador
        self.k = k
        self.anios_hold = anios_hold
        self.n_repeats = n_repeats

    def fit(self, X, y):
        from sklearn.inspection import permutation_importance
        y = np.asarray(y, float)
        corte = X.anio.max() - self.anios_hold
        a, b = (X.anio <= corte).to_numpy(), (X.anio > corte).to_numpy()
        m = clone(self.estimador).fit(X[a], y[a])
        imp = permutation_importance(m, X[b], y[b], scoring="neg_root_mean_squared_error",
                                     n_repeats=self.n_repeats, random_state=0)
        orden = np.argsort(-imp.importances_mean)
        self.cols_ = list(X.columns[orden[: self.k]])
        self.importancias_ = pd.Series(imp.importances_mean, index=X.columns).sort_values(ascending=False)
        self.est_ = clone(self.estimador).fit(X[self.cols_], y)
        return self

    def predict(self, X):
        return self.est_.predict(X[self.cols_])


# ── Validación temporal ──────────────────────────────────────────────────────
def folds_expansivos(df, anios=ANIOS_VALIDACION):
    """Para cada campaña v: entrena con todas las campañas < v y valida en v."""
    for v in anios:
        yield v, df[df.anio < v], df[df.anio == v]


def validar(modelo, train, anios=ANIOS_VALIDACION, n_jobs=1):
    """Corre la validación expansiva y devuelve las predicciones fuera de muestra."""
    from joblib import Parallel, delayed
    assert train.anio.max() <= ULTIMO_TRAIN, "la validación nunca mira el test"

    def un_fold(v, tr, va):
        m = clone(modelo).fit(tr)
        return pd.DataFrame({"anio": va.anio.to_numpy(), "departamento_id": va.departamento_id.to_numpy(),
                             "real": va[TARGET].to_numpy(), "pred": m.predict(va)})

    partes = Parallel(n_jobs=n_jobs)(delayed(un_fold)(v, tr, va)
                                     for v, tr, va in folds_expansivos(train, anios))
    return pd.concat(partes, ignore_index=True)


def resumen(pred, nombre="", rmse_baseline=None):
    """Métricas de validación. sesgo = promedio de (predicho - real): >0 sobreestima."""
    por_anio = pred.groupby("anio").apply(lambda g: rmse(g.real, g.pred), include_groups=False)
    seq = pred[pred.anio.isin(ANIOS_SEQUIA_VAL)]
    r = {"modelo": nombre,
         "rmse_cv": rmse(pred.real, pred.pred),     # RMSE sobre todas las predicciones de validación
         "mae_cv": float(np.mean(np.abs(pred.real - pred.pred))),
         "sesgo": float(np.mean(pred.pred - pred.real)),
         "rmse_medio_folds": float(por_anio.mean()),
         "rmse_peor_fold": float(por_anio.max()),
         "rmse_2017_sequia": rmse(seq.real, seq.pred) if len(seq) else np.nan,
         "sesgo_sequia": float(np.mean(seq.pred - seq.real)) if len(seq) else np.nan}
    if rmse_baseline is not None:
        r["mejora_pct"] = 100 * (1 - r["rmse_cv"] / rmse_baseline)
    return r


# ── Modelo final elegido: promedio ElasticNet + CatBoost ─────────────────────
class Promedio(BaseEstimator, RegressorMixin):
    """Entrena cada modelo por separado y promedia sus predicciones (mitad y mitad)."""

    def __init__(self, modelos=()):
        self.modelos = modelos

    def fit(self, df, y=None):
        self.modelos_ = [clone(m).fit(df) for m in self.modelos]
        return self

    def predict(self, df):
        return np.mean([m.predict(df) for m in self.modelos_], axis=0)


# Hiperparámetros encontrados con Optuna (ronda 9) sobre la validación expansiva 2010–2019.
HP_ELASTICNET = dict(alpha=0.013680095279726922, l1_ratio=0.9293168063780279)
HP_CATBOOST = dict(iterations=980, learning_rate=0.022465750943523745, depth=6,
                   l2_leaf_reg=25.998131320038244, rsm=0.4205093535318751)
HP_LIGHTGBM = dict(n_estimators=873, learning_rate=0.01401992201662606, num_leaves=20,
                   min_child_samples=27, colsample_bytree=0.31675192379597533,
                   subsample=0.5806912571082392, reg_lambda=1.7798697227985611)
HP_XGBOOST = dict(n_estimators=1086, learning_rate=0.006764473005162329, max_depth=2,
                  min_child_weight=6.351166716735872, colsample_bytree=0.5234082062216661,
                  subsample=0.5507221257506387, reg_lambda=4.4733201520530805)
EXTRAS_LINEAL = ("rezagos",)                                  # lo único que le sumó al lineal
EXTRAS_ARBOLES = ("acum", "region", "rezagos", "interac")     # los árboles aprovechan más


def modelo_elasticnet(**hp):
    """ElasticNet sobre el target relativo (% de caída respecto del nivel esperado)."""
    from sklearn.linear_model import ElasticNet
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    est = make_pipeline(StandardScaler(), ElasticNet(**(hp or HP_ELASTICNET), max_iter=100000))
    return ModeloRendimiento(est, "relativo", usar_dep=False, extras=EXTRAS_LINEAL)


def modelo_catboost(**hp):
    """CatBoost sobre el target relativo. thread_count=1 y semilla fija: resultado reproducible."""
    from catboost import CatBoostRegressor
    est = CatBoostRegressor(**(hp or HP_CATBOOST), verbose=0, thread_count=1, random_seed=0,
                            allow_writing_files=False)
    return ModeloRendimiento(est, "relativo", extras=EXTRAS_ARBOLES)


def modelo_final():
    """El modelo que se entrega: promedio simple de ElasticNet y CatBoost."""
    return Promedio((modelo_elasticnet(), modelo_catboost()))


# ── Estilo de los gráficos (mismos colores para la misma cosa en todos los notebooks) ──
COLORES = {"Modelo final": "#2a78d6", "ElasticNet": "#eb6834", "CatBoost": "#1baf7a",
           "Baseline": "#898781", "Real": "#0b0b0b"}


def estilo_graficos():
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb",
        "axes.edgecolor": "#c3c2b7", "axes.labelcolor": "#52514e", "axes.titlecolor": "#0b0b0b",
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "axes.grid.axis": "y", "grid.color": "#e1e0d9", "grid.linewidth": 0.8,
        "xtick.color": "#898781", "ytick.color": "#898781", "text.color": "#0b0b0b",
        "lines.linewidth": 2, "lines.markersize": 6, "legend.frameon": False,
        "figure.dpi": 110, "font.size": 10,
    })
