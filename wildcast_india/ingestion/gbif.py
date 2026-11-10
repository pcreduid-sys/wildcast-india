"""GBIF occurrence connector (no key required).

Docs: https://techdocs.gbif.org/en/openapi/v1/occurrence  (occurrence/search, max 300 per page)
Queries animal records (kingdomKey=1) inside each reserve footprint polygon. Records that GBIF
mirrors from iNaturalist are keyed `inat:<id>` so they never duplicate direct iNaturalist records.
"""
from __future__ import annotations

import time

import pandas as pd

from config import settings
from database import db
from ingestion.http import FetchError, get
from processing import wildlife
from processing.geospatial import footprint_wkt

API = "https://api.gbif.org/v1"
PAGE = 300


def parse_results(results: list[dict], today: pd.Timestamp | None = None) -> pd.DataFrame:
    today = today or pd.Timestamp.today()
    rows = []
    for r in results:
        name = r.get("species") or r.get("scientificName")
        occ_id = str(r.get("occurrenceID") or "")
        if "inaturalist.org/observations/" in occ_id:
            dup = "inat:" + occ_id.rstrip("/").split("/")[-1]
        else:
            dup = f"gbif:{r.get('key')}"
        if r.get("year") and r.get("month") and r.get("day"):
            date = f"{r['year']}-{int(r['month']):02d}-{int(r['day']):02d}"
        else:  # partial dates (e.g. '2019-03' or ranges) are left undated rather than guessed
            ev = str(r.get("eventDate") or "")
            date = ev[:10] if len(ev) >= 10 and ev[4] == "-" and ev[7] == "-" else None
        verif = r.get("identificationVerificationStatus")
        if not verif and dup.startswith("inat:"):
            verif = "Research grade (iNaturalist via GBIF)"
        rows.append({
            "source": "GBIF", "record_id": str(r.get("key")), "dup_key": dup,
            "dataset": r.get("datasetName") or r.get("datasetKey"), "scientific_name": name,
            "common_name": r.get("vernacularName"), "kingdom": r.get("kingdom"), "phylum": r.get("phylum"),
            "class_name": r.get("class"), "order_name": r.get("order"), "family": r.get("family"),
            "gbif_key": r.get("speciesKey"), "inat_taxon_id": None,
            "iucn_category": r.get("iucnRedListCategory"),
            "latitude": r.get("decimalLatitude"), "longitude": r.get("decimalLongitude"),
            "coord_uncertainty_m": r.get("coordinateUncertaintyInMeters"), "obs_date": date,
            "individual_count": r.get("individualCount"), "basis_of_record": r.get("basisOfRecord"),
            "verification_status": verif or r.get("basisOfRecord"),
            "record_url": f"https://www.gbif.org/occurrence/{r.get('key')}",
            "already_obscured": bool(r.get("informationWithheld") or r.get("dataGeneralizations")),
            "iconic": None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        recent = pd.to_datetime(df["obs_date"], errors="coerce") > today - pd.Timedelta(days=60)
        df["source_type"] = [settings.LIVE if x else settings.HISTORICAL for x in recent]
    return df


def fetch_reserve(row, max_records: int, start_year: int) -> tuple[pd.DataFrame, int]:
    params = {"geometry": footprint_wkt(row), "kingdomKey": 1, "hasCoordinate": "true",
              "hasGeospatialIssue": "false", "occurrenceStatus": "PRESENT",
              "year": f"{start_year},{pd.Timestamp.today().year}", "limit": PAGE}
    frames, offset, total = [], 0, 0
    while offset < max_records:
        js = get(f"{API}/occurrence/search", {**params, "offset": offset}).json()
        total = js.get("count", total)
        res = js.get("results", [])
        if res:
            frames.append(parse_results(res))
        if js.get("endOfRecords", True) or not res:
            break
        offset += PAGE
        time.sleep(0.3)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()), int(total)


def enrich_common_names(limit: int = 150) -> int:
    sp = db.query_df("""SELECT s.scientific_name, s.gbif_key FROM species s JOIN species_reserve r
                        ON r.scientific_name=s.scientific_name WHERE s.common_name IS NULL AND s.gbif_key IS NOT NULL
                        GROUP BY s.scientific_name ORDER BY SUM(r.n_records) DESC LIMIT ?""", (limit,))
    n = 0
    for r in sp.itertuples():
        try:
            names = get(f"{API}/species/{int(r.gbif_key)}/vernacularNames", {"limit": 100}, retries=0).json()
        except (FetchError, ValueError):
            continue
        eng = [x.get("vernacularName") for x in names.get("results", []) if x.get("language") in ("eng", "en")]
        if eng:
            with db.get_conn() as conn:
                conn.execute("UPDATE species SET common_name=? WHERE scientific_name=? AND common_name IS NULL",
                             (eng[0].strip().capitalize() if eng[0].islower() else eng[0].strip(), r.scientific_name))
            n += 1
        time.sleep(0.1)
    return n


def refresh(max_records: int = 1500, start_year: int = 2000, progress=None) -> dict:
    reserves = db.get_reserves()
    ok, failed, inserted, dups, held = [], [], 0, 0, 0
    for i, r in enumerate(reserves.itertuples(index=False)):
        row = r._asdict()
        if progress:
            progress(i / len(reserves), f"GBIF: {row['name']}")
        try:
            df, total = fetch_reserve(row, max_records, start_year)
        except (FetchError, ValueError) as exc:
            failed.append(f"{row['name']}: {str(exc)[:140]}")
            if not ok and len(failed) >= 2:
                failed.append("aborted after repeated failures (source unreachable?)")
                break
            continue
        held += total
        if not df.empty:
            res = wildlife.store_observations(df, reserves)
            inserted += res["inserted"]
            dups += res["duplicates"]
        ok.append(row["name"])
    if ok:
        if progress:
            progress(0.98, "GBIF: resolving common names")
        enrich_common_names()
    msg = (f"{len(ok)}/{len(reserves)} reserves queried; {inserted} new records "
           f"({dups} already stored). GBIF holds {held:,} matching records in total.")
    if failed:
        msg += " Failures: " + "; ".join(failed[:3])
    with db.get_conn() as conn:
        db.update_source(conn, "GBIF", bool(ok), msg, records=inserted,
                         status="OK" if ok and not failed else ("PARTIAL" if ok else "FAILED"))
    return {"ok": bool(ok), "records": inserted, "message": msg}
