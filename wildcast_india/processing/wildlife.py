"""Wildlife data processing: taxonomy normalisation, validation, sensitive-species
coordinate protection, duplicate prevention, persistence and reserve associations.

Every connector (GBIF, iNaturalist, eBird, uploads) produces a *standard observation
frame* (STD_COLS) and calls `store_observations`, so validation and storage logic exist once.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from config import settings
from database import db
from processing.geospatial import assign_fires as assign_points

STD_COLS = ["source", "record_id", "dup_key", "dataset", "scientific_name", "common_name", "kingdom",
            "phylum", "class_name", "order_name", "family", "gbif_key", "inat_taxon_id", "iucn_category",
            "latitude", "longitude", "coord_uncertainty_m", "obs_date", "individual_count",
            "basis_of_record", "verification_status", "record_url", "source_type", "already_obscured", "iconic"]

IUCN_CODES = ["EX", "EW", "CR", "EN", "VU", "NT", "LC", "DD", "NE"]
IUCN_LABELS = {"EX": "Extinct", "EW": "Extinct in the Wild", "CR": "Critically Endangered", "EN": "Endangered",
               "VU": "Vulnerable", "NT": "Near Threatened", "LC": "Least Concern", "DD": "Data Deficient",
               "NE": "Not Evaluated"}
IUCN_NAME_TO_CODE = {v.upper().replace(" ", "_"): k for k, v in IUCN_LABELS.items()}
THREATENED = {"CR", "EN", "VU"}
GROUPS = ["Mammals", "Birds", "Reptiles", "Amphibians", "Fish", "Insects", "Other invertebrates", "Other"]

# Species whose precise locations are withheld (poaching / trade / disturbance risk), in addition
# to every IUCN Critically Endangered or Endangered species.
SENSITIVE_TAXA = {
    "Panthera tigris", "Panthera leo", "Panthera pardus", "Panthera uncia", "Rhinoceros unicornis",
    "Elephas maximus", "Manis crassicaudata", "Manis pentadactyla", "Gavialis gangeticus",
    "Crocodylus palustris", "Geochelone elegans", "Ardeotis nigriceps", "Neofelis nebulosa",
    "Prionailurus viverrinus", "Lutrogale perspicillata", "Ursus thibetanus", "Melursus ursinus",
    "Bubalus arnee", "Bos gaurus", "Cuon alpinus", "Python bivittatus", "Python molurus",
    "Ophiophagus hannah", "Varanus bengalensis", "Hippocampus kuda",
}
GENERALISE_DEG = 0.1  # ~11 km grid

CLASS_GROUP = {
    "mammalia": "Mammals", "aves": "Birds", "reptilia": "Reptiles", "squamata": "Reptiles",
    "testudines": "Reptiles", "crocodylia": "Reptiles", "amphibia": "Amphibians",
    "actinopterygii": "Fish", "elasmobranchii": "Fish", "chondrichthyes": "Fish", "sarcopterygii": "Fish",
    "cephalaspidomorphi": "Fish", "petromyzonti": "Fish", "insecta": "Insects",
}
INAT_ICONIC = {"Mammalia": "Mammals", "Aves": "Birds", "Reptilia": "Reptiles", "Amphibia": "Amphibians",
               "Actinopterygii": "Fish", "Insecta": "Insects", "Arachnida": "Other invertebrates",
               "Mollusca": "Other invertebrates", "Animalia": "Other invertebrates"}


def taxon_group(class_name=None, kingdom=None, phylum=None, iconic=None) -> str:
    if isinstance(class_name, str) and class_name.lower() in CLASS_GROUP:
        return CLASS_GROUP[class_name.lower()]
    if iconic in INAT_ICONIC:
        return INAT_ICONIC[iconic]
    if isinstance(kingdom, str) and kingdom.lower() == "animalia":
        return "Fish" if isinstance(phylum, str) and phylum.lower() == "chordata" and not class_name \
            else ("Other" if isinstance(phylum, str) and phylum.lower() == "chordata" else "Other invertebrates")
    return "Other"


def canonical_name(name) -> str | None:
    """Reduce 'Panthera tigris tigris (Linnaeus, 1758)' to the binomial 'Panthera tigris'."""
    if not isinstance(name, str):
        return None
    parts = re.findall(r"[A-Za-z\-]+", name.strip())
    if len(parts) < 2 or not parts[0][0].isupper() or not parts[1].islower():
        return None
    return f"{parts[0]} {parts[1]}"


def iucn_code(value) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().upper()
    if v in IUCN_CODES:
        return v
    return IUCN_NAME_TO_CODE.get(v.replace(" ", "_"))


def is_sensitive(name: str, iucn: str | None) -> bool:
    return name in SENSITIVE_TAXA or iucn in {"CR", "EN"}


# ------------------------------------------------------------------ validation
def validate_observations(df: pd.DataFrame, today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Validate a standard observation frame. Returns (clean frame, notes)."""
    notes: list[str] = []
    today = (today or pd.Timestamp.today()).normalize()
    df = df.copy()
    for c in STD_COLS:
        if c not in df.columns:
            df[c] = None
    n0 = len(df)
    df["scientific_name"] = df["scientific_name"].map(canonical_name)
    bad = df["scientific_name"].isna()
    if bad.any():
        notes.append(f"{int(bad.sum())} record(s) not identified to species level were skipped.")
    df = df[~bad]
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    bad = ~(df["latitude"].between(5, 38) & df["longitude"].between(67, 98))
    if bad.any():
        notes.append(f"{int(bad.sum())} record(s) with missing or out-of-India coordinates were skipped.")
    df = df[~bad]
    df["obs_date"] = pd.to_datetime(df["obs_date"], errors="coerce", utc=True).dt.tz_localize(None).dt.normalize()
    fut = df["obs_date"] > today
    if fut.any():
        notes.append(f"{int(fut.sum())} record(s) dated in the future were skipped.")
    df = df[~fut]
    if df["obs_date"].isna().any():
        notes.append(f"{int(df['obs_date'].isna().sum())} record(s) have no usable date (kept, undated).")
    df["record_id"] = df["record_id"].astype(str)
    df["dup_key"] = df["dup_key"].fillna(df["source"].astype(str) + ":" + df["record_id"])
    d = df.duplicated("dup_key")
    if d.any():
        notes.append(f"{int(d.sum())} duplicate record(s) within the batch were dropped.")
    df = df[~d]
    df["iucn_category"] = df["iucn_category"].map(iucn_code)
    df["individual_count"] = pd.to_numeric(df["individual_count"], errors="coerce")
    if n0 and not len(df):
        notes.append("No valid records remained after validation.")
    return df.reset_index(drop=True), notes


def protect_sensitive(df: pd.DataFrame) -> pd.DataFrame:
    """Snap sensitive-species coordinates to the centre of a 0.1 degree cell."""
    df = df.copy()
    sens = np.array([is_sensitive(n, c) for n, c in zip(df["scientific_name"], df["iucn_category"])], bool)
    obsc = df["already_obscured"].fillna(False).astype(bool).to_numpy()
    snap = lambda v: (np.floor(v / GENERALISE_DEG) + 0.5) * GENERALISE_DEG  # noqa: E731
    df.loc[sens, "latitude"] = snap(df.loc[sens, "latitude"].to_numpy(float)).round(3)
    df.loc[sens, "longitude"] = snap(df.loc[sens, "longitude"].to_numpy(float)).round(3)
    df["coords_generalised"] = (sens | obsc).astype(int)
    unc = pd.to_numeric(df["coord_uncertainty_m"], errors="coerce")
    df["coord_uncertainty_m"] = np.where(sens, np.fmax(unc.fillna(0), 7800.0), unc)
    df["sensitive"] = sens.astype(int)
    return df


# ------------------------------------------------------------------ persistence
def upsert_species(conn, df: pd.DataFrame) -> int:
    ts = db.now_iso()
    sp = df.sort_values("obs_date", na_position="first").groupby("scientific_name").agg(
        common_name=("common_name", _first), kingdom=("kingdom", _first), phylum=("phylum", _first),
        class_name=("class_name", _first), order_name=("order_name", _first), family=("family", _first),
        gbif_key=("gbif_key", _first), inat_taxon_id=("inat_taxon_id", _first),
        iucn_category=("iucn_category", _mode), iconic=("iconic", _first),
    ).reset_index()
    rows = []
    for r in sp.itertuples():
        grp = taxon_group(r.class_name, r.kingdom, r.phylum, r.iconic)
        rows.append((r.scientific_name, r.common_name, grp, r.kingdom, r.phylum, r.class_name, r.order_name,
                     r.family, _int(r.gbif_key), _int(r.inat_taxon_id), r.iucn_category,
                     "GBIF occurrence (IUCN checklist)" if r.iucn_category else None,
                     int(is_sensitive(r.scientific_name, r.iucn_category)), ts))
    conn.executemany(
        """INSERT INTO species(scientific_name,common_name,taxon_group,kingdom,phylum,class_name,order_name,family,
           gbif_key,inat_taxon_id,iucn_category,iucn_source,sensitive,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(scientific_name) DO UPDATE SET
             common_name=COALESCE(species.common_name, excluded.common_name),
             taxon_group=CASE WHEN species.taxon_group IN ('Other','Other invertebrates') THEN excluded.taxon_group
                              ELSE species.taxon_group END,
             kingdom=COALESCE(species.kingdom, excluded.kingdom), phylum=COALESCE(species.phylum, excluded.phylum),
             class_name=COALESCE(species.class_name, excluded.class_name),
             order_name=COALESCE(species.order_name, excluded.order_name),
             family=COALESCE(species.family, excluded.family),
             gbif_key=COALESCE(species.gbif_key, excluded.gbif_key),
             inat_taxon_id=COALESCE(species.inat_taxon_id, excluded.inat_taxon_id),
             iucn_category=COALESCE(species.iucn_category, excluded.iucn_category),
             iucn_source=COALESCE(species.iucn_source, excluded.iucn_source),
             sensitive=MAX(species.sensitive, excluded.sensitive), updated_at=excluded.updated_at""", rows)
    return len(rows)


def store_observations(df: pd.DataFrame, reserves: pd.DataFrame, keep_outside: bool = False,
                       path=None) -> dict:
    """Validate, locate, protect and insert observations. Duplicates are ignored."""
    clean, notes = validate_observations(df)
    if clean.empty:
        return {"inserted": 0, "duplicates": 0, "notes": notes, "valid": 0}
    located = assign_points(clean, reserves)
    located = located.rename(columns={"inside_boundary": "inside_footprint"})
    if not keep_outside:
        out = located["inside_footprint"] == 0
        if out.any():
            notes.append(f"{int(out.sum())} record(s) outside the reserve footprints were not stored.")
        located = located[~out]
    else:
        located = located[located["pa_id"].notna()]
    located = protect_sensitive(located)
    ts = db.now_iso()
    with db.get_conn(path) as conn:
        upsert_species(conn, located)
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO wildlife_observations(obs_uid,dup_key,source,record_id,dataset,scientific_name,
               pa_id,inside_footprint,latitude,longitude,coords_generalised,coord_uncertainty_m,obs_date,obs_year,
               individual_count,basis_of_record,verification_status,record_url,source_type,retrieved_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(f"{r.source}:{r.record_id}", r.dup_key, r.source, r.record_id, r.dataset, r.scientific_name,
              r.pa_id, int(r.inside_footprint), float(r.latitude), float(r.longitude), int(r.coords_generalised),
              _float(r.coord_uncertainty_m), None if pd.isna(r.obs_date) else str(r.obs_date.date()),
              None if pd.isna(r.obs_date) else int(r.obs_date.year), _int(r.individual_count),
              r.basis_of_record, r.verification_status, r.record_url, r.source_type, ts)
             for r in located.itertuples()])
        inserted = conn.total_changes - before
        rebuild_species_reserve(conn)
    return {"inserted": inserted, "duplicates": len(located) - inserted, "notes": notes, "valid": len(located)}


def rebuild_species_reserve(conn) -> None:
    conn.execute("DELETE FROM species_reserve")
    conn.execute(
        """INSERT INTO species_reserve(pa_id,scientific_name,n_records,n_sources,sources,first_date,last_date)
           SELECT pa_id, scientific_name, COUNT(*), COUNT(DISTINCT source), GROUP_CONCAT(DISTINCT source),
                  MIN(obs_date), MAX(obs_date)
           FROM wildlife_observations WHERE pa_id IS NOT NULL GROUP BY pa_id, scientific_name""")


def load_reference_data(conn) -> None:
    """Load curated species reference rows and cited official population estimates (idempotent)."""
    ts = db.now_iso()
    ref = pd.read_csv(settings.DATA_DIR / "species_reference.csv")
    for r in ref.itertuples():
        conn.execute(
            """INSERT INTO species(scientific_name,common_name,taxon_group,kingdom,phylum,class_name,order_name,
               family,iucn_category,iucn_assessment_year,iucn_source,sensitive,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(scientific_name) DO UPDATE SET
               common_name=COALESCE(species.common_name, excluded.common_name),
               iucn_category=COALESCE(species.iucn_category, excluded.iucn_category),
               iucn_assessment_year=COALESCE(species.iucn_assessment_year, excluded.iucn_assessment_year),
               iucn_source=COALESCE(species.iucn_source, excluded.iucn_source)""",
            (r.scientific_name, r.common_name, r.taxon_group, r.kingdom, r.phylum, r.class_name, r.order_name,
             r.family, r.iucn_category, int(r.iucn_assessment_year), r.iucn_source,
             int(is_sensitive(r.scientific_name, r.iucn_category)), ts))
    pop = pd.read_csv(settings.DATA_DIR / "population_estimates.csv")
    insert_population(conn, pop, settings.HISTORICAL)


POP_REQUIRED = ["scientific_name", "scope", "estimate", "survey_year", "method", "institution"]


def validate_population(raw: pd.DataFrame, reserves: pd.DataFrame) -> tuple[pd.DataFrame | None, list[str]]:
    notes: list[str] = []
    df = raw.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in POP_REQUIRED if c not in df.columns]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)}"]
    for c in ["pa_id", "lower_ci", "upper_ci", "source_url", "notes"]:
        if c not in df.columns:
            df[c] = None
    df["scientific_name"] = df["scientific_name"].map(canonical_name)
    for c in ["estimate", "lower_ci", "upper_ci", "survey_year"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad = df["scientific_name"].isna() | df["estimate"].isna() | (df["estimate"] < 0) | \
        ~df["survey_year"].between(1900, pd.Timestamp.today().year)
    bad |= df[["method", "institution", "scope"]].isna().any(axis=1)
    if bad.any():
        notes.append(f"{int(bad.sum())} row(s) missing species, estimate, valid year, method, institution or scope "
                     "were skipped.")
    df = df[~bad]
    ci_bad = df["lower_ci"].notna() & df["upper_ci"].notna() & \
        ~((df["lower_ci"] <= df["estimate"]) & (df["estimate"] <= df["upper_ci"]))
    if ci_bad.any():
        notes.append(f"{int(ci_bad.sum())} row(s) with a confidence interval not containing the estimate were skipped.")
        df = df[~ci_bad]
    df["pa_id"] = df["pa_id"].where(df["pa_id"].isin(reserves["pa_id"]), None)
    return df, notes


def insert_population(conn, df: pd.DataFrame, source_type: str) -> int:
    ts = db.now_iso()
    for name in df["scientific_name"].unique():  # ensure species rows exist (minimal) for FK
        conn.execute("INSERT OR IGNORE INTO species(scientific_name,taxon_group,updated_at) VALUES (?,?,?)",
                     (name, "Other", ts))
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO population_estimates(scientific_name,pa_id,scope,estimate,lower_ci,upper_ci,
           survey_year,method,institution,source_url,notes,source_type,retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(r.scientific_name, r.pa_id if isinstance(r.pa_id, str) else None, r.scope, float(r.estimate),
          _float(r.lower_ci), _float(r.upper_ci), int(r.survey_year), r.method, r.institution,
          r.source_url if isinstance(r.source_url, str) else None,
          r.notes if isinstance(r.notes, str) else None, source_type, ts) for r in df.itertuples()])
    return conn.total_changes - before


# ------------------------------------------------------------------ uploads (Darwin Core style)
DWC_ALIASES = {
    "scientific_name": ["scientificname", "scientific_name", "species", "sciname"],
    "common_name": ["vernacularname", "common_name", "commonname", "comname"],
    "latitude": ["decimallatitude", "latitude", "lat"],
    "longitude": ["decimallongitude", "longitude", "lon", "lng"],
    "obs_date": ["eventdate", "obs_date", "date", "observed_on", "obsdt"],
    "record_id": ["occurrenceid", "record_id", "id", "catalognumber", "gbifid"],
    "class_name": ["class", "class_name"], "order_name": ["order", "order_name"], "family": ["family"],
    "kingdom": ["kingdom"], "phylum": ["phylum"],
    "individual_count": ["individualcount", "individual_count", "count", "howmany"],
    "basis_of_record": ["basisofrecord", "basis_of_record"],
    "verification_status": ["identificationverificationstatus", "verification_status", "quality_grade"],
    "coord_uncertainty_m": ["coordinateuncertaintyinmeters", "coord_uncertainty_m"],
    "iucn_category": ["iucnredlistcategory", "iucn_category"], "dataset": ["datasetname", "dataset"],
    "record_url": ["references", "url", "record_url"],
}


def from_upload(raw: pd.DataFrame, filename: str) -> tuple[pd.DataFrame | None, list[str]]:
    low = {c.strip().lower(): c for c in raw.columns}
    out = pd.DataFrame(index=raw.index)
    for k, aliases in DWC_ALIASES.items():
        col = next((low[a] for a in aliases if a in low), None)
        out[k] = raw[col] if col else None
    missing = [k for k in ["scientific_name", "latitude", "longitude", "obs_date"] if out[k].isna().all()]
    if missing:
        return None, [f"Missing required column(s): {', '.join(missing)} (Darwin Core names accepted, e.g. "
                      "scientificName, decimalLatitude, decimalLongitude, eventDate)."]
    notes = []
    if out["record_id"].isna().all():
        notes.append("No occurrenceID column: record IDs were derived from species, date and location.")
        out["record_id"] = (out["scientific_name"].astype(str) + "|" + out["obs_date"].astype(str) + "|"
                            + out["latitude"].astype(str) + "|" + out["longitude"].astype(str))
    out["source"], out["source_type"] = "Upload", settings.UPLOADED
    out["dataset"] = out["dataset"].fillna(filename)
    out["dup_key"] = "upload:" + out["record_id"].astype(str)
    out["already_obscured"] = False
    return out, notes


# ------------------------------------------------------------------ helpers
def _first(s):
    s = s.dropna()
    return s.iloc[-1] if len(s) else None


def _mode(s):
    s = s.dropna()
    return s.mode().iloc[0] if len(s) else None


def _int(v):
    try:
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        v = float(v)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None
