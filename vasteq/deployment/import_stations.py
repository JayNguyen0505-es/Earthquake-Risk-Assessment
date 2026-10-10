"""Validate the station XLSX workbook and generate a transactional MySQL import.

Uses only the standard library. SQL generation does not connect to the database.
"""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import posixpath
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET


NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HEADERS = ["Tỉnh", "STT", "Mã trạm", "Vĩ độ", "Kinh độ", "Địa chỉ lắp đặt", "Loại máy", "Serial"]


def workbook_rows(path, sheet_name):
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", NS):
                strings.append("".join(t.text or "" for t in item.findall(".//s:t", NS)))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = {s.attrib["name"]: s.attrib[f"{{{REL}}}id"] for s in workbook.findall("s:sheets/s:sheet", NS)}
        if sheet_name not in sheets:
            raise ValueError(f"Sheet {sheet_name!r} not found; available: {list(sheets)}")
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(item.attrib["Target"] for item in relationships if item.attrib["Id"] == sheets[sheet_name])
        sheet_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        sheet = ET.fromstring(archive.read(sheet_path))
        cells = {}
        for row in sheet.findall("s:sheetData/s:row", NS):
            for cell in row.findall("s:c", NS):
                if cell.find("s:f", NS) is not None:
                    raise ValueError(f"Formula cell {cell.attrib['r']} requires review")
                value = cell.findtext("s:v", default="", namespaces=NS)
                if cell.attrib.get("t") == "s":
                    value = strings[int(value)]
                elif cell.attrib.get("t") == "inlineStr":
                    value = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                elif cell.attrib.get("t") == "e":
                    raise ValueError(f"Excel error at {cell.attrib['r']}: {value}")
                cells[cell.attrib["r"]] = value.strip()
        # Expand merged provinces explicitly; do not carry labels across unmerged blanks.
        for merged in sheet.findall("s:mergeCells/s:mergeCell", NS):
            match = re.fullmatch(r"([A-Z]+)(\d+):\1(\d+)", merged.attrib["ref"])
            if match:
                column, start, end = match.groups()
                value = cells.get(f"{column}{start}", "")
                for number in range(int(start), int(end) + 1):
                    cells[f"{column}{number}"] = value
        columns = "ABCDEFGH"
        headers = [cells.get(f"{col}1", "") for col in columns]
        if headers != HEADERS:
            raise ValueError(f"Unexpected worksheet headers: {headers}")
        rows = []
        for row in sheet.findall("s:sheetData/s:row", NS):
            number = int(row.attrib["r"])
            if number == 1:
                continue
            values = [cells.get(f"{column}{number}", "") for column in columns]
            if not any(values):
                continue
            rows.append((number, dict(zip(HEADERS, values))))
        return rows


def parse_stations(path, sheet_name="Sheet1", waveform_dir=None):
    if waveform_dir is None:
        waveform_dir = Path(__file__).resolve().parents[2] / "data/samples"
    networks = {}
    for file in waveform_dir.rglob("*.mseed"):
        parts = file.name.split(".")
        if len(parts) >= 7:
            networks.setdefault(parts[1], set()).add(parts[0])
    if not networks:
        raise ValueError("No waveform filenames available to establish network/station identities")
    stations, seen = [], set()
    for row, values in workbook_rows(path, sheet_name):
        try:
            code_number = Decimal(values["Mã trạm"])
            if not code_number.is_finite() or code_number != code_number.to_integral_value():
                raise ValueError("Station code must be an integer")
            code = str(int(code_number))
            latitude, longitude = Decimal(values["Vĩ độ"]), Decimal(values["Kinh độ"])
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid station/coordinates at row {row}") from exc
        if not latitude.is_finite() or not longitude.is_finite() or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            raise ValueError(f"Invalid coordinate range at row {row}")
        if len(code) > 5 or code in seen:
            raise ValueError(f"Invalid or duplicate station code {code} at row {row}")
        if len(networks.get(code, set())) != 1:
            raise ValueError(f"No unique waveform network match for station {code}")
        for key in ["Tỉnh", "Địa chỉ lắp đặt", "Loại máy", "Serial"]:
            if not values[key]:
                raise ValueError(f"Missing {key} at row {row}")
        if len(values["Địa chỉ lắp đặt"]) > 120 or len(values["Tỉnh"]) > 120 or len(values["Loại máy"]) > 64 or len(values["Serial"]) > 64:
            raise ValueError(f"Metadata exceeds database column length at row {row}")
        seen.add(code)
        stations.append({
            "network_code": next(iter(networks[code])), "station_code": code,
            "name": values["Địa chỉ lắp đặt"], "province": values["Tỉnh"],
            "latitude": str(latitude), "longitude": str(longitude),
            "instrument_type": values["Loại máy"], "instrument_serial": values["Serial"],
            "spreadsheet_row": row,
        })
    if not stations:
        raise ValueError("Spreadsheet contains no stations")
    missing = set(networks) - seen
    if missing:
        raise ValueError(f"Waveform stations missing from spreadsheet: {sorted(missing)}")
    return stations


def sql_string(value):
    # Hex encoding avoids dependence on SQL backslash escaping or SQL mode.
    return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"


def generate_sql(stations, source_uri, digest, sheet_name="Sheet1"):
    lines = [
        "-- Generated from station workbook; upserts preserve station IDs and unrelated fields.",
        f"-- Source SHA-256: {digest}",
        "SET NAMES utf8mb4;", "SET time_zone = '+00:00';", "USE vasteq;", "START TRANSACTION;",
    ]
    for station in stations:
        fields = ["network_code", "station_code", "name", "province", "instrument_type", "instrument_serial"]
        values = {field: sql_string(station[field]) for field in fields}
        values.update({field: station[field] for field in ["latitude", "longitude"]})
        values["coordinate_crs"] = "NULL"
        values["metadata_uri"] = sql_string(source_uri)
        values["metadata_source"] = sql_string(f"{sheet_name}; row={station['spreadsheet_row']}; sha256={digest}; CRS unspecified")
        columns = list(values)
        updates = [f"{field} = {values[field]}" for field in columns if field not in ["network_code", "station_code"]]
        # Preserve city/elevation; clear CRS when replacing coordinates from an unspecified datum.
        lines.append(f"INSERT INTO stations ({', '.join(columns)}) VALUES ({', '.join(values.values())})\nON DUPLICATE KEY UPDATE {', '.join(updates)};")
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=root / "data/stations.xlsx")
    parser.add_argument("--sheet", default="Sheet1")
    parser.add_argument("--waveform-dir", type=Path, default=root / "data/samples")
    parser.add_argument("--output-dir", type=Path, default=root / "data/derived/stations")
    args = parser.parse_args()
    stations = parse_stations(args.input, args.sheet, args.waveform_dir)
    digest = hashlib.sha256(args.input.read_bytes()).hexdigest()
    try:
        uri = args.input.resolve().relative_to(root).as_posix()
    except ValueError:
        uri = args.input.resolve().as_posix()
    report = {
        "source": uri, "sha256": digest, "sheet": args.sheet,
        "station_count": len(stations),
        "province_counts": dict(Counter(s["province"] for s in stations)),
        "instrument_counts": dict(Counter(s["instrument_type"] for s in stations)),
        "coordinate_crs": None,
        "stations": stations,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "stations.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (args.output_dir / "import.sql").write_text(generate_sql(stations, uri, digest, args.sheet))
    print(json.dumps({key: value for key, value in report.items() if key != "stations"}, ensure_ascii=False, indent=2))
    print(f"Generated reports and import SQL in {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
