"""End-to-end 5.1.1 benchmark on real seismic networks (Part B).

fetch      FDSN download: reference catalogue (+ analyst arrivals), station inventory with
           responses, 20-station subset selection, hourly MiniSEED
magnitude  local magnitude ML from simulated Wood-Anderson amplitudes; DL magnitude hook
evaluate   matching against the reference catalogue, detection/location/magnitude/pick metrics, plots
pipeline   picks -> windowed association -> location -> magnitudes -> evaluation
regions    region definitions (511/config/regions.json) and their 1-D velocity models
"""
