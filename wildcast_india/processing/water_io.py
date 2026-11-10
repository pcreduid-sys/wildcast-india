"""Validation and storage for uploaded water bodies and water observations."""
from __future__ import annotations

import re

import pandas as pd

from config import settings
from database import db
from processing.geospatial import assign_fires as assign_points

WB_TYPES_PERM = {"Perennial", "Seasonal", "Managed (artificial)", "Unknown"}
METRICS = {"water_level_m": ("m", "DIRECT"), "water_spread_pct": ("%", "SATELLITE"), "ndwi": ("index", "SATELLITE"),
           "ndvi_buffer": ("NDVI", "SATELLITE"), "presence": ("0/1", "DIRECT")}


def _low(df):
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    return df


def validate_water_bodies(raw: pd.DataFrame, reserves: pd.DataFrame):
    """Columns: name, wb_type, latitude, longitude, reserve|pa_id, optional permanence, wb_id, location_basis, notes."""
    df, notes = _low(raw), []
    missing = [c for c in ["name", "wb_type", "latitude", "longitude"] if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    bad = ~(df["latitude"].between(5, 38) & df["longitude"].between(67, 98))
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) with missing or out-of-India coordinates were skipped.")
    df = df[~bad]
    located = assign_points(df[["latitude", "longitude"]], reserves)
    df["pa_auto"] = located["pa_id"].values
    if "pa_id" in df.columns:
        df["pa_id"] = df["pa_id"].astype(str).str.upper().where(df["pa_id"].astype(str).str.upper().isin(reserves["pa_id"]))
    elif "reserve" in df.columns:
        lk = {n.lower(): p for n, p in zip(reserves["name"], reserves["pa_id"])}
        df["pa_id"] = df["reserve"].astype(str).str.strip().str.lower().map(lk)
    else:
        df["pa_id"] = None
    df["pa_id"] = df["pa_id"].fillna(df["pa_auto"])
    bad = df["pa_id"].isna()
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) could not be linked to a pilot reserve (none given, >25 km away).")
    df = df[~bad]
    df["permanence"] = df.get("permanence", pd.Series("Unknown", index=df.index)).fillna("Unknown")
    df.loc[~df["permanence"].isin(WB_TYPES_PERM), "permanence"] = "Unknown"
    basis = df.get("location_basis", pd.Series("UPLOADED", index=df.index)).fillna("UPLOADED").str.upper()
    df["location_basis"] = basis.where(basis.isin(["UPLOADED", "VERIFIED"]), "UPLOADED")
    if "wb_id" not in df.columns or df["wb_id"].isna().all():
        df["wb_id"] = [f"{p}-U{re.sub(r'[^A-Za-z0-9]', '', str(n))[:12].upper()}" for p, n in zip(df["pa_id"], df["name"])]
    df["notes"] = df.get("notes", pd.Series(None, index=df.index))
    d = df.duplicated("wb_id")
    if d.any():
        notes.append(f"{int(d.sum())} duplicate water body row(s) dropped.")
    return df[~d][["wb_id", "pa_id", "name", "wb_type", "permanence", "latitude", "longitude", "location_basis",
                   "notes"]], notes


def store_water_bodies(df: pd.DataFrame, filename: str, path=None) -> int:
    ts = db.now_iso()
    with db.get_conn(path) as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO water_bodies VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r.wb_id, r.pa_id, r.name, r.wb_type, r.permanence, float(r.latitude), float(r.longitude),
              r.location_basis, f"Upload: {filename}", settings.UPLOADED,
              r.notes if isinstance(r.notes, str) else None, ts) for r in df.itertuples()])
        return conn.total_changes - before


def validate_water_obs(raw: pd.DataFrame, water_bodies: pd.DataFrame, today=None):
    """Columns: wb_id (or name), date, metric, value, optional obs_kind, unit, method."""
    df, notes = _low(raw), []
    today = (today or pd.Timestamp.today()).normalize()
    missing = [c for c in ["date", "metric", "value"] if c not in df.columns]
    if "wb_id" not in df.columns and "name" not in df.columns:
        missing.append("wb_id or name")
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    if "wb_id" not in df.columns:
        df["wb_id"] = df["name"].map(dict(zip(water_bodies["name"], water_bodies["wb_id"])))
    bad = ~df["wb_id"].isin(water_bodies["wb_id"])
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) reference unknown water bodies and were skipped.")
    df = df[~bad]
    df["metric"] = df["metric"].astype(str).str.strip().str.lower()
    bad = ~df["metric"].isin(METRICS)
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) with unsupported metric skipped (allowed: {', '.join(METRICS)}).")
    df = df[~bad]
    df["obs_date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    bad = df["obs_date"].isna() | df["value"].isna() | (df["obs_date"] > today)
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) with invalid/future dates or non-numeric values skipped.")
    df = df[~bad]
    rng = {"water_spread_pct": (0, 100), "ndwi": (-1, 1), "ndvi_buffer": (-1, 1), "water_level_m": (-50, 200),
           "presence": (0, 1)}
    ok = [rng[m][0] <= v <= rng[m][1] for m, v in zip(df["metric"], df["value"])]
    if not all(ok):
        notes.append(f"{len(ok) - sum(ok)} value(s) outside the valid range for their metric skipped.")
    df = df[ok]
    df["unit"] = df.get("unit", pd.Series(None, index=df.index)).fillna(df["metric"].map(lambda m: METRICS[m][0]))
    kind = df.get("obs_kind", pd.Series(None, index=df.index)).astype(str).str.upper()
    df["obs_kind"] = kind.where(kind.isin(["DIRECT", "SATELLITE"]), df["metric"].map(lambda m: METRICS[m][1]))
    df["method"] = df.get("method", pd.Series(None, index=df.index))
    return df[["wb_id", "obs_date", "metric", "value", "unit", "obs_kind", "method"]], notes


def store_water_obs(df: pd.DataFrame, filename: str, path=None) -> int:
    ts = db.now_iso()
    with db.get_conn(path) as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR REPLACE INTO water_observations(wb_id,obs_date,metric,value,unit,obs_kind,method,source,"
            "source_type,ingested_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(r.wb_id, str(r.obs_date.date()), r.metric, float(r.value), r.unit, r.obs_kind,
              r.method if isinstance(r.method, str) else None, f"Upload: {filename}", settings.UPLOADED, ts)
             for r in df.itertuples()])
        return conn.total_changes - before
