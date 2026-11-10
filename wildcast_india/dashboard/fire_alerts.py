"""Page 3 — Fire Monitoring & Alerts."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from components import charts, data, filters, maps
from components.cards import SEV_COLOURS, kpi_row, section
from components.sidebar import header
from database import db


def render() -> None:
    header("Fire Monitoring & Alerts", "Satellite-detected active fire in and around pilot protected areas",
           data.as_of(), "Detections: NASA FIRMS (VIIRS/MODIS) or demonstration data")
    fire_section()
    st.divider()
    alert_centre(data.reserves())


def fire_section() -> None:
    reserves = data.reserves()
    as_of = data.as_of()

    c = st.columns([1.2, 1, 1.4, 1])
    with c[0]:
        d0, d1 = filters.date_range("fa_dates", as_of.date(), 30)
    with c[1]:
        states = filters.state_filter(reserves, "fa_state")
    with c[2]:
        pa_ids = filters.reserve_filter(reserves, "fa_reserve", states)
    with c[3]:
        scope = st.selectbox("Spatial scope", ["Inside footprint", "Inside + 25 km buffer"], key="fa_scope")

    sel = reserves
    if states:
        sel = sel[sel["state"].isin(states)]
    if pa_ids:
        sel = sel[sel["pa_id"].isin(pa_ids)]

    recent = data.fires(str((as_of - pd.Timedelta(days=29)).date()), str(as_of.date()))
    recent = recent[recent["pa_id"].isin(sel["pa_id"])]
    if scope == "Inside footprint":
        recent = recent[recent["inside_boundary"] == 1]

    def n(days):
        return int((recent["acq_date"] > as_of - pd.Timedelta(days=days)).sum())

    kpi_row([
        dict(label="Last 24 hours", value=n(1), icon="🔥", sub=f"to {as_of:%d %b %Y}"),
        dict(label="Last 7 days", value=n(7), icon="📅", sub=f"{n(7) / 7:.1f} per day"),
        dict(label="Last 30 days", value=n(30), icon="🗓️", sub=f"{recent['pa_id'].nunique()} reserves affected"),
        dict(label="High-confidence (30 d)", value=int(recent["confidence"].isin(["h", "high"]).sum()
                                                       + (pd.to_numeric(recent["confidence"], errors="coerce") >= 80).sum()),
             icon="🎯", sub="VIIRS 'h' or MODIS ≥ 80%"),
    ])

    fires = data.fires(str(d0), str(d1))
    fires = fires[fires["pa_id"].isin(sel["pa_id"])]
    if scope == "Inside footprint":
        fires = fires[fires["inside_boundary"] == 1]

    st.write("")
    left, right = st.columns([1.6, 1])
    with left:
        section(f"Fire map · {d0:%d %b} – {d1:%d %b %Y} · {len(fires)} detections", "🗺️")
        heat = st.toggle("Density view", key="fa_heat")
        st_folium(maps.fire_map(fires, sel, heat=heat), height=470, use_container_width=True,
                  returned_objects=[], key="fa_map")
    with right:
        st.plotly_chart(charts.fire_timeline(fires), width="stretch", config={"displayModeBar": False})
        by_res = fires.groupby("reserve").agg(detections=("fire_id", "count"), max_frp=("frp", "max")) \
            .sort_values("detections", ascending=False).reset_index()
        st.dataframe(by_res, hide_index=True, width="stretch", height=200,
                     column_config={"reserve": "Protected area", "detections": "Detections",
                                    "max_frp": st.column_config.NumberColumn("Max FRP (MW)", format="%.1f")})

    section("Fire detection records", "📋")
    tbl = fires[["acq_date", "acq_time", "reserve", "state", "latitude", "longitude", "satellite", "instrument",
                 "confidence", "frp", "daynight", "inside_boundary", "source_type"]].copy()
    tbl["acq_date"] = tbl["acq_date"].dt.date
    st.dataframe(tbl, hide_index=True, width="stretch", height=260,
                 column_config={"acq_date": "Date", "acq_time": "Time (UTC)", "reserve": "Protected area",
                                "frp": st.column_config.NumberColumn("FRP (MW)", format="%.1f"),
                                "inside_boundary": st.column_config.CheckboxColumn("Inside"),
                                "source_type": "Provenance"})
    st.download_button("⬇ Download detections (CSV)", data.to_csv(tbl), f"fires_{d0}_{d1}.csv", "text/csv")


def alert_centre(sel: pd.DataFrame) -> None:
    section("Alert centre", "🔔")
    c = st.columns([1.3, 1, 1, 1])
    with c[0]:
        sev = st.multiselect("Severity", list(SEV_COLOURS), default=["Severe", "High", "Moderate"], key="al_sev")
    with c[1]:
        show_ack = st.toggle("Show acknowledged", key="al_ack")
    with c[2]:
        user = st.text_input("Acknowledge as", value=st.session_state.get("al_user", "analyst"), key="al_user")
    al = data.alerts(include_ack=True)
    al = al[al["pa_id"].isin(sel["pa_id"]) & al["severity"].isin(sev or list(SEV_COLOURS))]
    if not show_ack:
        al = al[al["acknowledged"] == 0]
    open_n = int((al["acknowledged"] == 0).sum())
    with c[3]:
        st.metric("Open alerts", open_n)
    if al.empty:
        st.success("No alerts match the current filters.")
        return
    icon = {"Severe": "🔴", "High": "🟠", "Moderate": "🟡", "Info": "🔵"}
    view = al.assign(select=False, sev=al["severity"].map(lambda s: f"{icon[s]} {s}"),
                     status=al["acknowledged"].map({0: "Open", 1: "Acknowledged"}))[
        ["select", "alert_id", "sev", "reserve", "alert_type", "message", "period_key", "status",
         "acknowledged_by", "acknowledged_at"]]
    edited = st.data_editor(
        view, hide_index=True, width="stretch", height=min(400, 40 + 35 * len(view)),
        disabled=[c for c in view.columns if c != "select"], key="al_editor",
        column_config={"select": st.column_config.CheckboxColumn("Ack", width="small"),
                       "alert_id": None, "sev": "Severity", "reserve": "Protected area",
                       "alert_type": "Type", "message": st.column_config.TextColumn("Alert", width="large"),
                       "period_key": "Period", "status": "Status", "acknowledged_by": "By",
                       "acknowledged_at": "At"})
    chosen = edited.loc[edited["select"], "alert_id"].tolist()
    b1, b2, _ = st.columns([1, 1, 3])
    with b1:
        if st.button(f"Acknowledge selected ({len(chosen)})", type="primary", disabled=not chosen):
            k = db.acknowledge_alerts(chosen, user)
            st.toast(f"{k} alert(s) acknowledged")
            st.rerun()
    with b2:
        st.download_button("⬇ Alerts (CSV)", data.to_csv(al), "wildcast_alerts.csv", "text/csv")
