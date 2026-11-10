"""Cached data access shared by every page. Call invalidate() after any write."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from config import settings
from database import db


@st.cache_data(show_spinner=False)
def reserves() -> pd.DataFrame:
    return db.get_reserves()


@st.cache_data(show_spinner=False)
def latest_scores() -> pd.DataFrame:
    return db.get_latest_scores()


@st.cache_data(show_spinner=False)
def scores(pa_id: str | None = None) -> pd.DataFrame:
    return db.get_scores(pa_id)


@st.cache_data(show_spinner=False)
def weather(pa_id: str | None = None, start: str | None = None) -> pd.DataFrame:
    return db.get_weather(pa_id, start)


@st.cache_data(show_spinner=False)
def ndvi(pa_id: str | None = None) -> pd.DataFrame:
    return db.get_ndvi(pa_id)


@st.cache_data(show_spinner=False)
def fires(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    return db.get_fires(start, end)


@st.cache_data(show_spinner=False)
def sources() -> pd.DataFrame:
    return db.get_data_sources()


def alerts(include_ack: bool = True) -> pd.DataFrame:
    return db.get_alerts(include_ack)  # never cached: acknowledgements must show immediately


def as_of() -> pd.Timestamp:
    s = latest_scores()
    return s["week_end"].max() if not s.empty else pd.Timestamp.today().normalize()


def demo_mode() -> bool:
    c = db.record_counts()
    return bool(not c.empty and (c["source_type"] == settings.SIMULATED).any())


def provenance(table_df: pd.DataFrame) -> str:
    if table_df.empty or "source_type" not in table_df:
        return "none"
    return ", ".join(f"{k} {v}" for k, v in table_df["source_type"].value_counts().items())


def invalidate() -> None:
    st.cache_data.clear()


def to_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


# ------------------------------------------------------------------ wildlife
@st.cache_data(show_spinner=False)
def species() -> pd.DataFrame:
    return db.get_species()


@st.cache_data(show_spinner=False)
def observations(pa_ids: tuple | None = None, sp: str | None = None) -> pd.DataFrame:
    return db.get_observations(list(pa_ids) if pa_ids else None, sp)


@st.cache_data(show_spinner=False)
def species_reserve() -> pd.DataFrame:
    return db.get_species_reserve()


@st.cache_data(show_spinner=False)
def population() -> pd.DataFrame:
    return db.get_population()


def has_wildlife() -> bool:
    return not species_reserve().empty


# ------------------------------------------------------------------ water
@st.cache_data(show_spinner=False)
def water_bodies() -> pd.DataFrame:
    return db.get_water_bodies()


@st.cache_data(show_spinner=False)
def water_obs(wb_id: str | None = None) -> pd.DataFrame:
    return db.get_water_obs(wb_id)


@st.cache_data(show_spinner=False)
def water_assessments() -> pd.DataFrame:
    return db.get_water_assessments()


def water_weeks() -> list:
    a = water_assessments()
    return sorted({str(pd.Timestamp(w).date()) for w in a["week_end"].unique()}, reverse=True) if not a.empty else []
