"""Page 4 — Research & Admin."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from components import charts, data, filters
from components.cards import badge, section
from components.sidebar import header
from config import settings
from config.settings import THEME as T
from database import db
from ingestion import nasa_firms, nasa_power, ndvi as ndvi_conn
from processing import cleaning
from processing.pipeline import reassign_fire_reserves, rebuild_derived
from processing.stress_scoring import describe_methodology

SEASONS = {12: "Winter (DJF)", 1: "Winter (DJF)", 2: "Winter (DJF)", 3: "Pre-monsoon (MAM)",
           4: "Pre-monsoon (MAM)", 5: "Pre-monsoon (MAM)", 6: "Monsoon (JJAS)", 7: "Monsoon (JJAS)",
           8: "Monsoon (JJAS)", 9: "Monsoon (JJAS)", 10: "Post-monsoon (ON)", 11: "Post-monsoon (ON)"}
SEASON_ORDER = ["Winter (DJF)", "Pre-monsoon (MAM)", "Monsoon (JJAS)", "Post-monsoon (ON)"]
NOCFG = {"displayModeBar": False}


def render() -> None:
    header("Research & Administration", "Comparative analytics, integrated exploration, exports and data management",
           data.as_of())
    t1, t2 = st.tabs(["📊 Research", "⚙️ Admin"])
    with t1:
        r1, r2, r3 = st.tabs(["Habitat comparison", "Biodiversity comparison", "Integrated exploration"])
        with r1:
            research()
        with r2:
            biodiversity_comparison()
        with r3:
            integrated_exploration()
    with t2:
        admin()


# ------------------------------------------------------------------ research
def research() -> None:
    reserves = data.reserves()
    c = st.columns([1, 1, 1])
    with c[0]:
        a = filters.reserve_select(reserves, "rs_a", "Protected area A", "Gir")
    with c[1]:
        b = filters.reserve_select(reserves, "rs_b", "Protected area B", "Periyar")
    with c[2]:
        weeks = st.slider("Weeks of history", 8, settings.SCORE_HISTORY_WEEKS, 52, key="rs_weeks")
    names = reserves.set_index("pa_id")["name"]
    sc = pd.concat([data.scores(a), data.scores(b)]).drop_duplicates(["pa_id", "week_end"])
    sc = sc[sc["week_end"] > sc["week_end"].max() - pd.Timedelta(weeks=weeks)]

    l, r = st.columns([1.5, 1])
    with l:
        st.plotly_chart(charts.score_trend(sc, [names[a], names[b]], 330, "HSS comparison"),
                        width="stretch", config=NOCFG)
    with r:
        latest = sc.sort_values("week_end").groupby("pa_id").tail(1).set_index("name")
        cols = {"total_score": "HSS", "category": "Category", "heat_score": "Heat", "drought_score": "Drought",
                "vegetation_score": "Vegetation", "fire_score": "Fire", "tmax_anomaly_c": "Tmax anomaly (°C)",
                "deficit_pct": "Rain deficit (%)", "ndvi_change_pct": "NDVI vs baseline (%)",
                "fire_count_7d": "Fires (7 d)", "completeness": "Completeness"}
        cmp = latest[list(cols)].rename(columns=cols).T
        st.markdown("**Latest week side-by-side**")
        st.dataframe(cmp.astype(str), width="stretch", height=420)

    section("Historical climate trends (annual)", "📈")
    wx = pd.concat([data.weather(a), data.weather(b)])
    wx["name"] = wx["pa_id"].map(names)
    wx["year"] = wx["obs_date"].dt.year
    full_years = wx.groupby(["pa_id", "year"])["obs_date"].transform("count") >= 330
    annual = wx[full_years].groupby(["name", "year"]).agg(rain=("precip_mm", "sum"),
                                                          tmax=("tmax_c", "mean")).reset_index()
    annual["season"] = annual["year"].astype(str)
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.seasonal_bars(annual, "rain", "Annual rainfall (complete years)", "mm"),
                        width="stretch", config=NOCFG)
    with r:
        st.plotly_chart(charts.seasonal_bars(annual, "tmax", "Mean annual max temperature", "°C"),
                        width="stretch", config=NOCFG)

    section("Seasonal comparison (all available years)", "🍂")
    wx["season"] = pd.Categorical(wx["obs_date"].dt.month.map(SEASONS), SEASON_ORDER, ordered=True)
    wx["season_year"] = wx["obs_date"].dt.year + (wx["obs_date"].dt.month == 12)
    seas = wx.groupby(["name", "season", "season_year"], observed=True).agg(
        rain=("precip_mm", "sum"), tmax=("tmax_c", "mean")).groupby(["name", "season"], observed=True).mean() \
        .reset_index()
    fr = data.fires()
    fr = fr[fr["pa_id"].isin([a, b]) & (fr["inside_boundary"] == 1)]
    fr["season"] = fr["acq_date"].dt.month.map(SEASONS)
    nyears = max(1, fr["acq_date"].dt.year.nunique())
    fseas = (fr.groupby(["reserve", "season"]).size() / nyears).rename("fires").reset_index() \
        .rename(columns={"reserve": "name"})
    fseas["season"] = pd.Categorical(fseas["season"], SEASON_ORDER, ordered=True)
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.seasonal_bars(seas, "rain", "Mean seasonal rainfall", "mm per season"),
                        width="stretch", config=NOCFG)
    with r:
        st.plotly_chart(charts.seasonal_bars(fseas.sort_values("season"), "fires",
                                             "Mean fire detections per season", "detections"),
                        width="stretch", config=NOCFG)

    section("Correlation matrix", "🧮")
    scope = st.radio("Scope", ["Selected pair", "All protected areas"], horizontal=True, key="rs_corr")
    allsc = data.scores() if scope == "All protected areas" else sc
    cm = allsc[["tmax_anomaly_c", "deficit_pct", "ndvi_change_pct", "fire_count_7d", "total_score"]] \
        .rename(columns={"tmax_anomaly_c": "Tmax anomaly", "deficit_pct": "Rain deficit",
                         "ndvi_change_pct": "NDVI change", "fire_count_7d": "Fires 7d", "total_score": "HSS"})
    corr = cm.apply(pd.to_numeric, errors="coerce").corr()
    l, r = st.columns([1.3, 1])
    with l:
        st.plotly_chart(charts.correlation_heatmap(corr), width="stretch", config=NOCFG)
    with r:
        st.markdown(f"""<div class="wc-card wc-note" style="font-size:0.85rem;line-height:1.5">
            Pearson correlation of weekly indicator values ({len(cm.dropna())} complete weekly records).
            Indicators share inputs (e.g. drought and NDVI respond to the same rainfall), so correlations
            describe co-variation, not causation. Demonstration data embeds simulated relationships and
            must not be interpreted scientifically.</div>""", unsafe_allow_html=True)
        section("Downloads", "⬇")
        st.download_button("Weekly scores — selected pair", data.to_csv(sc), "scores_pair.csv", "text/csv")
        st.download_button("Weekly scores — all areas", data.to_csv(data.scores()), "scores_all.csv", "text/csv")
        st.download_button("Daily weather — selected pair", data.to_csv(wx.drop(columns=["season"])),
                           "weather_pair.csv", "text/csv")
        st.download_button("NDVI — all areas", data.to_csv(data.ndvi()), "ndvi_all.csv", "text/csv")


# ------------------------------------------------------------------ admin
def _after_write(msg: str, recompute: bool = True) -> None:
    if recompute:
        with st.spinner("Recomputing habitat stress scores and alerts…"):
            res = rebuild_derived()
        msg += f" Scores recomputed to week ending {res['week_end']}."
    data.invalidate()
    st.session_state["admin_msg"] = msg


def admin() -> None:
    if msg := st.session_state.pop("admin_msg", None):
        st.success(msg)
    if err := st.session_state.pop("admin_err", None):
        st.error(err)
    src = data.sources()
    section("Data source status", "📡")
    colour = {"OK": T["green"], "DEMO": T["yellow"], "PARTIAL": T["orange"], "FAILED": T["red"],
              "NOT CONFIGURED": "#8A9A94", "NOT RUN": "#8A9A94"}
    rows = "".join(
        f"<tr><td><b>{r.name}</b><br><span class='wc-note'>{r.category}</span></td>"
        f"<td>{badge(r.status, colour.get(r.status, T['muted']))}</td>"
        f"<td class='wc-note'>{r.last_success or '—'}</td><td class='wc-note'>{r.last_attempt or '—'}</td>"
        f"<td class='wc-note'>{r.message or ''}</td></tr>" for r in src.itertuples())
    st.markdown(f"""<div class="wc-card"><table style="width:100%;font-size:0.84rem;color:{T['text']}">
        <tr style="color:{T['muted']};text-align:left"><th>Source</th><th>Status</th><th>Last successful update</th>
        <th>Last attempt</th><th>Message</th></tr>{rows}</table></div>""", unsafe_allow_html=True)

    counts = db.record_counts()
    if not counts.empty:
        st.dataframe(counts.pivot_table(index="table", columns="source_type", values="records", fill_value=0),
                     width="stretch")

    section("Refresh data", "🔄")
    st.caption("Connectors never fabricate responses: on failure, existing records are kept and the error is logged.")
    c = st.columns(5)
    prog = st.empty()

    def bar(frac, text):
        prog.progress(min(1.0, frac), text=text)

    with c[0]:
        if st.button("NASA POWER weather", width="stretch"):
            res = nasa_power.refresh(progress=bar)
            (_after_write if res["records"] else _fail)(f"NASA POWER: {res['message']}")
            st.rerun()
    with c[1]:
        if st.button("NASA FIRMS fires", width="stretch",
                     help="Requires FIRMS_MAP_KEY in .env" if not settings.FIRMS_MAP_KEY else None):
            res = nasa_firms.refresh(progress=bar)
            (_after_write if res["ok"] else _fail)(f"NASA FIRMS: {res['message']}")
            st.rerun()
    with c[2]:
        if st.button("MODIS NDVI (optional)", width="stretch"):
            res = ndvi_conn.refresh(progress=bar)
            (_after_write if res["records"] else _fail)(f"MODIS NDVI: {res['message']}")
            st.rerun()
    with c[3]:
        if st.button("Recompute scores", width="stretch"):
            _after_write("Scores recomputed from stored observations.")
            st.rerun()
    with c[4]:
        if st.button("Reset to demo data", width="stretch", help="Deletes all data incl. uploads"):
            st.session_state["confirm_reset"] = True
    if st.session_state.get("confirm_reset"):
        st.warning("This deletes all stored observations, uploads and alert acknowledgements.")
        y, n, _ = st.columns([1, 1, 4])
        if y.button("Confirm reset", type="primary"):
            with st.spinner("Rebuilding demonstration database…"):
                db.init_db(reset=True)
            st.session_state.pop("confirm_reset")
            _after_write("Database reset to the demonstration dataset.", recompute=False)
            st.rerun()
        if n.button("Cancel"):
            st.session_state.pop("confirm_reset")
            st.rerun()

    wildlife_admin()

    section("Upload data", "📤")
    kind = st.selectbox("Dataset type", ["Weather CSV", "NDVI CSV", "Fire detections CSV (FIRMS format)",
                                         "Boundary GeoJSON", "Wildlife occurrences CSV (Darwin Core)",
                                         "Population estimates CSV", "Water bodies CSV",
                                         "Water observations CSV"], key="up_kind")
    hints = {
        "Weather CSV": "Columns: `reserve` (name) or `pa_id`, `date`, `tmax_c`, `precip_mm`, optional `tmean_c`.",
        "NDVI CSV": "Columns: `reserve` or `pa_id`, `date`, `ndvi` (−1…1, or MODIS ×10000 integers).",
        "Fire detections CSV (FIRMS format)": "NASA FIRMS archive/NRT CSV: `latitude`, `longitude`, `acq_date`, "
                                              "optional `acq_time`, `satellite`, `confidence`, `frp`, `daynight`. "
                                              "The upload's date range is treated as fully covered.",
        "Wildlife occurrences CSV (Darwin Core)": "Columns: `scientificName`, `decimalLatitude`, `decimalLongitude`, "
            "`eventDate`, recommended `occurrenceID`, optional `vernacularName`, `class`, `family`, `individualCount`, "
            "`basisOfRecord`, `identificationVerificationStatus`, `iucnRedListCategory`. GBIF downloads work as-is. "
            "Records outside the reserve footprints are not stored; duplicates are ignored.",
        "Population estimates CSV": "Columns: `scientific_name`, `scope`, `estimate`, `survey_year`, `method`, "
            "`institution`, optional `pa_id`, `lower_ci`, `upper_ci`, `source_url`, `notes`. Only official/published "
            "survey estimates should be uploaded.",
        "Water bodies CSV": "Columns: `name`, `wb_type`, `latitude`, `longitude`, `reserve` or `pa_id` (else matched by "
            "location), optional `permanence` (Perennial/Seasonal/Managed (artificial)), `location_basis` "
            "(VERIFIED for surveyed points, else UPLOADED), `wb_id`, `notes`. Treat locations of sensitive water "
            "points with care before sharing exports.",
        "Water observations CSV": "Columns: `wb_id` (or `name`), `date`, `metric` (water_level_m, water_spread_pct, ndwi, "
            "ndvi_buffer, presence), `value`, optional `obs_kind` (DIRECT for gauge/field readings, SATELLITE for "
            "remote sensing), `unit`, `method`.",
        "Boundary GeoJSON": "FeatureCollection of Polygon/MultiPolygon features with a `pa_id` "
                            "(e.g. BAN) or `name` property — e.g. exported from Protected Planet (WDPA), "
                            "subject to its licence.",
    }
    st.caption(hints[kind])
    up = st.file_uploader("Choose file", type=["geojson", "json"] if kind == "Boundary GeoJSON" else ["csv", "txt"],
                          key=f"up_{kind}")
    if up is not None:
        _handle_upload(kind, up)

    section("Scoring weights & thresholds", "🎛️")
    cfg = settings.load_scoring_config()
    with st.form("scoring_cfg"):
        st.markdown("**Indicator weights** (maximum points; must total 100)")
        wc = st.columns(4)
        w = {k: wc[i].number_input(k.title(), 0, 100, int(cfg["weights"][k]), 5, key=f"w_{k}")
             for i, k in enumerate(["heat", "drought", "vegetation", "fire"])}
        st.markdown("**Thresholds** (value at which an indicator reaches its maximum)")
        tc = st.columns(4)
        th = dict(cfg["thresholds"])
        th["heat_anomaly_max_c"] = tc[0].number_input("Heat anomaly (°C)", 0.5, 10.0, float(th["heat_anomaly_max_c"]), 0.5)
        th["drought_deficit_max_pct"] = tc[1].number_input("Rain deficit (%)", 10.0, 100.0, float(th["drought_deficit_max_pct"]), 5.0)
        th["ndvi_decline_max_pct"] = tc[2].number_input("NDVI decline (%)", 5.0, 80.0, float(th["ndvi_decline_max_pct"]), 5.0)
        th["fire_count_max"] = tc[3].number_input("Fires in 7 days", 5, 500, int(th["fire_count_max"]), 5)
        st.markdown("**Alert rules**")
        ac = st.columns(4)
        al = dict(cfg["alerts"])
        al["fire_24h_count"] = ac[0].number_input("Fires in 24 h", 1, 200, int(al["fire_24h_count"]))
        al["fire_7d_count"] = ac[1].number_input("Fires in 7 days", 1, 500, int(al["fire_7d_count"]))
        al["drought_deficit_pct"] = ac[2].number_input("Rain deficit (%)", 10.0, 100.0, float(al["drought_deficit_pct"]), 5.0)
        al["heat_anomaly_c"] = ac[3].number_input("Heat anomaly (°C)", 0.5, 10.0, float(al["heat_anomaly_c"]), 0.5)
        s1, s2 = st.columns([1, 4])
        save = s1.form_submit_button("Save & recompute", type="primary")
        restore = s2.form_submit_button("Restore defaults")
    if save:
        if sum(w.values()) != 100:
            st.error(f"Weights total {sum(w.values())}; they must total 100.")
        else:
            settings.save_scoring_config({"weights": w, "thresholds": th, "alerts": al})
            _after_write("Scoring configuration saved.")
            st.rerun()
    if restore:
        settings.save_scoring_config(settings.DEFAULT_SCORING)
        _after_write("Default scoring configuration restored.")
        st.rerun()

    with st.expander("Scoring methodology", expanded=False):
        st.markdown(describe_methodology(cfg))


def _fail(msg: str) -> None:
    data.invalidate()
    st.session_state["admin_err"] = msg


def _handle_upload(kind: str, up) -> None:
    reserves = data.reserves()
    if kind == "Boundary GeoJSON":
        items, notes = cleaning.validate_geojson(up.getvalue().decode("utf-8", errors="replace"), reserves)
        for n_ in notes:
            st.warning(n_)
        if items:
            st.info(f"Matched {len(items)} boundary feature(s): "
                    + ", ".join(reserves.set_index('pa_id').loc[[p for p, _ in items], 'name']))
            if st.button("Import boundaries", type="primary"):
                with db.get_conn() as conn:
                    for pid, geom in items:
                        db.set_boundary(conn, pid, geom, f"UPLOADED: {up.name}")
                    db.update_source(conn, "UPLOADS", True, f"{len(items)} boundaries from {up.name}")
                reassign_fire_reserves()
                _after_write(f"Imported {len(items)} boundaries; fire detections re-assigned.")
                st.rerun()
        return
    try:
        raw = pd.read_csv(up, sep=None, engine="python")  # GBIF downloads are tab-separated
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not read CSV: {exc}")
        return
    if kind.startswith("Water"):
        _water_upload(kind, raw, up.name, reserves)
        return
    if kind.startswith("Wildlife") or kind.startswith("Population"):
        _wildlife_upload(kind, raw, up.name, reserves)
        return
    fn = {"Weather CSV": cleaning.validate_weather, "NDVI CSV": cleaning.validate_ndvi}.get(
        kind, cleaning.validate_fires)
    df, notes = fn(raw, reserves)
    for n_ in notes:
        st.warning(n_)
    if df is None or df.empty:
        st.error("No valid rows to import.")
        return
    st.markdown(f"**Validation passed for {len(df):,} row(s)** — preview:")
    st.dataframe(df.head(8), width="stretch", hide_index=True)
    if st.button(f"Import {len(df):,} rows", type="primary"):
        df = df.copy()
        df["source"], df["source_type"] = f"Upload: {up.name}", settings.UPLOADED
        with db.get_conn() as conn:
            if kind == "Weather CSV":
                n = db.upsert_weather(conn, df)
            elif kind == "NDVI CSV":
                n = db.upsert_ndvi(conn, df)
            else:
                lo, hi = str(df["acq_date"].min().date()), str(df["acq_date"].max().date())
                n = db.insert_fires(conn, df)
                db.update_source(conn, "UPLOADS", True, f"{n} fire detections from {up.name}",
                                 records=0, coverage=(lo, hi))
            db.update_source(conn, "UPLOADS", True, f"{n} rows imported from {up.name} ({kind})", records=n)
        _after_write(f"Imported {n:,} rows from {up.name}.")
        st.rerun()


# ------------------------------------------------------------------ wildlife research & admin
CORR_CAVEAT = """**Correlation is not causation.** Occurrence records depend on observation effort (how many
people visited and reported), accessibility, season, platform popularity and reporting bias, and the
environmental indicators share inputs with each other. Use the effort-normalised metric (records per
active recording day) and treat any pattern as a prompt for structured survey work, not as evidence of
an ecological effect. Demonstration environmental data is simulated."""


def biodiversity_comparison() -> None:
    from dashboard.wildlife import CAVEAT, associations
    reserves = data.reserves()
    names = st.multiselect("Protected areas", list(reserves["name"]), default=list(reserves["name"]), key="bc_res")
    sr = associations()
    sr = sr[sr["reserve"].isin(names)]
    obs_sr = sr[sr["n_records"] > 0]
    latest = data.latest_scores().set_index("name")
    pop = data.population()
    rows = []
    for n in names:
        g = sr[sr["reserve"] == n]
        o = g[g["n_records"] > 0]
        p = pop[pop["reserve"] == n].sort_values("survey_year").groupby("scientific_name").tail(1)
        rows.append({"Reserve": n, "Species": len(g), "Records": int(o["n_records"].sum()),
                     "Mammals": int((o["taxon_group"] == "Mammals").sum()), "Birds": int((o["taxon_group"] == "Birds").sum()),
                     "Reptiles & amphibians": int(o["taxon_group"].isin(["Reptiles", "Amphibians"]).sum()),
                     "Threatened": int(g["iucn_category"].isin(["CR", "EN", "VU"]).sum()),
                     "Population estimates": "; ".join(f"{(r.common_name or r.scientific_name)} {r.estimate:,.0f} ({r.survey_year})"
                                                       for r in p.itertuples()) or "—",
                     "HSS": latest.loc[n, "total_score"] if n in latest.index else None,
                     "HSS category": latest.loc[n, "category"] if n in latest.index else None,
                     "Rain deficit %": latest.loc[n, "deficit_pct"] if n in latest.index else None,
                     "Fires 7d": latest.loc[n, "fire_count_7d"] if n in latest.index else None})
    tbl = pd.DataFrame(rows)
    section("Biodiversity and habitat side by side", "🧭")
    st.dataframe(tbl, hide_index=True, width="stretch",
                 column_config={"HSS": st.column_config.ProgressColumn("HSS", min_value=0, max_value=100, format="%.0f"),
                                "Rain deficit %": st.column_config.NumberColumn(format="%.0f")})
    st.caption("ℹ️ Biodiversity columns count documented species/records; habitat columns are the latest weekly "
               "indicators. They are shown together for context and are computed independently. " + CAVEAT)
    st.download_button("⬇ Comparison (CSV)", data.to_csv(tbl), "wildcast_reserve_comparison.csv", "text/csv")
    if obs_sr.empty:
        st.info("Fetch occurrence records (Admin → Wildlife data) to enable diversity and observation charts.")
        return
    l, r = st.columns(2)
    with l:
        st.plotly_chart(charts.richness_by_reserve(obs_sr, "Species diversity across reserves"), width="stretch",
                        config=NOCFG)
    with r:
        st.plotly_chart(charts.threatened_by_reserve(sr, "Threatened species across reserves"), width="stretch",
                        config=NOCFG)
    obs = data.observations(tuple(reserves.loc[reserves["name"].isin(names), "pa_id"]))
    metric = st.radio("Over time", ["Records per year", "Species recorded per year"], horizontal=True, key="bc_m")
    d = obs.dropna(subset=["obs_date"])
    d = d[d["obs_date"].dt.year >= 2005]
    agg = d.groupby(["reserve", d["obs_date"].dt.year]).agg(
        v=("obs_uid", "count") if metric.startswith("Records") else ("scientific_name", "nunique")).reset_index()
    agg = agg.rename(columns={"obs_date": "season", "reserve": "name"})
    fig = charts.seasonal_bars(agg.assign(season=agg["season"].astype(str)), "v",
                               f"{metric} (retrieved records)", metric.split(" per")[0])
    st.plotly_chart(fig, width="stretch", config=NOCFG)


def monthly_panel(pa_ids: list[str]) -> pd.DataFrame:
    """Monthly reserve panel joining wildlife records with environmental indicators (computed separately)."""
    obs = data.observations(tuple(pa_ids)).dropna(subset=["obs_date"])
    obs["month"] = obs["obs_date"].dt.to_period("M").dt.to_timestamp()
    wl = obs.groupby(["pa_id", "month"]).agg(records=("obs_uid", "count"), species=("scientific_name", "nunique"),
                                            active_days=("obs_date", "nunique")).reset_index()
    wl["records_per_active_day"] = wl["records"] / wl["active_days"]
    wx = data.weather()
    wx = wx[wx["pa_id"].isin(pa_ids)]
    wx["month"] = wx["obs_date"].dt.to_period("M").dt.to_timestamp()
    env = wx.groupby(["pa_id", "month"]).agg(tmax=("tmax_c", "mean"), rainfall=("precip_mm", "sum")).reset_index()
    nd = data.ndvi()
    nd = nd[nd["pa_id"].isin(pa_ids)]
    nd["month"] = nd["obs_date"].dt.to_period("M").dt.to_timestamp()
    env = env.merge(nd.groupby(["pa_id", "month"])["ndvi"].mean().reset_index(), how="left")
    fr = data.fires()
    fr = fr[fr["pa_id"].isin(pa_ids) & (fr["inside_boundary"] == 1)]
    fr["month"] = fr["acq_date"].dt.to_period("M").dt.to_timestamp()
    env = env.merge(fr.groupby(["pa_id", "month"]).size().rename("fires").reset_index(), how="left")
    env["fires"] = env["fires"].fillna(0)
    sc = data.scores()
    sc["month"] = sc["week_end"].dt.to_period("M").dt.to_timestamp()
    env = env.merge(sc.groupby(["pa_id", "month"])["total_score"].mean().rename("hss").reset_index(), how="left")
    panel = wl.merge(env, on=["pa_id", "month"], how="inner")
    panel["reserve"] = panel["pa_id"].map(data.reserves().set_index("pa_id")["name"])
    return panel


def integrated_exploration() -> None:
    reserves = data.reserves()
    st.markdown(f'<div class="wc-alert" style="border-left-color:{T["yellow"]}">{badge("Read first", T["yellow"])} '
                + CORR_CAVEAT.replace("**", "").replace("\n", " ") + "</div>", unsafe_allow_html=True)
    if not data.has_wildlife():
        st.info("Fetch occurrence records (Admin → Wildlife data) to enable integrated exploration.")
        return
    names = st.multiselect("Protected areas", list(reserves["name"]), default=list(reserves["name"]), key="ie_res")
    panel = monthly_panel(list(reserves.loc[reserves["name"].isin(names), "pa_id"]))
    if len(panel) < 6:
        st.warning("Too few months with both wildlife records and environmental data for exploration "
                   f"({len(panel)} reserve-months).")
        return
    var = {"Records": "records", "Species recorded": "species", "Records per active day (effort-normalised)":
           "records_per_active_day", "Mean max temperature (°C)": "tmax", "Rainfall (mm)": "rainfall",
           "NDVI": "ndvi", "Fire detections": "fires", "Habitat Stress Score": "hss"}
    corr = panel[list(var.values())].rename(columns={v: k.split(" (")[0] for k, v in var.items()}).corr()
    l, r = st.columns([1.2, 1])
    with l:
        st.plotly_chart(charts.correlation_heatmap(corr).update_layout(
            title_text=f"Monthly correlations ({len(panel)} reserve-months)"), width="stretch", config=NOCFG)
    with r:
        x = st.selectbox("X axis", list(var)[3:], key="ie_x")
        y = st.selectbox("Y axis", list(var)[:3], index=2, key="ie_y")
        st.plotly_chart(charts.scatter(panel.rename(columns={var[x]: x, var[y]: y}), x, y, "reserve",
                                       f"{y} vs {x}"), width="stretch", config=NOCFG)
    st.caption("Monthly panel: wildlife records joined to the same reserve-month's environmental indicators. "
               "Months without wildlife records are excluded (absence of records ≠ absence of animals).")
    st.download_button("⬇ Monthly panel (CSV)", data.to_csv(panel), "wildcast_integrated_panel.csv", "text/csv")


def wildlife_admin() -> None:
    import os
    from dashboard.wildlife import run_wildlife_fetch, show_fetch_msgs
    section("Wildlife data", "🐾")
    show_fetch_msgs("adm")
    keys = {"GBIF": "no key needed", "iNaturalist": "no key needed",
            "eBird": "key set" if os.getenv("EBIRD_API_KEY") else "needs EBIRD_API_KEY",
            "IUCN": "token set" if os.getenv("IUCN_API_TOKEN") else "needs IUCN_API_TOKEN"}
    st.caption("Occurrence records are fetched only for the reserve footprints. Sensitive species are stored with "
               "generalised (~11 km) coordinates. Duplicates (including iNaturalist records mirrored by GBIF) are ignored.")
    c = st.columns(4)
    for col, (src, note) in zip(c, keys.items()):
        with col:
            if st.button(f"{src} ({note})", width="stretch", key=f"wa_{src}"):
                run_wildlife_fetch([src], key="adm")
                st.rerun()


def _wildlife_upload(kind: str, raw: pd.DataFrame, filename: str, reserves: pd.DataFrame) -> None:
    from processing import wildlife as wl
    if kind.startswith("Population"):
        df, notes = wl.validate_population(raw, reserves)
    else:
        df, notes = wl.from_upload(raw, filename)
        if df is not None:
            df, more = wl.validate_observations(df)
            notes += more
    for n_ in notes:
        st.warning(n_)
    if df is None or df.empty:
        st.error("No valid rows to import.")
        return
    st.markdown(f"**Validation passed for {len(df):,} row(s)** — preview:")
    st.dataframe(df.head(8), width="stretch", hide_index=True)
    if st.button(f"Import {len(df):,} rows", type="primary", key="wl_import"):
        if kind.startswith("Population"):
            with db.get_conn() as conn:
                n = wl.insert_population(conn, df, settings.UPLOADED)
                db.update_source(conn, "UPLOADS", True, f"{n} population estimates from {filename}", records=n)
            msg = f"Imported {n} population estimate(s) ({len(df) - n} duplicates ignored)."
        else:
            res = wl.store_observations(df, reserves)
            with db.get_conn() as conn:
                db.update_source(conn, "UPLOADS", True, f"{res['inserted']} wildlife records from {filename}",
                                 records=res["inserted"])
            msg = (f"Imported {res['inserted']} wildlife record(s); {res['duplicates']} duplicate(s) ignored. "
                   + " ".join(res["notes"]))
        _after_write(msg, recompute=False)
        st.rerun()


def _water_upload(kind: str, raw: pd.DataFrame, filename: str, reserves: pd.DataFrame) -> None:
    from processing import water_io
    from processing.pipeline import rebuild_water
    if kind == "Water bodies CSV":
        df, notes = water_io.validate_water_bodies(raw, reserves)
    else:
        df, notes = water_io.validate_water_obs(raw, data.water_bodies())
    for n_ in notes:
        st.warning(n_)
    if df is None or df.empty:
        st.error("No valid rows to import.")
        return
    st.markdown(f"**Validation passed for {len(df):,} row(s)** — preview:")
    st.dataframe(df.head(8), width="stretch", hide_index=True)
    if st.button(f"Import {len(df):,} rows", type="primary", key="water_import"):
        n = (water_io.store_water_bodies if kind == "Water bodies CSV" else water_io.store_water_obs)(df, filename)
        with db.get_conn() as conn:
            db.update_source(conn, "UPLOADS", True, f"{n} rows from {filename} ({kind})", records=n)
        with st.spinner("Recomputing water assessments…"):
            rebuild_water()
        _after_write(f"Imported {n} row(s) from {filename}; water assessments recomputed.", recompute=False)
        st.rerun()
