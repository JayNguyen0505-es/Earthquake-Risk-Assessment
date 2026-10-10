# Sample waveform metadata audit

Inspected on 2026-10-10 using `511/inspect_metadata.py`, ObsPy 1.5.1, and
the SEED 2.4 reference manual. All 60 files under `data/samples/4.0` were
checked at every record boundary, including the full linked blockette chain.

## Result: station coordinates are absent

The 347,715,072 bytes comprise 679,131 MiniSEED 2 data records, each 512 bytes
long. Every record contains exactly one blockette: **1000**, describing the
encoding, word order, and record length. All use encoding 11 (STEIM2).
There are no station-control records, geographic coordinates, response metadata,
or opaque metadata blockettes in these files.

The identifiers are network `VN`, stations `4001` through `4020`, blank
location identifiers, and channels `HLE`, `HLN`, and `HLZ`. The location
identifier is a two-character code distinguishing streams; it is not latitude,
longitude, or a city name. These identifiers alone do not determine a station's
geographic position or its assignment to Sơn La, Điện Biên, or Lai Châu.

## Available metadata

| Field | Observed value |
| --- | --- |
| Network | `VN` |
| Stations | `4001`–`4020` |
| Location code | Empty for all stations |
| Channels | `HLE`, `HLN`, `HLZ` for each station |
| Sample rate | 100 Hz |
| Overall UTC time bounds | 2026-10-02T00:00:01.280Z to 2026-10-03T00:00:01.960Z |
| Data record indicator | `D` in every record |
| Activity, I/O/clock, and data-quality flag bytes | Zero in every record |
| Header time correction | Zero in every record |
| Blockette 1001 timing-quality metadata | Absent |

`D` denotes an indeterminate quality-control state. Zero flag bytes do not
prove that data quality is good or that the clock is GPS locked. No GPS lock
flag is asserted and there is no timing-quality blockette. ObsPy's default
`stats.calib = 1.0` is not evidence of a supplied instrument calibration.
Sample values cannot be assigned physical units using these headers alone.

The earlier decoded waveform inventory found 147 gaps and 39 overlaps within
files. The record audit complements that analysis; it does not revise it.

## Required companion metadata

Update: `data/stations.xlsx` now supplies station coordinates, installation sites,
province labels and instrument identifiers for all 20 stations. See the
[spreadsheet analysis](511-station-spreadsheet.md). This does not change the
finding that these fields are absent from the waveform headers. The spreadsheet
does not specify a coordinate datum or instrument response.

Obtain a StationXML file, dataless/full SEED metadata, or the deployment station
table from the data provider. Match it by network, station, location, channel,
and validity dates covering 2026-10-02/03. It should provide latitude, longitude,
elevation, coordinate reference system, channel azimuth/dip, instrument response,
and sensitivity/units. No companion metadata file was available during the
original waveform audit; the spreadsheet was subsequently supplied.

`511/outputs/metadata/stations.csv` enumerates all 20 stations with coordinates
left blank and an explicit missing-metadata status. Do not fill these with zero
or infer them from the station numbering. `metadata.json` contains the per-file
and aggregate record audits. Generated reports are ignored by Git.

To reproduce from the repository root:

```bash
511/.venv/bin/python 511/inspect_metadata.py
```

The auditor supports MiniSEED 2 data files with a fixed record size and header
byte order within each file. It validates record sizes, blockette counts and
chains, and blockette 1000 word order. It fails rather than silently interpreting
full SEED, MiniSEED 3, partial records, or mixed record sizes/byte orders.

Reference: [FDSN SEED 2.4 manual](https://www.fdsn.org/pdf/SEEDManual_V2.4.pdf),
chapter 6 (station metadata), chapter 8 (data headers), and appendix G (MiniSEED).
