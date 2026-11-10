"""IUCN Red List API v4 connector - latest category and assessment year per species.

Requires a token: https://api.iucnredlist.org/users/sign_up  -> set IUCN_API_TOKEN in .env
Without it, categories come from GBIF occurrence records (which carry the IUCN checklist category
but no assessment date) and from data/species_reference.csv.
"""
from __future__ import annotations

import os
import time

from database import db
from ingestion.http import FetchError, get
from processing.wildlife import iucn_code

API = "https://api.iucnredlist.org/api/v4/taxa/scientific_name"


def token() -> str:
    return os.getenv("IUCN_API_TOKEN", "").strip()


def latest_assessment(js: dict) -> tuple[str | None, int | None]:
    assessments = js.get("assessments") or []
    if not assessments:
        return None, None
    latest = [a for a in assessments if a.get("latest")] or sorted(
        assessments, key=lambda a: str(a.get("year_published", "")))[-1:]
    a = latest[0]
    code = a.get("red_list_category_code") or (a.get("red_list_category") or {}).get("code")
    year = a.get("year_published")
    try:
        year = int(str(year)[:4])
    except (TypeError, ValueError):
        year = None
    return iucn_code(code), year


def refresh(limit: int = 300, progress=None) -> dict:
    tok = token()
    if not tok:
        with db.get_conn() as conn:
            db.update_source(conn, "IUCN", False, "IUCN_API_TOKEN not set in .env.", status="NOT CONFIGURED")
        return {"ok": False, "records": 0, "message": "IUCN_API_TOKEN not configured. Register at "
                                                      "https://api.iucnredlist.org and add the token to .env."}
    sp = db.query_df("""SELECT s.scientific_name FROM species s LEFT JOIN species_reserve r
                        ON r.scientific_name=s.scientific_name GROUP BY s.scientific_name
                        ORDER BY (s.iucn_category IN ('CR','EN','VU','NT')) DESC, SUM(r.n_records) DESC LIMIT ?""",
                     (limit,))
    updated, failures = 0, []
    for i, name in enumerate(sp["scientific_name"]):
        if progress:
            progress(i / max(1, len(sp)), f"IUCN: {name}")
        genus, species = name.split(" ", 1)
        try:
            js = get(API, {"genus_name": genus, "species_name": species},
                     headers={"Authorization": f"Bearer {tok}"}, retries=1).json()
        except (FetchError, ValueError) as exc:
            failures.append(f"{name}: {str(exc)[:100]}")
            if "Authentication" in str(exc) or (not updated and len(failures) >= 3):
                break
            continue
        code, year = latest_assessment(js)
        if code:
            with db.get_conn() as conn:
                conn.execute("UPDATE species SET iucn_category=?, iucn_assessment_year=?, "
                             "iucn_source='IUCN Red List API v4', sensitive=MAX(sensitive, ?) "
                             "WHERE scientific_name=?", (code, year, int(code in ("CR", "EN")), name))
            updated += 1
        time.sleep(0.5)
    ok = updated > 0
    msg = f"{updated} species updated with IUCN category and assessment year."
    if failures:
        msg += " Failures: " + "; ".join(failures[:3])
    with db.get_conn() as conn:
        db.update_source(conn, "IUCN", ok, msg, records=updated,
                         status="OK" if ok and not failures else ("PARTIAL" if ok else "FAILED"))
    return {"ok": ok, "records": updated, "message": msg}
