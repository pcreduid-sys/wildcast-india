"""Page 2 — Reserve Explorer."""
from __future__ import annotations

import re

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from components import charts, data, filters, maps
from components.cards import badge, indicator_card, kpi_card, kpi_row, score_gauge_card, section
from components.sidebar import header
from config import settings
from config.settings import THEME as T, category_for
from processing.geospatial import buffer_radius_km

PERIODS = {"Last 90 days": 90, "Last 12 months": 365, "Last 2 years": 730, "Last 5 years": 1825}


def research_summary(r: pd.Series, info: pd.Series, f30: int, hist: pd.DataFrame) -> str:
    parts = []
    label = r["category"]
    parts.append(f"For the week ending {r['week_end']:%d %B %Y}, **{info['name']}** ({info['state']}) recorded a "
                 f"Habitat Stress Score of **{r['total_score']:.0f}/100 ({label})**"
                 + (", provisional because not all indicators were available." if r["provisional"] else "."))
    comps = {k: r[f"{k}_score"] for k in ["heat", "drought", "vegetation", "fire"]
             if r[f"{k}_score"] == r[f"{k}_score"] and r[f"{k}_score"] is not None}
    if comps:
        top = max(comps, key=comps.get)
        parts.append(f"The largest contributor is **{top}** ({comps[top]:.1f} points).")
    if r["deficit_pct"] == r["deficit_pct"] and r["deficit_pct"] is not None:
        word = "below" if r["deficit_pct"] > 0 else "above"
        parts.append(f"90-day rainfall was {r['rain_90d_mm']:.0f} mm, {abs(r['deficit_pct']):.0f}% {word} the "
                     f"baseline normal of {r['rain_normal_mm']:.0f} mm.")
    if r["tmax_anomaly_c"] == r["tmax_anomaly_c"] and r["tmax_anomaly_c"] is not None:
        parts.append(f"Maximum temperatures averaged {r['tmax_anomaly_c']:+.1f} °C relative to the seasonal "
                     f"baseline, with {int(r['hot_days'])} day(s) above the 90th percentile.")
    if r["ndvi_change_pct"] == r["ndvi_change_pct"] and r["ndvi_change_pct"] is not None:
        parts.append(f"NDVI was {r['ndvi']:.2f}, {r['ndvi_change_pct']:+.0f}% versus its seasonal baseline.")
    else:
        parts.append("No recent NDVI observation was available, so vegetation was not scored.")
    parts.append(f"{f30} satellite fire detection(s) fell inside the reserve footprint in the last 30 days.")
    if len(hist) >= 5:
        delta = hist["total_score"].iloc[-1] - hist["total_score"].iloc[-5]
        parts.append(f"The score has {'risen' if delta > 0 else 'fallen'} by {abs(delta):.0f} points over four weeks."
                     if abs(delta) >= 3 else "The score has been broadly stable over four weeks.")
    parts.append("_Indicators describe habitat conditions only; they do not measure or predict wildlife "
                 "populations, mortality or movement._")
    return " ".join(parts)


def ndvi_baseline(nd: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    base = nd[nd["obs_date"] < as_of - pd.Timedelta(days=365)]
    if base.empty:
        return pd.DataFrame()
    clim = base.groupby(base["obs_date"].dt.dayofyear)["ndvi"].mean()
    out = nd[["obs_date"]].copy()
    out["baseline"] = out["obs_date"].dt.dayofyear.map(
        lambda d: clim.iloc[np.argmin(np.minimum(abs(clim.index - d), 365 - abs(clim.index - d)))])
    return out


def _md(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r'<br><span class="wc-note"><i>\1</i></span>', text)


def render() -> None:
    reserves = data.reserves()
    as_of = data.as_of()
    c1, c2, _ = st.columns([1.3, 1, 1.7])
    with c1:
        pa_id = filters.reserve_select(reserves, "rx_reserve", default=st.session_state.get("rx_default"))
    with c2:
        period = st.selectbox("Trend period", list(PERIODS), index=1, key="rx_period")
    info = reserves.set_index("pa_id").loc[pa_id]
    hist = data.scores(pa_id)
    r = hist.iloc[-1]
    header(info["name"], f"{info['designation']} · {info['state']}", r["week_end"],
           f"Provenance: {data.provenance(data.weather(pa_id, str((as_of - pd.Timedelta(days=90)).date())))}")

    g, i = st.columns([1, 2])
    with g:
        score_gauge_card(r["total_score"], r["completeness"], bool(r["provisional"]), r["week_end"])
    with i:
        verified = isinstance(info["boundary_geojson"], str) and info["boundary_geojson"]
        bsrc = badge("Verified boundary (uploaded)", T["green"]) if verified else \
            badge(f"Approximate footprint · r≈{buffer_radius_km(info['area_km2']):.0f} km", T["yellow"])
        st.markdown(f"""<div class="wc-card"><div class="lbl">Reserve information</div>
            <table style="width:100%;font-size:0.88rem;color:{T['text']};margin-top:0.4rem">
            <tr><td style="color:{T['muted']}">Designation</td><td>{info['designation']}</td>
                <td style="color:{T['muted']}">Established</td><td>{info['established']}</td></tr>
            <tr><td style="color:{T['muted']}">Area</td><td>{info['area_km2']:,.0f} km² <span class="wc-note">({info['area_basis']})</span></td>
                <td style="color:{T['muted']}">Coordinates</td><td>{info['latitude']:.3f}°N, {info['longitude']:.3f}°E</td></tr>
            <tr><td style="color:{T['muted']}">Ecosystem</td><td colspan=3>{info['ecosystem']}</td></tr>
            <tr><td style="color:{T['muted']}">Boundary</td><td colspan=3>{bsrc}</td></tr>
            </table></div>""", unsafe_allow_html=True)

    st.write("")
    tab_h, tab_x, tab_w = st.tabs(["🌿 Habitat conditions", "💧 Water & wildlife report", "🐾 Wildlife profile"])
    with tab_x:
        from dashboard.water import reserve_water_report
        reserve_water_report(pa_id)
    with tab_w:
        wildlife_profile(pa_id, info)
    with tab_h:
        st.write("")
        w = settings.load_scoring_config()["weights"]
        cols = st.columns(4)
        na = lambda v, fmt: "n/a" if v is None or v != v else fmt.format(v)  # noqa: E731
        with cols[0]:
            indicator_card("Heat stress", "🌡️", r["heat_score"], w["heat"],
                           f"Tmax anomaly {na(r['tmax_anomaly_c'], '{:+.1f} °C')} · hot days {na(r['hot_days'], '{:.0f}')}/7")
        with cols[1]:
            indicator_card("Rainfall deficit", "💧", r["drought_score"], w["drought"],
                           f"90-day deficit {na(r['deficit_pct'], '{:.0f}%')} · {na(r['rain_90d_mm'], '{:.0f}')} mm")
        with cols[2]:
            indicator_card("Vegetation (NDVI)", "🌿", r["vegetation_score"], w["vegetation"],
                           f"NDVI {na(r['ndvi'], '{:.2f}')} · vs baseline {na(r['ndvi_change_pct'], '{:+.0f}%')}")
        with cols[3]:
            indicator_card("Fire activity", "🔥", r["fire_score"], w["fire"],
                           f"{na(r['fire_count_7d'], '{:.0f}')} detections in 7 days")

        start = as_of - pd.Timedelta(days=PERIODS[period])
        wx = data.weather(pa_id, str(start.date()))
        nd = data.ndvi(pa_id)
        st.write("")
        a, b = st.columns(2)
        with a:
            st.plotly_chart(charts.temp_rain(wx), width="stretch", config={"displayModeBar": False})
        with b:
            h = hist[hist["week_end"] >= start]
            st.plotly_chart(charts.score_trend(h, title="Habitat Stress Score (weekly)"), width="stretch",
                            config={"displayModeBar": False})

        a, b = st.columns([1, 1])
        with a:
            ndv = nd[nd["obs_date"] >= start]
            if ndv.empty:
                st.info("No NDVI observations for this period. Import NDVI on Research & Admin → Admin.")
            else:
                st.plotly_chart(charts.ndvi_trend(ndv, ndvi_baseline(nd, as_of).loc[ndv.index]),
                                width="stretch", config={"displayModeBar": False})
            fires = data.fires(str((as_of - pd.Timedelta(days=29)).date()), str(as_of.date()))
            fr = fires[fires["pa_id"] == pa_id]
            inside = fr[fr["inside_boundary"] == 1]
            section("Fire detection summary", "🔥")
            fc = st.columns(3)
            with fc[0]:
                kpi_card("Last 7 days", int((inside["acq_date"] > as_of - pd.Timedelta(days=7)).sum()), "inside footprint")
            with fc[1]:
                kpi_card("Last 30 days", len(inside), f"+{len(fr) - len(inside)} within 25 km")
            with fc[2]:
                kpi_card("Max FRP (30 d)", f"{inside['frp'].max():.0f} MW" if not inside.empty else "—",
                         "fire radiative power")
        with b:
            section("Reserve map — 30-day detections", "🗺️")
            st_folium(maps.reserve_map(info.to_dict() | {"pa_id": pa_id}, fr, category_for(r["total_score"])[1]),
                      height=430, use_container_width=True, returned_objects=[], key=f"rx_map_{pa_id}")

        section("Automated research summary", "📝")
        st.markdown(f'<div class="wc-card" style="font-size:0.92rem;line-height:1.55">'
                    f'{_md(research_summary(r, info.to_dict(), len(inside), hist))}</div>',
                    unsafe_allow_html=True)


def wildlife_profile(pa_id: str, info) -> None:
    """Biodiversity profile — documented occurrences and official estimates, kept separate from habitat metrics."""
    from components.cards import empty_state, species_card
    from dashboard.wildlife import CAVEAT, associations
    sr = associations()
    sr = sr[sr["pa_id"] == pa_id]
    pop = data.population()
    pop = pop[pop["pa_id"] == pa_id]
    obs_rows = sr[sr["n_records"] > 0]
    g = obs_rows["taxon_group"]
    thr = sr[sr["iucn_category"].isin(["CR", "EN", "VU"])]
    kpi_row([
        dict(label="Documented species", value=len(sr), icon="🧬", sub=f"{int(obs_rows['n_records'].sum()):,} records"),
        dict(label="Mammals", value=int((g == "Mammals").sum()), icon="🐾", sub="species with records"),
        dict(label="Birds", value=int((g == "Birds").sum()), icon="🪶", sub="species with records"),
        dict(label="Reptiles & amphibians", value=int(g.isin(["Reptiles", "Amphibians"]).sum()), icon="🦎",
             sub=f"{int((g == 'Reptiles').sum())} reptiles · {int((g == 'Amphibians').sum())} amphibians"),
        dict(label="Threatened species", value=len(thr), icon="⚠️", colour=T["orange"] if len(thr) else None,
             sub="IUCN CR · EN · VU"),
    ])
    st.caption("ℹ️ " + CAVEAT + " Habitat Stress metrics are reported separately in the Habitat conditions tab.")
    if obs_rows.empty:
        empty_state("No occurrence records for this reserve yet",
                    "Fetch GBIF and iNaturalist records from Wildlife Intelligence or Research & Administration → Admin.",
                    "🐾")
    section("Notable species", "⭐")
    notable = sr.assign(rank=sr["iucn_category"].map({"CR": 0, "EN": 1, "VU": 2, "NT": 3}).fillna(9)) \
        .sort_values(["rank", "n_records"], ascending=[True, False]).head(6)
    sp = data.species().set_index("scientific_name")
    cols = st.columns(3)
    for i, row in enumerate(notable.to_dict("records")):
        meta = sp.loc[row["scientific_name"]].to_dict() if row["scientific_name"] in sp.index else {}
        with cols[i % 3]:
            species_card(meta | row, compact=True,
                         extra=f"{int(row['n_records'])} records · {row['sources']}")
            st.write("")
    a, b = st.columns([1.2, 1])
    with a:
        section("Historical wildlife observations", "🕒")
        obs = data.observations((pa_id,))
        st.plotly_chart(charts.obs_timeline(obs, "taxon_group", "Records by year and group"), width="stretch",
                        config={"displayModeBar": False})
    with b:
        section("Available population estimates", "📊")
        if pop.empty:
            st.info("No official population estimate is stored for this reserve.")
        else:
            st.dataframe(pop[["common_name", "scope", "estimate", "survey_year", "institution", "source_url"]],
                         hide_index=True, width="stretch",
                         column_config={"common_name": "Species", "scope": "Scope",
                                        "estimate": st.column_config.NumberColumn("Estimate", format="%d"),
                                        "survey_year": st.column_config.NumberColumn("Year", format="%d"),
                                        "institution": "Institution",
                                        "source_url": st.column_config.LinkColumn("Citation", display_text="source ↗")})
            st.caption("Official survey estimates — independent of occurrence-record counts.")
