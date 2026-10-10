-- One-time migration for stations created from the original eight-table script.
-- Fresh databases use the updated create_database.sql instead.
USE vasteq;
ALTER TABLE stations
    ADD COLUMN province VARCHAR(120) NULL AFTER city,
    ADD COLUMN instrument_type VARCHAR(64) NULL AFTER province,
    ADD COLUMN instrument_serial VARCHAR(64) NULL AFTER instrument_type,
    ADD COLUMN coordinate_crs VARCHAR(64) NULL
        COMMENT 'NULL when the source does not specify a CRS' AFTER instrument_serial,
    MODIFY COLUMN latitude DECIMAL(9,6) NULL
        COMMENT 'Geographic degrees; datum recorded in coordinate_crs',
    MODIFY COLUMN longitude DECIMAL(10,6) NULL
        COMMENT 'Geographic degrees; datum recorded in coordinate_crs',
    ADD KEY ix_stations_province (province);
