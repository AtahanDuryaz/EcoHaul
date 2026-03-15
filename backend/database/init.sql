CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS bins (
    id SERIAL PRIMARY KEY,
    bin_id TEXT UNIQUE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    status TEXT NOT NULL DEFAULT 'OFFLINE',
    region TEXT NOT NULL,
    last_emptied_at TIMESTAMP NULL,
    geom GEOGRAPHY(Point, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bins_status ON bins(status);
CREATE INDEX IF NOT EXISTS idx_bins_region ON bins(region);
CREATE INDEX IF NOT EXISTS idx_bins_geom ON bins USING GIST(geom);
