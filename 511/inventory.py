"""Inspect shared MiniSEED data without modifying or merging waveforms."""

import argparse
import csv
import json
from pathlib import Path
import warnings

import numpy as np
from obspy import read


ROOT = Path(__file__).resolve().parents[1]


def inspect_file(path):
    """Decode one file and retain discontinuities rather than filling them."""
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        stream = read(str(path), format="MSEED")
        if not stream:
            raise ValueError("No waveform traces found")
        stream.sort(keys=["network", "station", "location", "channel", "starttime", "endtime"])
        gaps = [
            {
                "trace_id": ".".join(gap[:4]),
                "start_time": str(gap[4]),
                "end_time": str(gap[5]),
                "duration_seconds": float(gap[6]),
                "sample_count": int(gap[7]),
                "kind": "gap" if gap[6] > 0 else "overlap",
            }
            for gap in stream.get_gaps()
        ]
        traces = []
        for trace in stream:
            values = np.asarray(trace.data, dtype=np.float64)
            finite = values[np.isfinite(values)]
            traces.append({
                "trace_id": trace.id,
                "start_time": str(trace.stats.starttime),
                "end_time": str(trace.stats.endtime),
                "sampling_rate_hz": float(trace.stats.sampling_rate),
                "sample_count": int(trace.stats.npts),
                "nonfinite_count": int(values.size - finite.size),
                "minimum_raw": float(finite.min()) if finite.size else None,
                "maximum_raw": float(finite.max()) if finite.size else None,
                "mean_raw": float(finite.mean()) if finite.size else None,
                "std_raw": float(finite.std()) if finite.size else None,
                "constant": bool(finite.size and np.all(finite == finite[0])),
            })
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "traces": traces,
        "discontinuities": gaps,
        "warnings": [str(item.message) for item in captured],
    }


def build_inventory(data_dir):
    paths = sorted(data_dir.rglob("*.mseed"))
    if not paths:
        raise ValueError(f"No .mseed files found in {data_dir}")
    files, errors = [], []
    for path in paths:
        try:
            files.append(inspect_file(path))
        except Exception as exc:
            errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
    traces = [trace for item in files for trace in item["traces"]]
    discontinuities = [gap for item in files for gap in item["discontinuities"]]
    return {
        "schema_version": 1,
        "data_directory": str(data_dir),
        "summary": {
            "file_count": len(paths),
            "readable_file_count": len(files),
            "error_count": len(errors),
            "trace_count": len(traces),
            "station_ids": sorted({".".join(t["trace_id"].split(".")[:2]) for t in traces}),
            "channels": sorted({t["trace_id"].split(".")[-1] for t in traces}),
            "sampling_rates_hz": sorted({t["sampling_rate_hz"] for t in traces}),
            "earliest_start": min((t["start_time"] for t in traces), default=None),
            "latest_end": max((t["end_time"] for t in traces), default=None),
            "sample_count": sum(t["sample_count"] for t in traces),
            "gap_count": sum(g["kind"] == "gap" for g in discontinuities),
            "overlap_count": sum(g["kind"] == "overlap" for g in discontinuities),
            "constant_trace_count": sum(t["constant"] for t in traces),
            "nonfinite_count": sum(t["nonfinite_count"] for t in traces),
            "warning_count": sum(len(item["warnings"]) for item in files),
        },
        "files": files,
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data/samples")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "outputs/inventory")
    args = parser.parse_args()
    try:
        report = build_inventory(args.data_dir.resolve())
    except ValueError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "inventory.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    rows = [{"path": item["path"], **trace} for item in report["files"] for trace in item["traces"]]
    with (args.output_dir / "traces.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "trace_id", "start_time", "end_time", "sampling_rate_hz", "sample_count", "nonfinite_count", "minimum_raw", "maximum_raw", "mean_raw", "std_raw", "constant"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps(report["summary"], indent=2))
    print(f"Reports: {args.output_dir.resolve()}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
