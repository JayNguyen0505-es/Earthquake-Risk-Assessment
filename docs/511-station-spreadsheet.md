# Station spreadsheet analysis

Source: `data/stations.xlsx`, worksheet `Sheet1`.
Workbook SHA-256: `aef3e3d1ac5b9a41c0d25f3a691b1343049b6e926b8cd060d73005708019e8b0`.

The workbook has 20 station rows, each matching a waveform station code under
network `VN`. Three merged province groups expand to:

| Province (`Tỉnh`) | Station codes | Count |
| --- | --- | --- |
| Sơn La | 4001–4007 | 7 |
| Điện Biên | 4008–4014 | 7 |
| Lai Châu | 4015–4020 | 6 |

There are 10 `S303` instruments and 10 `Palert` instruments. Station codes and
serials are unique in the source. Coordinates are decimal degrees with six
decimal places: latitude ranges from 21.208065 to 22.408107, longitude from
102.984729 to 104.016949. Precision in the spreadsheet does not establish the
measurement accuracy or the coordinate datum.

## Mapping to MySQL

| Source | Database field |
| --- | --- |
| Network inferred from matching waveform filenames | `network_code` |
| `Mã trạm` | `station_code` |
| `Địa chỉ lắp đặt` | `name` (installation site) |
| `Tỉnh` | `province` |
| `Vĩ độ` (column D) | `latitude` |
| `Kinh độ` (column E) | `longitude` |
| `Loại máy` | `instrument_type` |
| `Serial` | `instrument_serial` |
| Workbook path, sheet/row, SHA-256 | `metadata_uri`, `metadata_source` |

`STT` is a spreadsheet sequence number, not a database primary key. City,
elevation, coordinate reference system, deployment validity dates, instrument
response, and channel orientation are not supplied. Province must not be
interpreted as a city assignment. Latitude/longitude are imported faithfully;
`coordinate_crs` is NULL until the datum is confirmed.

The `stations` table was absent, so it was created using the updated approved
schema, then populated transactionally. Only that application table was created;
the remaining seven tables were not needed for this import. No station data was
added to the bootstrap schema as seed rows. The raw spreadsheet stays unchanged
and ignored by Git.

Five importer tests passed. A temporary-database trial verified 20 rows, province
counts, and stable station IDs after a second import. Verification against the
application database found exact matches for all 20 station names, province
labels, coordinate pairs, instrument types and serials. Generated SQL and the
complete parsed station report are in ignored `data/derived/stations/`.

Reproduce using [import_stations.py](../vasteq/deployment/import_stations.py).
