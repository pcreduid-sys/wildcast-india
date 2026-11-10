"""Page 3 — Habitat Monitoring: indicators across reserves, fire detections and the alert centre."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts, data, filters
from components.cards import section
from components.sidebar import header
from dashboard.fire_alerts import alert_centre, fire_section

INDICATORS = {"Habitat Stress Score (0–100)": "total_score", "Heat (points)": "heat_score",
              "Drought (points)": "drought_score", "Vegetation (points)": "vegetation_score",
              "Fire (points)": "fire_score"}


def render() -> None:
    open_n = int((data.alerts(include_ack=False)["severity"] != "Info").sum())
    header("Habitat Monitoring", "Environmental indicators, satellite fire activity and alerts", data.as_of(),
           f"{open_n} open alerts")
    t1, t2, t3 = st.tabs(["📊 Indicator monitor", "🔥 Fire detections", f"🔔 Alert centre ({open_n})"])
    with t1:
        indicator_monitor()
    with t2:
        fire_section()
    with t3:
        alert_centre(data.reserves())


def indicator_monitor() -> None:
    reserves = data.reserves()
    c = st.columns([1.3, 1, 1])
    label = c[0].selectbox("Indicator", list(INDICATORS), key="hm_ind")
    weeks = c[1].slider("Weeks", 8, 104, 26, key="hm_weeks")
    with c[2]:
        states = filters.state_filter(reserves, "hm_state")
    sc = data.scores()
    sc = sc[sc["week_end"] > sc["week_end"].max() - pd.Timedelta(weeks=weeks)]
    if states:
        sc = sc[sc["state"].isin(states)]
    st.plotly_chart(charts.hss_heatmap(sc, INDICATORS[label], f"{label} — weekly, by reserve"), width="stretch",
                    config={"displayModeBar": False})
    section("Latest week — indicator detail", "🧪")
    latest = data.latest_scores()
    if states:
        latest = latest[latest["state"].isin(states)]
    st.dataframe(latest[["name", "state", "total_score", "category", "tmax_anomaly_c", "hot_days", "deficit_pct",
                         "ndvi", "ndvi_change_pct", "fire_count_7d", "completeness"]],
                 hide_index=True, width="stretch",
                 column_config={"name": "Protected area", "state": "State",
                                "total_score": st.column_config.ProgressColumn("HSS", min_value=0, max_value=100, format="%.0f"),
                                "tmax_anomaly_c": st.column_config.NumberColumn("Tmax anomaly °C", format="%+.1f"),
                                "hot_days": "Hot days", "deficit_pct": st.column_config.NumberColumn("Rain deficit %", format="%.0f"),
                                "ndvi": st.column_config.NumberColumn("NDVI", format="%.2f"),
                                "ndvi_change_pct": st.column_config.NumberColumn("NDVI vs base %", format="%+.0f"),
                                "fire_count_7d": "Fires 7d",
                                "completeness": st.column_config.ProgressColumn("Data", min_value=0, max_value=1, format="percent")})
    st.download_button("⬇ Weekly indicators (CSV)", data.to_csv(sc), "wildcast_indicators.csv", "text/csv")
