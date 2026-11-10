"""iNaturalist connector (no key required). Research-grade animal observations only.

Docs: https://api.inaturalist.org/v1/docs/  (max 200 per page; please keep ~1 request/second)
Observations are fetched for each reserve's bounding box and only those inside the footprint are kept.
Obscured / private-geoprivacy observations keep iNaturalist's obscured coordinates and are flagged.
"""
from __future__ import annotations

import time

import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get
from processing import wildlife
from processing.geospatial import footprint_bbox

API = "https://api.inaturalist.org/v1/observations"
PAGE = 200


def parse_results(results: list[dict], today: pd.Timestamp | None = None) -> pd.DataFrame:
    today = today or pd.Timestamp.today()
    rows = []
    for r in results:
        t = r.get("taxon") or {}
        if t.get("rank") not in ("species", "subspecies", "variety"):
            continue
        coords = (r.get("geojson") or {}).get("coordinates") or [None, None]
        cs = t.get("conservation_status") or {}
        rows.append({
            "source": "iNaturalist", "record_id": str(r.get("id")), "dup_key": f"inat:{r.get('id')}",
            "dataset": "iNaturalist research-grade observations", "scientific_name": t.get("name"),
            "common_name": t.get("preferred_common_name"), "kingdom": "Animalia", "phylum": None,
            "class_name": None, "order_name": None, "family": None, "gbif_key": None,
            "inat_taxon_id": t.get("id"), "iucn_category": None if cs.get("authority") != "IUCN Red List"
            else cs.get("status"),
            "latitude": coords[1], "longitude": coords[0], "coord_uncertainty_m": r.get("positional_accuracy"),
            "obs_date": r.get("observed_on"), "individual_count": None, "basis_of_record": "HUMAN_OBSERVATION",
            "verification_status": f"{r.get('quality_grade', '').replace('_', ' ')} (iNaturalist)",
            "record_url": r.get("uri") or f"https://www.inaturalist.org/observations/{r.get('id')}",
            "already_obscured": bool(r.get("obscured") or r.get("geoprivacy") in ("obscured", "private")
                                     or r.get("taxon_geoprivacy") in ("obscured", "private")),
            "iconic": t.get("iconic_taxon_name"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        recent = pd.to_datetime(df["obs_date"], errors="coerce") > today - pd.Timedelta(days=60)
        df["source_type"] = [settings.LIVE if x else settings.HISTORICAL for x in recent]
    return df


def fetch_reserve(row, max_records: int) -> tuple[pd.DataFrame, int]:
    s, w, n, e = footprint_bbox(row)
    params = {"swlat": round(s, 4), "swlng": round(w, 4), "nelat": round(n, 4), "nelng": round(e, 4),
              "quality_grade": "research", "taxon_id": 1, "per_page": PAGE, "order_by": "observed_on",
              "order": "desc", "geo": "true"}
    frames, total = [], 0
    for page in range(1, max(1, max_records // PAGE) + 1):
        js = get(API, {**params, "page": page}, accept="application/json").json()
        total = js.get("total_results", total)
        res = js.get("results", [])
        if res:
            frames.append(parse_results(res))
        if len(res) < PAGE:
            break
        time.sleep(1.0)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), int(total)


def refresh(max_records: int = 1000, progress=None) -> dict:
    reserves = db.get_reserves()
    ok, failed, inserted, dups = [], [], 0, 0
    for i, r in enumerate(reserves.itertuples(index=False)):
        row = r._asdict()
        if progress:
            progress(i / len(reserves), f"iNaturalist: {row['name']}")
        try:
            df, _ = fetch_reserve(row, max_records)
        except (FetchError, ValueError) as exc:
            failed.append(f"{row['name']}: {str(exc)[:140]}")
            if not ok and len(failed) >= 2:
                failed.append("aborted after repeated failures (source unreachable?)")
                break
            continue
        if not df.empty:
            res = wildlife.store_observations(df, reserves)
            inserted += res["inserted"]
            dups += res["duplicates"]
        ok.append(row["name"])
        time.sleep(1.0)
    msg = f"{len(ok)}/{len(reserves)} reserves queried; {inserted} new records ({dups} already stored)."
    if failed:
        msg += " Failures: " + "; ".join(failed[:3])
    with db.get_conn() as conn:
        db.update_source(conn, "INAT", bool(ok), msg, records=inserted,
                         status="OK" if ok and not failed else ("PARTIAL" if ok else "FAILED"))
    return {"ok": bool(ok), "records": inserted, "message": msg}
