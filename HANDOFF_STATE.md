# HANDOFF_STATE (shared by Claude and Codex; keep it current)

Last update: 2026-11-24, Codex

## Research focus (fixed by the user)
Magnitude uncertainty under sparse networks (k = 2, 3, 5, 10, all) and transfer to new regions:
measure overconfidence and shrinkage, calibration methods, local-data curve (how many events N
until intervals are trustworthy). 5.1.2 only as downstream check: BSSA14 PGA exceedance before /
after calibration. Plan phases 0 -> G are in docs/PAPER.md and below.

## Machines
- Mac: ~/era-paper (git, branch feature/magnitude-calibration; push from here only). venv: .venv-mac
- DGX: `ssh dgx` (Tailscale 100.111.96.64, user hungntt), workdir ~/era-paper (rsync from Mac, no git push).
  Python: ~/era-paper/.venv (inherits ~/Projects/Earthquake-Risk-Assessment/.venv-dgx via .pth; torch cu130 OK).
  User's old repo ~/Projects/Earthquake-Risk-Assessment: READ ONLY, never modify.
  data/e2e/* and 511/outputs/magnitude/old_* and 511/outputs/e2e_old are symlinks into the old repo.
- Shared DGX: run every job through `bash scripts/dgx/guard.sh <name> <cmd>` inside tmux session `era`.
  Never touch other users' processes. Never print big logs (tail -n 20 only).
- Disk budget: 350 GB new data. Free at start: 1014 GB. ~/.seisbench already 146 GB (aq2009gm, ethz).

## Phase status
- [ ] 0 setup (repo synced, links made; venv, tmux, InstanceGM size check pending)
- [ ] A ablation: why DL magnitude shrinks (slope 0.3) - needs 511/e2e_magnitudes.py
- [ ] B data: InstanceGM (if fits), Marche 2022, ML+Mw subset
- [ ] C models: AQ2009GM gauss/event, InstanceGM gauss/event, GBM on amplitude features, WA ML + station terms, TEAM-LM (time-boxed)
- [ ] D e2e reruns -> station_magnitudes.csv
- [ ] E calibration study + local-data curve + bootstrap CIs
- [ ] F BSSA14 exceedance (OpenQuake)
- [ ] G results/REPORT.md

## Running jobs (DGX)
(none)

## Results so far
- Phase E tooling ready: default k=2/3/5/10/all, event bootstrap CIs, calibration-only station terms, and the parallel local-data curve. All 44 tests and pyflakes pass in `.venv-mac`; a 50k-event group with 1,000 bootstrap draws took 0.75 s. Real-data Phase E runs are pending.
- phase A code ready: `511/e2e_magnitudes.py`, `511/ablation_summary.py`, `511/tests/test_e2e_magnitudes.py`, tests pass (.venv-mac unittest discovery and pyflakes).
- Export 2026-11-23: DL coverage95 naive 51% in-domain, 8-26% e2e; DL slope 0.29-0.38 e2e vs WA ML ~1.
- AQ2009 pilot (calibration_study --temporal-split 0.66): shared+conformal ~96-97% at every k;
  fixed-width const_conf about equal in-domain (risk for the method claim).

## Next actions
1. Finish phase 0; start AQ2009GM training (gauss, then event) on DGX.
2. Run the phase A ablations on the reference datasets and compare the event and feature-shift summaries.
