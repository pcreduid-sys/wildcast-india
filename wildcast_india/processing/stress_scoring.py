"""Habitat Stress Score (HSS) engine — the single source of scoring logic.

HSS = Heat + Drought + Vegetation + Fire, each 0..weight (default 25 each, total 100).

* Heat       : 7-day mean Tmax anomaly vs day-of-year baseline (+/-7 days) and number of
               days above the baseline 90th percentile (+/-15 days).
* Drought    : 90-day rainfall vs the mean of the same calendar window in baseline years.
               deficit % = (normal - actual) / normal * 100. Damped when normal < 50 mm
               (dry season, where percentages are unstable).
* Vegetation : latest NDVI (<= ndvi_max_age_days old) vs seasonal baseline (+/-16 days DOY).
* Fire       : satellite detections inside the reserve footprint over the past 7 days
               (log-scaled, full score at fire_count_max). Only scored for periods for which
               fire data was actually retrieved; otherwise it is MISSING, not zero.

Baseline years = all observations dated more than 365 days before the week being scored
(at least 2 years required). Missing indicators are never treated as zero stress: the total
is re-scaled over the available indicators and flagged provisional.

This is a transparent screening index for research prioritisation. It is NOT an officially
validated ecological index.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config.settings import category_for

INDICATORS = ["heat", "drought", "vegetation", "fire"]


# ---------------------------------------------------------------- component scores
def _clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def heat_score(anomaly_c, hot_days, weight, th) -> float | None:
    if anomaly_c is None or hot_days is None:
        return None
    share = th["heat_anomaly_share"]
    return weight * (share * _clip01(anomaly_c / th["heat_anomaly_max_c"])
                     + (1 - share) * _clip01(hot_days / 7.0))


def rainfall_deficit_pct(actual_mm, normal_mm) -> float | None:
    if actual_mm is None or normal_mm is None or normal_mm <= 0:
        return None
    return (normal_mm - actual_mm) / normal_mm * 100.0


def drought_score(deficit_pct, normal_mm, weight, th) -> float | None:
    if deficit_pct is None or normal_mm is None:
        return None
    damp = min(1.0, normal_mm / 50.0)
    return weight * _clip01(deficit_pct / th["drought_deficit_max_pct"]) * damp


def vegetation_score(ndvi_change_pct, weight, th) -> float | None:
    if ndvi_change_pct is None:
        return None
    return weight * _clip01(-ndvi_change_pct / th["ndvi_decline_max_pct"])


def fire_score(count, weight, th) -> float | None:
    if count is None:
        return None
    return weight * min(1.0, math.log1p(count) / math.log1p(th["fire_count_max"]))


def combine(components: dict, weights: dict) -> dict:
    avail = {k: v for k, v in components.items() if v is not None}
    if not avail:
        return {"total_score": None, "completeness": 0.0, "provisional": 1, "category": "No data"}
    w_avail = sum(weights[k] for k in avail)
    raw = sum(avail.values())
    total = raw if len(avail) == len(INDICATORS) else raw * sum(weights.values()) / w_avail
    total = round(min(100.0, total), 1)
    return {"total_score": total, "completeness": len(avail) / len(INDICATORS),
            "provisional": int(len(avail) < len(INDICATORS)), "category": category_for(total)[0]}


# ---------------------------------------------------------------- metrics
def _doy_dist(doy: np.ndarray, target: int) -> np.ndarray:
    d = np.abs(doy - target)
    return np.minimum(d, 365 - d)


def compute_metrics(weather: pd.DataFrame, ndvi: pd.DataFrame, fire_dates: pd.Series,
                    week_end: pd.Timestamp, th: dict, fire_covered: bool) -> dict:
    """Raw indicator metrics for one reserve and one week (week_end inclusive)."""
    m = dict(tmax_anomaly_c=None, hot_days=None, rain_90d_mm=None, rain_normal_mm=None,
             deficit_pct=None, ndvi=None, ndvi_baseline=None, ndvi_change_pct=None,
             fire_count_7d=None)
    base_cut = week_end - pd.Timedelta(days=365)
    tdoy = week_end.dayofyear

    if not weather.empty:
        wd = weather["obs_date"]
        # Heat
        w7 = weather[(wd > week_end - pd.Timedelta(days=7)) & (wd <= week_end)]
        tmax7 = w7["tmax_c"].dropna()
        base = weather[(wd < base_cut) & weather["tmax_c"].notna()]
        if len(tmax7) >= th["min_weather_days_7"] and base["obs_date"].dt.year.nunique() >= 2:
            bdoy = base["obs_date"].dt.dayofyear.to_numpy()
            near7 = base["tmax_c"].to_numpy()[_doy_dist(bdoy, tdoy) <= 7]
            near15 = base["tmax_c"].to_numpy()[_doy_dist(bdoy, tdoy) <= 15]
            if len(near7) >= 10:
                m["tmax_anomaly_c"] = round(float(tmax7.mean() - near7.mean()), 2)
                m["hot_days"] = int((tmax7 > np.percentile(near15, 90)).sum())
        # Drought
        p = weather.set_index("obs_date")["precip_mm"]
        win = p[(p.index > week_end - pd.Timedelta(days=90)) & (p.index <= week_end)].dropna()
        if len(win) >= th["min_rain_days_90"]:
            actual = float(win.sum()) * 90.0 / len(win)
            normals = []
            for k in range(1, 30):
                e = week_end - pd.DateOffset(years=k)
                s =e - pd.Timedelta(days=89)
                if s < p.index.min():
                    break
                seg = p[(p.index >= s) & (p.index <= e)].dropna()
                if len(seg) >= th["min_rain_days_90"]:
                    normals.append(float(seg.sum()) * 90.0 / len(seg))
            if len(normals) >= 2:
                normal = float(np.mean(normals))
                m["rain_90d_mm"], m["rain_normal_mm"] = round(actual, 1), round(normal, 1)
                d = rainfall_deficit_pct(actual, normal)
                m["deficit_pct"] = None if d is None else round(d, 1)

    if not ndvi.empty:
        nv = ndvi[ndvi["ndvi"].notna()]
        recent = nv[(nv["obs_date"] <= week_end) &
                    (nv["obs_date"] > week_end - pd.Timedelta(days=th["ndvi_max_age_days"]))]
        base = nv[nv["obs_date"] < base_cut]
        if not recent.empty and not base.empty:
            last = recent.iloc[-1]
            bsel = base[_doy_dist(base["obs_date"].dt.dayofyear.to_numpy(),
                                  last["obs_date"].dayofyear) <= 16]
            if bsel["obs_date"].dt.year.nunique() >= 2:
                bl = float(bsel["ndvi"].mean())
                m["ndvi"], m["ndvi_baseline"] = round(float(last["ndvi"]), 3), round(bl, 3)
                if bl > 0.05:
                    m["ndvi_change_pct"] = round((last["ndvi"] - bl) / bl * 100, 1)

    if fire_covered:
        fd = fire_dates
        m["fire_count_7d"] = int(((fd > week_end - pd.Timedelta(days=7)) & (fd <= week_end)).sum())
    return m


def score_from_metrics(m: dict, cfg: dict) -> dict:
    w, th = cfg["weights"], cfg["thresholds"]
    comps = {
        "heat": heat_score(m["tmax_anomaly_c"], m["hot_days"], w["heat"], th),
        "drought": drought_score(m["deficit_pct"], m["rain_normal_mm"], w["drought"], th),
        "vegetation": vegetation_score(m["ndvi_change_pct"], w["vegetation"], th),
        "fire": fire_score(m["fire_count_7d"], w["fire"], th),
    }
    out = {f"{k}_score": (None if v is None else round(v, 1)) for k, v in comps.items()}
    out.update(combine(comps, w))
    return out


def is_covered(week_end: pd.Timestamp, coverage: list[tuple[str, str]]) -> bool:
    start = week_end - pd.Timedelta(days=6)
    return any(pd.Timestamp(a) <= start and pd.Timestamp(b) >= week_end for a, b in coverage)


def score_reserve_history(pa_id, weather, ndvi, fires, week_ends, cfg, coverage) -> list[dict]:
    th = cfg["thresholds"]
    fd = fires.loc[fires["inside_boundary"] == 1, "acq_date"] if not fires.empty else pd.Series(dtype="datetime64[ns]")
    rows = []
    for we in week_ends:
        m = compute_metrics(weather, ndvi, fd, we, th, is_covered(we, coverage))
        rows.append({"pa_id": pa_id, "week_end": str(we.date()), **m, **score_from_metrics(m, cfg)})
    return rows


def describe_methodology(cfg: dict) -> str:
    w, th = cfg["weights"], cfg["thresholds"]
    return f"""
**Habitat Stress Score (HSS) = Heat + Drought + Vegetation + Fire** (0–100)

| Indicator | Max points | Full score reached when |
|---|---:|---|
| Heat | {w['heat']} | 7-day Tmax anomaly ≥ {th['heat_anomaly_max_c']} °C ({th['heat_anomaly_share']:.0%} of points) and all 7 days above the baseline 90th percentile (remainder) |
| Drought | {w['drought']} | 90-day rainfall deficit ≥ {th['drought_deficit_max_pct']}% — deficit = (Normal − Actual) / Normal × 100 |
| Vegetation | {w['vegetation']} | NDVI ≥ {th['ndvi_decline_max_pct']}% below its seasonal baseline |
| Fire | {w['fire']} | ≥ {th['fire_count_max']} satellite detections inside the reserve footprint in 7 days (log scale) |

**Categories:** 0–39 Low · 40–59 Moderate · 60–79 High · 80–100 Severe.

**Baselines** use observations from more than one year before the scored week (minimum two years).
**Missing data** is never scored as zero stress: the total is re-scaled across available indicators,
the score is marked *provisional*, and completeness (indicators available ÷ 4) is shown.
**Footprints**: until verified boundary polygons are uploaded, fire counts use an approximate circular
footprint of the reserve's published area.

*HSS is a transparent screening index for prioritising attention. It monitors habitat conditions, not
animals, and is not an officially validated ecological index.*
"""
