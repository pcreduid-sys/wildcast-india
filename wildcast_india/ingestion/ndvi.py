"""Optional NDVI connector: MODIS MOD13Q1 (250 m, 16-day) via the ORNL DAAC web service.

Docs: https://modis.ornl.gov/data/modis_webservice.html  (no key; max 10 dates per request)
NDVI can alternatively be imported as CSV on the Admin page (columns: reserve|pa_id, date, ndvi).
The value per composite is the mean of valid pixels within +/- km_radius of the reserve centre —
a point sample, not a whole-reserve average.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get

BASE = "https://modis.ornl.gov/rst/api/v1/MOD13Q1"
BAND = "250m_16_days_NDVI"


def _modis_date(d: pd.Timestamp) -> str:
    return f"A{d.year}{d.dayofyear:03d}"


def fetch_point(lat, lon, start: pd.Timestamp, end: pd.Timestamp, km_radius: int = 2) -> pd.DataFrame:
    dates = get(f"{BASE}/dates", {"latitude": lat, "longitude": lon}, accept="application/json").json()
    wanted = [d["modis_date"] for d in dates.get("dates", [])
              if start <= pd.Timestamp(d["calendar_date"]) <= end]
    rows = []
    for i in range(0, len(wanted), 10):
        chunk = wanted[i:i + 10]
        js = get(f"{BASE}/subset", {"latitude": lat, "longitude": lon, "band": BAND,
                                    "startDate": chunk[0], "endDate": chunk[-1],
                                    "kmAboveBelow": km_radius, "kmLeftRight": km_radius},
                 accept="application/json").json()
        scale = float(js.get("scale", 0.0001) or 0.0001)
        for s in js.get("subset", []):
            vals = np.array(s.get("data", []), dtype=float)
            vals = vals[vals > -2000]  # -3000 = fill
            if vals.size:
                rows.append({"obs_date": pd.Timestamp(s["calendar_date"]),
                             "ndvi": round(float(vals.mean() * scale), 4)})
    return pd.DataFrame(rows)


def refresh(years: int = 4, progress=None) -> dict:
    reserves = db.get_reserves()
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=years)
    ok, failed, n = [], [], 0
    for i, r in enumerate(reserves.itertuples()):
        if progress:
            progress((i + 1) / len(reserves), f"MODIS NDVI: {r.name}")
        try:
            df = fetch_point(r.latitude, r.longitude, start, end)
        except (FetchError, ValueError, KeyError) as exc:
            failed.append(f"{r.name}: {str(exc)[:140]}")
            if not ok and len(failed) >= 2:
                failed.append("aborted after repeated failures (source unreachable?)")
                break
            continue
        if df.empty:
            failed.append(f"{r.name}: no valid composites")
            continue
        df["pa_id"], df["source"] = r.pa_id, "MODIS MOD13Q1 (ORNL DAAC)"
        df["source_type"] = np.where(df["obs_date"] > end - pd.Timedelta(days=60),
                                     settings.LIVE, settings.HISTORICAL)
        with db.get_conn() as conn:
            conn.execute("DELETE FROM vegetation_observations WHERE pa_id=? AND source_type='SIMULATED' "
                         "AND obs_date BETWEEN ? AND ?", (r.pa_id, str(start.date()), str(end.date())))
            n += db.upsert_ndvi(conn, df)
        ok.append(r.name)
    msg = f"{len(ok)}/{len(reserves)} reserves updated, {n} composites."
    if failed:
        msg += " Failures: " + "; ".join(failed[:3])
    with db.get_conn() as conn:
        db.update_source(conn, "MODIS_NDVI", bool(ok), msg, records=n,
                         status="OK" if ok and not failed else ("PARTIAL" if ok else "FAILED"))
    return {"ok": ok, "failed": failed, "records": n, "message": msg}
