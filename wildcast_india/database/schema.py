"""SQLite schema for WILDCAST INDIA."""

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS protected_areas (
    pa_id              TEXT PRIMARY KEY,
    name               TEXT NOT NULL UNIQUE,
    state              TEXT NOT NULL,
    designation        TEXT,
    latitude           REAL NOT NULL,
    longitude          REAL NOT NULL,
    area_km2           REAL,
    area_basis         TEXT,
    established        INTEGER,
    ecosystem          TEXT,
    fire_profile       TEXT,
    boundary_geojson   TEXT,              -- uploaded polygon (GeoJSON geometry); NULL if none
    boundary_source    TEXT DEFAULT 'APPROXIMATE_BUFFER'
);

CREATE TABLE IF NOT EXISTS weather_observations (
    pa_id        TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    obs_date     TEXT NOT NULL,            -- ISO date
    tmax_c       REAL,
    tmean_c      REAL,
    precip_mm    REAL,
    source       TEXT NOT NULL,            -- e.g. NASA POWER, Demo generator
    source_type  TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    ingested_at  TEXT NOT NULL,
    PRIMARY KEY (pa_id, obs_date)
);
CREATE INDEX IF NOT EXISTS idx_weather_date ON weather_observations(obs_date);

CREATE TABLE IF NOT EXISTS vegetation_observations (
    pa_id        TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    obs_date     TEXT NOT NULL,
    ndvi         REAL CHECK (ndvi BETWEEN -1 AND 1),
    source       TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    ingested_at  TEXT NOT NULL,
    PRIMARY KEY (pa_id, obs_date)
);
CREATE INDEX IF NOT EXISTS idx_veg_date ON vegetation_observations(obs_date);

CREATE TABLE IF NOT EXISTS fire_detections (
    fire_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pa_id        TEXT REFERENCES protected_areas(pa_id) ON DELETE SET NULL,  -- NULL = outside all reserves
    latitude     REAL NOT NULL,
    longitude    REAL NOT NULL,
    acq_date     TEXT NOT NULL,
    acq_time     TEXT,
    satellite    TEXT,
    instrument   TEXT,
    confidence   TEXT,
    frp          REAL,
    daynight     TEXT,
    inside_boundary INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    ingested_at  TEXT NOT NULL,
    UNIQUE (latitude, longitude, acq_date, acq_time, satellite)
);
CREATE INDEX IF NOT EXISTS idx_fire_date ON fire_detections(acq_date);
CREATE INDEX IF NOT EXISTS idx_fire_pa ON fire_detections(pa_id, acq_date);

CREATE TABLE IF NOT EXISTS habitat_stress_scores (
    pa_id           TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    week_end        TEXT NOT NULL,
    heat_score      REAL,
    drought_score   REAL,
    vegetation_score REAL,
    fire_score      REAL,
    total_score     REAL,
    category        TEXT,
    completeness    REAL NOT NULL,          -- 0..1 share of indicators available
    provisional     INTEGER NOT NULL,
    tmax_anomaly_c  REAL,
    hot_days        INTEGER,
    rain_90d_mm     REAL,
    rain_normal_mm  REAL,
    deficit_pct     REAL,
    ndvi            REAL,
    ndvi_baseline   REAL,
    ndvi_change_pct REAL,
    fire_count_7d   INTEGER,
    computed_at     TEXT NOT NULL,
    PRIMARY KEY (pa_id, week_end)
);
CREATE INDEX IF NOT EXISTS idx_scores_week ON habitat_stress_scores(week_end);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    pa_id          TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    alert_type     TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('Info','Moderate','High','Severe')),
    message        TEXT NOT NULL,
    period_key     TEXT NOT NULL,           -- de-duplication key (e.g. week end)
    created_at     TEXT NOT NULL,
    acknowledged   INTEGER NOT NULL DEFAULT 0,
    acknowledged_by TEXT,
    acknowledged_at TEXT,
    UNIQUE (pa_id, alert_type, period_key)
);
CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts(acknowledged, created_at);

-- ------------------------------------------------------------------ wildlife module
CREATE TABLE IF NOT EXISTS species (
    scientific_name   TEXT PRIMARY KEY,        -- canonical binomial
    common_name       TEXT,
    taxon_group       TEXT NOT NULL,           -- Mammals, Birds, Reptiles, Amphibians, Fish, Insects, ...
    kingdom           TEXT,
    phylum            TEXT,
    class_name        TEXT,
    order_name        TEXT,
    family            TEXT,
    gbif_key          INTEGER,
    inat_taxon_id     INTEGER,
    iucn_category     TEXT CHECK (iucn_category IN ('EX','EW','CR','EN','VU','NT','LC','DD','NE') OR iucn_category IS NULL),
    iucn_assessment_year INTEGER,
    iucn_source       TEXT,
    sensitive         INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_species_group ON species(taxon_group);
CREATE INDEX IF NOT EXISTS idx_species_iucn ON species(iucn_category);

CREATE TABLE IF NOT EXISTS wildlife_observations (
    obs_uid           TEXT PRIMARY KEY,        -- '<source>:<record id>'
    dup_key           TEXT NOT NULL UNIQUE,    -- cross-source duplicate key (e.g. inat:123 for iNat records mirrored in GBIF)
    source            TEXT NOT NULL,           -- GBIF / iNaturalist / eBird / Upload
    record_id         TEXT NOT NULL,
    dataset           TEXT,
    scientific_name   TEXT NOT NULL REFERENCES species(scientific_name) ON DELETE CASCADE,
    pa_id             TEXT REFERENCES protected_areas(pa_id) ON DELETE SET NULL,
    inside_footprint  INTEGER NOT NULL DEFAULT 1,
    latitude          REAL NOT NULL,
    longitude         REAL NOT NULL,
    coords_generalised INTEGER NOT NULL DEFAULT 0,
    coord_uncertainty_m REAL,
    obs_date          TEXT,                    -- ISO date (may be NULL if undated)
    obs_year          INTEGER,
    individual_count  INTEGER,
    basis_of_record   TEXT,
    verification_status TEXT,
    record_url        TEXT,
    source_type       TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    retrieved_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wobs_pa ON wildlife_observations(pa_id, obs_date);
CREATE INDEX IF NOT EXISTS idx_wobs_species ON wildlife_observations(scientific_name);
CREATE INDEX IF NOT EXISTS idx_wobs_date ON wildlife_observations(obs_date);

CREATE TABLE IF NOT EXISTS population_estimates (
    pop_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scientific_name   TEXT NOT NULL REFERENCES species(scientific_name) ON DELETE CASCADE,
    pa_id             TEXT REFERENCES protected_areas(pa_id) ON DELETE SET NULL,
    scope             TEXT NOT NULL,           -- spatial unit the estimate refers to
    estimate          REAL NOT NULL CHECK (estimate >= 0),
    lower_ci          REAL,
    upper_ci          REAL,
    survey_year       INTEGER NOT NULL,
    method            TEXT NOT NULL,
    institution       TEXT NOT NULL,
    source_url        TEXT,
    notes             TEXT,
    source_type       TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    retrieved_at      TEXT NOT NULL,
    UNIQUE (scientific_name, scope, survey_year)
);
CREATE INDEX IF NOT EXISTS idx_pop_pa ON population_estimates(pa_id);

CREATE TABLE IF NOT EXISTS species_reserve (
    pa_id             TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    scientific_name   TEXT NOT NULL REFERENCES species(scientific_name) ON DELETE CASCADE,
    n_records         INTEGER NOT NULL,
    n_sources         INTEGER NOT NULL,
    sources           TEXT,
    first_date        TEXT,
    last_date         TEXT,
    PRIMARY KEY (pa_id, scientific_name)
);

-- ------------------------------------------------------------------ water intelligence
CREATE TABLE IF NOT EXISTS water_bodies (
    wb_id           TEXT PRIMARY KEY,
    pa_id           TEXT NOT NULL REFERENCES protected_areas(pa_id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    wb_type         TEXT NOT NULL,           -- Natural waterhole, Artificial waterhole, River pool, Lake/reservoir, Wetland (beel), Tidal creek, ...
    permanence      TEXT NOT NULL CHECK (permanence IN ('Perennial','Seasonal','Managed (artificial)','Unknown')),
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    location_basis  TEXT NOT NULL CHECK (location_basis IN ('ILLUSTRATIVE','UPLOADED','VERIFIED')),
    source          TEXT NOT NULL,
    source_type     TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    notes           TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE (pa_id, name)
);
CREATE INDEX IF NOT EXISTS idx_wb_pa ON water_bodies(pa_id);

CREATE TABLE IF NOT EXISTS water_observations (
    wb_id        TEXT NOT NULL REFERENCES water_bodies(wb_id) ON DELETE CASCADE,
    obs_date     TEXT NOT NULL,
    metric       TEXT NOT NULL CHECK (metric IN ('water_level_m','water_spread_pct','ndwi','ndvi_buffer','presence')),
    value        REAL NOT NULL,
    unit         TEXT,
    obs_kind     TEXT NOT NULL CHECK (obs_kind IN ('DIRECT','SATELLITE')),  -- weather proxies are computed, never stored
    method       TEXT,
    source       TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('LIVE','HISTORICAL','UPLOADED','SIMULATED')),
    ingested_at  TEXT NOT NULL,
    PRIMARY KEY (wb_id, obs_date, metric)
);
CREATE INDEX IF NOT EXISTS idx_wobs_wb ON water_observations(wb_id, metric, obs_date);

CREATE TABLE IF NOT EXISTS water_assessments (
    wb_id              TEXT NOT NULL REFERENCES water_bodies(wb_id) ON DELETE CASCADE,
    week_end           TEXT NOT NULL,
    category           TEXT NOT NULL,       -- High / Moderate / Low availability, Potential water stress, Insufficient data
    evidence           TEXT NOT NULL,       -- DIRECT / SATELLITE / WEATHER_PROXY / NONE
    availability_ratio REAL,               -- current value relative to seasonal norm
    latest_direct_date TEXT,
    latest_satellite_date TEXT,
    rain_30d_mm REAL, rain_30d_normal REAL, deficit_30d_pct REAL,
    rain_60d_mm REAL, rain_60d_normal REAL, deficit_60d_pct REAL,
    rain_90d_mm REAL, rain_90d_normal REAL, deficit_90d_pct REAL,
    tmax_anomaly_30d REAL,
    ndvi_buffer REAL, ndvi_buffer_change_pct REAL,
    fires_5km_30d INTEGER,
    p_water REAL, p_rain REAL, p_heat REAL, p_veg REAL, p_fire REAL, p_uncertainty REAL,
    priority_score REAL NOT NULL,
    priority_band TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (wb_id, week_end)
);
CREATE INDEX IF NOT EXISTS idx_wass_week ON water_assessments(week_end);

CREATE TABLE IF NOT EXISTS data_sources (
    source_key     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    category       TEXT NOT NULL,
    url            TEXT,
    status         TEXT NOT NULL,           -- OK / FAILED / NOT CONFIGURED / DEMO
    last_attempt   TEXT,
    last_success   TEXT,
    records        INTEGER DEFAULT 0,
    message        TEXT
);
"""
