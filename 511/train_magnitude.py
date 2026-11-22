"""Train and evaluate the deep-learning magnitude model (Part C of 5.1.1).

    # accelerometer records in physical units, Central Italy (closest to the 20 Palert stations)
    python 511/train_magnitude.py --dataset AQ2009GM --channels HN --epochs 40 --device cuda \
        --out 511/outputs/magnitude/aq2009_hn

    # large Italian dataset, velocity sensors
    python 511/train_magnitude.py --dataset InstanceGM --channels HH EH --epochs 30 --device cuda \
        --out 511/outputs/magnitude/instance_hh

Event-grouped split (no earthquake in both train and test). Reported on the test set:
station-level RMSE/MAE/bias/R² and event-level metrics (inverse-variance weighted mean of the
station estimates), compared with a data-driven Richter-type baseline
M = a·log10(A_horizontal) + b·log10(R) + c fitted on the same training traces.

Outputs in --out: model.pt (checkpoint used by e2e_run.py --magnitude-model), metrics.json,
test_predictions.csv, training_history.csv, diagnostic PNGs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.data import apply_filters, data_unit, earthquake_mask, is_physical_unit, load_dataset, split_dataset  # noqa: E402
from dl.magnet import (DEFAULT_PRE, DEFAULT_WINDOW, ScalarScaler, build_model, combine_station_estimates,  # noqa: E402
                       gaussian_nll, make_generator, scalar_matrix)


def regression_metrics(y, yhat):
    y, yhat = np.asarray(y, float), np.asarray(yhat, float)
    r = yhat - y
    return {"n": int(len(y)), "rmse": float(np.sqrt(np.mean(r ** 2))), "mae": float(np.mean(np.abs(r))),
            "bias": float(np.mean(r)), "r2": float(1 - np.sum(r ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-12))}


def collect_scalars(gen, n_max, seed=0):
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(gen), min(n_max, len(gen)), replace=False)
    amp, ld, y = [], [], []
    for i in idx:
        s = gen[int(i)]
        amp.append(s["amp"])
        ld.append(s["logdist"][0])
        y.append(float(s["y"]))
    return np.array(amp), np.array(ld), np.array(y)


def richter_features(amp, logdist):
    a_h = np.max(np.asarray(amp)[:, 1:], axis=1)  # largest horizontal component
    return np.column_stack([a_h, np.asarray(logdist, float), np.ones(len(a_h))])


def iterate(model, loader, scaler, use_amp, device, optimizer=None, max_batches=None):
    import torch

    train = optimizer is not None
    model.train(train)
    total, n, preds = 0.0, 0, []
    for b, batch in enumerate(loader):
        if max_batches and b >= max_batches:
            break
        s = scaler.transform(scalar_matrix(batch["amp"].numpy(), batch["logdist"].numpy(), use_amp))
        x = batch["X"].to(device)
        st = torch.from_numpy(s).to(device)
        y = batch["y"].to(device)
        with torch.set_grad_enabled(train):
            mu, lv = model(x, st)
            loss = gaussian_nll(mu, lv, y)
            if train:
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
        total += loss.item() * len(y)
        n += len(y)
        if not train:
            preds.append(np.column_stack([y.cpu().numpy(), mu.detach().cpu().numpy(), lv.detach().cpu().numpy(),
                                          batch["amp"].numpy(), batch["logdist"].numpy().reshape(-1)]))
    return total / max(n, 1), (np.concatenate(preds) if preds else None)


def plots(test, events, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    lim = [min(test["m_true"].min(), test["m_pred"].min()) - 0.2, max(test["m_true"].max(), test["m_pred"].max()) + 0.2]
    ax[0].scatter(test["m_true"], test["m_pred"], s=3, alpha=0.3, label="station")
    ax[0].scatter(events["m_true"], events["m_pred"], s=10, c="r", label="event")
    ax[0].plot(lim, lim, "k--", lw=0.8)
    ax[0].set_xlabel("catalogue magnitude")
    ax[0].set_ylabel("predicted")
    ax[0].legend()
    r = test["m_pred"] - test["m_true"]
    ax[1].scatter(10 ** test["logdist"], r, s=3, alpha=0.3)
    ax[1].set_xscale("log")
    ax[1].axhline(0, color="k", lw=0.8)
    ax[1].set_xlabel("hypocentral distance (km)")
    ax[1].set_ylabel("station residual")
    ax[2].scatter(test["m_true"], r, s=3, alpha=0.3)
    ax[2].axhline(0, color="k", lw=0.8)
    ax[2].set_xlabel("catalogue magnitude")
    ax[2].set_ylabel("station residual")
    fig.tight_layout()
    fig.savefig(out / "test_diagnostics.png", dpi=120)
    plt.close(fig)


def main(argv=None):
    import torch
    from seisbench.util import worker_seeding
    from torch.utils.data import DataLoader

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dataset", required=True)
    p.add_argument("--channels", nargs="*", help="instrument codes, e.g. HN or HH EH")
    p.add_argument("--mag-types", nargs="*", help="keep only these source_magnitude_type values, e.g. ML Mw")
    p.add_argument("--min-mag", type=float, default=-1.0)
    p.add_argument("--max-dist", type=float, default=300.0, help="drop traces beyond this epicentral distance (km)")
    p.add_argument("--use-amplitude", default="auto", choices=["auto", "yes", "no"])
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    p.add_argument("--pre", type=int, default=DEFAULT_PRE)
    p.add_argument("--width", type=int, default=32)
    p.add_argument("--lstm", type=int, default=64)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--patience", type=int, default=5)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--max-train-batches", type=int)
    p.add_argument("--split-mode", default="event", choices=["event", "dataset"])
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)

    torch.manual_seed(a.seed)
    np.random.seed(a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    ds = load_dataset(a.dataset, sampling_rate=100.0)
    apply_filters(ds, channels=a.channels, require=["source_magnitude", "trace_p_arrival_sample"])
    md = ds.metadata
    mask = earthquake_mask(md) & (md["source_magnitude"].astype(float) >= a.min_mag).to_numpy()
    if a.mag_types and "source_magnitude_type" in md.columns:
        mask &= md["source_magnitude_type"].astype(str).str.upper().isin([m.upper() for m in a.mag_types]).to_numpy()
    if "path_ep_distance_km" in md.columns:
        d = md["path_ep_distance_km"].astype(float)
        mask &= (d.isna() | (d <= a.max_dist)).to_numpy()
    ds.filter(mask, inplace=True)
    measurement, unit = data_unit(ds)
    physical = is_physical_unit(ds)
    use_amp = physical if a.use_amplitude == "auto" else a.use_amplitude == "yes"
    if use_amp and not physical:
        print(f"warning: dataset unit is '{unit}': amplitude features mix instrument gains")
    splits = split_dataset(ds, mode=a.split_mode, seed=a.seed)
    print(f"{len(ds)} traces ({measurement}, {unit}); amplitude features: {use_amp}; "
          + ", ".join(f"{k} {len(v)}" for k, v in splits.items()))

    gens = {k: make_generator(v, a.window, a.pre) for k, v in splits.items()}
    amp_s, ld_s, y_s = collect_scalars(gens["train"], 20000, a.seed)
    scaler = ScalarScaler().fit(scalar_matrix(amp_s, ld_s, use_amp))
    baseline = None
    if use_amp:
        ok = np.isfinite(ld_s)
        coef, *_ = np.linalg.lstsq(richter_features(amp_s[ok], ld_s[ok]), y_s[ok], rcond=None)
        baseline = coef
        print(f"Richter-type baseline: M = {coef[0]:.3f} log10 A_h + {coef[1]:.3f} log10 R + {coef[2]:.3f}")

    loaders = {k: DataLoader(g, batch_size=a.batch_size, shuffle=(k == "train"), num_workers=a.workers,
                             worker_init_fn=worker_seeding) for k, g in gens.items() if len(g)}
    arch = {"width": a.width, "lstm": a.lstm}
    model = build_model(scaler.mean.shape[0], **arch).to(a.device)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=max(1, a.patience // 2))
    config = {"window": a.window, "pre": a.pre, "use_amplitude": bool(use_amp), "physical_units": bool(physical),
              "measurement": measurement, "unit": unit, "channels": a.channels, "dataset": str(a.dataset),
              "sampling_rate": 100.0, "component_order": "ZNE", "arch": arch}

    def save(path):
        torch.save({"state_dict": model.state_dict(), "config": config, "scaler_mean": scaler.mean,
                    "scaler_std": scaler.std, "richter_baseline": None if baseline is None else baseline.tolist()}, path)

    history, best, wait = [], np.inf, 0
    for epoch in range(1, a.epochs + 1):
        t0 = time.time()
        tr, _ = iterate(model, loaders["train"], scaler, use_amp, a.device, opt, a.max_train_batches)
        dv, pred = iterate(model, loaders["dev"], scaler, use_amp, a.device) if "dev" in loaders else (tr, None)
        rmse = float(np.sqrt(np.mean((pred[:, 1] - pred[:, 0]) ** 2))) if pred is not None else np.nan
        sched.step(dv)
        history.append({"epoch": epoch, "train_nll": tr, "dev_nll": dv, "dev_rmse": rmse, "seconds": time.time() - t0})
        print(f"epoch {epoch:3d}  train NLL {tr:.4f}  dev NLL {dv:.4f}  dev RMSE {rmse:.3f}  ({time.time() - t0:.0f} s)")
        if dv < best - 1e-4:
            best, wait = dv, 0
            save(out / "model.pt")
        else:
            wait += 1
            if wait >= a.patience:
                print("early stopping")
                break
    pd.DataFrame(history).to_csv(out / "training_history.csv", index=False)

    ck = torch.load(out / "model.pt", map_location=a.device, weights_only=False)
    model.load_state_dict(ck["state_dict"])
    _, pred = iterate(model, DataLoader(gens["test"], batch_size=a.batch_size, shuffle=False, num_workers=a.workers),
                      scaler, use_amp, a.device)
    md_test = splits["test"].metadata.reset_index(drop=True)
    test = pd.DataFrame({"m_true": pred[:, 0], "m_pred": pred[:, 1], "logvar": pred[:, 2],
                         "logdist": pred[:, -1]})
    test["source_id"] = md_test["source_id"].astype(str).to_numpy() if "source_id" in md_test else np.arange(len(test))
    test["trace_channel"] = md_test.get("trace_channel", pd.Series([""] * len(test))).to_numpy()
    metrics = {"config": config, "station_dl": regression_metrics(test["m_true"], test["m_pred"])}
    if baseline is not None:
        amp_cols = pred[:, 3:6]
        ok = np.isfinite(test["logdist"].to_numpy())
        test["m_richter"] = np.nan
        test.loc[ok, "m_richter"] = richter_features(amp_cols[ok], test.loc[ok, "logdist"]) @ baseline
        metrics["station_richter_baseline"] = regression_metrics(test.loc[ok, "m_true"], test.loc[ok, "m_richter"])
    ev_rows = []
    for sid, g in test.groupby("source_id"):
        m_w, m_se, m_med = combine_station_estimates(g["m_pred"], g["logvar"])
        row = {"source_id": sid, "n_stations": len(g), "m_true": g["m_true"].iloc[0], "m_pred": m_w, "m_se": m_se,
               "m_median": m_med}
        if "m_richter" in g:
            row["m_richter"] = float(np.nanmedian(g["m_richter"]))
        ev_rows.append(row)
    events = pd.DataFrame(ev_rows)
    metrics["event_dl"] = regression_metrics(events["m_true"], events["m_pred"])
    if "m_richter" in events:
        ok = events["m_richter"].notna()
        metrics["event_richter_baseline"] = regression_metrics(events.loc[ok, "m_true"], events.loc[ok, "m_richter"])
    # calibration of the predicted uncertainty: fraction of |residual| within 1 sigma (ideal 0.68)
    z = np.abs(test["m_pred"] - test["m_true"]) / np.exp(0.5 * test["logvar"])
    metrics["station_within_1sigma"] = float(np.mean(z <= 1.0))
    test.to_csv(out / "test_predictions.csv", index=False)
    events.to_csv(out / "test_events.csv", index=False)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    plots(test, events, out)
    print(json.dumps({k: v for k, v in metrics.items() if k != "config"}, indent=2))
    print(f"saved {out / 'model.pt'}")


if __name__ == "__main__":
    main()
