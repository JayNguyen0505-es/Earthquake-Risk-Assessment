"""Propagate Phase E magnitude intervals into BSSA14 PGA exceedance."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import ndtr, ndtri


DISTANCES = np.array([5, 10, 20, 40, 80])
THRESHOLDS = np.array([0.005, 0.01, 0.02, 0.05, 0.1])
SCENARIOS = (4.0, 5.0, 6.0)
LOG_THRESHOLDS = np.log(THRESHOLDS)
N_DRAWS = 20
N_BINS = 10
GRID_STEP = 0.01
NODES, WEIGHTS = np.polynomial.hermite.hermgauss(32)
GROUP_COLUMNS = ["method", "k", "mode"]
KEY_COLUMNS = [*GROUP_COLUMNS, "Ms", "threshold"]
METRICS = ["mae", "brier", "brier_ref", "missed_hazard"]
PLOT_METHODS = ("naive", "shared_conf", "const_conf")


def bssa14_ln_pga(mag, rjb_km, vs30=400, rake=0.0):
    """Return mean ln(PGA in g) and total sigma for broadcastable inputs."""
    from openquake.hazardlib.gsim.boore_2014 import BooreEtAl2014
    from openquake.hazardlib.imt import PGA

    values = np.broadcast_arrays(mag, rjb_km, vs30, rake)
    ctx = np.rec.fromarrays(
        [value.astype(float).ravel() for value in values],
        names="mag,rjb,vs30,rake",
    )
    mean, sigma, tau, phi = np.zeros((4, 1, ctx.size))
    BooreEtAl2014().compute(ctx, [PGA()], mean, sigma, tau, phi)
    return mean.reshape(values[0].shape), sigma.reshape(values[0].shape)


def conditional_probability(mean, sigma):
    return ndtr((mean[..., None] - LOG_THRESHOLDS) / sigma[..., None])


class GroundMotionGrid:
    """Interpolate cached BSSA14 parameters on a 0.01-magnitude grid."""

    def __init__(self, lower, upper):
        start = np.floor(lower / GRID_STEP)
        stop = np.ceil(upper / GRID_STEP)
        self.mags = np.arange(start, stop + 1) * GRID_STEP
        self.mean, self.sigma = bssa14_ln_pga(self.mags[:, None], DISTANCES)

    def exceedance(self, mag):
        mean = np.stack([
            np.interp(mag, self.mags, self.mean[:, site])
            for site in range(DISTANCES.size)
        ], axis=-1)
        sigma = np.stack([
            np.interp(mag, self.mags, self.sigma[:, site])
            for site in range(DISTANCES.size)
        ], axis=-1)
        return conditional_probability(mean, sigma)


def integrated_probability(m_hat, sigma_m, grid):
    """Integrate Gaussian magnitude uncertainty by Gauss-Hermite quadrature."""
    mag = m_hat[:, None] + np.sqrt(2) * sigma_m[:, None] * NODES
    probability = np.einsum("enst,n->est", grid.exceedance(mag), WEIGHTS) / np.sqrt(np.pi)
    exact = sigma_m == 0
    if exact.any():
        mean, sigma = bssa14_ln_pga(m_hat[exact, None], DISTANCES)
        probability[exact] = conditional_probability(mean, sigma)
    return probability


def evaluate(events, scenario_mode="transplant", seed=0):
    """Evaluate all Phase E groups with shared reference draws per event/site."""
    scenarios = SCENARIOS if scenario_mode == "transplant" else (None,)
    summary, reliability = [], []
    if events.empty:
        return (
            pd.DataFrame(columns=[*KEY_COLUMNS, "n_cases", *METRICS]),
            pd.DataFrame(columns=[*KEY_COLUMNS, "bin", "n_cases", "mean_p_hat", "outcome_rate"]),
        )

    event_index, event_ids = pd.factorize(events["event_id"], sort=True)
    events = events.assign(event_index=event_index)
    truth = events.groupby("event_index")["m_true"].first().to_numpy()
    if not np.array_equal(truth[event_index], events["m_true"].to_numpy()):
        raise ValueError("m_true must be consistent within each event_id")
    normals = np.random.default_rng(seed).standard_normal(
        (len(event_ids), DISTANCES.size, N_DRAWS)
    )
    errors = events["m_hat"] - events["m_true"]
    spread = np.sqrt(2) * abs(NODES[0]) * events["sigma_m"]
    lower_centers = errors + SCENARIOS[0] if scenario_mode == "transplant" else events["m_hat"]
    upper_centers = errors + SCENARIOS[-1] if scenario_mode == "transplant" else events["m_hat"]
    grid = GroundMotionGrid((lower_centers - spread).min(), (upper_centers + spread).max())

    for ms in scenarios:
        true_mag = truth if ms is None else np.full_like(truth, ms, dtype=float)
        mean, sigma = bssa14_ln_pga(true_mag[:, None], DISTANCES)
        p_ref = conditional_probability(mean, sigma)
        simulated = mean[..., None] + sigma[..., None] * normals
        outcome_rate = (simulated[..., None] > LOG_THRESHOLDS).mean(axis=2)

        for keys, group in events.groupby(GROUP_COLUMNS, sort=True):
            centers = group["m_hat"] if ms is None else ms + group["m_hat"] - group["m_true"]
            sigma_m = group["sigma_m"].to_numpy()
            indices = group["event_index"].to_numpy()
            n_cases = indices.size * DISTANCES.size
            totals = np.zeros((len(METRICS), THRESHOLDS.size))
            counts = np.zeros((THRESHOLDS.size, N_BINS), dtype=int)
            sums_p = np.zeros_like(counts, dtype=float)
            sums_outcomes = np.zeros_like(sums_p)
            for start in range(0, indices.size, 512):
                batch = slice(start, start + 512)
                p_hat = integrated_probability(centers.to_numpy()[batch], sigma_m[batch], grid)
                ref = p_ref[indices[batch]]
                rate = outcome_rate[indices[batch]]
                # Averaging binary Brier losses over the draws uses y² = y.
                totals += np.stack([
                    np.abs(p_hat - ref).sum(axis=(0, 1)),
                    (p_hat**2 - 2 * p_hat * rate + rate).sum(axis=(0, 1)),
                    (ref**2 - 2 * ref * rate + rate).sum(axis=(0, 1)),
                    ((p_hat < 0.1) & (ref > 0.3)).sum(axis=(0, 1)),
                ])
                bins = np.minimum((p_hat * N_BINS).astype(int), N_BINS - 1)
                for t in range(THRESHOLDS.size):
                    labels = bins[..., t].ravel()
                    counts[t] += np.bincount(labels, minlength=N_BINS)
                    sums_p[t] += np.bincount(labels, p_hat[..., t].ravel(), minlength=N_BINS)
                    sums_outcomes[t] += np.bincount(labels, rate[..., t].ravel(), minlength=N_BINS)

            for t, threshold in enumerate(THRESHOLDS):
                tags = dict(zip(KEY_COLUMNS, (*keys, ms, threshold)))
                summary.append(dict(tags, n_cases=n_cases,
                                    **dict(zip(METRICS, totals[:, t] / n_cases))))
                for b, count in enumerate(counts[t]):
                    reliability.append(dict(
                        tags, bin=b, n_cases=count,
                        mean_p_hat=sums_p[t, b] / count if count else np.nan,
                        outcome_rate=sums_outcomes[t, b] / count if count else np.nan,
                    ))
    return pd.DataFrame(summary), pd.DataFrame(reliability)


def plot_reliability(reliability, out):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(8, 4), sharex=True, sharey=True)
    for ax, k in zip(axes, ("3", "all")):
        ax.plot([0, 1], [0, 1], linestyle="--", color="0.6")
        for method in PLOT_METHODS:
            rows = reliability.loc[(reliability["k"] == k)
                                   & (reliability["method"] == method)
                                   & (reliability["n_cases"] > 0)]
            if rows.empty:
                continue
            values = rows[["mean_p_hat", "outcome_rate"]].multiply(rows["n_cases"], axis=0)
            pooled = values.groupby(rows["bin"]).sum().divide(
                rows.groupby("bin")["n_cases"].sum(), axis=0
            )
            ax.plot(pooled["mean_p_hat"], pooled["outcome_rate"], marker="o", label=method)
        if ax.get_legend_handles_labels()[0]:
            ax.legend()
        ax.set(title=f"k = {k}", xlabel="Mean predicted exceedance", xlim=(0, 1), ylim=(0, 1))
    axes[0].set_ylabel("Simulated exceedance rate")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    plt.close(fig)


def write_report(summary, out, mode, alpha, dropped, eligible):
    lines = [
        "# BSSA14 PGA exceedance", "",
        f"Run mode: {mode}. Phase E alpha: {alpha:g}.",
        f"Dropped {dropped} of {eligible} eligible intervals with non-finite or negative width.",
        "The Gaussian quadrature evaluates BSSA14 below M 3 if a node falls there.",
        "The reliability plot pools thresholds, scenario magnitudes, and dropout modes by case count.",
        "Each event/site has 20 simulated outcomes shared across methods and repetitions.", "",
        "Scores below pool sites, thresholds, and dropout modes by case count. The CSV includes "
        "all threshold and dropout-mode breakdowns. Missed hazard is a fraction.", "",
        "| Method | k | Ms | MAE | Brier | Reference Brier | Missed hazard |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for (method, k, ms), rows in summary.groupby(["method", "k", "Ms"], dropna=False):
        values = np.average(rows[METRICS], weights=rows["n_cases"], axis=0)
        cells = [method, k, f"{ms:g}" if pd.notna(ms) else "observed"]
        lines.append("| " + " | ".join([*cells, *(f"{value:.5f}" for value in values)]) + " |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--mode", choices=("transplant", "observed"), default="transplant")
    parser.add_argument("--methods", nargs="+")
    parser.add_argument("--ks", nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    alpha = float(json.loads(args.events.with_name("info.json").read_text())["alpha"])
    if not 0 < alpha < 1:
        parser.error("info.json alpha must be between 0 and 1")
    events = pd.read_csv(args.events, dtype={"event_id": str, "k": str})
    if args.methods:
        events = events[events["method"].isin(args.methods)]
    if args.ks:
        events = events[events["k"].isin(args.ks)]
    if args.mode == "observed":
        events = events[events["m_true"] >= 3.0]
    eligible = len(events)
    width = events["hi"] - events["lo"]
    valid = np.isfinite(width) & (width >= 0)
    events = events.loc[valid].assign(sigma_m=width.loc[valid] / (-2 * ndtri(alpha / 2)))
    if not np.isfinite(events[["m_hat", "m_true", "sigma_m"]]).all().all():
        parser.error("eligible intervals must have finite m_hat, m_true, and sigma_M")
    summary, reliability = evaluate(events, args.mode)
    args.out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out / "exceedance_summary.csv", index=False)
    reliability.to_csv(args.out / "reliability.csv", index=False)
    write_report(summary, args.out / "exceedance.md", args.mode, alpha,
                 eligible - len(events), eligible)
    plot_reliability(reliability, args.out / "reliability.png")


if __name__ == "__main__":
    main()
