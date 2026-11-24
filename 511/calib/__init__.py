"""Calibrated network-magnitude uncertainty (paper track).

Everything here works on a *station table*: one row per (event, station) magnitude estimate with
columns

    event_id   str    one earthquake
    station    str    station code (any unique string per event)
    m_true     float  reference (catalogue) magnitude of the event
    m_pred     float  this station's magnitude estimate
    sd         float  the estimator's own standard deviation for this station (NaN for classical ML)
    time       float  event origin time, UNIX seconds (orders events for temporal / online splits)
    azimuth    float  event-to-station azimuth in degrees (NaN if unknown; needed for one-sided dropout)
    estimator  str    e.g. "dl", "ml"

Modules:
    aggregate   event estimate + shared-error (random-effects) model and its maximum-likelihood fit
    conformal   split / Mondrian / adaptive conformal quantiles
    dropout     station subsets: random k, or k stations on one side of the event
    metrics     coverage, width, interval score
    io          converters from train_magnitude.py and e2e outputs into station tables
    study       the full comparison of interval methods
"""
