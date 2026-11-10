"""Water Intelligence & Species Impact Analysis.

Rendered as tabs inside Wildlife Intelligence and as the 'Water & wildlife report' tab of the
Reserve Explorer. All views read the stored water bodies, observations and weekly assessments
(recomputed by processing.pipeline.rebuild_water)."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from components import charts, data, maps
from components.cards import badge, empty_state, iucn_badge, kpi_card, kpi_row, section
from config.settings import THEME as T
from processing.water import (CATEGORIES, CATEGORY_COLOURS, EVIDENCE_LABELS, WEIGHTS, reserve_insights,
                              water_dependent_species)

NOCFG = {"displayModeBar": False}
PROV_COLOURS = {"SIMULATED": "#8A9A94", "UPLOADED": T["yellow"], "LIVE": T["green"], "HISTORICAL": T["blue"]}
EVIDENCE_COLOURS = {"DIRECT": T["green"], "SATELLITE": T["blue"], "WEATHER_PROXY": T["yellow"], "NONE": "#7D8C86"}
DEP_COLOURS = {"High": T["blue"], "Moderate": T["green"], "Indirect": T["yellow"]}


# ------------------------------------------------------------------ helpers
def _fmt(v, f="{:.0f}", na="n/a"):
    return na if v is None or (isinstance(v, float) and v != v) else f.format(v)


def _s(v, na="none"):
    return na if v is None or (isinstance(v, float) and v != v) or str(v) in ("", "nan", "None") else str(v)


def week_select(key: str):
    weeks = data.water_weeks()
    if not weeks:
        return None
    return st.selectbox("Assessment week", weeks, key=key, format_func=lambda d: f"Week ending {pd.Timestamp(d):%d %b %Y}")


def assessments_for(week) -> pd.DataFrame:
    a = data.water_assessments()
    return a[a["week_end"] == pd.Timestamp(week)].copy()


def reserve_cond(wa_pa: pd.DataFrame) -> dict:
    if wa_pa.empty:
        return {}
    r = wa_pa.iloc[0]
    keys = ["rain_30d_mm", "rain_30d_normal", "deficit_30d_pct", "rain_60d_mm", "rain_60d_normal", "deficit_60d_pct",
            "rain_90d_mm", "rain_90d_normal", "deficit_90d_pct", "tmax_anomaly_30d"]
    return {k: (None if pd.isna(r[k]) else float(r[k])) for k in keys}


def hss_at(pa_id: str, week) -> dict:
    s = data.scores(pa_id)
    s = s[s["week_end"] <= pd.Timestamp(week)]
    return s.iloc[-1].to_dict() if not s.empty else {}


def provenance_badges(row) -> str:
    loc = {"ILLUSTRATIVE": ("Illustrative location", "#8A9A94"), "UPLOADED": ("Uploaded location", T["yellow"]),
           "VERIFIED": ("Verified location", T["green"])}[row["location_basis"]]
    return badge(row["source_type"], PROV_COLOURS.get(row["source_type"], T["muted"])) + " " + badge(*loc)


def insights_panel(ins: dict) -> None:
    blocks = [("Observed environmental conditions", "observed", T["blue"], "📡"),
              ("Potential ecological implications", "implications", T["yellow"], "🧭"),
              ("Research recommendations", "recommendations", T["green"], "🔬"),
              ("Data limitations", "limitations", "#8A9A94", "⚠️")]
    cols = st.columns(2)
    for i, (title, k, colour, icon) in enumerate(blocks):
        items = "".join(f"<li style='margin-bottom:0.3rem'>{html.escape(x)}</li>" for x in ins[k])
        with cols[i % 2]:
            st.markdown(f"""<div class="wc-card" style="border-top:3px solid {colour};margin-bottom:0.8rem">
                <div class="lbl">{icon} {title}</div>
                <ul style="color:{T['text']};font-size:0.87rem;line-height:1.5;padding-left:1.1rem;margin:0.5rem 0 0">
                {items}</ul></div>""", unsafe_allow_html=True)


def build_insights(pa_id: str, week) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    from dashboard.wildlife import associations
    reserves = data.reserves().set_index("pa_id")
    wa = assessments_for(week)
    wa = wa[wa["pa_id"] == pa_id]
    assoc = associations()
    assoc = assoc[assoc["pa_id"] == pa_id]
    dep = water_dependent_species(assoc, data.species(), data.observations((pa_id,)), pd.Timestamp(week))
    wx = data.weather(pa_id, str((pd.Timestamp(week) - pd.Timedelta(days=95)).date()))
    sources = {"weather_simulated": bool((wx["source_type"] == "SIMULATED").any()) if not wx.empty else False}
    ins = reserve_insights(reserves.loc[pa_id, "name"], reserve_cond(wa), hss_at(pa_id, week), wa, dep, sources)
    return ins, wa, dep


# ------------------------------------------------------------------ Water Intelligence tab
def water_intelligence() -> None:
    reserves = data.reserves()
    if data.water_bodies().empty:
        empty_state("No water bodies stored", "Upload surveyed water points on Research & Administration → Admin.", "💧")
        return
    st.markdown(f"""<div class="wc-note" style="margin-bottom:0.6rem">Monitors watering holes and other water bodies
        using the best available evidence: {badge('Direct measurement', T['green'])} {badge('Satellite observation', T['blue'])}
        {badge('Weather-based proxy (unverified)', T['yellow'])}. No water body is reported as dry without direct evidence;
        the lowest category is <i>potential water stress</i>.</div>""", unsafe_allow_html=True)
    c = st.columns([1.2, 1.6, 1.2, 1.2])
    rname = c[0].selectbox("Reserve", ["All reserves"] + list(reserves["name"]), key="wi_res")
    cats = c[1].multiselect("Water availability", CATEGORIES, key="wi_cat", placeholder="All categories")
    evid = c[2].multiselect("Evidence", list(EVIDENCE_LABELS), key="wi_ev", placeholder="All evidence",
                            format_func=EVIDENCE_LABELS.get)
    with c[3]:
        week = week_select("wi_week")
    wa_all = assessments_for(week)
    pa_id = None
    if rname != "All reserves":
        pa_id = reserves.loc[reserves["name"] == rname, "pa_id"].iloc[0]
        wa_all = wa_all[wa_all["pa_id"] == pa_id]
    wa = wa_all
    if cats:
        wa = wa[wa["category"].isin(cats)]
    if evid:
        wa = wa[wa["evidence"].isin(evid)]
    wa = wa.sort_values("priority_score", ascending=False)

    kpi_row([
        dict(label="Mapped water bodies", value=len(wa_all), icon="💧",
             sub=f"{int((wa_all['location_basis'] == 'ILLUSTRATIVE').sum())} illustrative (SIMULATED)"),
        dict(label="Potential water stress", value=int((wa_all["category"] == "Potential water stress").sum()), icon="🔴",
             colour=T["red"] if (wa_all["category"] == "Potential water stress").any() else None,
             sub=f"{int((wa_all['category'] == 'Low availability').sum())} low availability"),
        dict(label="Priority 1 for field visit", value=int((wa_all["priority_score"] >= 60).sum()), icon="🧭",
             colour=T["orange"] if (wa_all["priority_score"] >= 60).any() else None,
             sub=f"{int(wa_all['priority_score'].between(40, 60, inclusive='left').sum())} at priority 2"),
        dict(label="Direct-measurement coverage", value=f"{(wa_all['evidence'] == 'DIRECT').mean():.0%}" if len(wa_all) else "—",
             icon="📏", sub=f"{int((wa_all['evidence'] == 'SATELLITE').sum())} satellite · "
                            f"{int((wa_all['evidence'] == 'WEATHER_PROXY').sum())} proxy only"),
        dict(label="Insufficient data", value=int((wa_all["category"] == "Insufficient data").sum()), icon="❔",
             sub="no usable evidence"),
    ])
    st.write("")
    left, right = st.columns([1.55, 1])
    with left:
        section(f"Water bodies · {len(wa)} shown — click a point to open its profile", "🗺️")
        sel = st.session_state.get("wi_wb_sel")
        out = st_folium(maps.water_map(wa, reserves[reserves["pa_id"] == pa_id] if pa_id else reserves, sel),
                        height=500, use_container_width=True, returned_objects=["last_object_clicked_tooltip"],
                        key=f"wi_map_{rname}")
        tip = (out or {}).get("last_object_clicked_tooltip")
        if tip and tip != st.session_state.get("wi_last_tip"):
            st.session_state["wi_last_tip"] = tip
            clicked = tip.split(" · ")[0].strip()
            if clicked in set(wa["wb_id"]):
                st.session_state["wi_wb_sel"] = clicked
    with right:
        section("Water stress monitoring priorities", "📋")
        st.dataframe(wa[["wb_id", "reserve", "wb_type", "category", "evidence", "priority_score"]], hide_index=True,
                     width="stretch", height=455,
                     column_config={"wb_id": "ID", "reserve": "Reserve", "wb_type": "Type", "category": "Availability",
                                    "evidence": st.column_config.TextColumn("Evidence"),
                                    "priority_score": st.column_config.ProgressColumn("Priority", min_value=0,
                                                                                      max_value=100, format="%.0f")})
    if wa.empty:
        st.info("No water bodies match the current filters.")
        return

    with st.expander("How the monitoring priority is calculated", expanded=False):
        st.markdown(f"""Priority (0–100) ranks water bodies by **need for field verification**, not by confirmed scarcity.
| Component | Max | Driver |
|---|---:|---|
| Water evidence | {WEIGHTS['p_water']} | How far the latest reading (or proxy) is below its seasonal norm |
| Rainfall deficit | {WEIGHTS['p_rain']} | 90-day deficit, full at 60% |
| Heat | {WEIGHTS['p_heat']} | 30-day max-temperature anomaly, full at +4 °C |
| Vegetation decline | {WEIGHTS['p_veg']} | NDVI within 500 m vs seasonal baseline, full at −30% |
| Nearby fire | {WEIGHTS['p_fire']} | Fire detections within 5 km in 30 days, full at 5 |
| Data uncertainty | {WEIGHTS['p_uncertainty']} | 0 direct · 8 satellite · 16 weather proxy · 20 no evidence |

**Availability categories** compare the latest value with the median of earlier same-season values (±45 days):
≥ 90% High · 60–90% Moderate · 35–60% Low · < 35% Potential water stress. Direct readings older than 21 days and
satellite readings older than 32 days are not used. Without either, a weather proxy (90/30-day rainfall relative to
normal, reduced for heat) is used and labelled unverified.""")
        st.plotly_chart(charts.priority_breakdown(wa), width="stretch", config=NOCFG)

    if pa_id:
        reserve_conditions_panel(pa_id, week, wa_all)
    else:
        section("Reserve water conditions", "🌧️")
        rows = []
        for p, g in wa_all.groupby("pa_id"):
            cnd, h = reserve_cond(g), hss_at(p, week)
            rows.append({"Reserve": g["reserve"].iloc[0], "Rain deficit 30d %": cnd.get("deficit_30d_pct"),
                         "Rain deficit 60d %": cnd.get("deficit_60d_pct"), "Rain deficit 90d %": cnd.get("deficit_90d_pct"),
                         "Tmax anomaly 30d": cnd.get("tmax_anomaly_30d"), "NDVI vs baseline %": h.get("ndvi_change_pct"),
                         "Water bodies": len(g), "Stress / low": int(g["category"].isin(
                             ["Potential water stress", "Low availability"]).sum()),
                         "Top priority": g["priority_score"].max()})
        st.dataframe(pd.DataFrame(rows).sort_values("Top priority", ascending=False), hide_index=True, width="stretch",
                     column_config={c_: st.column_config.NumberColumn(c_, format="%+.0f", help="Rainfall deficit (positive = below normal)")
                                    for c_ in ["Rain deficit 30d %", "Rain deficit 60d %", "Rain deficit 90d %"]}
                     | {"Tmax anomaly 30d": st.column_config.NumberColumn(format="%+.1f °C"),
                        "NDVI vs baseline %": st.column_config.NumberColumn(format="%+.0f"),
                        "Top priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f")})
        st.caption("Rainfall columns are deficits against the historical average for the same window: positive values "
                   "mean less rain than normal.")

    section("Watering hole profile", "🔎")
    ids = list(wa["wb_id"])
    if st.session_state.get("wi_wb_sel") not in ids:
        st.session_state["wi_wb_sel"] = ids[0]
    names = dict(zip(wa["wb_id"], wa["wb_id"] + " — " + wa["wb_type"] + " (" + wa["reserve"] + ")"))
    wb_id = st.selectbox("Water body", ids, key="wi_wb_sel", format_func=names.get)
    watering_hole_profile(wb_id, week)
    st.download_button("⬇ Water assessments (CSV)", data.to_csv(wa), "wildcast_water_assessments.csv", "text/csv")


def reserve_conditions_panel(pa_id: str, week, wa_pa: pd.DataFrame) -> None:
    cond = reserve_cond(wa_pa)
    h = hss_at(pa_id, week)
    section("Reserve water conditions", "🌧️")
    a, b, c = st.columns([1.1, 1.1, 0.8])
    with a:
        st.plotly_chart(charts.rain_windows(cond), width="stretch", config=NOCFG)
    with b:
        wx = data.weather(pa_id)
        ids = set(data.water_bodies().query("pa_id == @pa_id")["wb_id"])
        wo = data.water_obs()
        st.plotly_chart(charts.seasonal_water(wx, wo[wo["wb_id"].isin(ids)]), width="stretch", config=NOCFG)
    with c:
        kpi_card("Temperature (30 d)", _fmt(cond.get("tmax_anomaly_30d"), "{:+.1f} °C"), "max-temperature anomaly", "🌡️",
                 T["orange"] if (cond.get("tmax_anomaly_30d") or 0) >= 1.5 else None)
        st.write("")
        kpi_card("Vegetation (NDVI)", _fmt(h.get("ndvi_change_pct"), "{:+.0f}%"), "reserve vs seasonal baseline", "🌿",
                 T["yellow"] if (h.get("ndvi_change_pct") or 0) <= -10 else None)


def watering_hole_profile(wb_id: str, week) -> None:
    wb = data.water_bodies().set_index("wb_id").loc[wb_id]
    hist = data.water_assessments()
    hist = hist[hist["wb_id"] == wb_id].sort_values("week_end")
    cur = hist[hist["week_end"] == pd.Timestamp(week)]
    cur = cur.iloc[0] if not cur.empty else hist.iloc[-1]
    obs = data.water_obs(wb_id)
    last_obs = obs["obs_date"].max() if not obs.empty else None
    cat_c = CATEGORY_COLOURS.get(cur["category"], T["muted"])
    sources = ", ".join(sorted(set(obs["source"]))) if not obs.empty else wb["source"]
    l, r = st.columns([1.15, 1])
    with l:
        st.markdown(f"""<div class="wc-card" style="border-top:3px solid {cat_c}">
            <div style="display:flex;gap:0.9rem;align-items:center">
              <div style="font-size:2.3rem;background:#0E1714;border-radius:12px;padding:0.3rem 0.6rem">💧</div>
              <div><div style="font-size:1.25rem;font-weight:650;color:{T['text']}">{html.escape(wb['name'])}</div>
              <div class="wc-note">{wb['wb_type']} · {wb['permanence']} · {wb['reserve']}, {wb['state']}</div>
              <div style="margin-top:0.35rem">{badge(cur['category'], cat_c)}
              {badge(EVIDENCE_LABELS[cur['evidence']], EVIDENCE_COLOURS[cur['evidence']])}</div></div></div>
            <table style="width:100%;font-size:0.85rem;color:{T['text']};margin-top:0.7rem">
            <tr><td class="wc-note">Location</td><td>{wb['latitude']:.4f}°N, {wb['longitude']:.4f}°E</td>
                <td class="wc-note">Provenance</td><td>{provenance_badges(wb)}</td></tr>
            <tr><td class="wc-note">Availability vs norm</td><td>{_fmt(cur['availability_ratio'], '{:.0%}')}</td>
                <td class="wc-note">Priority</td><td><b>{cur['priority_score']:.0f}</b> · {cur['priority_band']}</td></tr>
            <tr><td class="wc-note">Last direct reading</td><td>{_s(cur['latest_direct_date'])}</td>
                <td class="wc-note">Last satellite obs.</td><td>{_s(cur['latest_satellite_date'])}</td></tr>
            <tr><td class="wc-note">Rain 30/60/90 d</td><td colspan=3>{_fmt(cur['rain_30d_mm'])} / {_fmt(cur['rain_60d_mm'])} /
                {_fmt(cur['rain_90d_mm'])} mm · 90-d deficit {_fmt(cur['deficit_90d_pct'], '{:+.0f}%')}</td></tr>
            <tr><td class="wc-note">Temperature</td><td>{_fmt(cur['tmax_anomaly_30d'], '{:+.1f} °C')} (30-d anomaly)</td>
                <td class="wc-note">Vegetation 500 m</td><td>NDVI {_fmt(cur['ndvi_buffer'], '{:.2f}')}
                ({_fmt(cur['ndvi_buffer_change_pct'], '{:+.0f}%')})</td></tr>
            <tr><td class="wc-note">Fires ≤ 5 km (30 d)</td><td>{int(cur['fires_5km_30d'] or 0)}</td>
                <td class="wc-note">Last observation</td><td>{'none' if last_obs is None else f'{last_obs:%d %b %Y}'}</td></tr>
            <tr><td class="wc-note">Data source</td><td colspan=3 class="wc-note">{html.escape(str(sources))}</td></tr>
            </table>
            <div class="wc-note" style="margin-top:0.5rem">{html.escape(_s(wb['notes'], ''))}</div></div>""",
                    unsafe_allow_html=True)
    with r:
        st.plotly_chart(charts.priority_history(hist), width="stretch", config=NOCFG)
    period = st.radio("Observation history", ["1 year", "3 years", "All"], horizontal=True, key="wi_hist", index=1)
    if period != "All":
        obs = obs[obs["obs_date"] >= obs["obs_date"].max() - pd.DateOffset(years=int(period[0]))] if not obs.empty else obs
    a, b = st.columns([1.4, 1])
    with a:
        st.plotly_chart(charts.water_series(obs, "Historical water observations"), width="stretch", config=NOCFG)
    with b:
        st.plotly_chart(charts.ndvi_buffer(obs), width="stretch", config=NOCFG)
    if cur["evidence"] == "WEATHER_PROXY":
        st.warning("This water body has no recent direct or satellite observation. Its category is inferred from the "
                   "reserve's rainfall and temperature and is **unverified**.")
    if wb["location_basis"] == "ILLUSTRATIVE":
        st.caption("⚠️ SIMULATED illustrative record: the location and all measurements are demonstration values, "
                   "not a real surveyed water body.")


# ------------------------------------------------------------------ Species Impact tab
def species_impact() -> None:
    reserves = data.reserves()
    c = st.columns([1.3, 1.2, 2])
    name = c[0].selectbox("Reserve", list(reserves["name"]), key="si_res")
    with c[1]:
        week = week_select("si_week")
    if week is None:
        empty_state("No water assessments", "Water assessments have not been computed yet.", "💧")
        return
    pa_id = reserves.loc[reserves["name"] == name, "pa_id"].iloc[0]
    ins, wa, dep = build_insights(pa_id, week)
    cond = reserve_cond(wa)
    h = hss_at(pa_id, week)
    obs = data.observations((pa_id,))
    herb = obs[obs["taxon_group"] == "Mammals"]
    herb = herb[herb["family"].isin(["Cervidae", "Bovidae", "Suidae", "Tragulidae"])] if "family" in herb else herb
    herb_5y = int((herb["obs_date"] >= pd.Timestamp(week) - pd.DateOffset(years=5)).sum())
    kpi_row([
        dict(label="Water-dependent species", value=len(dep), icon="🐘",
             sub=f"{int((dep['dependency'] == 'High').sum()) if len(dep) else 0} high dependency"),
        dict(label="90-day rainfall", value=_fmt(None if cond.get("deficit_90d_pct") is None
                                                 else -cond["deficit_90d_pct"], "{:+.0f}%"),
             icon="🌧️", sub="vs historical normal (negative = drier)",
             colour=T["yellow"] if (cond.get("deficit_90d_pct") or 0) >= 25 else None),
        dict(label="Temperature anomaly", value=_fmt(cond.get("tmax_anomaly_30d"), "{:+.1f} °C"), icon="🌡️",
             sub="30-day max temperature"),
        dict(label="Water points stressed / low", value=int(wa["category"].isin(
            ["Potential water stress", "Low availability"]).sum()), icon="💧", sub=f"of {len(wa)} mapped"),
        dict(label="Herbivore records (5 y)", value=herb_5y, icon="🦌", sub="prey-availability indicator (effort-biased)"),
    ])
    st.write("")
    section(f"Water-relevant species documented in {name}", "🐾")
    if dep.empty:
        empty_state("No water-dependent species documented yet",
                    "Only species with occurrence records or official estimates for this reserve are assessed. "
                    "Fetch GBIF/iNaturalist records from the Overview tab to populate this analysis.", "🐾")
    else:
        status = (f"Water: {int(wa['category'].isin(['Potential water stress', 'Low availability']).sum())}/{len(wa)} low or stressed · "
                  f"Rain 90 d {_fmt(cond.get('deficit_90d_pct'), '{:+.0f}% deficit')} · NDVI {_fmt(h.get('ndvi_change_pct'), '{:+.0f}%')}")
        tbl = dep.assign(current=[status + (f" · prey records 5 y: {herb_5y}" if d == "Indirect" else "")
                                  for d in dep["dependency"]])
        st.dataframe(tbl[["common_name", "scientific_name", "taxon_group", "iucn_category", "dependency", "why",
                          "indicators", "current", "records_total", "records_5y", "data_gaps"]],
                     hide_index=True, width="stretch", height=min(420, 40 + 35 * len(tbl)),
                     column_config={"common_name": "Species", "scientific_name": "Scientific name",
                                    "taxon_group": "Group", "iucn_category": "IUCN", "dependency": "Water relevance",
                                    "why": st.column_config.TextColumn("Why it matters", width="large"),
                                    "indicators": "Indicators to watch",
                                    "current": st.column_config.TextColumn("Current indicator status", width="large"),
                                    "records_total": "Records", "records_5y": "Records (5 y)", "data_gaps": "Data gaps"})
        st.download_button("⬇ Species impact table (CSV)", data.to_csv(tbl), f"wildcast_species_impact_{pa_id}.csv",
                           "text/csv")
    section(f"Weather-driven environmental insights — {name}", "🧠")
    insights_panel(ins)


# ------------------------------------------------------------------ Reserve Explorer report
def reserve_water_report(pa_id: str) -> None:
    weeks = data.water_weeks()
    if not weeks:
        empty_state("No water assessments", "Water bodies and assessments are not available yet.", "💧")
        return
    week = weeks[0]
    ins, wa, dep = build_insights(pa_id, week)
    cond = reserve_cond(wa)
    h = hss_at(pa_id, week)
    st.caption(f"Water & wildlife report for the week ending {pd.Timestamp(week):%d %b %Y}. Habitat Stress metrics are "
               "reported separately in the Habitat conditions tab.")
    kpi_row([
        dict(label="Rain 30 / 60 / 90 d", value=f"{_fmt(cond.get('rain_30d_mm'))}/{_fmt(cond.get('rain_60d_mm'))}/"
                                                f"{_fmt(cond.get('rain_90d_mm'))}", icon="🌧️",
             sub=f"mm · 90-d deficit {_fmt(cond.get('deficit_90d_pct'), '{:+.0f}%')}"),
        dict(label="Temperature", value=_fmt(cond.get("tmax_anomaly_30d"), "{:+.1f} °C"), icon="🌡️",
             sub="30-day max-temperature anomaly"),
        dict(label="Vegetation health", value=_fmt(h.get("ndvi_change_pct"), "{:+.0f}%"), icon="🌿",
             sub=f"NDVI {_fmt(h.get('ndvi'), '{:.2f}')} vs seasonal baseline"),
        dict(label="Mapped water bodies", value=len(wa), icon="💧",
             sub=" · ".join(f"{int(v)} {k.split()[0].lower()}" for k, v in wa["category"].value_counts().items())),
        dict(label="Water-dependent species", value=len(dep), icon="🐘",
             sub=", ".join(dep["common_name"].fillna(dep["scientific_name"]).head(3)) if len(dep) else "none documented yet"),
    ])
    st.write("")
    l, r = st.columns([1, 1.2])
    with l:
        st.plotly_chart(charts.rain_windows(cond), width="stretch", config=NOCFG)
    with r:
        section("Water availability indicators", "💧")
        st.dataframe(wa.sort_values("priority_score", ascending=False)[
            ["wb_id", "wb_type", "category", "evidence", "availability_ratio", "priority_score", "source_type"]],
            hide_index=True, width="stretch", height=230,
            column_config={"wb_id": "ID", "wb_type": "Type", "category": "Availability", "evidence": "Evidence",
                           "availability_ratio": st.column_config.NumberColumn("vs norm", format="percent"),
                           "priority_score": st.column_config.ProgressColumn("Priority", min_value=0, max_value=100,
                                                                             format="%.0f"),
                           "source_type": "Provenance"})
    if len(dep):
        section("Water-dependent species documented", "🐾")
        cols = st.columns(3)
        for i, row in enumerate(dep.head(6).to_dict("records")):
            with cols[i % 3]:
                st.markdown(f"""<div class="wc-card" style="padding:0.7rem 0.85rem;margin-bottom:0.6rem">
                    <b style="color:{T['text']}">{html.escape(str(row['common_name'] or row['scientific_name']))}</b>
                    {badge(row['dependency'] + ' water relevance', DEP_COLOURS[row['dependency']])}
                    {iucn_badge(row['iucn_category']) if row['iucn_category'] else ''}<br>
                    <i class="wc-note">{row['scientific_name']}</i>
                    <div class="sub" style="margin-top:0.3rem">{html.escape(row['why'])}<br>
                    Records: {row['records_total']} (5 y: {row['records_5y']}) · gaps: {html.escape(row['data_gaps'])}</div>
                    </div>""", unsafe_allow_html=True)
    section("Habitat implications and recommended field investigations", "🧠")
    insights_panel(ins)
