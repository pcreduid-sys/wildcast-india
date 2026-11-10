"""Database access layer. Every dashboard page reads through these functions."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import pandas as pd

from config import settings
from database.schema import SCHEMA

DATA_SOURCES = [
    ("NASA_POWER", "NASA POWER (daily temperature & precipitation)", "Weather",
     "https://power.larc.nasa.gov/"),
    ("NASA_FIRMS", "NASA FIRMS (VIIRS/MODIS active fire)", "Fire",
     "https://firms.modaps.eosdis.nasa.gov/"),
    ("MODIS_NDVI", "MODIS MOD13Q1 NDVI (ORNL DAAC subsets)", "Vegetation",
     "https://modis.ornl.gov/data/modis_webservice.html"),
    ("GBIF", "GBIF occurrence API (all animal taxa)", "Wildlife", "https://www.gbif.org/"),
    ("INAT", "iNaturalist API (research-grade observations)", "Wildlife", "https://www.inaturalist.org/"),
    ("EBIRD", "eBird API 2.0 (recent bird observations)", "Wildlife", "https://ebird.org/"),
    ("IUCN", "IUCN Red List API v4 (assessment dates)", "Wildlife", "https://api.iucnredlist.org/"),
    ("POP_OFFICIAL", "Official population estimates (NTCA/WII, state forest departments)", "Wildlife",
     "https://ntca.gov.in/"),
    ("WATER_DEMO", "Illustrative water bodies & water observations (SIMULATED)", "Water", None),
    ("UPLOADS", "User uploads (CSV / GeoJSON)", "Upload", None),
    ("DEMO", "Demonstration dataset (deterministic simulation)", "Demo", None),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def connect(path=None) -> sqlite3.Connection:
    path = path or settings.DB_PATH
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(path=None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def query_df(sql: str, params=(), path=None) -> pd.DataFrame:
    with get_conn(path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


# --------------------------------------------------------------------------- init
def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Coverage columns added for completeness tracking (fire data coverage window)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(data_sources)")}
    for col in ("coverage_start", "coverage_end"):
        if col not in cols:
            conn.execute(f"ALTER TABLE data_sources ADD COLUMN {col} TEXT")
    for key, name, cat, url in DATA_SOURCES:
        conn.execute(
            "INSERT OR IGNORE INTO data_sources(source_key,name,category,url,status,message) "
            "VALUES (?,?,?,?,?,?)",
            (key, name, cat, url, "NOT RUN", "No attempt yet"),
        )


def load_reserves(conn: sqlite3.Connection) -> None:
    df = pd.read_csv(settings.SAMPLE_RESERVES_CSV)
    for r in df.itertuples(index=False):
        conn.execute(
            """INSERT INTO protected_areas(pa_id,name,state,designation,latitude,longitude,area_km2,
               area_basis,established,ecosystem,fire_profile) VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(pa_id) DO UPDATE SET name=excluded.name, state=excluded.state,
               designation=excluded.designation, latitude=excluded.latitude,
               longitude=excluded.longitude, area_km2=excluded.area_km2,
               area_basis=excluded.area_basis, established=excluded.established,
               ecosystem=excluded.ecosystem, fire_profile=excluded.fire_profile""",
            (r.pa_id, r.name, r.state, r.designation, r.latitude, r.longitude, r.area_km2,
             r.area_basis, int(r.established), r.ecosystem, r.fire_profile),
        )


def is_initialised(path=None) -> bool:
    try:
        with get_conn(path) as conn:
            n = conn.execute("SELECT COUNT(*) FROM habitat_stress_scores").fetchone()[0]
            return n > 0
    except sqlite3.DatabaseError:
        return False


def init_db(path=None, reset: bool = False) -> None:
    """Create schema, load reserves and seed the deterministic demo dataset once."""
    from ingestion.demo_data import seed_demo_data
    from processing.pipeline import rebuild_derived

    path = path or settings.DB_PATH
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    if reset and path.exists():
        path.unlink()
    with get_conn(path) as conn:
        create_schema(conn)
        load_reserves(conn)
        has_weather = conn.execute("SELECT COUNT(*) FROM weather_observations").fetchone()[0]
        if not has_weather:
            seed_demo_data(conn)
        from processing.wildlife import load_reference_data
        n_pop = conn.execute("SELECT COUNT(*) FROM population_estimates").fetchone()[0]
        load_reference_data(conn)
        if not n_pop:
            n = conn.execute("SELECT COUNT(*) FROM population_estimates").fetchone()[0]
            update_source(conn, "POP_OFFICIAL", True, f"{n} cited official estimates loaded from "
                          "data/population_estimates.csv", records=n, status="OK")
        if not conn.execute("SELECT COUNT(*) FROM water_bodies").fetchone()[0]:
            from ingestion.water_demo import seed_water_demo
            seed_water_demo(conn)
    if not is_initialised(path):
        rebuild_derived(path)
    else:
        with get_conn(path) as conn:
            has_wa = conn.execute("SELECT COUNT(*) FROM water_assessments").fetchone()[0]
        if not has_wa:
            from processing.pipeline import rebuild_water
            rebuild_water(path)


# --------------------------------------------------------------------------- reads
def get_reserves(path=None) -> pd.DataFrame:
    return query_df("SELECT * FROM protected_areas ORDER BY name", path=path)


def get_weather(pa_id: str | None = None, start: str | None = None, end: str | None = None,
                path=None) -> pd.DataFrame:
    sql, p = "SELECT * FROM weather_observations WHERE 1=1", []
    if pa_id:
        sql += " AND pa_id=?"; p.append(pa_id)
    if start:
        sql += " AND obs_date>=?"; p.append(start)
    if end:
        sql += " AND obs_date<=?"; p.append(end)
    df = query_df(sql + " ORDER BY pa_id, obs_date", p, path)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def get_ndvi(pa_id: str | None = None, start: str | None = None, path=None) -> pd.DataFrame:
    sql, p = "SELECT * FROM vegetation_observations WHERE 1=1", []
    if pa_id:
        sql += " AND pa_id=?"; p.append(pa_id)
    if start:
        sql += " AND obs_date>=?"; p.append(start)
    df = query_df(sql + " ORDER BY pa_id, obs_date", p, path)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def get_fires(start: str | None = None, end: str | None = None, pa_ids=None, states=None,
              inside_only: bool = False, path=None) -> pd.DataFrame:
    sql = ("SELECT f.*, p.name AS reserve, p.state FROM fire_detections f "
           "LEFT JOIN protected_areas p ON p.pa_id=f.pa_id WHERE 1=1")
    p: list = []
    if start:
        sql += " AND f.acq_date>=?"; p.append(start)
    if end:
        sql += " AND f.acq_date<=?"; p.append(end)
    if pa_ids:
        sql += f" AND f.pa_id IN ({','.join('?'*len(pa_ids))})"; p += list(pa_ids)
    if states:
        sql += f" AND p.state IN ({','.join('?'*len(states))})"; p += list(states)
    if inside_only:
        sql += " AND f.inside_boundary=1"
    df = query_df(sql + " ORDER BY f.acq_date DESC, f.acq_time DESC", p, path)
    df["acq_date"] = pd.to_datetime(df["acq_date"])
    return df


def latest_data_date(path=None) -> pd.Timestamp:
    with get_conn(path) as conn:
        d = conn.execute("SELECT MAX(week_end) FROM habitat_stress_scores").fetchone()[0]
    return pd.Timestamp(d) if d else pd.Timestamp.today().normalize()


def get_scores(pa_id: str | None = None, path=None) -> pd.DataFrame:
    sql = ("SELECT s.*, p.name, p.state FROM habitat_stress_scores s "
           "JOIN protected_areas p ON p.pa_id=s.pa_id")
    p: list = []
    if pa_id:
        sql += " WHERE s.pa_id=?"; p.append(pa_id)
    df = query_df(sql + " ORDER BY s.week_end", p, path)
    df["week_end"] = pd.to_datetime(df["week_end"])
    return df


def get_latest_scores(path=None) -> pd.DataFrame:
    df = query_df(
        """SELECT s.*, p.name, p.state, p.latitude, p.longitude, p.area_km2, p.boundary_source
           FROM habitat_stress_scores s JOIN protected_areas p ON p.pa_id=s.pa_id
           WHERE s.week_end=(SELECT MAX(week_end) FROM habitat_stress_scores WHERE pa_id=s.pa_id)
           ORDER BY s.total_score DESC""", path=path)
    df["week_end"] = pd.to_datetime(df["week_end"])
    return df


def get_alerts(include_ack: bool = True, path=None) -> pd.DataFrame:
    sql = ("SELECT a.*, p.name AS reserve, p.state FROM alerts a "
           "JOIN protected_areas p ON p.pa_id=a.pa_id")
    if not include_ack:
        sql += " WHERE a.acknowledged=0"
    sql += (" ORDER BY a.acknowledged, CASE a.severity WHEN 'Severe' THEN 0 WHEN 'High' THEN 1 "
            "WHEN 'Moderate' THEN 2 ELSE 3 END, a.period_key DESC")
    return query_df(sql, path=path)


def acknowledge_alerts(alert_ids, user: str, path=None) -> int:
    ids = [int(i) for i in alert_ids]
    if not ids:
        return 0
    with get_conn(path) as conn:
        cur = conn.execute(
            f"UPDATE alerts SET acknowledged=1, acknowledged_by=?, acknowledged_at=? "
            f"WHERE alert_id IN ({','.join('?'*len(ids))}) AND acknowledged=0",
            [user or "analyst", now_iso(), *ids])
        return cur.rowcount


def get_data_sources(path=None) -> pd.DataFrame:
    return query_df("SELECT * FROM data_sources ORDER BY category", path=path)


def record_counts(path=None) -> pd.DataFrame:
    tables = ["weather_observations", "vegetation_observations", "fire_detections",
              "wildlife_observations", "population_estimates", "water_bodies", "water_observations"]
    rows = []
    with get_conn(path) as conn:
        for t in tables:
            for st, n in conn.execute(f"SELECT source_type, COUNT(*) FROM {t} GROUP BY source_type"):
                rows.append({"table": t, "source_type": st, "records": n})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- writes
def update_source(conn, key: str, ok: bool | None, message: str, records: int = 0,
                  status: str | None = None, coverage: tuple[str, str] | None = None) -> None:
    ts = now_iso()
    status = status or ("OK" if ok else "FAILED")
    conn.execute(
        "UPDATE data_sources SET status=?, last_attempt=?, message=?, "
        "records=COALESCE(records,0)+?, last_success=CASE WHEN ? THEN ? ELSE last_success END "
        "WHERE source_key=?",
        (status, ts, message, records if ok else 0, 1 if ok else 0, ts, key))
    if coverage and ok:
        conn.execute(
            "UPDATE data_sources SET coverage_start=CASE WHEN coverage_start IS NULL OR coverage_start>? "
            "THEN ? ELSE coverage_start END, coverage_end=CASE WHEN coverage_end IS NULL OR coverage_end<? "
            "THEN ? ELSE coverage_end END WHERE source_key=?",
            (coverage[0], coverage[0], coverage[1], coverage[1], key))


def fire_coverage(path=None) -> list[tuple[str, str]]:
    """Date windows for which fire data was actually retrieved (any source)."""
    df = query_df("SELECT coverage_start, coverage_end FROM data_sources "
                  "WHERE category IN ('Fire','Demo','Upload') AND coverage_start IS NOT NULL", path=path)
    return list(df.itertuples(index=False, name=None))


def upsert_weather(conn, df: pd.DataFrame) -> int:
    rows = [(r.pa_id, str(pd.Timestamp(r.obs_date).date()), _f(r.tmax_c), _f(r.tmean_c),
             _f(r.precip_mm), r.source, r.source_type, now_iso()) for r in df.itertuples()]
    conn.executemany(
        "INSERT OR REPLACE INTO weather_observations VALUES (?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def upsert_ndvi(conn, df: pd.DataFrame) -> int:
    rows = [(r.pa_id, str(pd.Timestamp(r.obs_date).date()), _f(r.ndvi), r.source,
             r.source_type, now_iso()) for r in df.itertuples()]
    conn.executemany("INSERT OR REPLACE INTO vegetation_observations VALUES (?,?,?,?,?,?)", rows)
    return len(rows)


def insert_fires(conn, df: pd.DataFrame) -> int:
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO fire_detections(pa_id,latitude,longitude,acq_date,acq_time,satellite,
           instrument,confidence,frp,daynight,inside_boundary,source,source_type,ingested_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(r.pa_id if isinstance(r.pa_id, str) else None, float(r.latitude), float(r.longitude),
          str(pd.Timestamp(r.acq_date).date()), str(r.acq_time), str(r.satellite),
          str(r.instrument), str(r.confidence), _f(r.frp), str(r.daynight),
          int(r.inside_boundary), r.source, r.source_type, now_iso()) for r in df.itertuples()])
    return conn.total_changes - before


def set_boundary(conn, pa_id: str, geojson: str, source: str) -> None:
    conn.execute("UPDATE protected_areas SET boundary_geojson=?, boundary_source=? WHERE pa_id=?",
                 (geojson, source, pa_id))


def _f(v):
    try:
        v = float(v)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- wildlife reads
def get_species(path=None) -> pd.DataFrame:
    return query_df(
        """SELECT s.*, COALESCE(r.n_records,0) AS n_records, COALESCE(r.n_reserves,0) AS n_reserves,
                  r.first_date, r.last_date
           FROM species s LEFT JOIN (SELECT scientific_name, SUM(n_records) n_records, COUNT(*) n_reserves,
                  MIN(first_date) first_date, MAX(last_date) last_date FROM species_reserve
                  GROUP BY scientific_name) r ON r.scientific_name=s.scientific_name
           ORDER BY n_records DESC, s.scientific_name""", path=path)


def get_observations(pa_ids=None, species=None, start=None, end=None, path=None) -> pd.DataFrame:
    sql = ("SELECT o.*, s.common_name, s.taxon_group, s.family, s.iucn_category, p.name AS reserve, p.state "
           "FROM wildlife_observations o JOIN species s ON s.scientific_name=o.scientific_name "
           "LEFT JOIN protected_areas p ON p.pa_id=o.pa_id WHERE 1=1")
    prm: list = []
    if pa_ids:
        sql += f" AND o.pa_id IN ({','.join('?'*len(pa_ids))})"; prm += list(pa_ids)
    if species:
        species = [species] if isinstance(species, str) else list(species)
        sql += f" AND o.scientific_name IN ({','.join('?'*len(species))})"; prm += species
    if start:
        sql += " AND o.obs_date>=?"; prm.append(str(start))
    if end:
        sql += " AND o.obs_date<=?"; prm.append(str(end))
    df = query_df(sql + " ORDER BY o.obs_date DESC", prm, path)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def get_species_reserve(path=None) -> pd.DataFrame:
    return query_df(
        """SELECT sr.*, s.common_name, s.taxon_group, s.iucn_category, s.family, p.name AS reserve, p.state
           FROM species_reserve sr JOIN species s ON s.scientific_name=sr.scientific_name
           JOIN protected_areas p ON p.pa_id=sr.pa_id""", path=path)


def get_population(path=None) -> pd.DataFrame:
    return query_df(
        """SELECT e.*, s.common_name, s.iucn_category, p.name AS reserve, p.state
           FROM population_estimates e JOIN species s ON s.scientific_name=e.scientific_name
           LEFT JOIN protected_areas p ON p.pa_id=e.pa_id ORDER BY e.scientific_name, e.scope, e.survey_year""",
        path=path)


# --------------------------------------------------------------------------- water reads
def get_water_bodies(path=None) -> pd.DataFrame:
    return query_df("""SELECT w.*, p.name AS reserve, p.state FROM water_bodies w
                       JOIN protected_areas p ON p.pa_id=w.pa_id ORDER BY w.pa_id, w.wb_id""", path=path)


def get_water_obs(wb_id: str | None = None, path=None) -> pd.DataFrame:
    sql, prm = "SELECT * FROM water_observations", []
    if wb_id:
        sql += " WHERE wb_id=?"; prm.append(wb_id)
    df = query_df(sql + " ORDER BY wb_id, metric, obs_date", prm, path)
    df["obs_date"] = pd.to_datetime(df["obs_date"])
    return df


def get_water_assessments(week_end: str | None = None, path=None) -> pd.DataFrame:
    sql = ("SELECT a.*, w.name, w.wb_type, w.permanence, w.latitude, w.longitude, w.location_basis, w.source_type, "
           "w.pa_id, p.name AS reserve, p.state FROM water_assessments a JOIN water_bodies w ON w.wb_id=a.wb_id "
           "JOIN protected_areas p ON p.pa_id=w.pa_id")
    prm = []
    if week_end:
        sql += " WHERE a.week_end=?"; prm.append(week_end)
    df = query_df(sql + " ORDER BY a.week_end, a.priority_score DESC", prm, path)
    df["week_end"] = pd.to_datetime(df["week_end"])
    return df
