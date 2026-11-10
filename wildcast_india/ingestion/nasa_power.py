"""NASA POWER daily point connector (no API key required).

Docs: https://power.larc.nasa.gov/docs/services/api/temporal/daily/
Parameters: T2M_MAX (max 2 m temperature), T2M (mean), PRECTOTCORR (bias-corrected precipitation).
"""
from __future__ import annotations

import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get

URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
FILL = -999.0


def fetch_point(lat: float, lon: float, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    params = {"parameters": "T2M_MAX,T2M,PRECTOTCORR", "community": "AG", "latitude": round(lat, 4),
              "longitude": round(lon, 4), "start": start.strftime("%Y%m%d"),
              "end": end.strftime("%Y%m%d"), "format": "JSON", "time-standard": "LST"}
    payload = get(URL, params).json()
    try:
        p = payload["properties"]["parameter"]
    except (KeyError, TypeError) as exc:
        raise FetchError(f"Unexpected POWER response: {str(payload)[:200]}") from exc
    df = pd.DataFrame({"tmax_c": p["T2M_MAX"], "tmean_c": p["T2M"], "precip_mm": p["PRECTOTCORR"]})
    df.index = pd.to_datetime(df.index, format="%Y%m%d")
    df = df.mask(df <= FILL + 1)  # fill values => missing
    return df.dropna(how="all").rename_axis("obs_date").reset_index()


def refresh(years: int = 8, pa_ids=None, progress=None) -> dict:
    """Fetch daily weather for each reserve. Failure leaves existing data untouched."""
    reserves = db.get_reserves()
    if pa_ids:
        reserves = reserves[reserves["pa_id"].isin(pa_ids)]
    end = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    start = end - pd.DateOffset(years=years)
    ok, failed, n = [], [], 0
    for i, r in enumerate(reserves.itertuples()):
        if progress:
            progress((i + 1) / len(reserves), f"NASA POWER: {r.name}")
        try:
            df = fetch_point(r.latitude, r.longitude, start, end)
        except (FetchError, ValueError) as exc:
            failed.append(f"{r.name}: {str(exc)[:140]}")
            if not ok and len(failed) >= 2:
                failed.append("aborted after repeated failures (source unreachable?)")
                break
            continue
        if df.empty:
            failed.append(f"{r.name}: empty response")
            continue
        df["pa_id"] = r.pa_id
        df["source"] = "NASA POWER"
        recent = df["obs_date"] > end - pd.Timedelta(days=60)
        df["source_type"] = [settings.LIVE if x else settings.HISTORICAL for x in recent]
        with db.get_conn() as conn:
            # Remove simulated rows in this window so live and demo records never mix
            conn.execute("DELETE FROM weather_observations WHERE pa_id=? AND source_type='SIMULATED' "
                         "AND obs_date BETWEEN ? AND ?", (r.pa_id, str(start.date()), str(end.date())))
            n += db.upsert_weather(conn, df)
        ok.append(r.name)
    msg = f"{len(ok)}/{len(reserves)} reserves updated, {n} daily records."
    if failed:
        msg += " Failures: " + "; ".join(failed[:3]) + (" …" if len(failed) > 3 else "")
    with db.get_conn() as conn:
        db.update_source(conn, "NASA_POWER", bool(ok), msg, records=n,
                         status="OK" if ok and not failed else ("PARTIAL" if ok else "FAILED"))
    return {"ok": ok, "failed": failed, "records": n, "message": msg}
