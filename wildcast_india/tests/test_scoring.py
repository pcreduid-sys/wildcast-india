"""Tests for the Habitat Stress Score engine, validation and database pipeline."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from processing import cleaning, stress_scoring as ss  # noqa: E402

CFG = settings.DEFAULT_SCORING
W, TH = CFG["weights"], CFG["thresholds"]


def test_rainfall_deficit_formula():
    assert ss.rainfall_deficit_pct(60, 100) == pytest.approx(40.0)
    assert ss.rainfall_deficit_pct(150, 100) == pytest.approx(-50.0)
    assert ss.rainfall_deficit_pct(10, 0) is None


def test_component_bounds():
    assert ss.drought_score(200, 300, 25, TH) == 25
    assert ss.drought_score(-30, 300, 25, TH) == 0
    assert ss.heat_score(10, 7, 25, TH) == pytest.approx(25)
    assert ss.heat_score(-2, 0, 25, TH) == 0
    assert ss.vegetation_score(-50, 25, TH) == 25
    assert ss.vegetation_score(10, 25, TH) == 0
    assert ss.fire_score(0, 25, TH) == 0
    assert ss.fire_score(10_000, 25, TH) == 25


def test_drought_damped_in_dry_season():
    assert ss.drought_score(60, 10, 25, TH) == pytest.approx(25 * 10 / 50)


def test_full_score_sums_components():
    out = ss.combine({"heat": 20, "drought": 25, "vegetation": 20, "fire": 20}, W)
    assert out["total_score"] == 85 and out["category"] == "Severe"
    assert out["completeness"] == 1 and out["provisional"] == 0


def test_missing_data_not_zero_and_provisional():
    out = ss.combine({"heat": 15, "drought": 15, "vegetation": None, "fire": 15}, W)
    assert out["provisional"] == 1 and out["completeness"] == 0.75
    assert out["total_score"] == pytest.approx(60)  # rescaled, not 45
    assert ss.combine(dict.fromkeys(ss.INDICATORS), W)["total_score"] is None


@pytest.mark.parametrize("score,label", [(0, "Low"), (39.9, "Low"), (40, "Moderate"), (59.9, "Moderate"),
                                         (60, "High"), (79.9, "High"), (80, "Severe"), (100, "Severe")])
def test_categories(score, label):
    assert settings.category_for(score)[0] == label


def _synthetic(years=4, rain=5.0, tmax=30.0):
    d = pd.date_range("2020-01-01", periods=365 * years, freq="D")
    return pd.DataFrame({"obs_date": d, "tmax_c": tmax, "precip_mm": rain})


def test_metrics_detect_deficit_and_heat():
    w = _synthetic()
    end = w["obs_date"].max()
    recent = w["obs_date"] > end - pd.Timedelta(days=90)
    w.loc[recent, "precip_mm"] = 2.0          # 60% deficit
    w.loc[w["obs_date"] > end - pd.Timedelta(days=7), "tmax_c"] = 34.0
    m = ss.compute_metrics(w, pd.DataFrame(), pd.Series(dtype="datetime64[ns]"), end, TH, fire_covered=False)
    assert m["deficit_pct"] == pytest.approx(60, abs=0.5)
    assert m["tmax_anomaly_c"] == pytest.approx(4, abs=0.1)
    assert m["fire_count_7d"] is None and m["ndvi_change_pct"] is None
    s = ss.score_from_metrics(m, CFG)
    assert s["provisional"] == 1 and s["fire_score"] is None and s["drought_score"] == pytest.approx(25)


def test_insufficient_history_is_missing():
    w = _synthetic(years=1)
    m = ss.compute_metrics(w, pd.DataFrame(), pd.Series(dtype="datetime64[ns]"), w["obs_date"].max(), TH, True)
    assert m["deficit_pct"] is None and m["tmax_anomaly_c"] is None and m["fire_count_7d"] == 0


def test_weather_validation():
    reserves = pd.read_csv(settings.SAMPLE_RESERVES_CSV)
    raw = pd.DataFrame({"Reserve": ["Gir", "Gir", "Atlantis"], "Date": ["2025-01-01", "bad", "2025-01-01"],
                        "TMAX": [30, 31, 32], "Rainfall": [0, 5, 1]})
    df, notes = cleaning.validate_weather(raw, reserves)
    assert len(df) == 1 and df["pa_id"].iloc[0] == "GIR" and len(notes) == 2


def test_database_pipeline(tmp_path, monkeypatch):
    from database import db
    monkeypatch.setattr(settings, "DB_PATH", tmp_path / "t.db")
    db.init_db(tmp_path / "t.db")
    latest = db.get_latest_scores(tmp_path / "t.db")
    assert len(latest) == 10
    assert latest["total_score"].between(0, 100).all()
    assert latest.loc[latest["pa_id"] == "SUN", "provisional"].iloc[0] == 1  # NDVI gap demo
    al = db.get_alerts(path=tmp_path / "t.db")
    assert not al.empty
    assert db.acknowledge_alerts([al["alert_id"].iloc[0]], "tester", tmp_path / "t.db") == 1
    from processing.pipeline import rebuild_derived
    rebuild_derived(tmp_path / "t.db")  # acknowledgement must survive recomputation
    al2 = db.get_alerts(path=tmp_path / "t.db")
    assert al2.loc[al2["alert_id"] == al["alert_id"].iloc[0], "acknowledged"].iloc[0] == 1
