# Local MySQL

This Docker Compose service runs the official MySQL 8.4 image and initializes an empty
`vasteq` database and a separate `vasteq` application user. The approved
eight-table schema is saved in [create_database.sql](create_database.sql);
it is not automatically installed.

## Start

From the repository root:

```bash
python3 vasteq/deployment/setup_mysql.py
docker compose -f vasteq/deployment/compose.yaml up -d --wait
docker compose -f vasteq/deployment/compose.yaml ps
```

Docker must be installed and the daemon accessible. The setup script generates
separate random root and application passwords in ignored `.secrets/` files and
preserves them on subsequent runs. The Compose secrets are local files, not an
external secrets manager.

The host connection is `127.0.0.1:3306`, database `vasteq`, user `vasteq`.
Read the application password locally from
`vasteq/deployment/.secrets/mysql_app_password` when configuring your SQL client
or backend. A future backend on the same Compose network connects to
`mysql:3306`. Keep credentials out of committed application configuration.

If port 3306 is occupied, start with
`MYSQL_PORT=3307 docker compose -f vasteq/deployment/compose.yaml up -d --wait`
and use port 3307 in the host client. The port is bound only to localhost.

## Open an application SQL session

```bash
docker compose -f vasteq/deployment/compose.yaml exec mysql sh -c \
  'MYSQL_PWD="$(cat /run/secrets/mysql_app_password)" exec mysql --default-character-set=utf8mb4 -u vasteq -D vasteq'
```

The application user has privileges on `vasteq`, not other databases. This is
suitable for local development; production should separate schema migration
credentials from application runtime credentials.

## Storage and lifecycle

To explicitly create the approved tables, run from the repository root:

```bash
docker compose -f vasteq/deployment/compose.yaml exec -T mysql sh -c \
  'MYSQL_PWD="$(cat /run/secrets/mysql_app_password)" exec mysql -u vasteq' \
  < vasteq/deployment/create_database.sql
```

The script creates the database if missing and creates eight tables with foreign
keys, validation constraints, and indexes. It does not create users or insert
sample data. Repeating it preserves existing tables and data; it does not update
existing table definitions. Use versioned migrations for later schema changes.
The Compose application user can run it on the existing `vasteq` database; a
standalone MySQL installation needs credentials with the relevant CREATE privileges.

## Station spreadsheet import

`data/stations.xlsx` supplies 20 stations. The importer expands merged province
cells, reads latitude/longitude by their column headers, validates coordinates
and duplicate codes, and matches network codes from the waveform filenames.
It preserves installation sites in `name`, and imports `province`,
`instrument_type`, and `instrument_serial`. The worksheet does not provide city,
elevation, or a coordinate reference system; these remain unknown for new rows.

Generate the analysis report and transactional upsert script:

```bash
python3 vasteq/deployment/import_stations.py
python3 -m unittest discover -s vasteq/deployment/tests -v
```

Outputs go to ignored `data/derived/stations/`. To apply the generated import
after creating the table:

```bash
docker compose -f vasteq/deployment/compose.yaml exec -T mysql sh -c \
  'MYSQL_PWD="$(cat /run/secrets/mysql_app_password)" exec mysql --default-character-set=utf8mb4 -u vasteq -D vasteq' \
  < data/derived/stations/import.sql
```

Existing installations using the original station columns must apply
[update_station_metadata_columns.sql](update_station_metadata_columns.sql)
once before importing. Fresh installations use the updated
`create_database.sql`; do not run the one-time migration on them.

Re-imports preserve station IDs and existing city/elevation values. Since the
workbook does not specify a CRS, importing its coordinates sets `coordinate_crs`
to NULL instead of retaining an unsupported previous CRS label. Provenance records
the source URI, worksheet row, and workbook SHA-256. Serial numbers are strings.
Confirm the datum with the provider before precise GIS or distance calculations.

The current database has all eight approved tables. Applying `create_database.sql`
preserved the 20 imported station records, including their IDs and timestamps.

Database files persist in the Compose-managed `vasteq_mysql_data` volume.
`docker compose -f vasteq/deployment/compose.yaml down` stops and removes the
container while keeping that volume. Do not add `--volumes` unless you intend
to delete the database. Keep `.secrets/` files across restarts: initialization
variables apply only when creating a new database directory; changing secret
files does not rotate existing database passwords.

The server uses UTF-8 (`utf8mb4`) and UTC. The health check authenticates as the
application user and executes `SELECT 1` against the application database.

Image initialization and `_FILE` variables follow the
[official MySQL image documentation](https://hub.docker.com/_/mysql).
