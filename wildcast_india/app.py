"""WILDCAST INDIA — habitat stress intelligence for India's protected areas.

Run:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from components import data  # noqa: E402
from components.sidebar import apply_theme, sidebar  # noqa: E402
from dashboard import habitat_monitoring, overview, research_admin, reserve_explorer, wildlife  # noqa: E402
from database import db  # noqa: E402

st.set_page_config(page_title="WILDCAST INDIA", page_icon="🌿", layout="wide",
                   initial_sidebar_state="expanded")


@st.cache_resource(show_spinner="Initialising database and demonstration dataset (first run only)…")
def _bootstrap() -> bool:
    db.init_db()
    return True


def main() -> None:
    apply_theme()
    _bootstrap()
    page = sidebar(data.demo_mode())
    {"overview": overview.render, "explorer": reserve_explorer.render,
     "habitat": habitat_monitoring.render, "wildlife": wildlife.render,
     "research": research_admin.render}[page]()


main()
