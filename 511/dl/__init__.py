"""Deep-learning and classic signal-processing components for work package 5.1.1.

data       SeisBench dataset loading (benchmark name or local folder), channel filters,
           event-grouped train/dev/test split, phase-column discovery
stalta     classic STA/LTA P/S picker (baseline against the deep-learning pickers)
pickers    one interface over SeisBench models and the STA/LTA baseline
magnet     deep-learning magnitude model (CNN + BiLSTM, amplitude/distance features, Gaussian NLL)
"""
