"""Page 4 — Wildlife Intelligence (overview, species explorer, occurrence map, populations, conservation)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from components import charts, data, filters, maps
from components.cards import (GROUP_ICONS, badge, empty_state, iucn_badge, kpi_row, section,
                              species_card)
from components.sidebar import header
from config.settings import THEME as T
from processing.wildlife import GROUPS, IUCN_LABELS, THREATENED

NOCFG = {"displayModeBar": False}
CAVEAT = ("Record counts reflect where and how often people and institutions have reported species "
          "(observation effort, accessibility, reporting bias) — not how many animals are present.")


# ------------------------------------------------------------------ shared helpers
def associations() -> pd.DataFrame:
    """Reserve-species pairs from retrieved records plus reserves with official population estimates."""
    sr = data.species_reserve()
    pop = data.population()
    sp = data.species().set_index("scientific_name")
    extra = pop.dropna(subset=["pa_id"]).drop_duplicates(["pa_id", "scientific_name"])
    extra = extra[~(extra["pa_id"] + extra["scientific_name"]).isin(sr["pa_id"] + sr["scientific_name"])]
    if not extra.empty:
        extra = pd.DataFrame({
            "pa_id": extra["pa_id"], "scientific_name": extra["scientific_name"], "n_records": 0, "n_sources": 0,
            "sources": "Official estimate", "first_date": None, "last_date": None,
            "common_name": extra["scientific_name"].map(sp["common_name"]),
            "taxon_group": extra["scientific_name"].map(sp["taxon_group"]),
            "iucn_category": extra["scientific_name"].map(sp["iucn_category"]),
            "family": extra["scientific_name"].map(sp["family"]), "reserve": extra["reserve"],
            "state": extra["state"]})
        sr = pd.concat([sr, extra], ignore_index=True)
    return sr


def documented_species() -> pd.DataFrame:
    sp = data.species()
    return sp[sp["scientific_name"].isin(associations()["scientific_name"])]


def run_wildlife_fetch(sources: list[str], key: str = "wf") -> None:
    from ingestion import ebird, gbif, inaturalist, iucn
    prog = st.progress(0.0, text="Starting…")

    def bar(frac, text):
        prog.progress(min(1.0, frac), text=text)

    msgs = []
    for s in sources:
        res = {"GBIF": lambda: gbif.refresh(progress=bar), "iNaturalist": lambda: inaturalist.refresh(progress=bar),
               "eBird": lambda: ebird.refresh(progress=bar), "IUCN": lambda: iucn.refresh(progress=bar)}[s]()
        msgs.append((res["ok"], f"{s}: {res['message']}"))
    prog.empty()
    data.invalidate()
    st.session_state[f"{key}_msgs"] = msgs


def show_fetch_msgs(key: str = "wf") -> None:
    for ok, m in st.session_state.pop(f"{key}_msgs", []):
        (st.success if ok else st.error)(m)


# ------------------------------------------------------------------ page
def render() -> None:
    sp_all = data.species()
    sr = associations()
    obs_n = int(data.species_reserve()["n_records"].sum()) if data.has_wildlife() else 0
    header("Wildlife Intelligence", "Documented biodiversity and official population estimates for the pilot reserves",
           None, f"{len(documented_species())} species · {obs_n:,} occurrence records · "
                 f"{len(data.population())} official estimates · {len(data.water_bodies())} water bodies")
    show_fetch_msgs()
    from dashboard import water
    tabs = st.tabs(["🧭 Overview", "💧 Water Intelligence", "🐘 Species Impact", "🔎 Species Explorer",
                    "🗺️ Occurrence Map", "📈 Population Monitoring", "🛡️ Conservation Status"])
    with tabs[0]:
        overview(sr)
    with tabs[1]:
        water.water_intelligence()
    with tabs[2]:
        water.species_impact()
    with tabs[3]:
        species_explorer(sr)
    with tabs[4]:
        occurrence_map()
    with tabs[5]:
        population_monitoring()
    with tabs[6]:
        conservation_status(sr)


def fetch_panel(key: str) -> None:
    empty_state(
        "No occurrence records retrieved yet",
        "WILDCAST does not generate wildlife locations. Fetch real, citable records from GBIF and iNaturalist "
        "(research grade) for all ten reserve footprints — about 1–3 minutes with an internet connection. "
        "Official population estimates are already loaded and shown in the Population and Conservation tabs.",
        "🐾")
    c = st.columns([1, 1, 1])
    with c[1]:
        if st.button("Fetch records from GBIF + iNaturalist", type="primary", width="stretch", key=f"wl_fetch_{key}"):
            run_wildlife_fetch(["GBIF", "iNaturalist"])
            st.rerun()


def overview(sr: pd.DataFrame) -> None:
    doc = documented_species()
    threatened = doc[doc["iucn_category"].isin(THREATENED)]
    obs_sr = data.species_reserve()
    kpi_row([
        dict(label="Documented species", value=len(doc), icon="🧬",
             sub=f"{doc['taxon_group'].nunique()} taxonomic groups"),
        dict(label="Observation records", value=f"{int(obs_sr['n_records'].sum()):,}", icon="📍",
             sub="retrieved, de-duplicated"),
        dict(label="Reserves with records", value=f"{obs_sr['pa_id'].nunique()}/{len(data.reserves())}", icon="🛡️",
             sub="with ≥1 occurrence record"),
        dict(label="Threatened species", value=len(threatened), icon="⚠️", colour=T["orange"] if len(threatened) else None,
             sub=f"{int((threatened['iucn_category'] == 'CR').sum())} CR · "
                 f"{int((threatened['iucn_category'] == 'EN').sum())} EN · {int((threatened['iucn_category'] == 'VU').sum())} VU"),
        dict(label="Population estimates", value=len(data.population()), icon="📊",
             sub=f"{data.population()['scientific_name'].nunique()} species · official surveys"),
    ])
    st.write("")
    if not data.has_wildlife():
        fetch_panel('overview')
        return
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.richness_by_reserve(obs_sr), width="stretch", config=NOCFG)
    with r:
        st.plotly_chart(charts.top_species(doc[doc["n_records"] > 0]), width="stretch", config=NOCFG)
    st.caption("ℹ️ " + CAVEAT)
    l, r = st.columns([1.35, 1])
    obs = data.observations()
    with l:
        section("Recent wildlife observations", "🕒")
        rec = obs.dropna(subset=["obs_date"]).head(200)
        st.dataframe(
            rec[["obs_date", "common_name", "scientific_name", "taxon_group", "reserve", "source", "verification_status",
                 "record_url"]], hide_index=True, width="stretch", height=340,
            column_config={"obs_date": st.column_config.DateColumn("Date"), "common_name": "Species",
                           "scientific_name": "Scientific name", "taxon_group": "Group", "reserve": "Reserve",
                           "source": "Source", "verification_status": "Verification",
                           "record_url": st.column_config.LinkColumn("Record", display_text="open ↗")})
    with r:
        st.plotly_chart(charts.obs_timeline(obs[obs["obs_date"].dt.year >= 2005], "source"), width="stretch",
                        config=NOCFG)


def species_explorer(sr: pd.DataFrame) -> None:
    doc = documented_species()
    if doc.empty:
        fetch_panel('explorer')
        return
    c = st.columns([1.6, 1, 1, 1])
    q = c[0].text_input("Search species", placeholder="Common or scientific name, family…", key="sx_q")
    groups = c[1].multiselect("Group", [g for g in GROUPS if g in set(doc["taxon_group"])], key="sx_g",
                              placeholder="All groups")
    cats = c[2].multiselect("IUCN", [k for k in IUCN_LABELS if k in set(doc["iucn_category"].dropna())], key="sx_i",
                            placeholder="All categories")
    reserves = data.reserves()
    res = c[3].selectbox("Reserve", ["All reserves"] + list(reserves["name"]), key="sx_r")
    v = doc.copy()
    if q:
        ql = q.lower()
        v = v[v[["common_name", "scientific_name", "family"]].fillna("").apply(
            lambda col: col.str.lower().str.contains(ql, regex=False)).any(axis=1)]
    if groups:
        v = v[v["taxon_group"].isin(groups)]
    if cats:
        v = v[v["iucn_category"].isin(cats)]
    if res != "All reserves":
        v = v[v["scientific_name"].isin(sr.loc[sr["reserve"] == res, "scientific_name"])]
    st.caption(f"{len(v)} of {len(doc)} documented species match")
    st.dataframe(v[["common_name", "scientific_name", "taxon_group", "family", "iucn_category", "n_records",
                    "n_reserves", "last_date"]], hide_index=True, width="stretch", height=260,
                 column_config={"common_name": "Common name", "scientific_name": "Scientific name",
                                "taxon_group": "Group", "family": "Family", "iucn_category": "IUCN",
                                "n_records": st.column_config.NumberColumn("Records"),
                                "n_reserves": st.column_config.NumberColumn("Reserves"),
                                "last_date": "Latest record"})
    st.download_button("⬇ Species list (CSV)", data.to_csv(v), "wildcast_species.csv", "text/csv", key="sx_dl")
    if v.empty:
        return
    labels = {s: f"{c_ or s} — {s}" for s, c_ in zip(v["scientific_name"], v["common_name"])}
    name = st.selectbox("Open species profile", list(labels), format_func=labels.get, key="sx_open")
    species_profile(name, sr)


def species_profile(name: str, sr: pd.DataFrame) -> None:
    sp = data.species().set_index("scientific_name").loc[name].to_dict() | {"scientific_name": name}
    rows = sr[sr["scientific_name"] == name].sort_values("n_records", ascending=False)
    pop = data.population()
    pop = pop[pop["scientific_name"] == name]
    links = []
    if sp.get("gbif_key") == sp.get("gbif_key") and sp.get("gbif_key"):
        links.append(f'<a href="https://www.gbif.org/species/{int(sp["gbif_key"])}" target="_blank">GBIF ↗</a>')
    if sp.get("inat_taxon_id") == sp.get("inat_taxon_id") and sp.get("inat_taxon_id"):
        links.append(f'<a href="https://www.inaturalist.org/taxa/{int(sp["inat_taxon_id"])}" target="_blank">iNaturalist ↗</a>')
    l, r = st.columns([1.1, 1])
    with l:
        species_card(sp, extra=f'<div class="wc-note" style="margin-top:0.5rem">{" · ".join(links)}</div>')
    with r:
        kpi_row([dict(label="Records", value=int(rows["n_records"].sum()), icon="📍", sub="retrieved occurrences"),
                 dict(label="Reserves", value=len(rows), icon="🛡️", sub="documented in"),
                 dict(label="Population estimates", value=len(pop), icon="📊",
                      sub="official surveys" if len(pop) else "none available")])
        st.dataframe(rows[["reserve", "state", "n_records", "sources", "first_date", "last_date"]], hide_index=True,
                     width="stretch", height=180,
                     column_config={"reserve": "Reserve", "state": "State", "n_records": "Records",
                                    "sources": "Sources", "first_date": "First", "last_date": "Latest"})
    obs = data.observations(sp=name)
    a, b = st.columns(2)
    with a:
        st.plotly_chart(charts.obs_timeline(obs, "reserve", "Historical observation timeline"), width="stretch",
                        config=NOCFG)
    with b:
        if pop.empty:
            empty_state("No official population estimate",
                        "No published survey estimate is stored for this species in the pilot reserves. "
                        "Observation records are not population estimates.", "📊")
        else:
            st.plotly_chart(charts.population_trend(pop, "Official population estimates"), width="stretch",
                            config=NOCFG)


def occurrence_map() -> None:
    if not data.has_wildlife():
        fetch_panel('map')
        return
    reserves = data.reserves()
    doc = documented_species()
    doc = doc[doc["n_records"] > 0]
    c = st.columns([1.5, 1, 1, 1.2])
    opts = ["All species"] + list(doc["scientific_name"])
    lab = dict(zip(doc["scientific_name"], doc["common_name"].fillna(doc["scientific_name"])))
    spc = c[0].selectbox("Species", opts, key="om_sp",
                         format_func=lambda s: s if s == "All species" else f"{lab.get(s)} — {s}")
    states = c[1].multiselect("State", sorted(reserves["state"].unique()), key="om_state", placeholder="All states")
    rsel = reserves[reserves["state"].isin(states)] if states else reserves
    pas = c[2].multiselect("Reserve", list(rsel["name"]), key="om_res", placeholder="All reserves")
    pa_ids = tuple(rsel.loc[rsel["name"].isin(pas), "pa_id"]) if pas else tuple(rsel["pa_id"])
    obs = data.observations(pa_ids, None if spc == "All species" else spc)
    dated = obs["obs_date"].dropna()
    with c[3]:
        if dated.empty:
            d0 = d1 = None
        else:
            d0, d1 = filters.date_range("om_dates", dated.max().date(), (dated.max() - dated.min()).days + 1,
                                        dated.min().date())
    c2 = st.columns([1, 1, 2])
    groups = c2[0].multiselect("Group", [g for g in GROUPS if g in set(obs["taxon_group"])], key="om_g",
                               placeholder="All groups")
    srcs = c2[1].multiselect("Source", sorted(obs["source"].unique()), key="om_src", placeholder="All sources")
    undated = c2[2].toggle("Include undated records", value=False, key="om_und")
    if d0:
        keep = obs["obs_date"].between(pd.Timestamp(d0), pd.Timestamp(d1))
        obs = obs[keep | (undated & obs["obs_date"].isna())]
    if groups:
        obs = obs[obs["taxon_group"].isin(groups)]
    if srcs:
        obs = obs[obs["source"].isin(srcs)]
    gen = int(obs["coords_generalised"].sum())
    section(f"{len(obs):,} documented occurrences · {obs['scientific_name'].nunique()} species", "🗺️")
    if len(obs) > 4000:
        st.caption("Showing the 4,000 most recent records on the map; narrow the filters to see others.")
    st_folium(maps.occurrence_map(obs, rsel), height=540, use_container_width=True, returned_objects=[],
              key="om_map")
    st.markdown(f'<div class="wc-note">Click a point for record details. {gen:,} record(s) of sensitive species '
                '(IUCN CR/EN or poaching-sensitive taxa) or source-obscured records are shown only as ~11 km grid '
                'cells (dashed squares). Points inside reserve footprints only.</div>', unsafe_allow_html=True)
    with st.expander("Records shown (table & export)"):
        cols = ["obs_date", "common_name", "scientific_name", "reserve", "latitude", "longitude",
                "coords_generalised", "source", "record_id", "verification_status", "source_type", "retrieved_at",
                "record_url"]
        st.dataframe(obs[cols], hide_index=True, width="stretch", height=300,
                     column_config={"record_url": st.column_config.LinkColumn("Record", display_text="open ↗"),
                                    "coords_generalised": st.column_config.CheckboxColumn("Generalised"),
                                    "obs_date": st.column_config.DateColumn("Date")})
        st.download_button("⬇ Occurrences (CSV)", data.to_csv(obs[cols]), "wildcast_occurrences.csv", "text/csv")


def population_monitoring() -> None:
    pop = data.population()
    st.markdown(f"""<div class="wc-alert" style="border-left-color:{T['yellow']}">{badge('Important', T['yellow'])}
        Population estimates come from structured official surveys with defined methods. They are
        <b>not</b> derived from, and must not be compared with, occurrence-record counts. Compare estimates
        only where the scope and method are comparable.</div>""", unsafe_allow_html=True)
    if pop.empty:
        empty_state("No population estimates", "Upload official estimates on Research & Admin → Admin.", "📊")
        return
    c = st.columns([1.3, 1.3, 2])
    names = dict(zip(pop["scientific_name"], pop["common_name"].fillna(pop["scientific_name"])))
    sps = c[0].multiselect("Species", list(names), format_func=lambda s: f"{names[s]} — {s}", key="pm_sp",
                           placeholder="All species")
    rs = c[1].multiselect("Reserve", sorted(pop["reserve"].dropna().unique()), key="pm_res", placeholder="All reserves")
    v = pop
    if sps:
        v = v[v["scientific_name"].isin(sps)]
    if rs:
        v = v[v["reserve"].isin(rs)]
    tbl = v.assign(ci=[f"{lo:,.0f}–{hi:,.0f}" if pd.notna(lo) and pd.notna(hi) else "not reported"
                       for lo, hi in zip(v["lower_ci"], v["upper_ci"])])
    st.dataframe(tbl[["common_name", "scientific_name", "reserve", "scope", "estimate", "ci", "survey_year", "method",
                      "institution", "source_type", "source_url", "notes"]].sort_values(["common_name", "scope", "survey_year"]),
                 hide_index=True, width="stretch", height=330,
                 column_config={"common_name": "Species", "scientific_name": "Scientific name", "reserve": "Reserve",
                                "scope": "Survey scope", "estimate": st.column_config.NumberColumn("Estimate", format="%d"),
                                "ci": "Confidence interval", "survey_year": st.column_config.NumberColumn("Year", format="%d"),
                                "method": "Methodology", "institution": "Source institution",
                                "source_type": "Provenance",
                                "source_url": st.column_config.LinkColumn("Citation", display_text="source ↗"),
                                "notes": "Notes"})
    st.download_button("⬇ Population estimates (CSV)", data.to_csv(tbl), "wildcast_population.csv", "text/csv")

    section("Historical comparison (same scope, repeated surveys)", "📈")
    rep = v.groupby(["scientific_name", "scope"]).filter(lambda g: len(g) > 1)
    if rep.empty:
        st.info("No repeated surveys with the same scope in the current selection — historical comparison "
                "is not possible. Single-survey estimates are listed above.")
        return
    for spn, g in rep.groupby("scientific_name"):
        l, r = st.columns([1.5, 1])
        with l:
            st.plotly_chart(charts.population_trend(g, f"{names[spn]} — repeated surveys"), width="stretch",
                            config=NOCFG)
        with r:
            ch = g.sort_values("survey_year").copy()
            ch["prev"] = ch.groupby("scope")["estimate"].shift()
            ch["prev_year"] = ch.groupby("scope")["survey_year"].shift()
            ch["same_method"] = ch["method"] == ch.groupby("scope")["method"].shift()
            ch = ch.dropna(subset=["prev"])
            ch["change"] = (ch["estimate"] - ch["prev"]) / ch["prev"] * 100
            st.dataframe(ch[["scope", "prev_year", "survey_year", "prev", "estimate", "change", "same_method"]],
                         hide_index=True, width="stretch",
                         column_config={"scope": "Scope", "prev_year": st.column_config.NumberColumn("From", format="%d"),
                                        "survey_year": st.column_config.NumberColumn("To", format="%d"),
                                        "prev": st.column_config.NumberColumn("Earlier", format="%d"),
                                        "estimate": st.column_config.NumberColumn("Later", format="%d"),
                                        "change": st.column_config.NumberColumn("Change", format="%+.1f%%"),
                                        "same_method": st.column_config.CheckboxColumn("Same method")})
            st.caption("Changes are only indicative where survey methods differ between years.")


def conservation_status(sr: pd.DataFrame) -> None:
    doc = documented_species()
    if doc.empty:
        fetch_panel('conservation')
        return
    cat = doc["iucn_category"]
    kpi_row([
        dict(label="Critically Endangered", value=int((cat == "CR").sum()), icon="🔴", colour=T["red"]),
        dict(label="Endangered", value=int((cat == "EN").sum()), icon="🟠", colour=T["orange"]),
        dict(label="Vulnerable", value=int((cat == "VU").sum()), icon="🟡", colour=T["yellow"]),
        dict(label="Near Threatened", value=int((cat == "NT").sum()), icon="🟢"),
        dict(label="Category known", value=f"{cat.notna().mean():.0%}", icon="🧾",
             sub=f"{int(cat.notna().sum())} of {len(doc)} species"),
    ])
    st.write("")
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.iucn_bar(doc), width="stretch", config=NOCFG)
    with r:
        st.plotly_chart(charts.threatened_by_reserve(sr), width="stretch", config=NOCFG)
    section("Critically Endangered and Endangered species", "🛡️")
    ce = doc[cat.isin(["CR", "EN"])].sort_values(["iucn_category", "n_records"], ascending=[True, False])
    if ce.empty:
        st.info("No CR or EN species documented in the retrieved records.")
    else:
        res_by = sr.groupby("scientific_name")["reserve"].apply(lambda s: ", ".join(sorted(set(s))))
        cols = st.columns(3)
        for i, row in enumerate(ce.head(9).to_dict("records")):
            yr = row.get("iucn_assessment_year")
            with cols[i % 3]:
                species_card(row, compact=True,
                             extra=f"{GROUP_ICONS.get(row['taxon_group'], '')} {row['taxon_group']} · "
                                   f"{int(row['n_records'])} records · assessed "
                                   f"{int(yr) if yr == yr and yr else 'n/a'}<br>{res_by.get(row['scientific_name'], '')}")
                st.write("")
    with st.expander("All assessed species — profiles and assessment dates"):
        t = doc[cat.notna()][["common_name", "scientific_name", "taxon_group", "family", "iucn_category",
                              "iucn_assessment_year", "iucn_source", "n_records", "n_reserves"]]
        st.dataframe(t, hide_index=True, width="stretch", height=320,
                     column_config={"iucn_assessment_year": st.column_config.NumberColumn("Assessed", format="%d"),
                                    "iucn_category": "IUCN", "iucn_source": "Category source"})
        st.caption("Assessment years are available from the IUCN Red List API (set IUCN_API_TOKEN) or the reference "
                   "list; GBIF provides the category but not the assessment date.")
