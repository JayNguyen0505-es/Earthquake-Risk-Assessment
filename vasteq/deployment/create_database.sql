-- VAST-Earthquake: approved eight-table bootstrap schema, MySQL 8.4.
-- Run explicitly; this file is not mounted into Docker's initialization folder.
-- No credentials, seed accounts, or destructive statements are included.
-- IF NOT EXISTS supports repeat execution but does not migrate existing tables.

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;
SET time_zone = '+00:00';

CREATE DATABASE IF NOT EXISTS vasteq
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE vasteq;

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    role ENUM('admin', 'user', 'guest') NOT NULL DEFAULT 'user',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_email (email),
    CONSTRAINT ck_users_email CHECK (CHAR_LENGTH(TRIM(email)) > 0),
    CONSTRAINT ck_users_password_hash CHECK (CHAR_LENGTH(password_hash) > 0),
    CONSTRAINT ck_users_enabled CHECK (enabled IN (0, 1))
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS stations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    network_code VARCHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    station_code VARCHAR(5) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(120) NULL,
    city VARCHAR(120) NULL,
    province VARCHAR(120) NULL,
    instrument_type VARCHAR(64) NULL,
    instrument_serial VARCHAR(64) NULL,
    coordinate_crs VARCHAR(64) NULL COMMENT 'NULL when the source does not specify a CRS',
    latitude DECIMAL(9,6) NULL COMMENT 'Geographic degrees; datum recorded in coordinate_crs',
    longitude DECIMAL(10,6) NULL COMMENT 'Geographic degrees; datum recorded in coordinate_crs',
    elevation_m DECIMAL(10,3) NULL,
    metadata_uri VARCHAR(1024) NULL,
    metadata_source VARCHAR(255) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_stations_codes (network_code, station_code),
    KEY ix_stations_city (city),
    KEY ix_stations_province (province),
    CONSTRAINT ck_stations_codes CHECK (
        CHAR_LENGTH(TRIM(network_code)) > 0 AND CHAR_LENGTH(TRIM(station_code)) > 0
    ),
    CONSTRAINT ck_stations_coordinate_pair CHECK (
        (latitude IS NULL AND longitude IS NULL) OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    ),
    CONSTRAINT ck_stations_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_stations_longitude CHECK (longitude BETWEEN -180 AND 180)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS channels (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    station_id BIGINT UNSIGNED NOT NULL,
    location_code VARCHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
    channel_code VARCHAR(3) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    sample_rate_hz DOUBLE NOT NULL,
    azimuth_deg DOUBLE NULL,
    dip_deg DOUBLE NULL,
    response_uri VARCHAR(1024) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_channels_stream (station_id, location_code, channel_code),
    CONSTRAINT fk_channels_station FOREIGN KEY (station_id) REFERENCES stations (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_channels_code CHECK (CHAR_LENGTH(TRIM(channel_code)) = 3),
    CONSTRAINT ck_channels_sample_rate CHECK (sample_rate_hz > 0),
    CONSTRAINT ck_channels_azimuth CHECK (azimuth_deg >= 0 AND azimuth_deg < 360),
    CONSTRAINT ck_channels_dip CHECK (dip_deg BETWEEN -90 AND 90)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS waveform_files (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    storage_uri VARCHAR(1024) NOT NULL,
    sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    size_bytes BIGINT UNSIGNED NOT NULL,
    format VARCHAR(16) NOT NULL DEFAULT 'MSEED',
    source VARCHAR(255) NULL,
    start_time DATETIME(6) NOT NULL,
    end_time DATETIME(6) NOT NULL,
    trace_metadata JSON NOT NULL COMMENT 'Trace IDs, rates, segments, gaps, overlaps and provenance; no waveform samples',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_waveform_files_sha256 (sha256),
    KEY ix_waveform_files_time (start_time, end_time),
    CONSTRAINT ck_waveform_files_uri CHECK (CHAR_LENGTH(TRIM(storage_uri)) > 0),
    CONSTRAINT ck_waveform_files_sha256 CHECK (CHAR_LENGTH(sha256) = 64),
    CONSTRAINT ck_waveform_files_size CHECK (size_bytes > 0),
    CONSTRAINT ck_waveform_files_time CHECK (end_time >= start_time)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS seismic_events (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    catalog_source VARCHAR(120) NOT NULL,
    external_event_id VARCHAR(120) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    origin_time DATETIME(6) NULL,
    latitude DECIMAL(9,6) NULL,
    longitude DECIMAL(10,6) NULL,
    depth_km DOUBLE NULL COMMENT 'Depth relative to catalog datum; may be negative',
    magnitude DOUBLE NULL,
    magnitude_type VARCHAR(16) NULL,
    provenance JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_seismic_events_catalog (catalog_source, external_event_id),
    KEY ix_seismic_events_origin_time (origin_time),
    CONSTRAINT ck_seismic_events_identity CHECK (
        CHAR_LENGTH(TRIM(catalog_source)) > 0 AND CHAR_LENGTH(TRIM(external_event_id)) > 0
    ),
    CONSTRAINT ck_seismic_events_coordinate_pair CHECK (
        (latitude IS NULL AND longitude IS NULL) OR
        (latitude IS NOT NULL AND longitude IS NOT NULL)
    ),
    CONSTRAINT ck_seismic_events_latitude CHECK (latitude BETWEEN -90 AND 90),
    CONSTRAINT ck_seismic_events_longitude CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_seismic_events_magnitude_type CHECK (
        magnitude IS NULL OR (magnitude_type IS NOT NULL AND CHAR_LENGTH(TRIM(magnitude_type)) > 0)
    )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS models (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    code VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(120) NOT NULL,
    task VARCHAR(64) NOT NULL,
    work_package VARCHAR(16) NOT NULL,
    artifact_uri VARCHAR(1024) NOT NULL,
    artifact_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    input_schema JSON NOT NULL,
    output_schema JSON NOT NULL,
    training_metadata JSON NULL,
    evaluation_metrics JSON NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    UNIQUE KEY uq_models_code_version (code, version),
    KEY ix_models_task (task),
    CONSTRAINT ck_models_identity CHECK (
        CHAR_LENGTH(TRIM(code)) > 0 AND CHAR_LENGTH(TRIM(version)) > 0
    ),
    CONSTRAINT ck_models_artifact CHECK (
        CHAR_LENGTH(TRIM(artifact_uri)) > 0 AND CHAR_LENGTH(artifact_sha256) = 64
    )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS model_runs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    model_id BIGINT UNSIGNED NOT NULL COMMENT 'References an exact model version',
    requested_by_user_id BIGINT UNSIGNED NULL,
    event_id BIGINT UNSIGNED NULL,
    status ENUM('queued', 'running', 'succeeded', 'failed', 'cancelled') NOT NULL DEFAULT 'queued',
    input_parameters JSON NOT NULL COMMENT 'File IDs/checksums, preprocessing, metadata snapshots and parameters',
    result JSON NULL COMMENT 'Predicted events/parameters and uncertainty; separate from catalog values',
    error_message TEXT NULL,
    queued_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    started_at DATETIME(6) NULL,
    finished_at DATETIME(6) NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY ix_model_runs_queue (status, queued_at),
    KEY ix_model_runs_model (model_id, queued_at),
    KEY ix_model_runs_user (requested_by_user_id, queued_at),
    KEY ix_model_runs_event (event_id),
    CONSTRAINT fk_model_runs_model FOREIGN KEY (model_id) REFERENCES models (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_model_runs_user FOREIGN KEY (requested_by_user_id) REFERENCES users (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_model_runs_event FOREIGN KEY (event_id) REFERENCES seismic_events (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_model_runs_start CHECK (started_at IS NULL OR started_at >= queued_at),
    CONSTRAINT ck_model_runs_finish CHECK (
        finished_at IS NULL OR
        (finished_at >= queued_at AND (started_at IS NULL OR finished_at >= started_at))
    )
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS phase_picks (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    channel_id BIGINT UNSIGNED NOT NULL,
    waveform_file_id BIGINT UNSIGNED NULL,
    event_id BIGINT UNSIGNED NULL,
    model_run_id BIGINT UNSIGNED NULL,
    phase VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    arrival_time DATETIME(6) NOT NULL,
    probability DOUBLE NULL,
    uncertainty_seconds DOUBLE NULL,
    source VARCHAR(120) NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (id),
    KEY ix_phase_picks_channel_time (channel_id, arrival_time),
    KEY ix_phase_picks_file (waveform_file_id),
    KEY ix_phase_picks_event (event_id, arrival_time),
    KEY ix_phase_picks_run (model_run_id),
    CONSTRAINT fk_phase_picks_channel FOREIGN KEY (channel_id) REFERENCES channels (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_phase_picks_file FOREIGN KEY (waveform_file_id) REFERENCES waveform_files (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_phase_picks_event FOREIGN KEY (event_id) REFERENCES seismic_events (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_phase_picks_run FOREIGN KEY (model_run_id) REFERENCES model_runs (id)
        ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT ck_phase_picks_phase CHECK (CHAR_LENGTH(TRIM(phase)) > 0),
    CONSTRAINT ck_phase_picks_source CHECK (CHAR_LENGTH(TRIM(source)) > 0),
    CONSTRAINT ck_phase_picks_probability CHECK (probability BETWEEN 0 AND 1),
    CONSTRAINT ck_phase_picks_uncertainty CHECK (uncertainty_seconds >= 0)
) ENGINE=InnoDB;
