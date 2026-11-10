"""Geometry helpers: reserve footprints and point-in-reserve assignment.

Boundaries: the app ships WITHOUT official boundary polygons (we do not invent them).
Until a verified boundary GeoJSON is uploaded on the Admin page, each reserve is
represented by an *approximate circular footprint* centred on its published
coordinates with an area equal to its published area. This is clearly labelled
APPROXIMATE_BUFFER everywhere it is used.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon, shape, mapping

KM_PER_DEG_LAT = 110.574


def km_per_deg_lon(lat: float) -> float:
    return 111.320 * math.cos(math.radians(lat))


def buffer_radius_km(area_km2: float) -> float:
    return math.sqrt(max(area_km2 or 100.0, 1.0) / math.pi)


def circle_polygon(lat: float, lon: float, radius_km: float, n: int = 72) -> Polygon:
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xs = lon + (radius_km * np.cos(ang)) / km_per_deg_lon(lat)
    ys = lat + (radius_km * np.sin(ang)) / KM_PER_DEG_LAT
    return Polygon(zip(xs, ys))


def reserve_geometry(row) -> tuple:
    """Return (shapely geometry, is_verified_boundary)."""
    gj = row.get("boundary_geojson") if hasattr(row, "get") else getattr(row, "boundary_geojson", None)
    if isinstance(gj, str) and gj.strip():
        try:
            return shape(json.loads(gj)), True
        except (ValueError, TypeError, KeyError):
            pass
    return circle_polygon(row["latitude"], row["longitude"], buffer_radius_km(row["area_km2"])), False


def reserve_geojson(row) -> dict:
    geom, verified = reserve_geometry(row)
    return {"type": "Feature", "geometry": mapping(geom),
            "properties": {"pa_id": row["pa_id"], "name": row["name"], "verified": verified}}


def distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arcsin(np.sqrt(a))


def assign_fires(fires: pd.DataFrame, reserves: pd.DataFrame, near_km: float = 25.0) -> pd.DataFrame:
    """Attach pa_id (nearest reserve within near_km of its footprint) and inside_boundary flag."""
    fires = fires.copy()
    fires["pa_id"] = None
    fires["inside_boundary"] = 0
    if fires.empty:
        return fires
    lats, lons = fires["latitude"].to_numpy(float), fires["longitude"].to_numpy(float)
    best_d = np.full(len(fires), np.inf)
    for _, r in reserves.iterrows():
        g, _ = reserve_geometry(r)
        pa_id, clat, clon = r["pa_id"], r["latitude"], r["longitude"]
        d = distance_km(lats, lons, clat, clon) - buffer_radius_km(r["area_km2"])
        inside = shapely.contains_xy(g, lons, lats)
        d = np.where(inside, -1.0, d)
        better = d < best_d
        best_d = np.where(better, d, best_d)
        fires.loc[better, "pa_id"] = pa_id
        fires.loc[better, "inside_boundary"] = inside[better].astype(int)
    fires.loc[best_d > near_km, "pa_id"] = None
    return fires


def bbox_for(reserves: pd.DataFrame, pad_km: float = 30.0) -> list[tuple[str, str]]:
    """Per-reserve 'west,south,east,north' bounding boxes for API queries."""
    out = []
    for _, r in reserves.iterrows():
        rad = buffer_radius_km(r["area_km2"]) + pad_km
        dlon, dlat = rad / km_per_deg_lon(r["latitude"]), rad / KM_PER_DEG_LAT
        out.append((r["pa_id"], f"{r['longitude']-dlon:.3f},{r['latitude']-dlat:.3f},"
                                f"{r['longitude']+dlon:.3f},{r['latitude']+dlat:.3f}"))
    return out


def footprint_wkt(row, max_vertices: int = 60) -> str:
    """Counter-clockwise WKT of a reserve footprint, simplified for API geometry filters (e.g. GBIF)."""
    from shapely.geometry.polygon import orient
    geom, _ = reserve_geometry(row)
    tol = 0.002
    while True:
        g = geom.simplify(tol, preserve_topology=True)
        n = sum(len(p.exterior.coords) for p in getattr(g, "geoms", [g]))
        if n <= max_vertices or tol > 0.2:
            break
        tol *= 2
    if g.geom_type == "MultiPolygon":
        from shapely.geometry import MultiPolygon
        g = MultiPolygon([orient(p, 1.0) for p in g.geoms])
    else:
        g = orient(g, 1.0)
    return shapely.to_wkt(g, rounding_precision=4)


def footprint_bbox(row) -> tuple[float, float, float, float]:
    """(south, west, north, east) bounds of a reserve footprint."""
    geom, _ = reserve_geometry(row)
    w, s, e, n = geom.bounds
    return s, w, n, e
