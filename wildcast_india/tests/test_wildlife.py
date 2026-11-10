"""Wildlife module tests: parsing, validation, sensitive-coordinate protection, de-duplication,
reference data, uploads and API failure handling. Network calls are replaced by tests/mock_apis.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import mock_apis  # noqa: E402
from config import settings  # noqa: E402
from database import db  # noqa: E402
from processing import wildlife as wl  # noqa: E402


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    path = tmp_path / "w.db"
    monkeypatch.setattr(settings, "DB_PATH", path)
    db.init_db(path)
    import time
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    return path


def test_name_and_iucn_normalisation():
    assert wl.canonical_name("Panthera tigris tigris (Linnaeus, 1758)") == "Panthera tigris"
    assert wl.canonical_name("Panthera") is None and wl.canonical_name(None) is None
    assert wl.iucn_code("ENDANGERED") == "EN" and wl.iucn_code("lc") == "LC" and wl.iucn_code("x") is None
    assert wl.taxon_group("Aves") == "Birds" and wl.taxon_group("Squamata") == "Reptiles"
    assert wl.taxon_group(None, iconic="Amphibia") == "Amphibians"


def test_validation_rejects_bad_records():
    df = pd.DataFrame({"source": "Upload", "record_id": ["1", "2", "3", "4", "4"],
                       "scientific_name": ["Axis axis", "Axis", "Axis axis", "Axis axis", "Axis axis"],
                       "latitude": [11.6, 11.6, 51.0, 11.6, 11.6], "longitude": [76.6] * 5,
                       "obs_date": ["2024-01-01", "2024-01-01", "2024-01-01", "2099-01-01", "2024-02-01"]})
    clean, notes = wl.validate_observations(df)
    assert list(clean["record_id"]) == ["1", "4"] or len(clean) == 2
    assert any("species level" in n for n in notes) and any("future" in n for n in notes)
    assert any("out-of-India" in n for n in notes)


def test_sensitive_species_generalised():
    df = pd.DataFrame({"scientific_name": ["Panthera tigris", "Axis axis", "Gyps bengalensis"],
                       "iucn_category": [None, "LC", "CR"], "latitude": [11.6234, 11.6234, 11.6234],
                       "longitude": [76.6789] * 3, "coord_uncertainty_m": [10, 10, 10],
                       "already_obscured": [False, False, False]})
    out = wl.protect_sensitive(df)
    assert list(out["coords_generalised"]) == [1, 0, 1]
    assert out.loc[0, "latitude"] == pytest.approx(11.65) and out.loc[1, "latitude"] == pytest.approx(11.6234)
    assert out.loc[0, "coord_uncertainty_m"] >= 7800


def test_reference_population_loaded_and_idempotent(tmp_db):
    pop = db.get_population(tmp_db)
    assert len(pop) == 19 and pop["source_url"].notna().all() and pop["institution"].notna().all()
    assert (pop["source_type"] == "HISTORICAL").all()
    db.init_db(tmp_db)  # re-running init must not duplicate
    assert len(db.get_population(tmp_db)) == 19
    assert db.get_observations(path=tmp_db).empty  # no fabricated occurrence records shipped


def test_connectors_parse_store_and_dedupe(tmp_db, monkeypatch):
    from ingestion import ebird, gbif, inaturalist, iucn
    for m in (gbif, inaturalist, ebird, iucn):
        monkeypatch.setattr(m, "get", mock_apis.fake_get)
    monkeypatch.setenv("EBIRD_API_KEY", "k")
    monkeypatch.setenv("IUCN_API_TOKEN", "t")
    r1 = gbif.refresh(max_records=300)
    assert r1["ok"] and r1["records"] > 0
    r2 = inaturalist.refresh(max_records=200)
    assert r2["ok"] and "already stored" in r2["message"]
    n_before = len(db.get_observations(path=tmp_db))
    assert gbif.refresh(max_records=300)["records"] == 0  # identical re-fetch adds nothing
    assert len(db.get_observations(path=tmp_db)) == n_before
    assert ebird.refresh()["records"] > 0
    assert iucn.refresh(limit=3)["records"] == 3
    obs = db.get_observations(path=tmp_db)
    assert obs["dup_key"].is_unique
    for col in ["source", "obs_date", "scientific_name", "latitude", "longitude", "record_id",
                "verification_status", "retrieved_at"]:
        assert obs[col].notna().any(), col
    assert (obs.loc[obs["scientific_name"] == "Panthera tigris", "coords_generalised"] == 1).all()
    assert obs["inside_footprint"].eq(1).all()
    sr = db.get_species_reserve(tmp_db)
    assert sr["n_records"].sum() == len(obs[obs["pa_id"].notna()])
    sp = db.get_species(tmp_db)
    assert sp.loc[sp["scientific_name"] == "Axis axis", "common_name"].iloc[0] == "Chital"


def test_api_failures_and_missing_keys(tmp_db, monkeypatch):
    from ingestion import ebird, gbif, inaturalist, iucn
    for m in (gbif, inaturalist):
        monkeypatch.setattr(m, "get", mock_apis.failing_get)
    for mod in (gbif, inaturalist):
        res = mod.refresh()
        assert not res["ok"] and "aborted" in res["message"]
    monkeypatch.delenv("EBIRD_API_KEY", raising=False)
    monkeypatch.delenv("IUCN_API_TOKEN", raising=False)
    assert "not configured" in ebird.refresh()["message"]
    assert "not configured" in iucn.refresh()["message"]
    src = db.get_data_sources(tmp_db).set_index("source_key")
    assert src.loc["GBIF", "status"] == "FAILED" and src.loc["EBIRD", "status"] == "NOT CONFIGURED"
    assert db.get_observations(path=tmp_db).empty


def test_darwin_core_upload_and_population_upload(tmp_db):
    reserves = db.get_reserves(tmp_db)
    raw = pd.DataFrame({"scientificName": ["Axis axis", "Axis axis", "Pavo cristatus"],
                        "decimalLatitude": [11.66, 11.66, 28.0], "decimalLongitude": [76.63, 76.63, 72.0],
                        "eventDate": ["2023-03-01", "2023-03-01", "2023-03-02"], "occurrenceID": ["a", "a", "b"],
                        "class": ["Mammalia", "Mammalia", "Aves"]})
    df, notes = wl.from_upload(raw, "test.csv")
    res = wl.store_observations(df, reserves, path=tmp_db)
    assert res["inserted"] == 1  # duplicate dropped, out-of-footprint record not stored
    assert any("outside" in n for n in res["notes"]) and any("duplicate" in n for n in res["notes"])
    again = wl.store_observations(df, reserves, path=tmp_db)
    assert again["inserted"] == 0
    pop = pd.DataFrame({"scientific_name": ["Elephas maximus", "Elephas maximus"], "scope": ["Test scope"] * 2,
                        "estimate": [100, 50], "lower_ci": [80, 60], "upper_ci": [120, 70],
                        "survey_year": [2017, 2017], "method": ["Block count"] * 2, "institution": ["Test"] * 2})
    clean, notes = wl.validate_population(pop, reserves)
    assert len(clean) == 1 and any("confidence interval" in n for n in notes)
