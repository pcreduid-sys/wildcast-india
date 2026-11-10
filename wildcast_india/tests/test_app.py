"""Headless smoke tests: every page renders without exceptions (Streamlit AppTest)."""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")
PAGES = ["overview", "explorer", "habitat", "wildlife", "research"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.sidebar.radio(key="nav_page").set_value(page).run()
    assert not at.exception, at.exception


def test_filters_and_reserve_switch():
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.multiselect(key="ov_cat").set_value(["High", "Severe"]).run()
    assert not at.exception
    at.sidebar.radio(key="nav_page").set_value("explorer").run()
    for name in ["Kaziranga", "Sundarbans", "Gir"]:
        at.selectbox(key="rx_reserve").set_value(name).run()
        assert not at.exception, (name, at.exception)
    at.selectbox(key="rx_period").set_value("Last 5 years").run()
    assert not at.exception
    at.sidebar.radio(key="nav_page").set_value("habitat").run()
    at.multiselect(key="fa_state").set_value(["Gujarat"]).run()
    at.selectbox(key="fa_scope").set_value("Inside + 25 km buffer").run()
    at.selectbox(key="hm_ind").set_value("Drought (points)").run()
    assert not at.exception
    at.sidebar.radio(key="nav_page").set_value("wildlife").run()
    at.selectbox(key="wi_res").set_value("Gir").run()
    at.multiselect(key="wi_cat").set_value(["Potential water stress", "Moderate availability"]).run()
    assert not at.exception
    at.selectbox(key="wi_res").set_value("All reserves").run()
    for r in ["Kaziranga", "Sundarbans", "Gir"]:
        at.selectbox(key="si_res").set_value(r).run()
        assert not at.exception, (r, at.exception)
    at.multiselect(key="pm_sp").set_value(["Rhinoceros unicornis"]).run()
    at.text_input(key="sx_q").set_value("tiger").run()
    assert not at.exception
