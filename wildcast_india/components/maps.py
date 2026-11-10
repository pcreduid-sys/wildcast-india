"""Folium map builders shared by all pages."""
from __future__ import annotations

import html

import folium
import pandas as pd
from folium.plugins import Fullscreen, HeatMap

from config.settings import THEME as T, category_for
from processing.geospatial import reserve_geojson

DARK = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
LABELS = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
ESRI_ATTR = "Tiles &copy; Esri &mdash; Esri, HERE, Garmin, &copy; OpenStreetMap contributors"
INDIA_CENTRE, INDIA_ZOOM = (22.6, 80.5), 5


def _base(location=INDIA_CENTRE, zoom=INDIA_ZOOM) -> folium.Map:
    m = folium.Map(location=location, zoom_start=zoom, tiles=None, control_scale=True,
                   prefer_canvas=True, min_zoom=4)
    folium.TileLayer(DARK, attr=ESRI_ATTR, name="Dark basemap", max_zoom=16).add_to(m)
    folium.TileLayer("Esri.WorldImagery", name="Satellite imagery", show=False, overlay=False).add_to(m)
    folium.TileLayer(LABELS, attr=ESRI_ATTR, name="Place labels", overlay=True, max_zoom=16).add_to(m)
    Fullscreen(position="topleft").add_to(m)
    return m


def _footprint(m, row, colour, weight=1.5, fill=0.18):
    feat = reserve_geojson(row)
    verified = feat["properties"]["verified"]
    folium.GeoJson(
        feat, name=f"{row['name']} footprint",
        style_function=lambda _f, c=colour, v=verified: {
            "color": c, "weight": weight, "fillColor": c, "fillOpacity": fill,
            "dashArray": None if v else "5,5"},
        tooltip=f"{row['name']} — {'verified boundary (uploaded)' if verified else 'approximate footprint (area-equivalent circle)'}",
    ).add_to(m)


def national_map(latest: pd.DataFrame, reserves: pd.DataFrame, fires: pd.DataFrame | None = None) -> folium.Map:
    m = _base()
    res = reserves.set_index("pa_id")
    for r in latest.itertuples():
        label, colour = category_for(r.total_score)
        row = res.loc[r.pa_id].to_dict() | {"pa_id": r.pa_id}
        _footprint(m, row, colour)
        prov = " · provisional" if r.provisional else ""
        popup = f"""<div style="font-family:sans-serif;min-width:190px">
            <b style="font-size:14px">{html.escape(r.name)}</b><br><span style="color:#666">{r.state}</span><hr style="margin:4px 0">
            HSS <b>{r.total_score:.0f}</b>/100 — <b style="color:{colour}">{label}</b>{prov}<br>
            Heat {_fmt(r.heat_score)} · Drought {_fmt(r.drought_score)}<br>
            Vegetation {_fmt(r.vegetation_score)} · Fire {_fmt(r.fire_score)}<br>
            Completeness {r.completeness:.0%}</div>"""
        folium.CircleMarker(
            [r.latitude, r.longitude], radius=9 + (r.total_score or 0) / 10, color="#0B1210", weight=1.5,
            fill=True, fill_color=colour, fill_opacity=0.95,
            tooltip=f"{r.name}: {r.total_score:.0f} ({label})", popup=folium.Popup(popup, max_width=260),
        ).add_to(m)
    if fires is not None and not fires.empty:
        fg = folium.FeatureGroup(name="Fire detections (7 days)", show=True)
        for f in fires.itertuples():
            folium.CircleMarker([f.latitude, f.longitude], radius=2.5, color=T["red"], weight=0,
                                fill=True, fill_opacity=0.8).add_to(fg)
        fg.add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    _legend(m)
    return m


def reserve_map(row: dict, fires: pd.DataFrame, colour: str) -> folium.Map:
    m = _base((row["latitude"], row["longitude"]), 10)
    _footprint(m, row, colour, weight=2.5, fill=0.12)
    folium.Marker([row["latitude"], row["longitude"]], tooltip=row["name"],
                  icon=folium.Icon(color="green", icon="tree-conifer")).add_to(m)
    _fire_points(m, fires)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def fire_map(fires: pd.DataFrame, reserves: pd.DataFrame, heat: bool = False) -> folium.Map:
    m = _base()
    for _, r in reserves.iterrows():
        _footprint(m, r.to_dict(), T["green"], weight=1.2, fill=0.08)
    if heat and not fires.empty:
        HeatMap(fires[["latitude", "longitude"]].values.tolist(), radius=12, blur=14, name="Fire density",
                gradient={0.3: T["yellow"], 0.6: T["orange"], 1: T["red"]}).add_to(m)
    else:
        _fire_points(m, fires)
    if not fires.empty:
        m.fit_bounds([[fires.latitude.min() - 0.3, fires.longitude.min() - 0.3],
                      [fires.latitude.max() + 0.3, fires.longitude.max() + 0.3]])
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def _fire_points(m, fires: pd.DataFrame, cap: int = 3000) -> None:
    fg = folium.FeatureGroup(name="Fire detections")
    for f in fires.head(cap).itertuples():
        c = T["red"] if f.inside_boundary else T["yellow"]
        folium.CircleMarker(
            [f.latitude, f.longitude], radius=3 + min(6, (f.frp or 0) / 10), color=c, weight=0.5,
            fill=True, fill_opacity=0.85,
            tooltip=(f"{pd.Timestamp(f.acq_date):%d %b %Y} {f.acq_time} · {f.satellite} · "
                     f"FRP {f.frp or 0:.1f} MW · conf {f.confidence} · "
                     f"{'inside' if f.inside_boundary else 'outside'} footprint · {f.source_type}"),
        ).add_to(fg)
    fg.add_to(m)


def _fmt(v):
    return "n/a" if v is None or v != v else f"{v:.1f}"


def _legend(m):
    items = "".join(f'<div><span style="background:{c};width:10px;height:10px;display:inline-block;'
                    f'border-radius:50%;margin-right:6px"></span>{l}</div>'
                    for l, c in [("Low (0–39)", T["green"]), ("Moderate (40–59)", T["yellow"]),
                                 ("High (60–79)", T["orange"]), ("Severe (80–100)", T["red"])])
    legend = f"""<div style="position:absolute;bottom:22px;right:12px;z-index:9999;background:{T['card']}ee;
        color:{T['text']};padding:8px 12px;border-radius:8px;font:12px sans-serif;border:1px solid {T['border']}">
        <b>Habitat Stress</b>{items}<div style="color:{T['muted']};margin-top:4px">Dashed = approximate footprint</div></div>"""
    m.get_root().html.add_child(folium.Element(legend))


def occurrence_map(obs: pd.DataFrame, reserves: pd.DataFrame, cap: int = 4000) -> folium.Map:
    """Clustered wildlife occurrence map. Generalised (sensitive) locations are drawn as grid cells."""
    from folium.plugins import MarkerCluster
    from components.charts import GROUP_COLOURS
    if not obs.empty and obs["pa_id"].nunique() == 1:
        r0 = reserves.set_index("pa_id").loc[obs["pa_id"].iloc[0]]
        m = _base((r0["latitude"], r0["longitude"]), 10)
    else:
        m = _base()
    for _, r in reserves.iterrows():
        _footprint(m, r.to_dict(), T["green"], weight=1.2, fill=0.06)
    cluster = MarkerCluster(name="Occurrence records", options={"maxClusterRadius": 40}).add_to(m)
    cells = folium.FeatureGroup(name="Generalised locations (sensitive species)").add_to(m)
    for o in obs.head(cap).itertuples():
        colour = GROUP_COLOURS.get(o.taxon_group, T["muted"])
        name = html.escape(str(o.common_name or o.scientific_name))
        date = "undated" if pd.isna(o.obs_date) else f"{pd.Timestamp(o.obs_date):%d %b %Y}"
        popup = f"""<div style="font-family:sans-serif;min-width:220px;font-size:12px">
            <b style="font-size:13px">{name}</b><br><i>{html.escape(o.scientific_name)}</i><hr style="margin:4px 0">
            <b>Date:</b> {date}<br><b>Reserve:</b> {html.escape(str(o.reserve))}<br>
            <b>Source:</b> {o.source} · {o.source_type}<br><b>Record ID:</b> {html.escape(str(o.record_id))}<br>
            <b>Verification:</b> {html.escape(str(o.verification_status or 'n/a'))}<br>
            <b>IUCN:</b> {o.iucn_category or 'n/a'}<br>
            {'<b style="color:#c0392b">Location generalised to ~11 km grid</b><br>' if o.coords_generalised else ''}
            {f'<a href="{o.record_url}" target="_blank">Open original record ↗</a>' if isinstance(o.record_url, str) else ''}</div>"""
        if o.coords_generalised:
            h = 0.05
            folium.Rectangle([[o.latitude - h, o.longitude - h], [o.latitude + h, o.longitude + h]], color=colour,
                             weight=1, fill=True, fill_opacity=0.15, dash_array="4,4",
                             tooltip=f"{name} (generalised)", popup=folium.Popup(popup, max_width=280)).add_to(cells)
        else:
            folium.CircleMarker([o.latitude, o.longitude], radius=5, color=colour, weight=1, fill=True,
                                fill_opacity=0.9, tooltip=f"{name} · {date}",
                                popup=folium.Popup(popup, max_width=280)).add_to(cluster)
    folium.LayerControl(collapsed=True).add_to(m)
    return m


def water_map(wa: pd.DataFrame, reserves: pd.DataFrame, selected: str | None = None) -> folium.Map:
    """Water bodies coloured by availability category; marker style shows the evidence type.
    Tooltips start with the water-body ID so a click can open its profile."""
    from components.charts import WATER_CAT_COLOURS
    if not wa.empty and wa["pa_id"].nunique() == 1:
        r0 = reserves.set_index("pa_id").loc[wa["pa_id"].iloc[0]]
        m = _base((r0["latitude"], r0["longitude"]), 10)
    else:
        m = _base()
    for _, r in reserves.iterrows():
        _footprint(m, r.to_dict(), T["green"], weight=1.2, fill=0.05)
    style = {"DIRECT": dict(weight=3, fill_opacity=0.95, dash_array=None),
             "SATELLITE": dict(weight=1.5, fill_opacity=0.8, dash_array=None),
             "WEATHER_PROXY": dict(weight=2, fill_opacity=0.25, dash_array="3,3"),
             "NONE": dict(weight=1, fill_opacity=0.1, dash_array="2,4")}
    for w in wa.itertuples():
        c = WATER_CAT_COLOURS.get(w.category, T["muted"])
        st_ = style[w.evidence]
        sel = w.wb_id == selected
        folium.CircleMarker(
            [w.latitude, w.longitude], radius=11 if sel else 8, color="#FFFFFF" if sel else c, weight=st_["weight"],
            fill=True, fill_color=c, fill_opacity=st_["fill_opacity"], dash_array=st_["dash_array"],
            tooltip=f"{w.wb_id} · {w.wb_type} · {w.category} · priority {w.priority_score:.0f} · "
                    f"{w.evidence.replace('_', ' ').lower()} · {w.source_type}",
        ).add_to(m)
    items = "".join(f'<div><span style="background:{c};width:10px;height:10px;display:inline-block;border-radius:50%;'
                    f'margin-right:6px"></span>{k}</div>' for k, c in WATER_CAT_COLOURS.items())
    legend = f"""<div style="position:absolute;bottom:22px;right:12px;z-index:9999;background:{T['card']}ee;
        color:{T['text']};padding:8px 12px;border-radius:8px;font:12px sans-serif;border:1px solid {T['border']}">
        <b>Water availability</b>{items}<div style="color:{T['muted']};margin-top:4px">Thick ring = direct measurement<br>
        Solid = satellite · Dashed = weather proxy</div></div>"""
    m.get_root().html.add_child(folium.Element(legend))
    folium.LayerControl(collapsed=True).add_to(m)
    return m
