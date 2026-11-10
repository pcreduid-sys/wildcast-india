"""Deterministic demonstration dataset (labelled SIMULATED).

Generated ONCE on first start with a fixed seed and persisted in SQLite; it is never
regenerated on page loads. Climate parameters are coarse, plausible values for each
region and are NOT observations. Live/uploaded data replaces simulated rows for the
same reserve and date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import settings
from database import db
from processing.geospatial import assign_fires, buffer_radius_km, km_per_deg_lon, KM_PER_DEG_LAT

# annual rain (mm), mean Tmax (C), Tmax seasonal amplitude, NE-monsoon share, pre-monsoon share,
# NDVI mean, NDVI seasonal amplitude
CLIMATE = {
    "BAN": (1100, 29.5, 3.5, 0.30, 0.10, 0.58, 0.14),
    "NAG": (1500, 29.0, 3.5, 0.20, 0.10, 0.66, 0.12),
    "COR": (1550, 29.0, 8.5, 0.00, 0.05, 0.62, 0.12),
    "RAN": (800, 33.0, 7.5, 0.00, 0.02, 0.38, 0.16),
    "SIM": (1650, 31.5, 5.0, 0.05, 0.10, 0.64, 0.12),
    "KAZ": (2200, 29.5, 4.5, 0.05, 0.25, 0.60, 0.10),
    "KAN": (1500, 31.5, 7.0, 0.00, 0.05, 0.60, 0.15),
    "GIR": (950, 33.0, 4.5, 0.02, 0.02, 0.45, 0.18),
    "PER": (2400, 28.0, 2.5, 0.30, 0.15, 0.74, 0.06),
    "SUN": (1750, 31.0, 3.5, 0.08, 0.10, 0.55, 0.08),
}
FIRE_RATE = {"high": 5.0, "medium": 2.0, "low": 0.5}  # peak-season detections/day

# Scenario applied to the most recent ~100 days so the demo shows a spread of conditions.
# (rain multiplier, Tmax offset C, NDVI decline fraction, extra fires in last 7 days)
RECENT_SCENARIO = {
    "GIR": (0.28, 4.8, 0.34, 26),
    "RAN": (0.45, 2.4, 0.18, 4),
    "BAN": (0.55, 1.6, 0.12, 7),
    "SIM": (0.85, 1.0, 0.05, 9),
    "KAN": (0.60, 2.8, 0.14, 6),
    "COR": (1.00, 0.6, 0.00, 2),
    "NAG": (0.95, 0.4, 0.02, 1),
    "KAZ": (1.15, 0.0, 0.00, 0),
    "PER": (1.05, -0.3, 0.00, 0),
    "SUN": (1.00, 0.2, 0.00, 0),
}
NDVI_GAP_RESERVES = {"SUN"}  # recent NDVI withheld (cloud cover) to demonstrate provisional scores


def _gauss(doy, centre, width):
    d = np.minimum(np.abs(doy - centre), 365 - np.abs(doy - centre))
    return np.exp(-0.5 * (d / width) ** 2)


def _rain_profile(doy, ne_share, pre_share):
    sw = _gauss(doy, 205, 32)
    ne = _gauss(doy, 300, 22)
    pre = _gauss(doy, 125, 20)
    prof = (1 - ne_share - pre_share) * sw / sw.mean() + ne_share * ne / ne.mean() \
        + pre_share * pre / pre.mean()
    return prof / 365.0  # fraction of annual total per day (on average)


def generate(reserves: pd.DataFrame, end: pd.Timestamp | None = None):
    end = (end or pd.Timestamp.today()).normalize()
    start = end - pd.DateOffset(years=settings.DEMO_YEARS_HISTORY)
    dates = pd.date_range(start, end, freq="D")
    doy = dates.dayofyear.to_numpy()
    recent = (end - dates).days < 100
    weather, ndvi, fires = [], [], []

    for i, r in enumerate(reserves.sort_values("pa_id").itertuples()):
        rng = np.random.default_rng(settings.DEMO_SEED + i)
        rain_mm, tmax_mu, amp, ne, pre, nd_mu, nd_amp = CLIMATE[r.pa_id]
        rain_mult, t_off, nd_decl, extra_fires = RECENT_SCENARIO[r.pa_id]

        prof = _rain_profile(doy, ne, pre)
        exp_rain = rain_mm * prof * np.where(recent, rain_mult, 1.0)
        year_factor = pd.Series(rng.normal(1.0, 0.12, dates.year.nunique()),
                                index=sorted(dates.year.unique()))
        exp_rain = exp_rain * year_factor.reindex(dates.year).to_numpy()
        p_wet = np.clip(exp_rain / 12.0, 0.02, 0.9)
        wet = rng.random(len(dates)) < p_wet
        amount = rng.gamma(1.4, (exp_rain / p_wet) / 1.4)
        precip = np.round(np.where(wet, amount, 0.0), 1)

        wetness = prof / prof.max()
        seasonal = amp * np.cos(2 * np.pi * (doy - 130) / 365.0) - 4.0 * wetness
        noise = np.zeros(len(dates))
        e = rng.normal(0, 1.1, len(dates))
        for k in range(1, len(dates)):
            noise[k] = 0.7 * noise[k - 1] + e[k]
        ramp = np.clip(1 - (end - dates).days / 100.0, 0, 1)  # scenario offset ramps in
        tmax = np.round(tmax_mu + seasonal + noise + t_off * ramp, 1)
        tmean = np.round(tmax - 7.5 + 2.0 * wetness + rng.normal(0, 0.5, len(dates)), 1)
        weather.append(pd.DataFrame({"pa_id": r.pa_id, "obs_date": dates, "tmax_c": tmax,
                                     "tmean_c": tmean, "precip_mm": precip}))

        # NDVI: 16-day composites (MODIS-style), lagging the rainy season by ~40 days
        comp = [d for d in dates if (d.dayofyear - 1) % 16 == 0]
        cdoy = np.array([d.dayofyear for d in comp])
        lagged = _rain_profile((cdoy - 40) % 365 + 1, ne, pre)
        lagged = (lagged - lagged.min()) / (lagged.max() - lagged.min())
        nd = nd_mu - nd_amp / 2 + nd_amp * lagged + rng.normal(0, 0.02, len(comp))
        age = np.array([(end - d).days for d in comp])
        nd = nd * (1 - nd_decl * np.clip(1 - age / 100.0, 0, 1))
        keep = ~((age < 45) & (r.pa_id in NDVI_GAP_RESERVES))
        ndvi.append(pd.DataFrame({"pa_id": r.pa_id, "obs_date": np.array(comp)[keep],
                                  "ndvi": np.round(np.clip(nd, -1, 1), 3)[keep]}))

        # Fires: Poisson by season (Feb-May peak) scaled by fire profile and dryness
        season = _gauss(doy, 95, 30) + 0.08
        lam = FIRE_RATE[r.fire_profile] * season * np.where(recent, 1.0 / max(rain_mult, 0.4), 1.0)
        counts = rng.poisson(lam)
        counts[-7:] += rng.multinomial(extra_fires, [1 / 7] * 7)
        rad = buffer_radius_km(r.area_km2) * 1.25
        c = int(counts.sum())
        rr = rad * np.sqrt(rng.random(c))
        th = rng.random(c) * 2 * np.pi
        sat = rng.choice(["N", "N20", "Aqua", "Terra"], c)
        hours = rng.choice([1, 2, 7, 8, 13, 14, 19, 20], c)
        mins = rng.integers(0, 60, c)
        fires.append(pd.DataFrame({
            "latitude": np.round(r.latitude + rr * np.sin(th) / KM_PER_DEG_LAT, 4),
            "longitude": np.round(r.longitude + rr * np.cos(th) / km_per_deg_lon(r.latitude), 4),
            "acq_date": np.repeat(dates.to_numpy(), counts),
            "acq_time": [f"{h:02d}{m:02d}" for h, m in zip(hours, mins)],
            "satellite": sat,
            "instrument": np.where(np.isin(sat, ["Aqua", "Terra"]), "MODIS", "VIIRS"),
            "confidence": rng.choice(["l", "n", "h"], c, p=[0.15, 0.65, 0.2]),
            "frp": np.round(rng.gamma(1.5, 6.0, c), 1),
            "daynight": rng.choice(["D", "N"], c, p=[0.6, 0.4]),
        }))

    w = pd.concat(weather, ignore_index=True)
    v = pd.concat(ndvi, ignore_index=True)
    f = assign_fires(pd.concat(fires, ignore_index=True), reserves)
    for df in (w, v, f):
        df["source"], df["source_type"] = "Demo generator", settings.SIMULATED
    return w, v, f, (str(start.date()), str(end.date()))


def seed_demo_data(conn) -> None:
    reserves = pd.read_sql_query("SELECT * FROM protected_areas", conn)
    w, v, f, cov = generate(reserves)
    n = db.upsert_weather(conn, w) + db.upsert_ndvi(conn, v) + db.insert_fires(conn, f)
    db.update_source(conn, "DEMO", True,
                     f"Deterministic demo data generated (seed {settings.DEMO_SEED}).",
                     records=n, status="DEMO", coverage=cov)
