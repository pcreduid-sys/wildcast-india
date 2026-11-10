"""Water Intelligence engine: rainfall windows, water-availability categories, monitoring
priorities, water-dependent species and reserve-specific insights.

Evidence hierarchy for each water body (best available is used, and always reported):
  1. DIRECT     - in-situ water-level measurements (gauge / field survey), <= 21 days old
  2. SATELLITE  - remote-sensing water spread (%) or NDWI, <= 32 days old
  3. WEATHER_PROXY - inferred from the reserve's rainfall and temperature anomalies (unverified)
  4. NONE       - Insufficient data
A water body is never described as dry. The lowest category is 'Potential water stress', and
proxy-based categories are explicitly unverified.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from processing.geospatial import distance_km

CATEGORIES = ["High availability", "Moderate availability", "Low availability", "Potential water stress",
              "Insufficient data"]
CATEGORY_COLOURS = {"High availability": "#6FA3C7", "Moderate availability": "#6FAF83",
                    "Low availability": "#E5B65B", "Potential water stress": "#D95F59",
                    "Insufficient data": "#7D8C86"}
EVIDENCE_LABELS = {"DIRECT": "Direct measurement", "SATELLITE": "Satellite observation",
                   "WEATHER_PROXY": "Weather-based proxy (unverified)", "NONE": "No usable evidence"}
BANDS = [(60, "Priority 1 — field verification recommended"), (40, "Priority 2 — verify soon"),
         (20, "Priority 3 — monitor"), (0, "Routine")]
MAX_AGE = {"DIRECT": 21, "SATELLITE": 32}
WEIGHTS = {"p_water": 35, "p_rain": 20, "p_heat": 10, "p_veg": 10, "p_fire": 5, "p_uncertainty": 20}


# ------------------------------------------------------------------ weather windows
def window_rain(p: pd.Series, end: pd.Timestamp, days: int, min_frac: float = 0.8):
    """(actual, normal, deficit%) for the `days`-day window ending `end`.
    Normal = mean of the same calendar window in earlier years (>= 2 complete years needed)."""
    win = p[(p.index > end - pd.Timedelta(days=days)) & (p.index <= end)].dropna()
    if len(win) < days * min_frac:
        return None, None, None
    actual = float(win.sum()) * days / len(win)
    normals = []
    for k in range(1, 30):
        e = end - pd.DateOffset(years=k)
        s = e - pd.Timedelta(days=days - 1)
        if s < p.index.min():
            break
        seg = p[(p.index >= s) & (p.index <= e)].dropna()
        if len(seg) >= days * min_frac:
            normals.append(float(seg.sum()) * days / len(seg))
    if len(normals) < 2:
        return round(actual, 1), None, None
    normal = float(np.mean(normals))
    deficit = (normal - actual) / normal * 100 if normal > 0 else None
    return round(actual, 1), round(normal, 1), None if deficit is None else round(deficit, 1)


def tmax_anomaly(weather: pd.DataFrame, end: pd.Timestamp, days: int = 30):
    w = weather.dropna(subset=["tmax_c"])
    cur = w[(w["obs_date"] > end - pd.Timedelta(days=days)) & (w["obs_date"] <= end)]
    base = w[w["obs_date"] < end - pd.Timedelta(days=365)]
    if len(cur) < days * 0.7 or base["obs_date"].dt.year.nunique() < 2:
        return None
    doys = set(cur["obs_date"].dt.dayofyear)
    bd = base["obs_date"].dt.dayofyear.to_numpy()
    near = np.zeros(len(base), bool)
    for d in doys:
        dd = np.abs(bd - d)
        near |= np.minimum(dd, 365 - dd) <= 3
    if near.sum() < 20:
        return None
    return round(float(cur["tmax_c"].mean() - base.loc[near, "tmax_c"].mean()), 2)


def reserve_conditions(weather: pd.DataFrame, end: pd.Timestamp) -> dict:
    p = weather.set_index("obs_date")["precip_mm"]
    out = {}
    for d in (30, 60, 90):
        a, n, dfc = window_rain(p, end, d) if not p.empty else (None, None, None)
        out.update({f"rain_{d}d_mm": a, f"rain_{d}d_normal": n, f"deficit_{d}d_pct": dfc})
    out["tmax_anomaly_30d"] = tmax_anomaly(weather, end) if not weather.empty else None
    return out


# ------------------------------------------------------------------ availability
def ratio_to_seasonal_norm(obs: pd.DataFrame, end: pd.Timestamp, max_age: int):
    """Latest value relative to the median of earlier same-season values (+/-45 days of year)."""
    o = obs[obs["obs_date"] <= end].sort_values("obs_date")
    if o.empty:
        return None, None
    last = o.iloc[-1]
    if (end - last["obs_date"]).days > max_age:
        return None, last["obs_date"]
    hist = o[o["obs_date"] < last["obs_date"] - pd.Timedelta(days=60)]
    doy = last["obs_date"].dayofyear
    d = np.abs(hist["obs_date"].dt.dayofyear.to_numpy() - doy)
    same = hist[np.minimum(d, 365 - d) <= 45]
    ref = same if len(same) >= 4 else (hist if len(hist) >= 8 else None)
    if ref is None:
        return None, last["obs_date"]
    med = float(ref["value"].median())
    if med <= 0:
        return None, last["obs_date"]
    return float(last["value"]) / med, last["obs_date"]


def proxy_ratio(cond: dict):
    """Weather-only availability proxy: rainfall relative to normal, penalised by heat."""
    r90 = None if cond.get("rain_90d_normal") in (None, 0) or cond.get("rain_90d_mm") is None \
        else cond["rain_90d_mm"] / cond["rain_90d_normal"]
    if r90 is None:
        return None
    r30 = None if cond.get("rain_30d_normal") in (None, 0) or cond.get("rain_30d_mm") is None \
        else cond["rain_30d_mm"] / cond["rain_30d_normal"]
    r = 0.75 * min(r90, 1.5) + 0.25 * min(r30 if r30 is not None else r90, 1.5)
    heat = cond.get("tmax_anomaly_30d") or 0
    return max(0.0, r - 0.05 * max(0.0, heat - 1.0))


def category_from_ratio(r) -> str:
    if r is None:
        return "Insufficient data"
    if r >= 0.9:
        return "High availability"
    if r >= 0.6:
        return "Moderate availability"
    if r >= 0.35:
        return "Low availability"
    return "Potential water stress"


def assess(direct: pd.DataFrame, sat: pd.DataFrame, cond: dict, end: pd.Timestamp):
    """Return (category, evidence, ratio, latest_direct_date, latest_satellite_date)."""
    r_d, d_last = ratio_to_seasonal_norm(direct, end, MAX_AGE["DIRECT"]) if not direct.empty else (None, None)
    r_s, s_last = ratio_to_seasonal_norm(sat, end, MAX_AGE["SATELLITE"]) if not sat.empty else (None, None)
    if r_d is not None:
        return category_from_ratio(r_d), "DIRECT", r_d, d_last, s_last
    if r_s is not None:
        return category_from_ratio(r_s), "SATELLITE", r_s, d_last, s_last
    r_p = proxy_ratio(cond)
    if r_p is not None:
        return category_from_ratio(r_p), "WEATHER_PROXY", r_p, d_last, s_last
    return "Insufficient data", "NONE", None, d_last, s_last


def priority(ratio, evidence: str, cond: dict, ndvi_change, fires: int, stale_days: int | None) -> dict:
    """Transparent monitoring-priority score (0-100). High = most in need of field verification."""
    def c(x):
        return float(min(1.0, max(0.0, x)))
    p = {
        "p_water": WEIGHTS["p_water"] * (c(1 - ratio) if ratio is not None else 0.5),
        "p_rain": WEIGHTS["p_rain"] * c((cond.get("deficit_90d_pct") or 0) / 60),
        "p_heat": WEIGHTS["p_heat"] * c((cond.get("tmax_anomaly_30d") or 0) / 4),
        "p_veg": WEIGHTS["p_veg"] * c(-(ndvi_change or 0) / 30),
        "p_fire": WEIGHTS["p_fire"] * c((fires or 0) / 5),
        "p_uncertainty": WEIGHTS["p_uncertainty"] * {"DIRECT": 0.0, "SATELLITE": 0.4, "WEATHER_PROXY": 0.8,
                                                     "NONE": 1.0}[evidence],
    }
    if evidence == "DIRECT" and stale_days and stale_days > 14:
        p["p_uncertainty"] += 4
    p = {k: round(v, 1) for k, v in p.items()}
    total = round(min(100.0, sum(p.values())), 1)
    band = next(label for lo, label in BANDS if total >= lo)
    return p | {"priority_score": total, "priority_band": band}


def assess_water_bodies(wbs: pd.DataFrame, wobs: pd.DataFrame, weather: pd.DataFrame, fires: pd.DataFrame,
                        week_ends: list[pd.Timestamp]) -> list[dict]:
    rows = []
    for pa, wb_pa in wbs.groupby("pa_id"):
        wx = weather[weather["pa_id"] == pa]
        fr = fires[fires["pa_id"] == pa] if not fires.empty else fires
        conds = {we: reserve_conditions(wx, we) for we in week_ends}
        for wb in wb_pa.itertuples():
            o = wobs[wobs["wb_id"] == wb.wb_id]
            direct = o[o["metric"] == "water_level_m"]
            sat = o[o["metric"].isin(["water_spread_pct", "ndwi"])]
            sat = sat[sat["metric"] == ("water_spread_pct" if (sat["metric"] == "water_spread_pct").any() else "ndwi")]
            if not sat.empty and sat["metric"].iloc[0] == "ndwi":
                sat = sat.assign(value=sat["value"] + 1)  # shift NDWI (-1..1) to a positive scale for ratios
            nd = o[o["metric"] == "ndvi_buffer"]
            near_fire = fr[distance_km(fr["latitude"].to_numpy(float), fr["longitude"].to_numpy(float),
                                       wb.latitude, wb.longitude) <= 5] if not fr.empty else fr
            for we in week_ends:
                cond = conds[we]
                cat, ev, ratio, d_last, s_last = assess(direct, sat, cond, we)
                ndv, ndv_chg = _ndvi_change(nd, we)
                nf = int(((near_fire["acq_date"] > we - pd.Timedelta(days=30)) & (near_fire["acq_date"] <= we)).sum()) \
                    if not near_fire.empty else 0
                stale = (we - d_last).days if d_last is not None else None
                rows.append({"wb_id": wb.wb_id, "week_end": str(we.date()), "category": cat, "evidence": ev,
                             "availability_ratio": None if ratio is None else round(ratio, 3),
                             "latest_direct_date": None if d_last is None else str(d_last.date()),
                             "latest_satellite_date": None if s_last is None else str(s_last.date()),
                             **cond, "ndvi_buffer": ndv, "ndvi_buffer_change_pct": ndv_chg, "fires_5km_30d": nf,
                             **priority(ratio, ev, cond, ndv_chg, nf, stale)})
    return rows


def _ndvi_change(nd: pd.DataFrame, end: pd.Timestamp):
    o = nd[nd["obs_date"] <= end].sort_values("obs_date")
    if o.empty or (end - o["obs_date"].iloc[-1]).days > 40:
        return None, None
    last = o.iloc[-1]
    base = o[o["obs_date"] < end - pd.Timedelta(days=365)]
    d = np.abs(base["obs_date"].dt.dayofyear.to_numpy() - last["obs_date"].dayofyear)
    same = base[np.minimum(d, 365 - d) <= 16]
    if same["obs_date"].dt.year.nunique() < 2:
        return round(float(last["value"]), 3), None
    bl = float(same["value"].mean())
    return round(float(last["value"]), 3), (round((last["value"] - bl) / bl * 100, 1) if bl > 0.05 else None)


# ------------------------------------------------------------------ water-dependent species
# (dependency, why it matters, indicators to watch)
_ELEPHANT = ("High", "Daily drinking and bathing; seasonal movements track water access.",
             ["Water availability", "Rainfall deficit", "Vegetation (NDVI)"])
_RHINO = ("High", "Depends on wetlands, wallows and floodplain grassland.",
          ["Wetland water spread", "Vegetation (NDVI)", "Rainfall"])
_HERBIVORE = ("Moderate", "Needs regular drinking water and green forage; concentrates near water in dry months.",
              ["Water availability", "Vegetation (NDVI)", "Rainfall deficit"])
_CARNIVORE = ("Indirect", "Large carnivores track prey, which concentrates around water in dry periods.",
              ["Water availability", "Prey (herbivore) records", "Fire activity"])
_WATERBIRD = ("High", "Feeds and breeds in wetlands; numbers shift with wetland extent and season.",
              ["Wetland water spread", "Rainfall", "Seasonal timing"])
_AQUATIC = ("High", "Lives in or depends directly on surface water.",
            ["Water availability", "Water level", "Temperature"])
_AMPHIBIAN = ("High", "Breeding requires standing water; sensitive to drying and heat.",
              ["Water availability", "Rainfall", "Temperature anomaly"])
SPECIES_TRAITS = {
    "Elephas maximus": _ELEPHANT, "Rhinoceros unicornis": _RHINO,
    "Panthera tigris": _CARNIVORE, "Panthera pardus": _CARNIVORE, "Panthera leo": _CARNIVORE,
    "Cuon alpinus": _CARNIVORE, "Bubalus arnee": ("High", "Wild water buffalo wallows daily and grazes wet grassland.",
                                                  ["Wetland water spread", "Vegetation (NDVI)"]),
    "Lutrogale perspicillata": _AQUATIC, "Aonyx cinereus": _AQUATIC, "Lutra lutra": _AQUATIC,
    "Melursus ursinus": ("Moderate", "Needs water within its range; dry-season foraging shifts towards water.",
                         ["Water availability", "Rainfall deficit"]),
    "Sus scrofa": ("Moderate", "Wallows and drinks regularly; concentrates near water in dry months.",
                   ["Water availability", "Vegetation (NDVI)"]),
}
FAMILY_TRAITS = {
    "Elephantidae": _ELEPHANT, "Rhinocerotidae": _RHINO, "Cervidae": _HERBIVORE, "Bovidae": _HERBIVORE,
    "Tragulidae": _HERBIVORE, "Felidae": _CARNIVORE, "Crocodylidae": _AQUATIC, "Gavialidae": _AQUATIC,
    "Mustelidae": ("Moderate", "Several species (otters) depend directly on water.", ["Water availability"]),
    "Anatidae": _WATERBIRD, "Ardeidae": _WATERBIRD, "Ciconiidae": _WATERBIRD, "Threskiornithidae": _WATERBIRD,
    "Rallidae": _WATERBIRD, "Phalacrocoracidae": _WATERBIRD, "Anhingidae": _WATERBIRD, "Jacanidae": _WATERBIRD,
    "Scolopacidae": _WATERBIRD, "Charadriidae": _WATERBIRD, "Laridae": _WATERBIRD, "Podicipedidae": _WATERBIRD,
    "Alcedinidae": _WATERBIRD, "Pelecanidae": _WATERBIRD, "Recurvirostridae": _WATERBIRD, "Gruidae": _WATERBIRD,
    "Geoemydidae": _AQUATIC, "Trionychidae": _AQUATIC, "Homalopsidae": _AQUATIC,
}
GROUP_TRAITS = {"Amphibians": _AMPHIBIAN, "Fish": _AQUATIC}


def water_trait(scientific_name: str, family=None, group=None):
    t = SPECIES_TRAITS.get(scientific_name) or FAMILY_TRAITS.get(family or "") or GROUP_TRAITS.get(group or "")
    if t is None:
        return None
    return {"dependency": t[0], "why": t[1], "indicators": ", ".join(t[2])}


def water_dependent_species(assoc: pd.DataFrame, species: pd.DataFrame, obs: pd.DataFrame,
                            as_of: pd.Timestamp) -> pd.DataFrame:
    """Documented species in a reserve that are ecologically relevant to water availability."""
    sp = species.set_index("scientific_name")
    rows = []
    recent = obs[obs["obs_date"] >= as_of - pd.DateOffset(years=5)] if not obs.empty else obs
    for r in assoc.itertuples():
        fam = sp["family"].get(r.scientific_name) if r.scientific_name in sp.index else None
        grp = sp["taxon_group"].get(r.scientific_name) if r.scientific_name in sp.index else None
        t = water_trait(r.scientific_name, fam, grp)
        if not t:
            continue
        n5 = int((recent["scientific_name"] == r.scientific_name).sum()) if not recent.empty else 0
        gaps = []
        if r.n_records == 0:
            gaps.append("no occurrence records retrieved")
        elif n5 == 0:
            gaps.append("no records in the last 5 years")
        if r.sources == "Official estimate" or r.n_records < 5:
            gaps.append("too few records for trend analysis")
        rows.append({"scientific_name": r.scientific_name, "common_name": sp["common_name"].get(r.scientific_name)
                     if r.scientific_name in sp.index else None, "taxon_group": grp,
                     "iucn_category": sp["iucn_category"].get(r.scientific_name) if r.scientific_name in sp.index else None,
                     **t, "records_total": int(r.n_records), "records_5y": n5,
                     "data_gaps": "; ".join(gaps) or "—"})
    out = pd.DataFrame(rows)
    if not out.empty:
        out["_o"] = out["dependency"].map({"High": 0, "Moderate": 1, "Indirect": 2})
        out = out.sort_values(["_o", "records_total"], ascending=[True, False]).drop(columns="_o")
    return out


# ------------------------------------------------------------------ insights
def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _fmt(v, f):
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f.format(v)


def reserve_insights(name: str, cond: dict, hss_row: dict, wa: pd.DataFrame, dep: pd.DataFrame,
                     sources: dict) -> dict:
    """Reserve-specific insight text, separated into observed / implications / recommendations / limitations."""
    obs, imp, rec, lim = [], [], [], []
    d90, d30 = cond.get("deficit_90d_pct"), cond.get("deficit_30d_pct")
    t = cond.get("tmax_anomaly_30d")
    ndvi = hss_row.get("ndvi_change_pct")
    fires = hss_row.get("fire_count_7d")
    if d90 is not None:
        word = "below" if d90 > 0 else "above"
        obs.append(f"{name} received {_fmt(cond.get('rain_90d_mm'), '{:.0f}')} mm of rain in the last 90 days, "
                   f"{abs(d90):.0f}% {word} its baseline of {_fmt(cond.get('rain_90d_normal'), '{:.0f}')} mm"
                   + (f"; the last 30 days were {abs(d30):.0f}% {'below' if d30 > 0 else 'above'} normal."
                      if d30 is not None else "."))
    if t is not None:
        obs.append(f"Mean maximum temperature over 30 days was {t:+.1f} °C relative to the seasonal baseline.")
    if ndvi is not None:
        obs.append(f"Reserve-level NDVI is {ndvi:+.0f}% relative to its seasonal baseline.")
    if fires is not None and fires == fires:
        obs.append(f"{int(fires)} satellite fire detection(s) inside the reserve footprint in the past 7 days.")
    n = len(wa)
    if n:
        cats = wa["category"].value_counts()
        ev = wa["evidence"].value_counts()
        obs.append(f"{_plural(n, 'mapped water body', 'mapped water bodies')}: " + ", ".join(f"{v} {k.lower()}" for k, v in cats.items()) +
                   f". Evidence: {ev.get('DIRECT', 0)} direct, {ev.get('SATELLITE', 0)} satellite, "
                   f"{ev.get('WEATHER_PROXY', 0)} weather-proxy only.")

    dry = (d90 or 0) >= 25
    hot = (t or 0) >= 1.5
    green_loss = (ndvi or 0) <= -10
    stressed = wa[wa["category"].isin(["Potential water stress", "Low availability"])] if n else wa
    high_dep = dep[dep["dependency"] == "High"] if not dep.empty else dep
    names = lambda d: ", ".join((d["common_name"].fillna(d["scientific_name"])).head(4))  # noqa: E731
    if dry and hot:
        imp.append("A prolonged rainfall deficit combined with above-normal temperatures may increase pressure on "
                   "seasonal surface water and accelerate drying of shallow water points.")
    elif dry:
        imp.append("The rainfall deficit may reduce recharge of seasonal water bodies ahead of the dry season.")
    elif (d90 or 0) <= -20:
        imp.append("Above-normal rainfall suggests surface-water recharge is unlikely to be limiting at present.")
    if green_loss:
        imp.append("Reduced vegetation greenness may lower forage quality for grazing and browsing herbivores, "
                   "which can increase reliance on remaining green patches near water.")
    if len(stressed):
        imp.append(f"{_plural(len(stressed), 'water body shows', 'water bodies show')} low availability or potential "
                   "water stress; animals "
                   "may concentrate at the remaining water, which can raise local grazing, disturbance and "
                   "human-wildlife interaction pressure.")
    pressure = dry or hot or green_loss or len(stressed) > 0
    if not dep.empty:
        sci = set(dep["scientific_name"])
        verb = "may" if pressure else "would"
        if "Elephas maximus" in sci:
            imp.append(f"Asian elephants are documented here; under drier conditions they {verb} concentrate around "
                       "perennial and managed water, increasing use of those sites and nearby forage.")
        if "Rhinoceros unicornis" in sci:
            imp.append("Greater one-horned rhinoceros depend on wetland and floodplain-grassland condition; "
                       + ("current wetland indicators are favourable." if not pressure else
                          "reduced wetland extent or grass greenness would be relevant to their habitat use."))
        carn = dep[dep["dependency"] == "Indirect"]
        if len(carn):
            imp.append(f"{names(carn)} {'tracks' if len(carn) == 1 else 'track'} prey; if herbivores aggregate at fewer water points, predator activity "
                       f"around those sites {verb} change.")
        wb_birds = dep[(dep["taxon_group"] == "Birds") & (dep["dependency"] == "High")]
        if len(wb_birds):
            imp.append(f"Waterbirds documented here ({names(wb_birds)}) respond to wetland extent and seasonal "
                       "flooding; their records can help indicate wetland condition.")
        aq = dep[dep["taxon_group"].isin(["Fish", "Amphibians"]) | dep["why"].str.startswith("Lives in or depends")]
        if len(aq) and pressure:
            imp.append(f"Aquatic and semi-aquatic species ({names(aq)}) are the most directly exposed to shrinking "
                       "or warming water bodies.")
    if not imp:
        imp.append("Current indicators do not point to unusual water-related pressure.")

    top = wa.sort_values("priority_score", ascending=False).head(3) if n else wa
    for r in top.itertuples():
        if r.priority_score >= 40:
            rec.append(f"Field-verify {r.wb_id} ({r.wb_type.lower()}): priority {r.priority_score:.0f}, "
                       f"{r.category.lower()} based on {EVIDENCE_LABELS[r.evidence].lower()}.")
    proxy_only = wa[wa["evidence"].isin(["WEATHER_PROXY", "NONE"])] if n else wa
    if len(proxy_only):
        rec.append(f"Install water-level gauges or schedule photo-point checks at {_plural(len(proxy_only), 'water body', 'water bodies')} "
                   f"({', '.join(proxy_only['wb_id'])}) that currently {'relies' if len(proxy_only) == 1 else 'rely'} "
                   "on weather proxies only.")
    terr = dep[dep["taxon_group"].isin(["Mammals", "Birds", "Reptiles"])] if not dep.empty else dep
    aqua = dep[dep["taxon_group"].isin(["Fish", "Amphibians"])] if not dep.empty else dep
    if len(terr):
        rec.append(f"Run camera traps or sign surveys at the highest-priority water points to record use by {names(terr)}.")
    if len(aqua) and (dry or len(stressed)):
        rec.append(f"Add water-quality checks and amphibian/fish surveys where {names(aqua)} are documented.")
    if dep.empty or (dep["records_total"] == 0).all():
        rec.append("Fetch GBIF/iNaturalist records (Wildlife Intelligence) to identify water-dependent species "
                   "documented in this reserve.")
    if not rec:
        rec.append("Continue routine monitoring; no water body currently exceeds the verification threshold.")

    if sources.get("weather_simulated"):
        lim.append("Rainfall, temperature and NDVI shown are SIMULATED demonstration data.")
    if n and (wa["location_basis"] == "ILLUSTRATIVE").all():
        lim.append("All water-body locations and water measurements are SIMULATED illustrations, not verified "
                   "real-world sites. Upload surveyed water points to replace them.")
    if n and not (wa["evidence"] == "DIRECT").any():
        lim.append("No current direct water-level measurements: actual water availability remains unverified.")
    lim.append("Weather and satellite indicators cannot establish population decline, mortality or migration; "
               "occurrence records reflect observation effort, not abundance.")
    return {"observed": obs, "implications": imp, "recommendations": rec, "limitations": lim}
