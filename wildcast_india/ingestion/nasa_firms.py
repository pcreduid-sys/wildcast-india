"""NASA FIRMS area API connector (requires a free MAP_KEY in .env as FIRMS_MAP_KEY).

Docs: https://firms.modaps.eosdis.nasa.gov/api/area/
URL : /api/area/csv/{MAP_KEY}/{SOURCE}/{west,south,east,north}/{DAY_RANGE}/{YYYY-MM-DD}
"""
from __future__ import annotations

import io

import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get
from processing.cleaning import validate_fires
from processing.geospatial import bbox_for

BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
CHUNK_DAYS = 5


def fetch_area(bbox: str, start: pd.Timestamp, days: int, key: str, source: str) -> pd.DataFrame:
    url = f"{BASE}/{key}/{source}/{bbox}/{days}/{start.date()}"
    text = get(url).text
    if not text.lower().startswith("latitude"):
        raise FetchError(f"FIRMS returned: {text.strip()[:160]}")
    return pd.read_csv(io.StringIO(text))


def refresh(days: int = 30, progress=None) -> dict:
    key = settings.FIRMS_MAP_KEY
    if not key:
        with db.get_conn() as conn:
            db.update_source(conn, "NASA_FIRMS", False,
                             "FIRMS_MAP_KEY not set in .env — demonstration fire data in use.",
                             status="NOT CONFIGURED")
        return {"ok": False, "records": 0,
                "message": "FIRMS_MAP_KEY not configured. Get a free key at "
                           "https://firms.modaps.eosdis.nasa.gov/api/map_key/ and add it to .env."}
    reserves = db.get_reserves()
    end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=days - 1)
    chunks = list(pd.date_range(start, end, freq=f"{CHUNK_DAYS}D"))
    frames, failures = [], []
    boxes = bbox_for(reserves)
    total = len(chunks) * len(boxes)
    k = 0
    for c in chunks:
        if failures:
            break
        span = min(CHUNK_DAYS, (end - c).days + 1)
        for pa_id, bbox in boxes:
            k += 1
            if progress:
                progress(k / total, f"NASA FIRMS: {pa_id} {c.date()}")
            try:
                frames.append(fetch_area(bbox, c, span, key, settings.FIRMS_SOURCE))
            except (FetchError, ValueError) as exc:
                failures.append(f"{pa_id} {c.date()}: {str(exc)[:140]}")
                break
    n = 0
    if frames and not failures:
        raw = pd.concat(frames, ignore_index=True)
        df, notes = validate_fires(raw, reserves) if not raw.empty else (raw, [])
        with db.get_conn() as conn:
            conn.execute("DELETE FROM fire_detections WHERE source_type='SIMULATED' AND acq_date BETWEEN ? AND ?",
                         (str(start.date()), str(end.date())))
            if df is not None and not df.empty:
                df["source"] = f"NASA FIRMS {settings.FIRMS_SOURCE}"
                df["source_type"] = settings.LIVE
                n = db.insert_fires(conn, df)
            db.update_source(conn, "NASA_FIRMS", True, f"{n} new detections over {days} days.",
                             records=n, coverage=(str(start.date()), str(end.date())))
        return {"ok": True, "records": n, "message": f"{n} new detections stored."}
    msg = (f"{len(failures)} of {total} requests failed; nothing stored to avoid partial coverage. "
           + "; ".join(failures[:2]))
    with db.get_conn() as conn:
        db.update_source(conn, "NASA_FIRMS", False, msg)
    return {"ok": False, "records": 0, "message": msg}
