"""Work package 5.1.2: ground-motion (PGA/PSA) estimation with ML.

Modules
-------
flatfile      unified record schema; readers for NGA-West2 and ShakeMap flatfiles
fetch_shakemap download USGS ShakeMap station observations into a flatfile (needs network)
vs30          sample the USGS global Vs30 grid at points / over a bounding box
features      feature matrix construction from a flatfile
baseline      parametric GMPE-form regression fitted on the same data (classical baseline)
models        scikit-learn models (RF, gradient boosting, MLP) with event-grouped CV
evaluate      metrics incl. between/within-event residual decomposition
scenario      scenario PGA/PSA maps over the three cities (GIS output)
synth         synthetic flatfile generator for tests and smoke runs
"""

INTENSITY_MEASURES = ["pga", "pgv", "sa_0.3", "sa_1.0", "sa_3.0"]
