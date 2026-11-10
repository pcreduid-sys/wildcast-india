"""Page 1 — National Overview."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from components import charts, data, filters, maps
from components.cards import alert_list, kpi_row, section
from components.sidebar import header
from config.settings import THEME as T, category_for


def render() -> None:
    reserves, latest = data.reserves(), data.latest_scores()
    as_of = data.as_of()
    header("National Overview", "Weekly habitat stress across ten pilot protected areas", as_of,
           f"{len(reserves)} protected areas · {latest['provisional'].sum()} provisional")

    c1, c2, _ = st.columns([1, 1, 2])
    with c1:
        states = filters.state_filter(reserves, "ov_state")
    with c2:
        cats = filters.category_filter("ov_cat")
    view = filters.apply(latest, states=states, cats=cats)

    fires_all = data.fires(str((as_of - pd.Timedelta(days=13)).date()), str(as_of.date()))
    fires_v = fires_all[fires_all["pa_id"].isin(view["pa_id"]) & (fires_all["inside_boundary"] == 1)]
    f7 = fires_v[fires_v["acq_date"] > as_of - pd.Timedelta(days=7)]
    f_prev = len(fires_v) - len(f7)
    avg = view["total_score"].mean() if not view.empty else None
    avg_label, avg_col = category_for(avg)
    high = int(view["category"].isin(["High", "Severe"]).sum())
    deficit = int((view["deficit_pct"] >= 20).sum())
    trend = "▲" if len(f7) > f_prev else "▼" if len(f7) < f_prev else "■"

    kpi_row([
        dict(label="Protected areas monitored", value=len(view), icon="🛡️",
             sub=f"of {len(reserves)} pilot areas · {int((view['completeness'] == 1).sum())} fully scored"),
        dict(label="Average stress score", value="—" if avg is None else f"{avg:.0f}", icon="📊",
             sub=f"{avg_label} · scale 0–100", colour=avg_col, bar=avg),
        dict(label="High / severe stress", value=high, icon="⚠️",
             sub=f"{int((view['category'] == 'Severe').sum())} severe · {int((view['category'] == 'High').sum())} high",
             colour=T["orange"] if high else T["green"]),
        dict(label="Fire detections (7 days)", value=len(f7), icon="🔥",
             sub=f"{trend} vs {f_prev} in previous 7 days · inside footprints",
             colour=T["red"] if len(f7) >= 20 else T["text"]),
        dict(label="Rainfall-deficit areas", value=deficit, icon="💧",
             sub="90-day rainfall ≥ 20% below normal", colour=T["yellow"] if deficit else T["green"]),
    ])
    st.write("")

    left, right = st.columns([2.3, 1])
    with left:
        section("Habitat stress map", "🗺️")
        st_folium(maps.national_map(view, reserves, f7), height=520, use_container_width=True,
                  returned_objects=[], key="ov_map")
    with right:
        section("Recent environmental alerts", "🔔")
        al = data.alerts(include_ack=False)
        al = al[al["pa_id"].isin(view["pa_id"]) & (al["severity"] != "Info")]
        al = al.sort_values("period_key", ascending=False).drop_duplicates(["pa_id", "alert_type"])
        al = al.sort_values(["severity"], key=lambda s: s.map({"Severe": 0, "High": 1, "Moderate": 2}))
        alert_list(al, limit=7)
        if len(al) > 7:
            st.caption(f"+{len(al) - 7} more on Habitat Monitoring → Alert centre")

    left, right = st.columns([2.3, 1])
    with left:
        section("Reserve stress ranking", "🏆")
        tbl = view.assign(Rank=range(1, len(view) + 1))[
            ["Rank", "name", "state", "total_score", "category", "heat_score", "drought_score",
             "vegetation_score", "fire_score", "completeness", "provisional"]]
        st.dataframe(
            tbl, hide_index=True, width="stretch", height=min(420, 38 + 35 * len(tbl)),
            column_config={
                "name": "Protected area", "state": "State",
                "total_score": st.column_config.ProgressColumn("HSS", min_value=0, max_value=100, format="%.0f"),
                "category": "Category",
                "heat_score": st.column_config.NumberColumn("Heat", format="%.1f"),
                "drought_score": st.column_config.NumberColumn("Drought", format="%.1f"),
                "vegetation_score": st.column_config.NumberColumn("Veg.", format="%.1f"),
                "fire_score": st.column_config.NumberColumn("Fire", format="%.1f"),
                "completeness": st.column_config.ProgressColumn("Data", min_value=0, max_value=1, format="percent"),
                "provisional": st.column_config.CheckboxColumn("Prov."),
            })
        st.download_button("⬇ Download ranking (CSV)", data.to_csv(tbl), "wildcast_ranking.csv", "text/csv")
    with right:
        section("Stress distribution", "📈")
        st.plotly_chart(charts.stress_distribution(view), width="stretch",
                        config={"displayModeBar": False})
