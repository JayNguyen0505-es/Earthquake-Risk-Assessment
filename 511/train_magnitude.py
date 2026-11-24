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

Loss: --loss gaussian (per-trace Gaussian NLL, MagNet style) or --loss event (Gaussian NLL with an
error shared by all stations of an event, tau learned jointly; batches are whole events). The event
interval of a model trained with --loss event is sqrt(tau^2 + 1/sum w) instead of sqrt(1/sum w).

Outputs in --out: model.pt (checkpoint used by e2e_run.py --magnitude-model), metrics.json,
test_predictions.csv and dev_predictions.csv (one row per trace with event/station metadata, input
features and the predicted mean/log-variance: the station tables of calibration_study.py),
split_manifest.csv (event id -> split, to check for overlap), training_history.csv, diagnostic PNGs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dl.data import (apply_filters, data_unit, earthquake_mask, is_physical_unit, load_dataset,  # noqa: E402
                     snr_mask, split_dataset)
from dl.data import hypocentral_distance_km  # noqa: E402
from dl.magnet import (DEFAULT_PRE, DEFAULT_WINDOW, EventBatchSampler, ScalarScaler, build_model,  # noqa: E402
                       combine_station_estimates, event_nll, gaussian_nll, make_generator, scalar_matrix)


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


def iterate(model, loader, scaler, use_amp, device, optimizer=None, max_batches=None, log_tau=None):
    """One pass. With log_tau (a tensor) the loss is event_nll, otherwise the per-trace Gaussian NLL."""
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
            if log_tau is not None and train:
                loss = event_nll(mu, lv, y, batch["eid"].to(device), log_tau)
            else:
                loss = gaussian_nll(mu, lv, y)
            if train:
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_([q for g in optimizer.param_groups for q in g["params"]], 5.0)
                optimizer.step()
        total += loss.item() * len(y)
        n += len(y)
        if not train:
            preds.append(np.column_stack([y.cpu().numpy(), mu.detach().cpu().numpy(), lv.detach().cpu().numpy(),
                                          batch["amp"].numpy(), batch["logdist"].numpy().reshape(-1)]))
    return total / max(n, 1), (np.concatenate(preds) if preds else None)


def event_nll_numpy(df, tau):
    """Exact per-trace event NLL on a whole prediction table (used for early stopping with --loss event)."""
    from calib.aggregate import shared_error_nll, _event_sums

    t = df.assign(sd=np.exp(0.5 * df["logvar"]))
    return shared_error_nll([np.log(max(tau, 1e-6)), 0.0], _event_sums(t), fit_bias=False) - 0.5 * np.log(2 * np.pi)


def prediction_table(pred, metadata):
    """Trace-level predictions joined with the event/station metadata of the same (sequential) order."""
    md = metadata.reset_index(drop=True)
    t = pd.DataFrame({"m_true": pred[:, 0], "m_pred": pred[:, 1], "logvar": pred[:, 2],
                      "log_amp_z": pred[:, 3], "log_amp_n": pred[:, 4], "log_amp_e": pred[:, 5], "logdist": pred[:, -1]})
    col = lambda name, default=np.nan: md[name].to_numpy() if name in md else np.full(len(md), default)  # noqa: E731
    t["source_id"] = md["source_id"].astype(str).to_numpy() if "source_id" in md else np.arange(len(t)).astype(str)
    net, sta = col("station_network_code", ""), col("station_code", "")
    t["station_code"] = [f"{n}.{s}" if n else str(s) for n, s in zip(net, sta)]
    ch = next((c for c in ("trace_channel", "station_channel") if c in md), None)
    t["channel"] = md[ch].astype(str).to_numpy() if ch else ""
    t["trace_name"] = col("trace_name", "")
    t["source_time"] = col("source_origin_time", "")
    t["mag_type"] = col("source_magnitude_type", "")
    for a, b in (("source_lat", "source_latitude_deg"), ("source_lon", "source_longitude_deg"),
                 ("source_depth_km", "source_depth_km"), ("station_lat", "station_latitude_deg"),
                 ("station_lon", "station_longitude_deg")):
        t[a] = pd.to_numeric(pd.Series(col(b)), errors="coerce").to_numpy()
    t["dist_km"] = [hypocentral_distance_km(r) for r in md.to_dict("records")]
    if t[["source_lat", "source_lon", "station_lat", "station_lon"]].notna().all(axis=None):
        from calib.io import azimuth_deg

        t["azimuth"] = azimuth_deg(t["source_lat"], t["source_lon"], t["station_lat"], t["station_lon"])
    return t


def split_manifest(splits):
    rows = []
    for name, d in splits.items():
        md = d.metadata
        ids = md["source_id"].astype(str) if "source_id" in md else pd.Series(np.arange(len(md)).astype(str))
        for sid, n in ids.value_counts().items():
            rows.append({"source_id": sid, "split": name, "n_traces": int(n)})
    man = pd.DataFrame(rows).sort_values(["split", "source_id"]).reset_index(drop=True)
    overlap = man.groupby("source_id")["split"].nunique()
    if (overlap > 1).any():
        raise SystemExit(f"split leak: {int((overlap > 1).sum())} events in more than one split")
    digest = hashlib.sha256("\n".join(man["split"] + ":" + man["source_id"]).encode()).hexdigest()[:16]
    return man, digest


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
    p.add_argument("--min-snr-db", type=float, help="keep traces whose every component has SNR >= this (drops dead channels)")
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
    p.add_argument("--loss", default="gaussian", choices=["gaussian", "event"],
                   help="per-trace Gaussian NLL, or Gaussian NLL with a learned shared event error tau")
    p.add_argument("--events-per-batch", type=int, default=32, help="--loss event: events per batch")
    p.add_argument("--stations-per-event", type=int, default=16, help="--loss event: max traces per event per batch")
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
    if a.min_snr_db is not None:
        m_snr, cols = snr_mask(md, a.min_snr_db)
        if m_snr is None:
            print("warning: no SNR columns in this dataset; --min-snr-db ignored")
        else:
            print(f"SNR >= {a.min_snr_db} dB on {cols}: keeps {int((mask & m_snr).sum())}/{int(mask.sum())} traces")
            mask &= m_snr
    ds.filter(mask, inplace=True)
    print(f"magnitude of kept traces: mean {ds.metadata['source_magnitude'].mean():.2f}, "
          f"std {ds.metadata['source_magnitude'].std():.2f}, max {ds.metadata['source_magnitude'].max():.2f}")
    measurement, unit = data_unit(ds)
    physical = is_physical_unit(ds)
    use_amp = physical if a.use_amplitude == "auto" else a.use_amplitude == "yes"
    if use_amp and not physical:
        print(f"warning: dataset unit is '{unit}': amplitude features mix instrument gains")
    splits = split_dataset(ds, mode=a.split_mode, seed=a.seed)
    print(f"{len(ds)} traces ({measurement}, {unit}); amplitude features: {use_amp}; "
          + ", ".join(f"{k} {len(v)}" for k, v in splits.items()))
    empty = [k for k, v in splits.items() if len(v) == 0]
    if empty:
        raise SystemExit(f"empty split(s) {empty}: check the filters (--min-mag, --channels, --min-snr-db)")
    manifest, split_hash = split_manifest(splits)
    manifest.to_csv(out / "split_manifest.csv", index=False)
    print(f"split manifest: {manifest['source_id'].nunique()} events, hash {split_hash}")

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
    if a.loss == "event":
        ids = splits["train"].metadata["source_id"].astype(str).to_numpy()
        loaders["train"] = DataLoader(gens["train"], num_workers=a.workers, worker_init_fn=worker_seeding,
                                      batch_sampler=EventBatchSampler(ids, a.events_per_batch, a.stations_per_event,
                                                                      shuffle=True, seed=a.seed))
    arch = {"width": a.width, "lstm": a.lstm}
    model = build_model(scaler.mean.shape[0], **arch).to(a.device)
    groups = [{"params": list(model.parameters()), "weight_decay": 1e-4}]
    log_tau = None
    if a.loss == "event":
        log_tau = torch.nn.Parameter(torch.tensor(np.log(0.1), dtype=torch.float32, device=a.device))
        groups.append({"params": [log_tau], "weight_decay": 0.0})
    opt = torch.optim.AdamW(groups, lr=a.lr)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=max(1, a.patience // 2))
    config = {"window": a.window, "pre": a.pre, "use_amplitude": bool(use_amp), "physical_units": bool(physical),
              "measurement": measurement, "unit": unit, "channels": a.channels, "dataset": str(a.dataset),
              "sampling_rate": 100.0, "component_order": "ZNE", "arch": arch, "loss": a.loss,
              "split_hash": split_hash, "min_mag": a.min_mag, "min_snr_db": a.min_snr_db, "mag_types": a.mag_types,
              "seed": a.seed}

    def tau_value():
        return float(torch.exp(log_tau).item()) if log_tau is not None else 0.0

    def save(path):
        torch.save({"state_dict": model.state_dict(), "config": config, "scaler_mean": scaler.mean,
                    "scaler_std": scaler.std, "richter_baseline": None if baseline is None else baseline.tolist(),
                    "tau": tau_value()}, path)

    history, best, wait = [], np.inf, 0
    for epoch in range(1, a.epochs + 1):
        t0 = time.time()
        tr, _ = iterate(model, loaders["train"], scaler, use_amp, a.device, opt, a.max_train_batches, log_tau)
        dv, pred = iterate(model, loaders["dev"], scaler, use_amp, a.device) if "dev" in loaders else (tr, None)
        rmse = float(np.sqrt(np.mean((pred[:, 1] - pred[:, 0]) ** 2))) if pred is not None else np.nan
        if a.loss == "event" and pred is not None:  # early-stop on the exact event NLL of the whole dev set
            dv = event_nll_numpy(prediction_table(pred, splits["dev"].metadata), tau_value())
        sched.step(dv)
        history.append({"epoch": epoch, "train_nll": tr, "dev_nll": dv, "dev_rmse": rmse, "tau": tau_value(),
                        "seconds": time.time() - t0})
        print(f"epoch {epoch:3d}  train NLL {tr:.4f}  dev NLL {dv:.4f}  dev RMSE {rmse:.3f}  tau {tau_value():.3f}  "
              f"({time.time() - t0:.0f} s)")
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
    tau = float(ck.get("tau") or 0.0)
    tables = {}
    for name in ("dev", "test"):
        _, pred = iterate(model, DataLoader(gens[name], batch_size=a.batch_size, shuffle=False, num_workers=a.workers),
                          scaler, use_amp, a.device)
        tables[name] = prediction_table(pred, splits[name].metadata)
    test = tables["test"]
    metrics = {"config": config, "tau": tau, "station_dl": regression_metrics(test["m_true"], test["m_pred"])}
    if baseline is not None:
        amp_cols = test[["log_amp_z", "log_amp_n", "log_amp_e"]].to_numpy()
        ok = np.isfinite(test["logdist"].to_numpy())
        test["m_richter"] = np.nan
        test.loc[ok, "m_richter"] = richter_features(amp_cols[ok], test.loc[ok, "logdist"]) @ baseline
        metrics["station_richter_baseline"] = regression_metrics(test.loc[ok, "m_true"], test.loc[ok, "m_richter"])
    ev_rows = []
    for sid, g in test.groupby("source_id"):
        m_w, m_se, m_med = combine_station_estimates(g["m_pred"], g["logvar"])
        row = {"source_id": sid, "n_stations": len(g), "m_true": g["m_true"].iloc[0], "m_pred": m_w, "m_se": m_se,
               "m_se_shared": float(np.sqrt(tau ** 2 + m_se ** 2)), "m_median": m_med}
        if "m_richter" in g:
            row["m_richter"] = float(np.nanmedian(g["m_richter"]))
        ev_rows.append(row)
    events = pd.DataFrame(ev_rows)
    metrics["event_dl"] = regression_metrics(events["m_true"], events["m_pred"])
    if "m_richter" in events:
        ok = events["m_richter"].notna()
        metrics["event_richter_baseline"] = regression_metrics(events.loc[ok, "m_true"], events.loc[ok, "m_richter"])
    r = (events["m_pred"] - events["m_true"]).abs()
    metrics["event_coverage95_independent"] = float(np.mean(r <= 1.96 * events["m_se"]))
    metrics["event_coverage95_shared"] = float(np.mean(r <= 1.96 * events["m_se_shared"]))
    tables["dev"].to_csv(out / "dev_predictions.csv", index=False)
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
