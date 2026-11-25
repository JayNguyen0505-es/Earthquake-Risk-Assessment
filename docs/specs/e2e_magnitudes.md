# Spec: 511/e2e_magnitudes.py + 511/ablation_summary.py (phase A)

Goal: explain why the DL magnitude shrinks toward the mean in end-to-end runs (slope ~0.3 vs ~1 for
Wood-Anderson ML). Compute station magnitudes for EVERY reference (catalogue) event of a run folder,
with controlled inputs, so magnitude errors are not mixed with detection/location errors.

## 511/e2e_magnitudes.py (CLI)
    python 511/e2e_magnitudes.py --run data/e2e/ridgecrest --out OUT [--magnitude-model model.pt]
        [--loc-source ref|auto] [--p-source analyst|theory|auto] [--auto-dir E2E_OUTPUT_DIR]
        [--max-dist-km 300] [--max-events N] [--device cpu] [--workers 1] [--no-ml]
- Run folder layout: see e2e/fetch.py (stations.csv, inventory.xml, events.csv, arrivals.csv, waveforms/<hour>/<NET.STA>.mseed, run.json).
- Reuse, do not duplicate: e2e.pipeline.WaveformStore, e2e.regions (get_region, velocity_model),
  loc.velocity.TravelTimeTable, loc.geometry.to_local_km, e2e.magnitude.station_local_magnitudes and
  station_dl_magnitudes, dl.magnet.MagnitudePredictor. Local frame centre = mean station lat/lon.
- Events: rows of events.csv whose time_s falls inside the waveform hours on disk.
- loc-source ref: catalogue lat/lon/depth/time. auto: the matched automatic event from
  <auto-dir>/matches.csv (ref_id -> det_id) and <auto-dir>/catalog.csv; skip unmatched events.
- p-source analyst: arrivals.csv phase P for (event_id, station); if absent use theory and record
  p_source_used="theory". theory: origin + TravelTimeTable P time from the location in use.
  auto: nearest P pick in <auto-dir>/picks.csv (columns station, phase, time_s) within +-2 s of the
  theoretical P; if none, skip the DL estimate for that station (ML does not need P).
- Stations: every station of stations.csv with data, hypocentral distance <= max-dist-km.
- ML rows from station_local_magnitudes (they include snr); DL rows from station_dl_magnitudes.
- Output OUT/station_magnitudes.csv with columns: event_id (reference id, str), time (reference time_s),
  m_true (reference mag), mag_type, station, estimator (ml|dl), m_pred, sd, logvar, hyp_km, azimuth, snr,
  p_time, p_source_used, loc_source, log_amp_z, log_amp_n, log_amp_e, logdist (NaN where not applicable).
  It must load with calib.io.load_table(OUT) -> from_e2e (m_true present, so no matches needed).
  Also OUT/config.json (args, model sha256[:16], n events) and OUT/events_summary.csv
  (per event and estimator: n stations, median and IVW magnitude, m_true).
- --workers > 1: split events by hour, process chunks in a multiprocessing Pool (each worker builds its
  own WaveformStore and predictor; device cpu for workers). Default 1. Keep memory modest.
- Print one progress line every 50 events; never print per-station lines.

## 511/ablation_summary.py (CLI)
    python 511/ablation_summary.py --runs LABEL=OUT_DIR ... [--train-pred TEST_PREDICTIONS_CSV] --out DIR
- For each run and estimator: event magnitude (ML: median of stations; DL: inverse-variance mean),
  n events, MAE, bias, OLS slope of event magnitude on m_true, bias per reference-magnitude bin
  (bins -1,1,1.5,2,2.5,3,4,10), and the same restricted to stations with snr >= 3.
- Feature shift (DL rows only): for log_amp_z/n/e and logdist, train vs run mean, std, p5, p50, p95,
  and standardized mean difference, using --train-pred (columns log_amp_z, log_amp_n, log_amp_e, logdist).
- Write DIR/ablation_events.csv, DIR/ablation_by_bin.csv, DIR/feature_shift.csv, DIR/ablation.md
  (short markdown tables), and a figure DIR/ablation_scatter.png (event magnitude vs m_true per run).

## Tests
511/tests/test_e2e_magnitudes.py: build the offline synthetic run the way 511/e2e_selftest.py does
(e2e.fake_fdsn), run e2e_magnitudes.py with --loc-source ref --p-source theory and ML only, check that
station_magnitudes.csv loads with calib.io.load_table, ML event medians are within 0.1 of m_true, and
ablation_summary.py writes its outputs. Must pass with:
    .venv-mac/bin/python -m unittest discover -s 511/tests
and `.venv-mac/bin/python -m pyflakes 511/e2e_magnitudes.py 511/ablation_summary.py 511/tests/test_e2e_magnitudes.py`.

## Rules
No network access needed. Do not change public behaviour of existing modules except small, tested
additions. Do not commit or push. When done, update HANDOFF_STATE.md: tick nothing, but add a line
under "Results so far" -> "phase A code ready: <files>, tests pass" or the blocking problem.
