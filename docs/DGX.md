# Running 5.1.1 and 5.1.2 on the NVIDIA DGX Spark

Everything below uses open international data only (no Vietnamese recordings are needed yet).
Commands are run from the repository root in a Jupyter terminal on the DGX.

## 1. Get the code

```bash
cd ~/Projects
git clone -b feature/511-512-open-data https://github.com/JayNguyen0505-es/Earthquake-Risk-Assessment.git
cd Earthquake-Risk-Assessment
# already cloned? update (the branch history was rewritten once, so reset instead of pull):
git fetch origin && git reset --hard origin/feature/511-512-open-data
```

`git reset --hard` keeps untracked files (`data/`, outputs, logs, your own scripts) but discards
edits to tracked files.

## 2. Environment (once, ~10 min)

```bash
bash scripts/dgx/setup_env.sh          # creates .venv-dgx: CUDA PyTorch for aarch64 + 511 + 512 requirements
source .venv-dgx/bin/activate          # in every new terminal
python scripts/dgx/check_env.py        # packages, GPU, disk, reachability of INGV/SCEDC/USGS/SeisBench
```

* The DGX Spark is aarch64 with a Blackwell GPU; the script installs PyTorch from the CUDA wheel
  index (cu130, then cu129, cu128) and pins it before installing the rest, so pip cannot replace it
  with a CPU build. If no CUDA build works everything still runs on CPU; pass `--device cpu`.
* SeisBench stores datasets and weights in `~/.seisbench`. Point it at a larger disk if needed:
  `export SEISBENCH_CACHE_ROOT=/path/with/space` (add it to `~/.bashrc` / `~/.zshrc`).
* If the SeisBench server is unreachable, use its mirror once per session:
  `python -c "import seisbench; seisbench.use_backup_repository()"`.

## 3. Runs

All scripts log to `logs/` and keep going if one step fails. Use `nohup ... &` so a run survives
closing the browser tab; follow it with `tail -f logs/<file>.log`.

| Step | Command | What it does | Time / disk |
|---|---|---|---|
| self-test | `bash scripts/dgx/run_511.sh selftest` | 28 unit tests + offline end-to-end chain | ~2 min |
| 5.1.1 A | `nohup bash scripts/dgx/run_511.sh picker > logs/511_picker_main.log 2>&1 &` | STA/LTA vs PhaseNet vs EQTransformer, weights trained on ETHZ/STEAD/INSTANCE, all tested on ETHZ | dataset download + ~30 min on GPU |
| 5.1.1 B | `nohup bash scripts/dgx/run_511.sh fetch > logs/511_fetch_main.log 2>&1 &` | Central Italy (INGV) and Ridgecrest (SCEDC): 20 stations, 2 days each, catalogue + analyst arrivals; plus an accelerometer-only (HN) Italy run | 1-3 h, ~1-4 GB |
| 5.1.1 C | `nohup bash scripts/dgx/run_511.sh magnitude > logs/511_mag_main.log 2>&1 &` | DL magnitude model on AQ2009GM (L'Aquila, ground-motion units) vs a data-driven Richter baseline | dataset download + ~1 h |
| 5.1.1 B | `nohup bash scripts/dgx/run_511.sh e2e > logs/511_e2e_main.log 2>&1 &` | full chain on every downloaded run with 4 pickers (+ DL magnitude if trained) | ~10-30 min per run |
| 5.1.1 A+ | `bash scripts/dgx/run_511.sh finetune` | fine-tune PhaseNet on accelerometer (HN) traces, evaluate before/after | ~1 h |
| 5.1.2 | `nohup bash scripts/dgx/run_512.sh > logs/512.log 2>&1 &` | Vs30 → California ShakeMap flatfile → GMPE vs ML → scenario PGA maps | 1-3 h, CPU |
| all 5.1.1 | `nohup bash scripts/dgx/run_511.sh all > logs/511_all.log 2>&1 &` | selftest → picker → fetch → magnitude → e2e | several hours |

Settings are environment variables, e.g.
`PICKER_DATASETS="ETHZ AQ2009Counts" PICKER_N=5000 bash scripts/dgx/run_511.sh picker` or
`MAG_DATASET=InstanceGM MAG_CHANNELS="HH EH" bash scripts/dgx/run_511.sh magnitude`
(InstanceGM is ~160 GB). See the header of `scripts/dgx/run_511.sh`.

The DGX is shared: GPU jobs use moderate batch sizes; `rf` in 5.1.2 uses every CPU core — run
`MODELS="baseline hybrid gbm mlp" bash scripts/dgx/run_512.sh` when others are busy.

## 4. Results to bring back

| Part | Files |
|---|---|
| 5.1.1 A | `511/outputs/picker_eval/ALL_SUMMARIES.csv`, `*_residuals.png` |
| 5.1.1 B | `511/outputs/e2e/<run>/<picker>/metrics.json`, `map.png`, `errors.png`, `recall_by_magnitude.csv`; the summary table printed at the end of `logs/511_e2e.log` |
| 5.1.1 C | `511/outputs/magnitude/<dataset>/metrics.json`, `test_diagnostics.png` |
| 5.1.2 | `512/outputs/ca/metrics.csv`, `residuals_*.png`, `maps/*.png` (and `*.tif` for QGIS) |

Download them from the Jupyter file browser (right click → Download). Outputs and `data/` are
git-ignored; only code goes into the repository.

## 5. Caveats to state in reports

* Velocity models: Ridgecrest uses the SCSN Hadley-Kanamori model; Central Italy uses an
  approximate Apennines profile (replace with Chiaraluce et al. 2011 for publication). Depth errors
  depend strongly on this choice, epicentres much less.
* The networks are thinned to 20 stations on purpose, to match the NW Vietnam network; recall and
  location errors are therefore worse than the agencies' dense networks and that is the point.
* ML uses the IASPEI formula without station corrections; expect a regional bias of a few tenths.
