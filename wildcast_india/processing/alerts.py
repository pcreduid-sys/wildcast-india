"""Rule-based environmental alerts derived from scores and fire detections.

Alerts are keyed (reserve, type, period) so regeneration never duplicates them and
acknowledgements persist across refreshes.
"""
from __future__ import annotations

import pandas as pd

from database import db

SEVERITY_ORDER = {"Severe": 0, "High": 1, "Moderate": 2, "Info": 3}


def build_alerts(scores: pd.DataFrame, fires: pd.DataFrame, cfg: dict,
                 weeks: int = 8, fire_days: int = 30) -> list[tuple]:
    a = cfg["alerts"]
    out = []
    if scores.empty:
        return out
    recent_weeks = sorted(scores["week_end"].unique())[-weeks:]
    for r in scores[scores["week_end"].isin(recent_weeks)].itertuples():
        key = str(pd.Timestamp(r.week_end).date())
        if r.total_score is not None and r.total_score == r.total_score and r.total_score >= 60:
            sev = "Severe" if r.total_score >= 80 else "High"
            prov = " (provisional)" if r.provisional else ""
            out.append((r.pa_id, "HABITAT_STRESS", sev,
                        f"Habitat Stress Score {r.total_score:.1f}/100 — {r.category}{prov}", key))
        if r.deficit_pct is not None and r.deficit_pct == r.deficit_pct and r.deficit_pct >= a["drought_deficit_pct"]:
            sev = "Severe" if r.deficit_pct >= 70 else "High"
            out.append((r.pa_id, "RAINFALL_DEFICIT", sev,
                        f"90-day rainfall {r.deficit_pct:.0f}% below normal "
                        f"({r.rain_90d_mm:.0f} mm vs {r.rain_normal_mm:.0f} mm)", key))
        if r.tmax_anomaly_c is not None and r.tmax_anomaly_c == r.tmax_anomaly_c and r.tmax_anomaly_c >= a["heat_anomaly_c"]:
            out.append((r.pa_id, "HEAT_ANOMALY", "High" if r.tmax_anomaly_c >= 4 else "Moderate",
                        f"7-day max temperature {r.tmax_anomaly_c:+.1f} °C above baseline "
                        f"({int(r.hot_days)} unusually hot days)", key))
        if r.fire_count_7d is not None and r.fire_count_7d == r.fire_count_7d and r.fire_count_7d >= a["fire_7d_count"]:
            out.append((r.pa_id, "FIRE_7D", "High",
                        f"{int(r.fire_count_7d)} fire detections inside reserve in 7 days", key))
        if r.provisional:
            missing = [k for k in ("heat", "drought", "vegetation", "fire")
                       if getattr(r, f"{k}_score") is None or getattr(r, f"{k}_score") != getattr(r, f"{k}_score")]
            out.append((r.pa_id, "DATA_GAP", "Info",
                        f"Provisional score — missing: {', '.join(missing)}", key))
    if not fires.empty:
        inside = fires[fires["inside_boundary"] == 1].copy()
        last = inside["acq_date"].max() if not inside.empty else None
        if last is not None:
            inside = inside[inside["acq_date"] > last - pd.Timedelta(days=fire_days)]
            daily = inside.groupby(["pa_id", "acq_date"]).size().reset_index(name="n")
            for r in daily[daily["n"] >= a["fire_24h_count"]].itertuples():
                out.append((r.pa_id, "FIRE_24H", "Severe" if r.n >= 2 * a["fire_24h_count"] else "High",
                            f"{r.n} fire detections inside reserve on {pd.Timestamp(r.acq_date).date()}",
                            str(pd.Timestamp(r.acq_date).date())))
    return out


def write_alerts(conn, alerts: list[tuple]) -> int:
    before = conn.total_changes
    ts = db.now_iso()
    conn.executemany(
        "INSERT INTO alerts(pa_id,alert_type,severity,message,period_key,created_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(pa_id,alert_type,period_key) DO UPDATE SET severity=excluded.severity, "
        "message=excluded.message",
        [(*a, ts) for a in alerts])
    return conn.total_changes - before
