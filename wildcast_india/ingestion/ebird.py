"""eBird API 2.0 connector - recent (last 30 days) bird observations near each reserve.

Requires a free API key: https://ebird.org/api/keygen  -> set EBIRD_API_KEY in .env
Docs: https://documenter.getpostman.com/view/664302/S1ENwy59
Note: the eBird API serves recent observations only. Historical eBird records reach GBIF through
the eBird Observation Dataset, so use the GBIF connector for history.
"""
from __future__ import annotations

import os

import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get
from processing import wildlife
from processing.geospatial import buffer_radius_km

API = "https://api.ebird.org/v2/data/obs/geo/recent"


def api_key() -> str:
    return os.getenv("EBIRD_API_KEY", "").strip()


def parse_results(results: list[dict]) -> pd.DataFrame:
    rows = []
    for r in results:
        rid = f"{r.get('subId')}:{r.get('speciesCode')}"
        rows.append({
            "source": "eBird", "record_id": rid, "dup_key": f"ebird:{rid}", "dataset": "eBird (recent observations)",
            "scientific_name": r.get("sciName"), "common_name": r.get("comName"), "kingdom": "Animalia",
            "phylum": "Chordata", "class_name": "Aves", "order_name": None, "family": None, "gbif_key": None,
            "inat_taxon_id": None, "iucn_category": None, "latitude": r.get("lat"), "longitude": r.get("lng"),
            "coord_uncertainty_m": None, "obs_date": str(r.get("obsDt", ""))[:10],
            "individual_count": r.get("howMany"), "basis_of_record": "HUMAN_OBSERVATION",
            "verification_status": ("reviewed" if r.get("obsReviewed") else "not reviewed")
            + ("; valid" if r.get("obsValid") else "; flagged"),
            "record_url": f"https://ebird.org/checklist/{r.get('subId')}",
            "already_obscured": bool(r.get("locationPrivate")), "iconic": "Aves",
            "source_type": settings.LIVE,
        })
    return pd.DataFrame(rows)


def refresh(progress=None) -> dict:
    key = api_key()
    if not key:
        with db.get_conn() as conn:
            db.update_source(conn, "EBIRD", False, "EBIRD_API_KEY not set in .env.", status="NOT CONFIGURED")
        return {"ok": False, "records": 0, "message": "EBIRD_API_KEY not configured. Request a free key at "
                                                      "https://ebird.org/api/keygen and add it to .env."}
    reserves = db.get_reserves()
    ok, failed, inserted = [], [], 0
    for i, r in enumerate(reserves.itertuples(index=False)):
        row = r._asdict()
        if progress:
            progress(i / len(reserves), f"eBird: {row['name']}")
        try:
            js = get(API, {"lat": round(row["latitude"], 3), "lng": round(row["longitude"], 3),
                           "dist": int(min(50, buffer_radius_km(row["area_km2"]) + 2)), "back": 30,
                           "maxResults": 10000}, headers={"X-eBirdApiToken": key}).json()
        except (FetchError, ValueError) as exc:
            failed.append(f"{row['name']}: {str(exc)[:140]}")
            if "Authentication" in str(exc) or (not ok and len(failed) >= 2):
                break
            continue
        df = parse_results(js if isinstance(js, list) else [])
        if not df.empty:
            inserted += wildlife.store_observations(df, reserves)["inserted"]
        ok.append(row["name"])
    msg = f"{len(ok)}/{len(reserves)} reserves queried; {inserted} new recent bird records."
    if failed:
        msg += " Failures: " + "; ".join(failed[:3])
    with db.get_conn() as conn:
        db.update_source(conn, "EBIRD", bool(ok), msg, records=inserted,
                         status="OK" if ok and not failed else ("PARTIAL" if ok else "FAILED"))
    return {"ok": bool(ok), "records": inserted, "message": msg}
