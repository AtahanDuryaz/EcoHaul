CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS bins (
    id SERIAL PRIMARY KEY,
    bin_id TEXT UNIQUE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    region TEXT NOT NULL,
    last_emptied_at TIMESTAMP NULL,
    -- IoT-related fields
    fill_level TEXT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_seen_at TIMESTAMP NULL,
    -- last enum transition summary, e.g. "EMPTY->FULL"
    last_enum_transition TEXT NULL,
    last_enum_change_at TIMESTAMP NULL,
    -- last anomaly summary (optional)
    last_event_type TEXT NULL,
    last_event_at TIMESTAMP NULL,
    geom GEOGRAPHY(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry (
    id SERIAL PRIMARY KEY,
    bin_id TEXT NOT NULL,
    enum_state TEXT NOT NULL,
    raw_distance_cm DOUBLE PRECISION NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bins_status ON bins(status);
CREATE INDEX IF NOT EXISTS idx_bins_region ON bins(region);
CREATE INDEX IF NOT EXISTS idx_bins_geom ON bins USING GIST(geom);
CREATE INDEX IF NOT EXISTS idx_telemetry_bin_id_created_at ON telemetry(bin_id, created_at DESC);

-- Ensure new columns exist when migrating an existing database
ALTER TABLE bins ADD COLUMN IF NOT EXISTS last_event_type TEXT NULL;
ALTER TABLE bins ADD COLUMN IF NOT EXISTS last_event_at TIMESTAMP NULL;

CREATE TABLE IF NOT EXISTS event_log (
    id SERIAL PRIMARY KEY,
    bin_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_event_log_bin_id_created_at
    ON event_log(bin_id, created_at DESC);
