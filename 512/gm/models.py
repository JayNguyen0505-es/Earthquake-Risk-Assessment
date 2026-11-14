"""Model zoo for 5.1.2 (numpy / scikit-learn only, per repository guidelines)."""

from __future__ import annotations

from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .baseline import BaselineGMPE


def make_model(name, random_state=0):
    if name == "baseline":
        return BaselineGMPE()
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


MODEL_NAMES = ["baseline", "rf", "gbm", "mlp"]
