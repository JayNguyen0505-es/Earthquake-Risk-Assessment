# Approved eight-table database structure

The eight-table design is approved. Its MySQL 8.4 bootstrap script is
[deployment/create_database.sql](../../deployment/create_database.sql).
All eight tables are applied to the application database. The `stations` table
contains the 20 records imported from `data/stations.xlsx`.

See the [schema diagram](schema.svg) and [Mermaid source](schema.mmd).
Common creation/update timestamps are omitted from the diagram.

| Table | Responsibility |
| --- | --- |
| `users` | Accounts, password hashes, roles, enabled status |
| `stations` | Network/station identity, installation site, city/province, instrument type/serial, coordinates/CRS, elevation, metadata source |
| `channels` | Station streams, location/channel codes, sample rate, orientation, response URI |
| `waveform_files` | File URI/checksum, size, time bounds, trace and segment metadata JSON |
| `seismic_events` | Catalog/analyst event parameters and provenance |
| `models` | One immutable row per model code/version, artifact and schemas, evaluation metadata |
| `model_runs` | Exact model version, optional user/event, status, input JSON, result JSON, execution times |
| `phase_picks` | Channel, optional waveform file/event/run, phase, arrival time, probability and uncertainty |

## Data rules

- Use InnoDB, UTF-8 (`utf8mb4`), unsigned bigint IDs, and UTC `DATETIME(6)`.
  Set backend connections to UTC too; DATETIME does not store a timezone.
- Station coordinates must be both present or both NULL. `coordinate_crs` records
  the source datum; keep it NULL if unspecified rather than assuming WGS84.
  Unknown city and elevation stay NULL. The workbook's `Tỉnh` maps to `province`,
  not `city`; installation site maps to `name`.
- A channel is unique by station, location code, and channel code. Blank
  location codes are valid and do not represent geographic coordinates.
- Model rows are unique by code/version. Referenced model artifacts and schemas
  should be immutable; publish another version instead of changing one used by runs.
- Waveform records identify immutable raw files. Store trace IDs, segment timing,
  sampling rates, gaps and overlaps in `trace_metadata`, without waveform samples.
  A file can contain multiple channels.
- Run input JSON stores file IDs/checksums, preprocessing configuration, and
  station/channel metadata snapshots. The backend validates references within JSON.
- Predicted event parameters and uncertainties remain in `model_runs.result`.
  Do not overwrite catalog values without an explicit review/import workflow.
- The database enforces foreign keys, unique identities, coordinate ranges,
  positive rates/sizes, timing order, magnitude-type requirements, and pick
  probability/uncertainty ranges. Foreign-key deletion is restrictive.
- The backend validates normalized email and password-hash format, SHA-256
  hexadecimal content, JSON contracts, run-status transitions, and whether a
  pick's channel and time occur within its referenced waveform file.

## Simplifications

City/province live directly on stations; there is no regions table. Current station and
channel metadata replace deployment epochs. Trace/segment metadata, run inputs,
and predicted event estimates use JSON instead of separate tables. Model identity
and version information share one table.

Large waveform/model artifacts and GIS layers remain in file/object storage.
Keep source metadata documents and capture the exact metadata used by each run
for reproducibility. Add station epochs, normalized run inputs/results, and
risk/scenario tables when their query or history requirements are established.

## Initialization

See [deployment instructions](../../deployment/README.md) for the explicit import
command. The script uses `CREATE DATABASE/TABLE IF NOT EXISTS`, adds no accounts
or sample records, and contains no DROP statements. Re-running it preserves data
but does not reconcile existing schema differences. Later changes should use
versioned migrations.

Validated on MySQL 8.4.11 in a temporary database: eight tables, repeated import,
valid linked records across all tables, and rejection of invalid coordinates,
probabilities, missing magnitude types, duplicate station identities, orphan
foreign keys, and deletion of referenced stations. The temporary database was
removed and the application database was unchanged.

The subsequent station import matched all 20 waveform station codes, preserved
IDs on re-import in a temporary database, and verified all imported station names,
province labels, coordinates, instrument types, and serials against the source.
See [station spreadsheet analysis](../../../docs/511-station-spreadsheet.md).
