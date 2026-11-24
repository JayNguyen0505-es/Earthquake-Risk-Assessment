# Spec: phase F, magnitude uncertainty -> BSSA14 PGA exceedance (512/magnitude_to_shaking.py)

Downstream check only. Question: if the event magnitude interval is overconfident, how wrong is the
probability that PGA exceeds a threshold at a site, and does calibration fix it?

## Inputs
events.csv.gz written by 511/calibration_study.py (columns event_id, k, mode, rep, method, m_hat, lo, hi,
m_true; alpha in the sibling info.json). Convert each interval to a Gaussian-equivalent
sigma_M = (hi - lo) / (2 * z_{1-alpha/2}); infinite or NaN widths -> drop and count them.

## Ground motion
OpenQuake BSSA14: `from openquake.hazardlib.gsim.boore_2014 import BooreEtAl2014` (installed in
.venv-mac without GDAL; import it lazily inside functions). Write a small vectorised wrapper
`bssa14_ln_pga(mag, rjb_km, vs30=400, rake=0.0)` -> (mean ln PGA [g], total sigma), built with the
OpenQuake RuptureContext/contexts API of the installed version (check the version, write a unit test
against a few values you compute independently with the same API, e.g. monotonic in M and R).
Cache results on a magnitude grid (step 0.01) x site distances to keep it fast.

## Probabilities
Sites: Rjb in {5, 10, 20, 40, 80} km, Vs30 400 m/s, strike-slip. Thresholds x in {0.005, 0.01, 0.02, 0.05, 0.1} g.
- P_ref = P(PGA > x | M = m_true)          (magnitude known)
- P_hat = integral of P(PGA > x | M) N(M; m_hat, sigma_M^2) dM, Gauss-Hermite with 32 nodes.
- Outcomes: for each (event, site) draw 20 ln PGA ~ N(mean(m_true), sigma(m_true)), seeded.
BSSA14 is meant for M >= 3, so two modes:
- observed: only events with m_true >= 3.0;
- transplant (default): keep each event's error e = m_hat - m_true and its sigma_M, but place them on
  scenario magnitudes Ms in {4.0, 5.0, 6.0} (m_hat' = Ms + e, m_true' = Ms). Report per Ms.

## Metrics per (method, k, mode, threshold, Ms)
mean |P_hat - P_ref|, Brier score of P_hat vs outcomes, Brier of P_ref (floor), share of cases with
P_hat < 0.1 while P_ref > 0.3 ("missed hazard"), and a reliability table (10 bins of P_hat vs outcome rate).

## CLI and outputs
    python 512/magnitude_to_shaking.py --events DIR/events.csv.gz [--mode transplant|observed]
        [--methods naive naive_conf const_conf shared_conf ...] [--ks 3 all] --out OUTDIR
OUTDIR/exceedance_summary.csv, OUTDIR/reliability.csv, OUTDIR/exceedance.md (short tables),
OUTDIR/reliability.png (reliability curves, naive vs shared_conf vs const_conf, k=3 and k=all).

## Tests
512/tests/test_exceedance.py: the wrapper is monotonic in M and R; with sigma_M -> 0 and m_hat = m_true,
P_hat equals P_ref; on synthetic events where the naive sigma is 4x too small, naive has a worse Brier
than a correctly scaled interval. Run `.venv-mac/bin/python -m unittest discover -s 512/tests` and
pyflakes on new files. Touch only 512/ (and append one line to HANDOFF_STATE.md "Results so far").
Do not commit. Another agent is editing 511/ at the same time: do not modify 511/.
