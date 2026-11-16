"""Model zoo for 5.1.2 (numpy / scikit-learn only, per repository guidelines)."""

from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import BaselineGMPE


class HybridGMPE:
    """GMPE-form baseline + gradient boosting on its residuals.

    Trees cannot extrapolate: a GBM trained mostly on M4-5 under-predicts the rare M6-7 events.
    Letting the physics-shaped baseline carry magnitude/distance scaling and the GBM learn only the
    residual pattern keeps the extrapolation of the GMPE and the flexibility of ML.
    """

    def __init__(self, random_state=0):
        self.random_state = random_state

    def fit(self, X, y):
        self.base_ = BaselineGMPE().fit(X, y)
        self.gbm_ = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                                  min_samples_leaf=50, l2_regularization=1.0,
                                                  random_state=self.random_state)
        self.gbm_.fit(X, y - self.base_.predict(X))
        return self

    def predict(self, X):
        return self.base_.predict(X) + self.gbm_.predict(X)

    def get_params(self, deep=False):
        return {"random_state": self.random_state}

    def set_params(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        return self


def make_model(name, random_state=0):
    if name == "baseline":
        return BaselineGMPE()
    if name == "hybrid":
        return HybridGMPE(random_state)
    if name == "rf":
        return RandomForestRegressor(n_estimators=300, min_samples_leaf=3, n_jobs=-1, random_state=random_state)
    if name == "gbm":
        return HistGradientBoostingRegressor(max_iter=500, learning_rate=0.05, max_leaf_nodes=31,
                                             min_samples_leaf=20, l2_regularization=1.0, random_state=random_state)
    if name == "mlp":
        return make_pipeline(
            StandardScaler(),
            MLPRegressor(hidden_layer_sizes=(64, 64), activation="relu", alpha=1e-3, learning_rate_init=1e-3,
                         max_iter=2000, early_stopping=True, n_iter_no_change=30, random_state=random_state),
        )
    raise ValueError(f"unknown model {name}")


MODEL_NAMES = ["baseline", "hybrid", "rf", "gbm", "mlp"]
