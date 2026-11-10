"""Validation and normalisation of uploaded / retrieved datasets."""
from __future__ import annotations

import json

import pandas as pd

from processing.geospatial import assign_fires

ALIASES = {
    "reserve": ["reserve", "name", "protected_area", "pa_name"],
    "pa_id": ["pa_id", "id", "code"],
    "obs_date": ["obs_date", "date", "acq_date", "time"],
    "tmax_c": ["tmax_c", "tmax", "t2m_max", "max_temp"],
    "tmean_c": ["tmean_c", "tmean", "t2m", "mean_temp"],
    "precip_mm": ["precip_mm", "precip", "rain", "rainfall", "prectotcorr", "rainfall_mm"],
    "ndvi": ["ndvi"],
}
WEATHER_REQUIRED = ["obs_date", "precip_mm", "tmax_c"]
FIRE_REQUIRED = ["latitude", "longitude", "acq_date"]


def _rename(df: pd.DataFrame, keys) -> pd.DataFrame:
    low = {c.lower().strip(): c for c in df.columns}
    mapping = {}
    for k in keys:
        for alias in ALIASES.get(k, [k]):
            if alias in low:
                mapping[low[alias]] = k
                break
    return df.rename(columns=mapping)


def _resolve_reserve(df: pd.DataFrame, reserves: pd.DataFrame, errors: list) -> pd.DataFrame:
    if "pa_id" not in df.columns:
        if "reserve" not in df.columns:
            errors.append("Missing a reserve identifier column ('pa_id' or 'reserve').")
            return df.iloc[0:0]
        lookup = {n.lower(): p for n, p in zip(reserves["name"], reserves["pa_id"])}
        df["pa_id"] = df["reserve"].astype(str).str.strip().str.lower().map(lookup)
    else:
        df["pa_id"] = df["pa_id"].astype(str).str.strip().str.upper()
    bad = ~df["pa_id"].isin(reserves["pa_id"])
    if bad.any():
        errors.append(f"{int(bad.sum())} row(s) reference unknown reserves and were skipped.")
    return df[~bad]


def _dates(df: pd.DataFrame, col: str, errors: list) -> pd.DataFrame:
    df[col] = pd.to_datetime(df[col], errors="coerce")
    bad = df[col].isna()
    if bad.any():
        errors.append(f"{int(bad.sum())} row(s) with unparseable dates were skipped.")
    return df[~bad]


def _range(df, col, lo, hi, errors):
    if col not in df.columns:
        return df
    df[col] = pd.to_numeric(df[col], errors="coerce")
    bad = df[col].notna() & ((df[col] < lo) | (df[col] > hi))
    if bad.any():
        errors.append(f"{int(bad.sum())} {col} value(s) outside [{lo}, {hi}] set to missing.")
        df.loc[bad, col] = None
    return df


def validate_weather(raw: pd.DataFrame, reserves: pd.DataFrame):
    errors: list[str] = []
    df = _rename(raw.copy(), ["reserve", "pa_id", "obs_date", "tmax_c", "tmean_c", "precip_mm"])
    missing = [c for c in WEATHER_REQUIRED if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    df = _resolve_reserve(df, reserves, errors)
    df = _dates(df, "obs_date", errors)
    if "tmean_c" not in df.columns:
        df["tmean_c"] = None
    df = _range(df, "tmax_c", -30, 55, errors)
    df = _range(df, "tmean_c", -40, 50, errors)
    df = _range(df, "precip_mm", 0, 1000, errors)
    df = df.drop_duplicates(["pa_id", "obs_date"], keep="last")
    return df[["pa_id", "obs_date", "tmax_c", "tmean_c", "precip_mm"]], errors


def validate_ndvi(raw: pd.DataFrame, reserves: pd.DataFrame):
    errors: list[str] = []
    df = _rename(raw.copy(), ["reserve", "pa_id", "obs_date", "ndvi"])
    missing = [c for c in ["obs_date", "ndvi"] if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    df = _resolve_reserve(df, reserves, errors)
    df = _dates(df, "obs_date", errors)
    df["ndvi"] = pd.to_numeric(df["ndvi"], errors="coerce")
    if df["ndvi"].abs().max() > 1.5:  # MODIS scaled integers (x 10000)
        df["ndvi"] = df["ndvi"] / 10000.0
        errors.append("NDVI looked scaled (x10000); divided by 10000.")
    df = _range(df, "ndvi", -1, 1, errors)
    df = df.dropna(subset=["ndvi"]).drop_duplicates(["pa_id", "obs_date"], keep="last")
    return df[["pa_id", "obs_date", "ndvi"]], errors


def validate_fires(raw: pd.DataFrame, reserves: pd.DataFrame):
    """Accepts NASA FIRMS CSV format (VIIRS or MODIS)."""
    errors: list[str] = []
    df = raw.copy()
    df.columns = [c.lower().strip() for c in df.columns]
    missing = [c for c in FIRE_REQUIRED if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    df = _dates(df, "acq_date", errors)
    df = _range(df, "latitude", 5, 38, errors)
    df = _range(df, "longitude", 67, 98, errors)
    df = df.dropna(subset=["latitude", "longitude"])
    for col, default in [("acq_time", ""), ("satellite", ""), ("instrument", ""), ("confidence", ""),
                         ("frp", None), ("daynight", "")]:
        if col not in df.columns:
            df[col] = default
    df["acq_time"] = df["acq_time"].astype(str).str.zfill(4)
    df = assign_fires(df, reserves)
    outside = df["pa_id"].isna().sum()
    if outside:
        errors.append(f"{int(outside)} detection(s) are more than 25 km from any pilot reserve "
                      "(stored, not attributed).")
    return df, errors


def validate_geojson(text: str, reserves: pd.DataFrame):
    """Return list of (pa_id, geometry_json) matched by a name/pa_id property."""
    errors: list[str] = []
    try:
        gj = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"Invalid JSON: {exc}"]
    feats = gj.get("features", [gj] if gj.get("type") == "Feature" else [])
    if not feats:
        return [], ["No features found (expected a FeatureCollection)."]
    by_name = {n.lower(): p for n, p in zip(reserves["name"], reserves["pa_id"])}
    from shapely.geometry import shape
    out = []
    for i, f in enumerate(feats):
        props = {k.lower(): v for k, v in (f.get("properties") or {}).items()}
        pid = str(props.get("pa_id", "")).upper()
        if pid not in set(reserves["pa_id"]):
            name = str(props.get("name") or props.get("orig_name") or props.get("name_eng") or "").lower()
            pid = next((p for n, p in by_name.items() if n and (n == name or n in name)), None)
        if not pid:
            errors.append(f"Feature {i}: no 'pa_id' or recognisable 'name' property — skipped.")
            continue
        try:
            geom = shape(f["geometry"])
            if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid:
                raise ValueError(f"{geom.geom_type} (valid={geom.is_valid})")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Feature {i}: invalid polygon geometry ({exc}) — skipped.")
            continue
        out.append((pid, json.dumps(f["geometry"])))
    return out, errors
