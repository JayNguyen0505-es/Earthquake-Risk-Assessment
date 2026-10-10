# Database tables and columns

The database contains eight tables. Their SQL definitions are in
[create_database.sql](create_database.sql), and their relationships are shown in
[schema.svg](schema.svg).

All eight tables share these columns:

| Column | Meaning |
| --- | --- |
| `id` | Automatically generated primary key identifying the row |
| `created_at` | Creation time, with microsecond precision |
| `updated_at` | Last modification time; present in all tables except `waveform_files` and `models` |

Times use UTC. **Optional** below means the column permits `NULL`.

## 1. users — accounts and access

| Column | Meaning |
| --- | --- |
| `email` | Unique login email |
| `password_hash` | Password hash; never the plain password |
| `display_name` | Name shown in the interface |
| `role` | `admin`, `user`, or `guest`; defaults to `user` |
| `enabled` | Whether the account is active; defaults to true |

## 2. stations — monitoring station identity and metadata

| Column | Meaning |
| --- | --- |
| `network_code` | Network identifier, currently `VN` |
| `station_code` | Station identifier, such as `4001` |
| `name` | Optional installation site name |
| `city` | Optional city assignment |
| `province` | Optional province, such as Sơn La |
| `instrument_type` | Optional instrument model/type, such as `S303` or `Palert` |
| `instrument_serial` | Optional instrument serial number, stored as text |
| `coordinate_crs` | Optional coordinate reference system/datum |
| `latitude` | Optional latitude in degrees |
| `longitude` | Optional longitude in degrees |
| `elevation_m` | Optional elevation in meters |
| `metadata_uri` | Optional location of the source metadata document |
| `metadata_source` | Optional provenance, including worksheet row and file checksum |

The combination of `network_code` and `station_code` is unique. Latitude and
longitude must be supplied together. `province` and `city` are separate because
the spreadsheet supplies provinces.

## 3. channels — individual streams at a station

| Column | Meaning |
| --- | --- |
| `station_id` | Foreign key linking the channel to `stations` |
| `location_code` | Stream location identifier; defaults to an empty string. It is not geographic coordinates |
| `channel_code` | Three-character identifier, such as `HLE`, `HLN`, or `HLZ` |
| `sample_rate_hz` | Samples per second; must be positive |
| `azimuth_deg` | Optional channel orientation angle |
| `dip_deg` | Optional channel inclination angle |
| `response_uri` | Optional location of instrument response/calibration metadata |

A stream is uniquely identified by `(station_id, location_code, channel_code)`.

## 4. waveform_files — references to recorded data

| Column | Meaning |
| --- | --- |
| `storage_uri` | Location of the waveform file in shared file/object storage |
| `sha256` | Unique file checksum for identification and deduplication |
| `size_bytes` | File size in bytes; must be positive |
| `format` | File format; defaults to `MSEED` |
| `source` | Optional data-provider or acquisition information |
| `start_time` | Earliest waveform time in the file |
| `end_time` | Latest waveform time in the file |
| `trace_metadata` | JSON describing trace IDs, sampling rates, segments, gaps, overlaps, and provenance |

The actual waveform samples remain in the file. The time bounds do **not** imply
uninterrupted recording. One file can contain multiple channels.

## 5. seismic_events — reference earthquake records

| Column | Meaning |
| --- | --- |
| `catalog_source` | Catalog or organization supplying the event |
| `external_event_id` | Event identifier assigned by that source |
| `origin_time` | Optional earthquake origin time |
| `latitude` | Optional earthquake latitude |
| `longitude` | Optional earthquake longitude |
| `depth_km` | Optional depth in kilometers relative to the catalog's datum |
| `magnitude` | Optional magnitude value |
| `magnitude_type` | Optional magnitude scale, such as `ML` or `Mw`; required when magnitude is present |
| `provenance` | Optional JSON containing source details, uncertainties, or review information |

`(catalog_source, external_event_id)` is unique. Model predictions remain separate
from these reference values unless explicitly reviewed and imported.

## 6. models — one row per model version

| Column | Meaning |
| --- | --- |
| `code` | Stable model identifier |
| `version` | Version identifier |
| `name` | Human-readable model name |
| `task` | Task performed, such as phase picking or magnitude estimation |
| `work_package` | Associated work package, such as `5.1.1` |
| `artifact_uri` | Location of the trained model artifact |
| `artifact_sha256` | Artifact checksum |
| `input_schema` | JSON definition of accepted inputs |
| `output_schema` | JSON definition of expected outputs |
| `training_metadata` | Optional JSON describing training data, preprocessing, and configuration |
| `evaluation_metrics` | Optional JSON containing evaluation results |

`(code, version)` is unique. A version used by runs should remain immutable;
publish a new version when the model changes.

## 7. model_runs — inference requests and results

| Column | Meaning |
| --- | --- |
| `model_id` | Foreign key identifying the exact model version executed |
| `requested_by_user_id` | Optional foreign key to the requesting user; can be absent for automated runs |
| `event_id` | Optional foreign key to the earthquake being analyzed |
| `status` | `queued`, `running`, `succeeded`, `failed`, or `cancelled` |
| `input_parameters` | JSON containing parameters, waveform file IDs/checksums, preprocessing, and metadata snapshots |
| `result` | Optional JSON containing predictions and uncertainty |
| `error_message` | Optional failure details |
| `queued_at` | Time the run entered the queue |
| `started_at` | Optional execution start time |
| `finished_at` | Optional execution completion time |

The backend validates file references inside JSON and controls status transitions.
A queued database row alone does not execute a model.

## 8. phase_picks — seismic phase arrival measurements

| Column | Meaning |
| --- | --- |
| `channel_id` | Foreign key identifying the channel where the arrival was observed |
| `waveform_file_id` | Optional foreign key to the corresponding waveform file |
| `event_id` | Optional foreign key to the associated earthquake |
| `model_run_id` | Optional foreign key to the run that produced the pick |
| `phase` | Phase label, such as `P` or `S` |
| `arrival_time` | Arrival time of that phase |
| `probability` | Optional model probability between 0 and 1 |
| `uncertainty_seconds` | Optional nonnegative arrival-time uncertainty |
| `source` | Origin of the pick, such as an analyst, imported catalog, or model |

Manual picks can have no `model_run_id`. Picks can also exist before they are
associated with an earthquake.
