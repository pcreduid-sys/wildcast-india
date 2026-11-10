"""Recompute derived tables (scores, alerts) from raw observations in SQLite."""
from __future__ import annotations

import pandas as pd

from config import settings
from database import db
from processing import alerts as alert_mod
from processing.geospatial import assign_fires
from processing.stress_scoring import score_reserve_history

SCORE_COLS = ["pa_id", "week_end", "heat_score", "drought_score", "vegetation_score", "fire_score",
              "total_score", "category", "completeness", "provisional", "tmax_anomaly_c", "hot_days",
              "rain_90d_mm", "rain_normal_mm", "deficit_pct", "ndvi", "ndvi_baseline",
              "ndvi_change_pct", "fire_count_7d"]


def reassign_fire_reserves(path=None) -> None:
    """Re-run point-in-footprint assignment (after boundary uploads)."""
    reserves = db.get_reserves(path)
    fires = db.query_df("SELECT fire_id, latitude, longitude FROM fire_detections", path=path)
    if fires.empty:
        return
    f = assign_fires(fires, reserves)
    with db.get_conn(path) as conn:
        conn.executemany("UPDATE fire_detections SET pa_id=?, inside_boundary=? WHERE fire_id=?",
                         [(r.pa_id if isinstance(r.pa_id, str) else None, int(r.inside_boundary),
                           int(r.fire_id)) for r in f.itertuples()])


def rebuild_derived(path=None, cfg: dict | None = None) -> dict:
    cfg = cfg or settings.load_scoring_config()
    reserves = db.get_reserves(path)
    weather = db.get_weather(path=path)
    ndvi = db.get_ndvi(path=path)
    fires = db.get_fires(path=path)
    coverage = db.fire_coverage(path)
    end = weather["obs_date"].max() if not weather.empty else pd.Timestamp.today().normalize()
    week_ends = list(pd.date_range(end=end, periods=settings.SCORE_HISTORY_WEEKS, freq="7D"))

    rows = []
    for pa in reserves["pa_id"]:
        rows += score_reserve_history(
            pa, weather[weather["pa_id"] == pa], ndvi[ndvi["pa_id"] == pa],
            fires[fires["pa_id"] == pa], week_ends, cfg, coverage)
    scores = pd.DataFrame(rows)
    with db.get_conn(path) as conn:
        conn.execute("DELETE FROM habitat_stress_scores")
        ts = db.now_iso()
        conn.executemany(
            f"INSERT INTO habitat_stress_scores({','.join(SCORE_COLS)},computed_at) "
            f"VALUES ({','.join('?'*(len(SCORE_COLS)+1))})",
            [tuple(_clean(r[c]) for c in SCORE_COLS) + (ts,) for r in rows])
        scores["week_end"] = pd.to_datetime(scores["week_end"])
        n_alerts = alert_mod.write_alerts(conn, alert_mod.build_alerts(scores, fires, cfg))
    n_water = rebuild_water(path, weather=weather, fires=fires, end=end)
    return {"scores": len(rows), "alerts_changed": n_alerts, "week_end": str(end.date()), "water": n_water}


WATER_COLS = ["wb_id", "week_end", "category", "evidence", "availability_ratio", "latest_direct_date",
              "latest_satellite_date", "rain_30d_mm", "rain_30d_normal", "deficit_30d_pct", "rain_60d_mm",
              "rain_60d_normal", "deficit_60d_pct", "rain_90d_mm", "rain_90d_normal", "deficit_90d_pct",
              "tmax_anomaly_30d", "ndvi_buffer", "ndvi_buffer_change_pct", "fires_5km_30d", "p_water", "p_rain",
              "p_heat", "p_veg", "p_fire", "p_uncertainty", "priority_score", "priority_band"]
WATER_WEEKS = 26


def rebuild_water(path=None, weather=None, fires=None, end=None) -> int:
    """Recompute weekly water-availability assessments and monitoring priorities."""
    from processing.water import assess_water_bodies
    wbs = db.get_water_bodies(path)
    if wbs.empty:
        with db.get_conn(path) as conn:
            conn.execute("DELETE FROM water_assessments")
        return 0
    weather = db.get_weather(path=path) if weather is None else weather
    fires = db.get_fires(path=path) if fires is None else fires
    if end is None:
        end = weather["obs_date"].max() if not weather.empty else pd.Timestamp.today().normalize()
    week_ends = list(pd.date_range(end=end, periods=WATER_WEEKS, freq="7D"))
    rows = assess_water_bodies(wbs, db.get_water_obs(path=path), weather, fires, week_ends)
    with db.get_conn(path) as conn:
        conn.execute("DELETE FROM water_assessments")
        ts = db.now_iso()
        conn.executemany(
            f"INSERT INTO water_assessments({','.join(WATER_COLS)},computed_at) "
            f"VALUES ({','.join('?' * (len(WATER_COLS) + 1))})",
            [tuple(_clean(r[c]) for c in WATER_COLS) + (ts,) for r in rows])
    return len(rows)


def _clean(v):
    if v is None:
        return None
    try:
        if v != v:
            return None
    except TypeError:
        pass
    return v.item() if hasattr(v, "item") else v
