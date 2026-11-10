"""Central configuration for WILDCAST INDIA."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
DB_PATH = Path(os.getenv("WILDCAST_DB_PATH", DATA_DIR / "wildcast.db"))
SAMPLE_RESERVES_CSV = DATA_DIR / "sample_reserves.csv"
SCORING_CONFIG_PATH = DATA_DIR / "scoring_config.json"

FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "").strip()
FIRMS_SOURCE = os.getenv("FIRMS_SOURCE", "VIIRS_SNPP_NRT")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

# Demonstration dataset: deterministic seed so every install produces identical data.
DEMO_SEED = 20260101
DEMO_YEARS_HISTORY = 6          # years of simulated daily history (gives a climatology baseline)
SCORE_HISTORY_WEEKS = 104       # weekly scores computed back this many weeks

# Record provenance labels
LIVE, HISTORICAL, UPLOADED, SIMULATED = "LIVE", "HISTORICAL", "UPLOADED", "SIMULATED"
SOURCE_TYPES = [LIVE, HISTORICAL, UPLOADED, SIMULATED]

CATEGORIES = [  # (lower bound inclusive, label, colour)
    (80, "Severe", "#D95F59"),
    (60, "High", "#E58B43"),
    (40, "Moderate", "#E5B65B"),
    (0, "Low", "#6FAF83"),
]

THEME = {
    "bg": "#101A18", "sidebar": "#15231F", "card": "#1B2C27", "border": "#2A4038",
    "green": "#6FAF83", "yellow": "#E5B65B", "orange": "#E58B43", "red": "#D95F59",
    "text": "#F1F4F2", "muted": "#9DB0A8", "blue": "#6FA3C7",
}

DEFAULT_SCORING = {
    "weights": {"heat": 25, "drought": 25, "vegetation": 25, "fire": 25},
    "thresholds": {
        "heat_anomaly_max_c": 4.0,       # 7-day Tmax anomaly giving full anomaly sub-score
        "heat_anomaly_share": 0.6,       # share of heat score from anomaly (rest = hot days)
        "drought_deficit_max_pct": 60.0, # 90-day deficit giving full drought score
        "ndvi_decline_max_pct": 30.0,    # NDVI below seasonal baseline giving full score
        "fire_count_max": 50,            # 7-day detections giving full fire score
        "ndvi_max_age_days": 32,         # older NDVI observation => vegetation missing
        "min_weather_days_7": 5,         # min days of weather in 7-day window
        "min_rain_days_90": 75,          # min days of rainfall in 90-day window
    },
    "alerts": {
        "fire_24h_count": 5,
        "fire_7d_count": 20,
        "drought_deficit_pct": 50.0,
        "heat_anomaly_c": 3.0,
    },
}


def load_scoring_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_SCORING))
    if SCORING_CONFIG_PATH.exists():
        try:
            saved = json.loads(SCORING_CONFIG_PATH.read_text())
            for section in cfg:
                cfg[section].update(saved.get(section, {}))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save_scoring_config(cfg: dict) -> None:
    SCORING_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCORING_CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


def category_for(score: float | None) -> tuple[str, str]:
    if score is None or score != score:  # NaN check
        return "No data", "#5E6E68"
    for lower, label, colour in CATEGORIES:
        if score >= lower:
            return label, colour
    return "Low", THEME["green"]
