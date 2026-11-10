"""Plotly chart builders with a shared dark theme."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from config.settings import CATEGORIES, THEME as T

CAT_ORDER = ["Low", "Moderate", "High", "Severe"]
CAT_COLOURS = {label: colour for _, label, colour in CATEGORIES}
SERIES = [T["green"], T["yellow"], T["blue"], T["orange"], "#B48EAD", T["red"]]


def _layout(fig: go.Figure, height: int = 320, title: str | None = None, legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=48 if title else 12, b=10),
        title=dict(text=title, font=dict(size=14, color=T["text"]), x=0.01) if title else None,
        paper_bgcolor=T["card"], plot_bgcolor=T["card"],
        font=dict(color=T["muted"], size=12, family="Inter, Segoe UI, sans-serif"),
        hoverlabel=dict(bgcolor="#0E1714", bordercolor=T["border"], font_color=T["text"]),
        showlegend=legend,
        legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.01, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)"),
    )
    fig.update_xaxes(gridcolor="#24372F", zeroline=False, linecolor=T["border"])
    fig.update_yaxes(gridcolor="#24372F", zeroline=False, linecolor=T["border"])
    return fig


def stress_distribution(latest: pd.DataFrame) -> go.Figure:
    counts = latest["category"].value_counts().reindex(CAT_ORDER, fill_value=0)
    fig = go.Figure(go.Bar(x=counts.index, y=counts.values, marker_color=[CAT_COLOURS[c] for c in CAT_ORDER],
                           text=counts.values, textposition="outside",
                           hovertemplate="%{x}: %{y} reserves<extra></extra>"))
    fig.update_yaxes(dtick=1, rangemode="tozero", range=[0, max(counts.max() + 1, 3)])
    return _layout(fig, 280, "Stress category distribution", legend=False)




def score_trend(scores: pd.DataFrame, names: list[str] | None = None, height=300, title="Habitat Stress Score trend"):
    fig = go.Figure()
    for band, (lo, hi) in {"Moderate": (40, 60), "High": (60, 80), "Severe": (80, 100)}.items():
        fig.add_hrect(y0=lo, y1=hi, fillcolor=CAT_COLOURS[band], opacity=0.06, line_width=0)
    for i, (name, g) in enumerate(scores.groupby("name")):
        if names and name not in names:
            continue
        fig.add_trace(go.Scatter(
            x=g["week_end"], y=g["total_score"], name=name, mode="lines",
            line=dict(color=SERIES[i % len(SERIES)] if names else SERIES[0], width=2.2),
            customdata=np.stack([g["category"], g["completeness"] * 100], axis=-1),
            hovertemplate="%{x|%d %b %Y}<br>HSS %{y:.1f} (%{customdata[0]})<br>"
                          "Completeness %{customdata[1]:.0f}%<extra>" + name + "</extra>"))
    fig.update_yaxes(range=[0, 100], title="HSS")
    return _layout(fig, height, title)


def temp_rain(weather: pd.DataFrame, title="Temperature & rainfall (weekly)") -> go.Figure:
    w = weather.set_index("obs_date").resample("W").agg({"tmax_c": "mean", "precip_mm": "sum"}).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=w["obs_date"], y=w["precip_mm"], name="Rainfall (mm/week)", marker_color=T["blue"],
                         opacity=0.75, yaxis="y2", hovertemplate="%{x|%d %b %Y}: %{y:.0f} mm<extra></extra>"))
    fig.add_trace(go.Scatter(x=w["obs_date"], y=w["tmax_c"], name="Mean max temp (°C)", mode="lines",
                             line=dict(color=T["orange"], width=2.2),
                             hovertemplate="%{x|%d %b %Y}: %{y:.1f} °C<extra></extra>"))
    fig.update_layout(yaxis=dict(title="°C"), yaxis2=dict(title="mm", overlaying="y", side="right",
                                                          showgrid=False))
    return _layout(fig, 300, title)


def ndvi_trend(ndvi: pd.DataFrame, baseline: pd.DataFrame | None = None) -> go.Figure:
    fig = go.Figure()
    if baseline is not None and not baseline.empty:
        fig.add_trace(go.Scatter(x=baseline["obs_date"], y=baseline["baseline"], name="Seasonal baseline",
                                 line=dict(color=T["muted"], dash="dot", width=1.5),
                                 hovertemplate="%{x|%d %b %Y}: %{y:.3f}<extra>baseline</extra>"))
    fig.add_trace(go.Scatter(x=ndvi["obs_date"], y=ndvi["ndvi"], name="NDVI", mode="lines+markers",
                             line=dict(color=T["green"], width=2.2), marker=dict(size=5),
                             hovertemplate="%{x|%d %b %Y}: %{y:.3f}<extra>NDVI</extra>"))
    fig.update_yaxes(title="NDVI")
    return _layout(fig, 280, "Vegetation health (NDVI, 16-day)")


def fire_timeline(fires: pd.DataFrame, title="Daily fire detections") -> go.Figure:
    if fires.empty:
        fig = go.Figure()
        fig.add_annotation(text="No detections in the selected period", showarrow=False, font=dict(color=T["muted"]))
        return _layout(fig, 260, title, legend=False)
    d = fires.groupby([fires["acq_date"].dt.date, "inside_boundary"]).size().unstack(fill_value=0)
    fig = go.Figure()
    for flag, label, colour in [(1, "Inside reserve footprint", T["red"]), (0, "Within 25 km buffer", T["yellow"])]:
        if flag in d.columns:
            fig.add_trace(go.Bar(x=d.index, y=d[flag], name=label, marker_color=colour,
                                 hovertemplate="%{x}: %{y}<extra>" + label + "</extra>"))
    fig.update_layout(barmode="stack")
    return _layout(fig, 260, title)


def correlation_heatmap(corr: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Heatmap(z=corr.values, x=corr.columns, y=corr.index, zmin=-1, zmax=1,
                               colorscale=[[0, T["blue"]], [0.5, T["card"]], [1, T["red"]]],
                               text=np.round(corr.values, 2), texttemplate="%{text}",
                               hovertemplate="%{y} vs %{x}: %{z:.2f}<extra></extra>"))
    return _layout(fig, 380, "Correlation matrix (weekly indicators)", legend=False)


def seasonal_bars(df: pd.DataFrame, value: str, title: str, ytitle: str) -> go.Figure:
    fig = go.Figure()
    for i, (name, g) in enumerate(df.groupby("name")):
        fig.add_trace(go.Bar(x=g["season"], y=g[value], name=name, marker_color=SERIES[i % len(SERIES)],
                             hovertemplate="%{x}: %{y:.1f}<extra>" + name + "</extra>"))
    fig.update_layout(barmode="group")
    fig.update_yaxes(title=ytitle)
    return _layout(fig, 300, title)


# ------------------------------------------------------------------ wildlife charts
GROUP_COLOURS = {"Mammals": T["orange"], "Birds": T["blue"], "Reptiles": T["green"], "Amphibians": "#7FC8B0",
                 "Fish": "#5B8DB8", "Insects": T["yellow"], "Other invertebrates": "#B48EAD", "Other": "#8A9A94"}
IUCN_ORDER = ["CR", "EN", "VU", "NT", "LC", "DD", "NE", "Unknown"]
IUCN_COLOURS = {"CR": "#D95F59", "EN": "#E58B43", "VU": "#E5B65B", "NT": "#B9C46A", "LC": "#6FAF83",
                "DD": "#8A9A94", "NE": "#5E6E68", "Unknown": "#46524E"}


def richness_by_reserve(sr: pd.DataFrame, title="Documented species by reserve") -> go.Figure:
    t = sr.groupby(["reserve", "taxon_group"]).size().unstack(fill_value=0)
    t = t.loc[t.sum(axis=1).sort_values().index]
    fig = go.Figure()
    for g in [c for c in GROUP_COLOURS if c in t.columns]:
        fig.add_trace(go.Bar(y=t.index, x=t[g], name=g, orientation="h", marker_color=GROUP_COLOURS[g],
                             hovertemplate="%{y}: %{x} " + g.lower() + " species<extra></extra>"))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title="Species with ≥1 retrieved record")
    return _layout(fig, 380, title)


def top_species(df: pd.DataFrame, n=12, title="Most frequently documented species") -> go.Figure:
    d = df.head(n).iloc[::-1]
    labels = [f"{c or s}" for c, s in zip(d["common_name"], d["scientific_name"])]
    fig = go.Figure(go.Bar(y=labels, x=d["n_records"], orientation="h",
                           marker_color=[GROUP_COLOURS.get(g, T["muted"]) for g in d["taxon_group"]],
                           customdata=d["scientific_name"],
                           hovertemplate="%{y} (<i>%{customdata}</i>): %{x} records<extra></extra>"))
    fig.update_xaxes(title="Retrieved records")
    return _layout(fig, 380, title, legend=False)


def obs_timeline(obs: pd.DataFrame, by="source", title="Observation records by year") -> go.Figure:
    d = obs.dropna(subset=["obs_date"])
    fig = go.Figure()
    if d.empty:
        fig.add_annotation(text="No dated records", showarrow=False, font=dict(color=T["muted"]))
        return _layout(fig, 280, title, legend=False)
    t = d.groupby([d["obs_date"].dt.year, by]).size().unstack(fill_value=0)
    pal = GROUP_COLOURS if by == "taxon_group" else {}
    for i, c in enumerate(t.columns):
        fig.add_trace(go.Bar(x=t.index, y=t[c], name=str(c), marker_color=pal.get(c, SERIES[i % len(SERIES)]),
                             hovertemplate="%{x}: %{y} records<extra>" + str(c) + "</extra>"))
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title="Records")
    return _layout(fig, 290, title)


def iucn_bar(sp: pd.DataFrame, title="Documented species by IUCN category") -> go.Figure:
    c = sp["iucn_category"].fillna("Unknown").value_counts().reindex(IUCN_ORDER, fill_value=0)
    fig = go.Figure(go.Bar(x=c.index, y=c.values, marker_color=[IUCN_COLOURS[k] for k in c.index],
                           text=c.values, textposition="outside",
                           hovertemplate="%{x}: %{y} species<extra></extra>"))
    fig.update_yaxes(rangemode="tozero")
    return _layout(fig, 300, title, legend=False)


def threatened_by_reserve(sr: pd.DataFrame, title="Threatened species by reserve (CR · EN · VU)") -> go.Figure:
    d = sr[sr["iucn_category"].isin(["CR", "EN", "VU"])]
    t = d.groupby(["reserve", "iucn_category"]).size().unstack(fill_value=0)
    fig = go.Figure()
    if t.empty:
        fig.add_annotation(text="No threatened species documented yet", showarrow=False, font=dict(color=T["muted"]))
        return _layout(fig, 300, title, legend=False)
    t = t.loc[t.sum(axis=1).sort_values(ascending=False).index]
    for k in ["CR", "EN", "VU"]:
        if k in t.columns:
            fig.add_trace(go.Bar(x=t.index, y=t[k], name=k, marker_color=IUCN_COLOURS[k],
                                 hovertemplate="%{x}: %{y} " + k + " species<extra></extra>"))
    fig.update_layout(barmode="stack")
    return _layout(fig, 300, title)


def population_trend(pop: pd.DataFrame, title="Population estimates over survey years") -> go.Figure:
    fig = go.Figure()
    for i, (scope, g) in enumerate(pop.sort_values("survey_year").groupby("scope")):
        err = None
        if g["lower_ci"].notna().any():
            err = dict(type="data", symmetric=False, array=(g["upper_ci"] - g["estimate"]).fillna(0),
                       arrayminus=(g["estimate"] - g["lower_ci"]).fillna(0), color=T["muted"])
        fig.add_trace(go.Scatter(x=g["survey_year"], y=g["estimate"], name=scope, mode="lines+markers",
                                 line=dict(color=SERIES[i % len(SERIES)], width=2.2), marker=dict(size=8),
                                 error_y=err, customdata=g[["method", "institution"]].values,
                                 hovertemplate="%{x}: <b>%{y:,.0f}</b><br>%{customdata[1]}<br>"
                                               "<i>%{customdata[0]}</i><extra>" + scope + "</extra>"))
    yrs = sorted(pop["survey_year"].unique())
    fig.update_xaxes(tickmode="array", tickvals=yrs, ticktext=[str(int(y)) for y in yrs])
    fig.update_yaxes(title="Estimated individuals", rangemode="tozero")
    return _layout(fig, 330, title)


def scatter(df: pd.DataFrame, x: str, y: str, colour: str, title: str) -> go.Figure:
    fig = go.Figure()
    for i, (k, g) in enumerate(df.groupby(colour)):
        fig.add_trace(go.Scatter(x=g[x], y=g[y], mode="markers", name=str(k),
                                 marker=dict(color=SERIES[i % len(SERIES)], size=7, opacity=0.75),
                                 hovertemplate=f"{x}: %{{x:.2f}}<br>{y}: %{{y:.2f}}<extra>{k}</extra>"))
    fig.update_xaxes(title=x)
    fig.update_yaxes(title=y)
    return _layout(fig, 340, title)


def hss_heatmap(scores: pd.DataFrame, value: str = "total_score", title="Weekly Habitat Stress Score") -> go.Figure:
    p = scores.pivot_table(index="name", columns="week_end", values=value)
    fig = go.Figure(go.Heatmap(
        z=p.values, x=p.columns, y=p.index, zmin=0, zmax=100 if value == "total_score" else 25,
        colorscale=[[0, T["green"]], [0.4, T["green"]], [0.4, T["yellow"]], [0.6, T["yellow"]],
                    [0.6, T["orange"]], [0.8, T["orange"]], [0.8, T["red"]], [1, T["red"]]]
        if value == "total_score" else [[0, T["card"]], [1, T["red"]]],
        hovertemplate="%{y}<br>Week ending %{x|%d %b %Y}<br>%{z:.1f}<extra></extra>"))
    return _layout(fig, 380, title, legend=False)


# ------------------------------------------------------------------ water charts
WATER_CAT_COLOURS = {"High availability": "#6FA3C7", "Moderate availability": "#6FAF83",
                     "Low availability": "#E5B65B", "Potential water stress": "#D95F59",
                     "Insufficient data": "#7D8C86"}


def rain_windows(cond: dict, title="Recent rainfall vs baseline") -> go.Figure:
    xs = ["30 days", "60 days", "90 days"]
    act = [cond.get(f"rain_{d}d_mm") for d in (30, 60, 90)]
    nor = [cond.get(f"rain_{d}d_normal") for d in (30, 60, 90)]
    dfc = [cond.get(f"deficit_{d}d_pct") for d in (30, 60, 90)]
    lbl = ["n/a" if v is None or v != v else (f"{-v:+.0f}%") for v in dfc]
    fig = go.Figure([
        go.Bar(x=xs, y=nor, name="Baseline normal", marker_color="#46524E",
               hovertemplate="%{x}: normal %{y:.0f} mm<extra></extra>"),
        go.Bar(x=xs, y=act, name="Observed", marker_color=T["blue"], text=lbl, textposition="outside",
               hovertemplate="%{x}: %{y:.0f} mm<extra>observed</extra>")])
    fig.update_layout(barmode="group")
    fig.update_yaxes(title="mm")
    return _layout(fig, 290, title)


def water_series(obs: pd.DataFrame, title="Water observations") -> go.Figure:
    fig = go.Figure()
    lv = obs[obs["metric"] == "water_level_m"]
    sp = obs[obs["metric"] == "water_spread_pct"]
    nw = obs[obs["metric"] == "ndwi"]
    if not sp.empty:
        fig.add_trace(go.Scatter(x=sp["obs_date"], y=sp["value"], name="Satellite water spread (%)", mode="lines+markers",
                                 line=dict(color=T["blue"], width=1.8), marker=dict(size=4), yaxis="y2",
                                 hovertemplate="%{x|%d %b %Y}: %{y:.0f}%<extra>SATELLITE</extra>"))
    if not nw.empty:
        fig.add_trace(go.Scatter(x=nw["obs_date"], y=nw["value"], name="Satellite NDWI", mode="lines+markers",
                                 line=dict(color=T["blue"], width=1.8, dash="dot"), yaxis="y2",
                                 hovertemplate="%{x|%d %b %Y}: %{y:.2f}<extra>SATELLITE</extra>"))
    if not lv.empty:
        fig.add_trace(go.Scatter(x=lv["obs_date"], y=lv["value"], name="Direct water level (m)", mode="lines",
                                 line=dict(color=T["green"], width=2.4),
                                 hovertemplate="%{x|%d %b %Y}: %{y:.2f} m<extra>DIRECT</extra>"))
    if not fig.data:
        fig.add_annotation(text="No direct or satellite water observations — weather proxy only",
                           showarrow=False, font=dict(color=T["muted"]))
    fig.update_layout(yaxis=dict(title="Water level (m)"),
                      yaxis2=dict(title="Spread % / NDWI", overlaying="y", side="right", showgrid=False))
    return _layout(fig, 300, title)


def ndvi_buffer(obs: pd.DataFrame, title="Vegetation around the water body (NDVI, 500 m)") -> go.Figure:
    d = obs[obs["metric"] == "ndvi_buffer"]
    fig = go.Figure(go.Scatter(x=d["obs_date"], y=d["value"], mode="lines+markers", line=dict(color=T["green"], width=2),
                               marker=dict(size=4), hovertemplate="%{x|%d %b %Y}: %{y:.3f}<extra>NDVI</extra>"))
    if d.empty:
        fig.add_annotation(text="No vegetation observations", showarrow=False, font=dict(color=T["muted"]))
    fig.update_yaxes(title="NDVI")
    return _layout(fig, 260, title, legend=False)


def priority_history(a: pd.DataFrame, title="Monitoring priority and availability (weekly)") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=a["week_end"], y=a["priority_score"], mode="lines", line=dict(color=T["muted"], width=1.5),
                             showlegend=False, hoverinfo="skip"))
    for cat, g in a.groupby("category"):
        fig.add_trace(go.Scatter(x=g["week_end"], y=g["priority_score"], mode="markers", name=cat,
                                 marker=dict(color=WATER_CAT_COLOURS.get(cat), size=9, line=dict(width=0)),
                                 customdata=g["evidence"],
                                 hovertemplate="%{x|%d %b %Y}<br>Priority %{y:.0f}<br>" + cat +
                                               " (%{customdata})<extra></extra>"))
    fig.update_yaxes(range=[0, 100], title="Priority score")
    return _layout(fig, 280, title)


def priority_breakdown(a: pd.DataFrame, n=12, title="What drives each priority score") -> go.Figure:
    d = a.head(n).iloc[::-1]
    fig = go.Figure()
    parts = [("p_water", "Water evidence", T["blue"]), ("p_rain", "Rainfall deficit", T["yellow"]),
             ("p_heat", "Heat", T["orange"]), ("p_veg", "Vegetation decline", T["green"]),
             ("p_fire", "Nearby fire", T["red"]), ("p_uncertainty", "Data uncertainty", "#8A9A94")]
    for col, lab, colour in parts:
        fig.add_trace(go.Bar(y=d["wb_id"] + " · " + d["reserve"], x=d[col], name=lab, orientation="h",
                             marker_color=colour, hovertemplate="%{y}: %{x:.1f} pts<extra>" + lab + "</extra>"))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(range=[0, 100], title="Priority points")
    return _layout(fig, 60 + 28 * len(d) + 80, title)


def seasonal_water(weather: pd.DataFrame, wobs: pd.DataFrame, title="Seasonal water availability pattern") -> go.Figure:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    w = weather.copy()
    w["m"], w["y"] = w["obs_date"].dt.month, w["obs_date"].dt.year
    rain = w.groupby(["y", "m"])["precip_mm"].sum().groupby("m").mean().reindex(range(1, 13))
    fig = go.Figure(go.Bar(x=months, y=rain.values, name="Mean monthly rainfall (mm)", marker_color="#46524E",
                           hovertemplate="%{x}: %{y:.0f} mm<extra>rainfall</extra>"))
    sp = wobs[wobs["metric"] == "water_spread_pct"]
    if not sp.empty:
        sm = sp.groupby(sp["obs_date"].dt.month)["value"].mean().reindex(range(1, 13))
        fig.add_trace(go.Scatter(x=months, y=sm.values, name="Mean satellite water spread (%)", yaxis="y2",
                                 mode="lines+markers", line=dict(color=T["blue"], width=2.4), connectgaps=True,
                                 hovertemplate="%{x}: %{y:.0f}%<extra>water spread</extra>"))
    fig.update_layout(yaxis=dict(title="mm"), yaxis2=dict(title="%", overlaying="y", side="right", showgrid=False,
                                                          range=[0, 100]))
    return _layout(fig, 300, title)
