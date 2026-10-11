"""Audit every header in fixed-record-length MiniSEED 2 sample files."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import struct

from obspy import read
from obspy.io.mseed.util import get_record_information


def audit_file(path):
    info = get_record_information(str(path))
    length, order = info["record_length"], info["byteorder"]
    content = path.read_bytes()
    if len(content) % length:
        raise ValueError(f"Partial record: {path}")
    counts = {key: Counter() for key in ["record_types", "trace_ids", "blockettes", "encodings", "activity_flags", "io_clock_flags", "data_quality_flags", "time_corrections"]}
    for offset in range(0, len(content), length):
        record = content[offset:offset + length]
        kind = record[6:7].decode("ascii")
        if kind not in "DRQM":
            raise ValueError(f"Not a MiniSEED 2 data record: {path}:{offset}")
        network, station, location, channel = [record[a:b].decode("ascii").strip() for a, b in [(18, 20), (8, 13), (13, 15), (15, 18)]]
        counts["record_types"][kind] += 1
        counts["trace_ids"][".".join([network, station, location, channel])] += 1
        for key, index in [("activity_flags", 36), ("io_clock_flags", 37), ("data_quality_flags", 38)]:
            counts[key][record[index]] += 1
        counts["time_corrections"][struct.unpack_from(order + "i", record, 40)[0]] += 1
        data_offset, position = struct.unpack_from(order + "HH", record, 44)
        seen = set()
        blockette_1000 = False
        while position:
            if position in seen or not 48 <= position <= data_offset - 4 or data_offset > length:
                raise ValueError(f"Invalid blockette chain: {path}:{offset}")
            seen.add(position)
            blockette, next_position = struct.unpack_from(order + "HH", record, position)
            counts["blockettes"][blockette] += 1
            if blockette == 1000:
                if position + 8 > data_offset:
                    raise ValueError(f"Truncated blockette 1000: {path}:{offset}")
                encoding, word_order, exponent = record[position + 4:position + 7]
                if 2 ** exponent != length or word_order != (1 if order == ">" else 0):
                    raise ValueError(f"Mixed record sizes/byte orders unsupported: {path}:{offset}")
                counts["encodings"][encoding] += 1
                blockette_1000 = True
            position = next_position
        if not blockette_1000 or len(seen) != record[39]:
            raise ValueError(f"Missing blockette 1000 or invalid count: {path}:{offset}")
    stream = read(str(path), headonly=True, details=True)
    return {
        "path": str(path), "size_bytes": len(content),
        "record_length": length, "header_byte_order": order,
        "record_count": len(content) // length,
        "sampling_rates_hz": sorted({t.stats.sampling_rate for t in stream}),
        "start_time": str(min(t.stats.starttime for t in stream)),
        "end_time": str(max(t.stats.endtime for t in stream)),
        **{key: dict(value) for key, value in counts.items()},
    }


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=root / "data/samples")
    parser.add_argument("--output-dir", type=Path, default=root / "511/outputs/metadata")
    args = parser.parse_args()
    paths = sorted(args.data_dir.resolve().rglob("*.mseed"))
    if not paths:
        parser.error("No .mseed files found")
    files = [audit_file(path) for path in paths]
    totals = {key: Counter() for key in ["record_types", "blockettes", "encodings", "activity_flags", "io_clock_flags", "data_quality_flags", "time_corrections"]}
    stations = {}
    for item in files:
        for key in totals:
            totals[key].update(item[key])
        for trace_id in item["trace_ids"]:
            network, station, location, channel = trace_id.split(".")
            row = stations.setdefault((network, station, location), {
                "network": network, "station": station, "location_code": location,
                "channels": set(), "latitude": None, "longitude": None,
                "elevation_m": None, "coordinate_status": "not_present_in_waveform_headers",
            })
            row["channels"].add(channel)
            if set(item["blockettes"]) != {1000}:
                row["coordinate_status"] = "additional_blockettes_require_review"
    summary = {
        "file_count": len(files), "record_count": sum(f["record_count"] for f in files),
        "record_lengths": sorted({f["record_length"] for f in files}),
        "station_count": len(stations),
        **{key: dict(value) for key, value in totals.items()},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "metadata.json").write_text(json.dumps({"summary": summary, "files": files}, indent=2) + "\n")
    with (args.output_dir / "stations.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["network", "station", "location_code", "channels", "latitude", "longitude", "elevation_m", "coordinate_status"])
        writer.writeheader()
        writer.writerows({**row, "channels": ";".join(sorted(row["channels"]))} for _, row in sorted(stations.items()))
    print(json.dumps(summary, indent=2))
    print(f"Reports: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
