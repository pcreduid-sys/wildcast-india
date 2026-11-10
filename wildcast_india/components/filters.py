"""Shared filter widgets."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

CATS = ["Low", "Moderate", "High", "Severe"]


def state_filter(reserves: pd.DataFrame, key: str) -> list[str]:
    return st.multiselect("State", sorted(reserves["state"].unique()), key=key, placeholder="All states")


def reserve_filter(reserves: pd.DataFrame, key: str, states: list[str] | None = None) -> list[str]:
    r = reserves[reserves["state"].isin(states)] if states else reserves
    names = st.multiselect("Protected area", sorted(r["name"]), key=key, placeholder="All reserves")
    return list(reserves.loc[reserves["name"].isin(names), "pa_id"])


def category_filter(key: str) -> list[str]:
    return st.multiselect("Stress category", CATS, key=key, placeholder="All categories")


def reserve_select(reserves: pd.DataFrame, key: str, label: str = "Protected area", default: str | None = None) -> str:
    names = list(reserves["name"])
    idx = names.index(default) if default in names else 0
    name = st.selectbox(label, names, index=idx, key=key)
    return reserves.loc[reserves["name"] == name, "pa_id"].iloc[0]


def date_range(key: str, end: date, default_days: int = 30, min_date: date | None = None) -> tuple[date, date]:
    val = st.date_input("Date range", value=(end - timedelta(days=default_days - 1), end),
                        min_value=min_date, max_value=end, key=key)
    if isinstance(val, (tuple, list)) and len(val) == 2:
        return val[0], val[1]
    d = val[0] if isinstance(val, (tuple, list)) else val
    return d, d


def apply(df: pd.DataFrame, states=None, pa_ids=None, cats=None) -> pd.DataFrame:
    if states:
        df = df[df["state"].isin(states)]
    if pa_ids:
        df = df[df["pa_id"].isin(pa_ids)]
    if cats:
        df = df[df["category"].isin(cats)]
    return df
