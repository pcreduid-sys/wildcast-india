"""Illustrative water-body demonstration data (ALL records labelled SIMULATED / ILLUSTRATIVE).

Generated once with a fixed seed and stored in SQLite, so values never change between sessions.
Water bodies are placed at arbitrary points inside each reserve's approximate footprint: they are
NOT real, surveyed locations. The water-level and satellite series come from a simple daily water
balance driven by the reserve's stored rainfall and temperature, so they respond plausibly to
drought and monsoon. Replace them by uploading surveyed water points and measurements.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config import settings
from database import db
from processing.geospatial import KM_PER_DEG_LAT, buffer_radius_km, km_per_deg_lon

SEED = 20260611
# (type, permanence, gauge: none/active/stale, satellite: bool)
SPECS = {
    "BAN": [("Artificial waterhole", "Managed (artificial)", "active", True), ("Natural waterhole", "Seasonal", None, True),
            ("River pool", "Perennial", None, True), ("Tank (small reservoir)", "Perennial", "stale", True),
            ("Seasonal stream pool", "Seasonal", None, False)],
    "NAG": [("Reservoir backwater", "Perennial", "active", True), ("Natural waterhole", "Seasonal", None, True),
            ("Artificial waterhole", "Managed (artificial)", None, False), ("Seasonal stream pool", "Seasonal", None, True),
            ("Swamp (hadlu)", "Seasonal", None, True)],
    "COR": [("River pool", "Perennial", "active", True), ("Reservoir", "Perennial", None, True),
            ("Seasonal stream pool", "Seasonal", None, False), ("Grassland wetland", "Seasonal", None, True),
            ("Artificial waterhole", "Managed (artificial)", "active", False)],
    "RAN": [("Lake", "Seasonal", "active", True), ("Lake", "Seasonal", None, True),
            ("Artificial waterhole", "Managed (artificial)", "active", False), ("Seasonal stream pool", "Seasonal", None, False),
            ("Natural waterhole", "Seasonal", None, True)],
    "SIM": [("River pool", "Perennial", None, True), ("Plunge pool", "Perennial", None, False),
            ("Natural waterhole", "Seasonal", None, True), ("Artificial waterhole", "Managed (artificial)", "stale", False),
            ("Seasonal stream pool", "Seasonal", None, True)],
    "KAZ": [("Wetland (beel)", "Perennial", "active", True), ("Wetland (beel)", "Seasonal", None, True),
            ("Wetland (beel)", "Seasonal", None, False), ("River channel", "Perennial", None, True),
            ("Grassland swamp", "Seasonal", None, True)],
    "KAN": [("Natural waterhole", "Seasonal", None, True), ("Artificial waterhole", "Managed (artificial)", "active", True),
            ("River pool", "Perennial", None, True), ("Meadow wetland", "Seasonal", None, False),
            ("Tank (small reservoir)", "Perennial", "active", False)],
    "GIR": [("Reservoir", "Perennial", "active", True), ("Artificial water point", "Managed (artificial)", "active", False),
            ("Artificial water point", "Managed (artificial)", None, False), ("River pool", "Seasonal", None, True),
            ("Natural waterhole", "Seasonal", None, True)],
    "PER": [("Reservoir lake", "Perennial", "active", True), ("Seasonal stream pool", "Seasonal", None, True),
            ("Marsh", "Seasonal", None, True), ("Natural waterhole", "Seasonal", None, False),
            ("River pool", "Perennial", None, True)],
    "SUN": [("Freshwater pond", "Managed (artificial)", "active", True), ("Freshwater pond", "Managed (artificial)", None, False),
            ("Tidal creek", "Perennial", None, True), ("Mangrove channel", "Perennial", None, False),
            ("Rain-fed pool", "Seasonal", None, True)],
}
LOSS = {"Perennial": 0.004, "Seasonal": 0.013, "Managed (artificial)": 0.009}
FLOOR = {"Perennial": 0.30, "Seasonal": 0.0, "Managed (artificial)": 0.40}


def _balance(rain: np.ndarray, tmax: np.ndarray, annual: float, permanence: str, tidal: bool, rng) -> np.ndarray:
    s = np.empty(len(rain))
    cur = 0.6
    gain_scale = max(annual / 10.0, 40.0)
    for i in range(len(rain)):
        if tidal:
            cur = 0.82 + 0.06 * math.sin(i / 14.77 * math.pi) + rng.normal(0, 0.01)
        else:
            loss = LOSS[permanence] * (1 + 0.08 * max(0.0, (tmax[i] if tmax[i] == tmax[i] else 30) - 30))
            cur = cur * (1 - loss) + (rain[i] if rain[i] == rain[i] else 0) / gain_scale
            cur = max(FLOOR[permanence], cur)
        cur = min(1.0, max(0.02, cur))
        s[i] = cur
    return s


def seed_water_demo(conn) -> int:
    reserves = pd.read_sql_query("SELECT * FROM protected_areas", conn)
    weather = pd.read_sql_query("SELECT pa_id, obs_date, tmax_c, precip_mm FROM weather_observations", conn,
                                parse_dates=["obs_date"])
    ndvi = pd.read_sql_query("SELECT pa_id, obs_date, ndvi FROM vegetation_observations", conn,
                             parse_dates=["obs_date"])
    ts = db.now_iso()
    wb_rows, obs_rows = [], []
    for i, r in enumerate(reserves.sort_values("pa_id").itertuples()):
        rng = np.random.default_rng(SEED + i)
        wx = weather[weather["pa_id"] == r.pa_id].sort_values("obs_date")
        if wx.empty:
            continue
        dates = wx["obs_date"].to_numpy()
        end = wx["obs_date"].max()
        annual = float(wx["precip_mm"].sum()) / max(1.0, (wx["obs_date"].max() - wx["obs_date"].min()).days / 365.25)
        nd = ndvi[ndvi["pa_id"] == r.pa_id].set_index("obs_date")["ndvi"].sort_index()
        rad = buffer_radius_km(r.area_km2)
        for j, (wtype, perm, gauge, sat) in enumerate(SPECS.get(r.pa_id, [])):
            wb_id = f"{r.pa_id}-W{j + 1:02d}"
            ang = math.radians(j * 72 + 25 + rng.uniform(-15, 15))
            dist = rad * rng.uniform(0.2, 0.65)
            lat = round(r.latitude + dist * math.sin(ang) / KM_PER_DEG_LAT, 4)
            lon = round(r.longitude + dist * math.cos(ang) / km_per_deg_lon(r.latitude), 4)
            wb_rows.append((wb_id, r.pa_id, f"Demo water point {wb_id} ({wtype})", wtype, perm, lat, lon,
                            "ILLUSTRATIVE", "WILDCAST demonstration generator", settings.SIMULATED,
                            "Illustrative location inside the approximate reserve footprint — not a surveyed site.", ts))
            s = _balance(wx["precip_mm"].to_numpy(float), wx["tmax_c"].to_numpy(float), annual, perm,
                         wtype in ("Tidal creek", "Mangrove channel"), rng)
            series = pd.Series(s, index=pd.DatetimeIndex(dates))
            depth = round(rng.uniform(1.4, 3.8), 2)
            if gauge:
                g_end = end if gauge == "active" else end - pd.Timedelta(days=150)
                gd = pd.date_range(end - pd.DateOffset(years=3), g_end, freq="7D")
                for d in gd:
                    v = depth * series.asof(d) + rng.normal(0, 0.04)
                    obs_rows.append((wb_id, str(d.date()), "water_level_m", round(max(0.0, v), 2), "m", "DIRECT",
                                     "Staff-gauge reading (illustrative)"))
            comp = [d for d in pd.DatetimeIndex(dates) if (d.dayofyear - 1) % 16 == 0]
            for d in comp:
                monsoon_cloud = d.month in (6, 7, 8, 9) and rng.random() < 0.5
                if sat and not monsoon_cloud:
                    v = 100 * series.asof(d) * rng.uniform(0.9, 1.0) + rng.normal(0, 2)
                    obs_rows.append((wb_id, str(d.date()), "water_spread_pct", round(min(100, max(0, v)), 1), "%",
                                     "SATELLITE", "Surface-water extent within water-body outline (illustrative)"))
                base = nd.asof(d) if not nd.empty and d >= nd.index.min() else None
                if base is not None and base == base and (d - nd.index[nd.index <= d][-1]).days <= 20:
                    v = base + 0.06 + 0.06 * (series.asof(d) - 0.5) + rng.normal(0, 0.015)
                    obs_rows.append((wb_id, str(d.date()), "ndvi_buffer", round(min(1, max(-1, v)), 3), "NDVI",
                                     "SATELLITE", "Mean NDVI within 500 m of the water body (illustrative)"))
    conn.executemany("INSERT OR IGNORE INTO water_bodies VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", wb_rows)
    conn.executemany(
        "INSERT OR IGNORE INTO water_observations(wb_id,obs_date,metric,value,unit,obs_kind,method,source,source_type,"
        "ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        [(*o, "WILDCAST demonstration generator", settings.SIMULATED, ts) for o in obs_rows])
    db.update_source(conn, "WATER_DEMO", True, f"{len(wb_rows)} illustrative water bodies, {len(obs_rows)} simulated "
                     "observations (fixed seed).", records=len(obs_rows), status="DEMO")
    return len(wb_rows)
