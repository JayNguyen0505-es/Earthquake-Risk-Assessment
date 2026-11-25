"""Build Phase G tables and figures from the Mac copies of experiment outputs."""
from pathlib import Path
import json
import os
import tempfile

import pandas as pd


HERE = Path(__file__).resolve().parent
OUTPUTS = HERE.parent / "511/outputs"
CAL = OUTPUTS / "calibration_final"
METHODS = ["naive", "naive_conf_bc", "const_mondrian_bc", "shared_gauss", "shared_conf"]
CURVE_METHODS = ["const_mondrian_bc", "shared_conf"]
KS = ["2", "3", "5", "10", "all"]
NS = [0, 10, 20, 30, 50, 100]
REGIONS = {
    "central_italy": "Central Italy",
    "central_italy_hn": "Central Italy (HN)",
    "marche_2022": "Marche",
    "ridgecrest": "Ridgecrest",
}
COLORS = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00"]
KEYS = ["method", "k", "mode"]


def read(path):
    if not path.is_file():
        print(f"Note: missing {path.relative_to(HERE.parent)}")
        return None
    if path.suffix == ".json":
        return json.loads(path.read_text())
    return pd.read_csv(path, dtype={"k": str})


def markdown(frame):
    def cell(value):
        if pd.isna(value):
            return "—"
        if isinstance(value, float):
            return f"{value:.6g}"
        return str(value).replace("|", r"\|").replace("\n", "<br>")

    rows = [frame.columns, ["---"] * len(frame.columns)]
    rows.extend(frame.itertuples(index=False, name=None))
    return "\n".join("| " + " | ".join(map(cell, row)) + " |" for row in rows) + "\n"


def save(name, parts):
    if not parts:
        print(f"Note: skipping {name}, no input rows")
        return
    frame = pd.concat(parts, ignore_index=True)
    if frame.empty:
        print(f"Note: skipping {name}, no matching rows")
        return
    frame.to_csv(HERE / "tables" / f"{name}.csv", index=False)
    (HERE / "tables" / f"{name}.md").write_text(markdown(frame))
    print(f"{name}: {len(frame)} rows")
    return frame


def tag(frame, **labels):
    return frame.assign(**labels)[[*labels, *frame.columns]]


def standard_mode(frame):
    return frame[(frame["mode"] == "random") |
                 ((frame["k"] == "all") & (frame["mode"] == "all"))]


def summary(folder):
    frame = read(folder / "summary_by_k.csv")
    if frame is None:
        return
    ci = read(folder / "summary_by_k_ci.csv")
    if ci is not None:
        # CI centres use event weighting. Preserve the original summary estimate as well.
        ci = ci.rename(columns={m: f"{m}_event_weighted" for m in
                               ("coverage", "mean_width", "interval_score")})
        frame = frame.merge(ci, on=KEYS, how="left", validate="one_to_one")
    return frame[frame["method"].isin(METHODS) & frame["k"].isin(KS)]


def test_table_stats(folder, n_test):
    path = folder / "events.csv.gz"
    if not path.exists():
        print(f"Note: station count unavailable for {folder.name} ({folder.parent.name})")
        return None, None
    chunks = []
    for rows in pd.read_csv(path, usecols=["event_id", "method", "k", "mode", "n_sta", "time"],
                            dtype={"k": str, "event_id": str}, chunksize=100_000):
        all_rows = rows[(rows["k"] == "all") & (rows["mode"] == "all") &
                        (rows["method"] == "naive")]
        chunks.append(all_rows[["event_id", "n_sta", "time"]])
    events = pd.concat(chunks, ignore_index=True)
    if len(events) != n_test or events["event_id"].duplicated().any():
        print(f"Note: {folder.name} lacks one full-station row per test event")
        return None, None
    span_hours = (events["time"].max() - events["time"].min()) / 3600
    return int(events["n_sta"].sum()), span_hours


def data_row(folder, tags, info, metrics):
    n_test = info["n_test_events"]
    station_rows, span_hours = test_table_stats(folder, n_test)
    source = "events.csv.gz (all, naive)" if station_rows is not None else None
    if station_rows is None and metrics and metrics.get("event_dl", {}).get("n") == n_test:
        station_rows = metrics.get("station_dl", {}).get("n")
        if station_rows is not None:
            source = "metrics.json"
    return pd.DataFrame([{**tags, "label_type": "ML", "n_test_events": n_test,
                          "n_station_rows": station_rows, "test_span_hours": span_hours,
                          "station_count_source": source}])


def read_curves(folder, tags, parts, classical):
    curve = read(folder / "curve.csv")
    prefix = "T7" if classical else "T5"
    if curve is not None:
        curve = tag(curve[curve["n"].isin(NS) & curve["k"].isin(["2", "3", "all"]) &
                          curve["method"].isin(CURVE_METHODS) &
                          (((curve["n"] == 0) & (curve["scheme"] == "source_only")) |
                           ((curve["n"] > 0) & (curve["scheme"] == "target_only")))], **tags)
        normal = standard_mode(curve)
        parts[f"{prefix}_curve"].append(normal)
        pairs = normal[normal["n"] == 30].pivot(
            index=["model", "region", "k", "mode", "n", "scheme"],
            columns="method", values="interval_score_mean").reindex(columns=CURVE_METHODS)
        pairs = pairs.dropna()
        pairs["relative_gain"] = (1 - pairs["shared_conf"] /
                                  pairs["const_mondrian_bc"].where(pairs["const_mondrian_bc"] != 0))
        parts[f"{prefix}_gain"].append(pairs.reset_index())
        parts["T6_curve"].append(curve[curve["mode"].isin(["random", "one_sided"])])
    needed = read(folder / "n_needed.csv")
    if needed is not None:
        parts[f"{prefix}_n_needed"].append(tag(needed, **tags))


def make_tables():
    names = [
        "T1_data", "T2_checkpoint", "T3_indomain", "T3_fit", "T4_transfer",
        "T5_curve", "T5_n_needed", "T5_gain", "T6_transfer", "T6_curve",
        "T7_temporal", "T7_curve", "T7_n_needed", "T7_gain",
        "T8_bssa14", "T9_training", "T9_history",
    ]
    parts = {name: [] for name in names}
    model_dirs = [CAL / model for model in ("AQ2009GM_gauss", "InstanceGM_gauss", "ml")]
    for model_dir in model_dirs:
        model = model_dir.name
        classical = model == "ml"
        if not model_dir.is_dir():
            print(f"Note: missing {model_dir.relative_to(HERE.parent)}")
            continue
        metrics = None if classical else read(OUTPUTS / "magnitude_meta" / model / "metrics.json")
        for folder in sorted(path for path in model_dir.iterdir() if path.is_dir()):
            study, _, region = folder.name.partition("_")
            tags = {"model": model, "region": region or model.removesuffix("_gauss")}
            if study == "curve":
                tags["region"] = region.removeprefix("dl_") if not classical else region
                read_curves(folder, tags, parts, classical)
                continue
            if study not in {"indomain", "transfer", "temporal", "fewshot30"}:
                continue
            info = read(folder / "info.json")
            if info is not None:
                parts["T1_data"].append(data_row(
                    folder, dict(tags, study=study), info, metrics if study == "indomain" else None))
                if study == "indomain":
                    parts["T3_fit"].append(pd.DataFrame([{
                        **tags, **info["shared_error_model"], "alpha": info["alpha"],
                        "icc_calibration": info["icc_calibration"], "icc_test": info["icc_test"],
                    }]))
            if study != "fewshot30":
                frame = summary(folder)
                if frame is not None:
                    frame = tag(frame, **tags)
                    standard = standard_mode(frame)
                    if study == "transfer":
                        parts["T4_transfer"].append(standard[standard["k"].isin(["2", "all"])])
                        parts["T6_transfer"].append(frame[frame["mode"].isin(["random", "one_sided"])])
                    else:
                        table = "T3_indomain" if study == "indomain" else "T7_temporal"
                        parts[table].append(standard)
            if study in {"transfer", "fewshot30"}:
                shaking = read(folder / "shaking" / "exceedance_summary.csv")
                if shaking is not None:
                    chosen = shaking[(shaking["k"] == "all") & (shaking["mode"] == "all") &
                                     (shaking["Ms"] == 5) & (shaking["threshold"] == 0.1)]
                    parts["T8_bssa14"].append(tag(
                        chosen, **tags, study=study, n=0 if study == "transfer" else 30))

    checkpoints = {"old": "AQ2009GM full", "m15": "AQ2009GM_M1.5_snr10"}
    for checkpoint, checkpoint_name in checkpoints.items():
        for region in ("central_italy", "ridgecrest"):
            frame = read(OUTPUTS / "ablation" / checkpoint / region / "summary/ablation_events.csv")
            if frame is not None:
                runs = ["auto_auto", "ref_analyst"] if checkpoint == "old" else ["auto_auto"]
                chosen = frame[(frame["estimator"] == "dl") & (frame["subset"] == "all") &
                               frame["run"].isin(runs)]
                parts["T2_checkpoint"].append(tag(
                    chosen, checkpoint=checkpoint, checkpoint_name=checkpoint_name, region=region))

    for model in ("AQ2009GM_gauss", "AQ2009GM_event", "InstanceGM_gauss"):
        meta = OUTPUTS / "magnitude_meta" / model
        metrics = read(meta / "metrics.json")
        history = read(meta / "training_history.csv")
        if history is not None and not history.empty:
            parts["T9_history"].append(tag(history, model=model))
        if metrics is not None:
            row = {"model": model, "loss": metrics["config"]["loss"], "tau": metrics["tau"],
                   **{f"test_event_{key}": val for key, val in metrics["event_dl"].items()},
                   **{key: metrics[key] for key in
                      ("event_coverage95_independent", "event_coverage95_shared")}}
            if history is not None and not history.empty:
                last = history.sort_values("epoch").iloc[-1]
                row.update(last_epoch=last["epoch"], last_dev_rmse=last["dev_rmse"],
                           last_history_tau=last["tau"])
            parts["T9_training"].append(pd.DataFrame([row]))

    return {name: save(name, rows) for name, rows in parts.items()}


def make_figures(tables, plt):
    def export(fig, name):
        fig.savefig(HERE / "figures" / f"{name}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)

    data = tables["T3_indomain"]
    if data is not None:
        models = data["model"].unique()
        fig, axes = plt.subplots(1, len(models), squeeze=False, figsize=(6 * len(models), 4.5),
                                 layout="constrained")
        for ax, model in zip(axes[0], models):
            for method, color in zip(METHODS, COLORS):
                group = data[(data["model"] == model) & (data["method"] == method)].set_index("k")
                if group.empty:
                    continue
                group = group.reindex(KS)
                ax.plot(KS, 100 * group["coverage"], "o-", color=color, label=method)
                if "coverage_lo" in group:
                    ax.fill_between(KS, 100 * group["coverage_lo"], 100 * group["coverage_hi"],
                                    color=color, alpha=0.12)
            ax.axhline(95, color="0.35", linestyle=":", label="95% nominal")
            ax.set(xlabel="Stations retained", ylabel="Coverage (%)", title=model, ylim=(0, 102))
            ax.legend(fontsize=8)
        export(fig, "F1_coverage_vs_k")

    data = tables["T5_curve"]
    if data is not None:
        for model, model_data in data.groupby("model"):
            regions = list(model_data["region"].unique())
            fig, axes = plt.subplots(len(regions), 2, squeeze=False,
                                     figsize=(10, 2.65 * len(regions) + 0.5), layout="constrained")
            for (cov, score), region in zip(axes, regions):
                region_data = model_data[model_data["region"] == region]
                for method, color in zip(CURVE_METHODS, COLORS):
                    for k, style in (("2", "-"), ("all", "--")):
                        group = region_data[(region_data["method"] == method) &
                                            (region_data["k"] == k)].sort_values("n")
                        for ax, column, scale in ((cov, "coverage_mean", 100),
                                                  (score, "interval_score_mean", 1)):
                            ax.plot(group["n"], scale * group[column], style, color=color,
                                    marker="o", markersize=3, label=f"{method}, k={k}")
                name = REGIONS.get(region, region)
                cov.axhline(95, color="0.4", linestyle=":")
                cov.set(ylabel="Coverage (%)", title=name, ylim=(0, 102))
                score.set(ylabel="Interval score (lower is better)", title=name)
                for ax in (cov, score):
                    ax.set_xticks(NS)
            axes[0, 1].legend(fontsize=8)
            for ax in axes[-1]:
                ax.set_xlabel("Local calibration events (N)")
            name = "F2_local_data" if model == "AQ2009GM_gauss" else f"F2_local_data_{model}"
            export(fig, name)

    data = tables["T8_bssa14"]
    if data is not None:
        for model, model_data in data.groupby("model"):
            shared = model_data[model_data["method"] == "shared_conf"]
            if shared.empty:
                print(f"Note: skipping F3 for {model}, shared_conf missing")
                continue
            bars = shared.pivot(index="region", columns="n", values="missed_hazard")
            bars = bars.reindex(columns=[0, 30]).mul(100).rename(columns={0: "N=0", 30: "N=30"})
            bars.index = [REGIONS.get(r, r) for r in bars.index]
            fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
            bars.plot.bar(ax=ax, color=COLORS[:2], rot=15)
            ax.set(xlabel="", ylabel="Missed hazard (%)",
                   title="BSSA14 · shared_conf · Mₛ=5 · 0.1 g · all stations")
            name = "F3_missed_hazard" if model == "AQ2009GM_gauss" else f"F3_missed_hazard_{model}"
            export(fig, name)

    data = tables["T2_checkpoint"]
    if data is not None:
        bars = data[data["run"] == "auto_auto"].pivot(index="region", columns="checkpoint",
                                                    values="slope")
        if not bars.empty:
            bars = bars.reindex(columns=["old", "m15"]).rename(
                columns={"old": "AQ2009GM full", "m15": "AQ2009GM M1.5 SNR10"})
            bars.index = [REGIONS.get(r, r) for r in bars.index]
            fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
            bars.plot.bar(ax=ax, color=COLORS[:2], rot=0)
            ax.axhline(1, color="0.4", linestyle=":")
            ax.set(xlabel="", ylabel="Slope (predicted vs catalogue magnitude)", title="Auto location and P pick")
            export(fig, "F4_checkpoint_slope")


def main():
    for directory in ("tables", "figures"):
        (HERE / directory).mkdir(exist_ok=True)
    # Use a writable cache when running under the workspace sandbox.
    with tempfile.TemporaryDirectory(prefix="era-mpl-") as cache:
        os.environ.setdefault("MPLCONFIGDIR", cache)
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        make_figures(make_tables(), plt)


if __name__ == "__main__":
    main()
