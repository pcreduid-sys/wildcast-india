"""Water Intelligence tests: demo seeding/labelling, assessment rules, priorities, species traits,
insights wording, uploads and persistence."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from database import db  # noqa: E402
from processing import water as w  # noqa: E402
from processing import water_io  # noqa: E402


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("water") / "w.db"
    old = settings.DB_PATH
    settings.DB_PATH = path
    db.init_db(path)
    yield path
    settings.DB_PATH = old


def test_demo_water_bodies_all_reserves_and_labelled(tmp_db):
    wbs = db.get_water_bodies(tmp_db)
    assert set(wbs["pa_id"]) == set(db.get_reserves(tmp_db)["pa_id"])
    assert (wbs["source_type"] == "SIMULATED").all() and (wbs["location_basis"] == "ILLUSTRATIVE").all()
    assert wbs["name"].str.startswith("Demo water point").all()
    obs = db.get_water_obs(path=tmp_db)
    assert (obs["source_type"] == "SIMULATED").all()
    assert set(obs["obs_kind"]) == {"DIRECT", "SATELLITE"}


def test_demo_data_is_fixed(tmp_path):
    p1, p2 = tmp_path / "a.db", tmp_path / "b.db"
    db.init_db(p1)
    db.init_db(p2)
    a, b = db.get_water_obs(path=p1), db.get_water_obs(path=p2)
    pd.testing.assert_frame_equal(a.drop(columns="ingested_at"), b.drop(columns="ingested_at"))
    assert db.get_water_bodies(p1)[["latitude", "longitude"]].equals(db.get_water_bodies(p2)[["latitude", "longitude"]])


def test_assessments_cover_categories_and_bounds(tmp_db):
    a = db.get_water_assessments(path=tmp_db)
    assert set(a["category"]) <= set(w.CATEGORIES)
    assert a["priority_score"].between(0, 100).all()
    assert set(a["evidence"]) <= {"DIRECT", "SATELLITE", "WEATHER_PROXY", "NONE"}
    latest = a[a["week_end"] == a["week_end"].max()]
    assert len(latest) == len(db.get_water_bodies(tmp_db))
    assert (latest["evidence"] == "DIRECT").any() and (latest["evidence"] == "WEATHER_PROXY").any()
    # GIR (demo drought scenario) must outrank KAZ (wet) on average priority
    pr = latest.groupby("pa_id")["priority_score"].mean()
    assert pr["GIR"] > pr["KAZ"]


def _series(vals, end="2026-11-01", step=16):
    d = pd.date_range(end=end, periods=len(vals), freq=f"{step}D")
    return pd.DataFrame({"obs_date": d, "value": vals})


def test_evidence_hierarchy_and_staleness():
    end = pd.Timestamp("2026-11-01")
    sat = _series([60.0] * 40 + [15.0])            # far below seasonal norm
    direct = _series([2.0] * 60 + [2.0], step=7)   # normal
    cond = {"rain_90d_mm": 100, "rain_90d_normal": 100, "rain_30d_mm": 30, "rain_30d_normal": 30, "tmax_anomaly_30d": 0}
    cat, ev, r, *_ = w.assess(direct, sat, cond, end)
    assert ev == "DIRECT" and cat == "High availability"
    stale = direct.assign(obs_date=direct["obs_date"] - pd.Timedelta(days=40))
    cat, ev, r, *_ = w.assess(stale, sat, cond, end)
    assert ev == "SATELLITE" and cat == "Potential water stress"
    cat, ev, r, *_ = w.assess(stale.iloc[0:0], sat.iloc[0:0], cond, end)
    assert ev == "WEATHER_PROXY" and cat == "High availability"
    cat, ev, r, *_ = w.assess(stale.iloc[0:0], sat.iloc[0:0], {}, end)
    assert (cat, ev, r) == ("Insufficient data", "NONE", None)


def test_window_rain_deficit():
    d = pd.date_range("2020-01-01", "2026-11-01")
    p = pd.Series(2.0, index=d)
    p[p.index > pd.Timestamp("2026-11-01") - pd.Timedelta(days=90)] = 1.0
    a, n, dfc = w.window_rain(p, pd.Timestamp("2026-11-01"), 90)
    assert n == pytest.approx(180) and a == pytest.approx(90) and dfc == pytest.approx(50)


def test_priority_components():
    p = w.priority(0.2, "WEATHER_PROXY", {"deficit_90d_pct": 60, "tmax_anomaly_30d": 4}, -30, 5, None)
    assert p["priority_score"] == pytest.approx(35 * 0.8 + 20 + 10 + 10 + 5 + 16)
    assert p["priority_band"].startswith("Priority 1")
    q = w.priority(1.1, "DIRECT", {"deficit_90d_pct": -20, "tmax_anomaly_30d": -1}, 5, 0, 3)
    assert q["priority_score"] == 0 and q["priority_band"] == "Routine"


def test_species_traits():
    assert w.water_trait("Elephas maximus")["dependency"] == "High"
    assert w.water_trait("Panthera tigris")["dependency"] == "Indirect"
    assert w.water_trait("Axis axis", "Cervidae")["dependency"] == "Moderate"
    assert w.water_trait("Ardea alba", "Ardeidae")["dependency"] == "High"
    assert w.water_trait("Hoplobatrachus tigerinus", None, "Amphibians")["dependency"] == "High"
    assert w.water_trait("Dicrurus macrocercus", "Dicruridae", "Birds") is None


def test_insights_are_reserve_specific_and_careful(tmp_db):
    a = db.get_water_assessments(path=tmp_db)
    latest = a[a["week_end"] == a["week_end"].max()]
    texts = {}
    for pa, name in [("GIR", "Gir"), ("KAZ", "Kaziranga")]:
        wa = latest[latest["pa_id"] == pa]
        cond = wa.iloc[0][["rain_30d_mm", "rain_30d_normal", "deficit_30d_pct", "rain_60d_mm", "rain_60d_normal",
                           "deficit_60d_pct", "rain_90d_mm", "rain_90d_normal", "deficit_90d_pct",
                           "tmax_anomaly_30d"]].to_dict()
        ins = w.reserve_insights(name, cond, {"ndvi_change_pct": -20 if pa == "GIR" else 2, "fire_count_7d": 3},
                                 wa, pd.DataFrame(columns=["scientific_name", "common_name", "taxon_group", "dependency",
                                                           "why", "records_total"]), {"weather_simulated": True})
        assert set(ins) == {"observed", "implications", "recommendations", "limitations"}
        assert all(ins[k] for k in ins)
        texts[pa] = " ".join(sum(ins.values(), []))
    assert texts["GIR"] != texts["KAZ"] and "Gir" in texts["GIR"] and "Kaziranga" in texts["KAZ"]
    for t in texts.values():
        low = t.lower()
        assert " is dry" not in low and "has dried" not in low
        assert "cannot establish population decline" in low and "simulated" in low


def test_water_uploads_and_reassessment(tmp_db):
    from processing.pipeline import rebuild_water
    reserves = db.get_reserves(tmp_db)
    raw = pd.DataFrame({"name": ["Survey pond A", "Far away"], "wb_type": ["Natural waterhole", "Lake"],
                        "latitude": [11.66, 28.6], "longitude": [76.64, 77.2], "location_basis": ["verified", ""]})
    df, notes = water_io.validate_water_bodies(raw, reserves)
    assert len(df) == 1 and df["pa_id"].iloc[0] == "BAN" and df["location_basis"].iloc[0] == "VERIFIED"
    assert water_io.store_water_bodies(df, "t.csv", tmp_db) == 1
    assert water_io.store_water_bodies(df, "t.csv", tmp_db) == 0  # duplicate ignored
    wb_id = df["wb_id"].iloc[0]
    today = pd.Timestamp.today().normalize()
    dates = pd.date_range(end=today - pd.Timedelta(days=2), periods=30, freq="7D")
    obs = pd.DataFrame({"wb_id": wb_id, "date": dates.astype(str), "metric": "water_level_m",
                        "value": np.r_[np.full(29, 2.0), 0.4]})
    bad = pd.DataFrame({"wb_id": [wb_id, "NOPE"], "date": ["2099-01-01", "2024-01-01"], "metric": ["water_level_m"] * 2,
                        "value": [1, 1]})
    clean, notes = water_io.validate_water_obs(pd.concat([obs, bad]), db.get_water_bodies(tmp_db))
    assert len(clean) == 30 and len(notes) == 2
    assert water_io.store_water_obs(clean, "o.csv", tmp_db) == 30
    rebuild_water(tmp_db)
    a = db.get_water_assessments(path=tmp_db)
    cur = a[(a["wb_id"] == wb_id) & (a["week_end"] == a["week_end"].max())].iloc[0]
    assert cur["evidence"] == "DIRECT" and cur["category"] == "Potential water stress"
    assert cur["source_type"] == "UPLOADED"
