"""Theme CSS, header and sidebar navigation."""
from __future__ import annotations

import streamlit as st

from config.settings import THEME as T

PAGES = {
    "overview": ("National Overview", ":material/public:"),
    "explorer": ("Reserve Explorer", ":material/forest:"),
    "habitat": ("Habitat Monitoring", ":material/local_fire_department:"),
    "wildlife": ("Wildlife Intelligence", ":material/pets:"),
    "research": ("Research & Administration", ":material/analytics:"),
}

CSS = f"""
<style>
html, body, [class*="css"] {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; }}
.stApp {{ background: {T['bg']}; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px; }}
section[data-testid="stSidebar"] {{ background: {T['sidebar']}; border-right: 1px solid {T['border']}; }}
section[data-testid="stSidebar"] .stRadio label p {{ font-size: 0.95rem; }}
section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
    padding: 0.45rem 0.6rem; border-radius: 8px; margin-bottom: 2px; }}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {{ background: {T['card']}; }}
section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
    background: {T['card']}; border-left: 3px solid {T['green']}; }}
.wc-header {{ display:flex; justify-content:space-between; align-items:flex-end;
    border-bottom:1px solid {T['border']}; padding-bottom:0.7rem; margin-bottom:1.1rem; }}
.wc-header h1 {{ font-size:1.55rem; margin:0; color:{T['text']}; font-weight:650; letter-spacing:-0.01em; }}
.wc-header p {{ margin:0.15rem 0 0; color:{T['muted']}; font-size:0.88rem; }}
.wc-meta {{ text-align:right; color:{T['muted']}; font-size:0.8rem; line-height:1.4; }}
.wc-card {{ background:{T['card']}; border:1px solid {T['border']}; border-radius:12px;
    padding:0.9rem 1rem; height:100%; }}
.wc-kpi {{ min-height: 132px; }}
.wc-card .lbl {{ color:{T['muted']}; font-size:0.74rem; text-transform:uppercase; letter-spacing:0.06em;
    display:flex; align-items:center; gap:0.4rem; }}
.wc-card .val {{ color:{T['text']}; font-size:1.75rem; font-weight:650; margin-top:0.25rem; line-height:1.1; }}
.wc-card .sub {{ color:{T['muted']}; font-size:0.8rem; margin-top:0.3rem; }}
.wc-bar {{ height:6px; background:#0E1714; border-radius:3px; margin-top:0.55rem; overflow:hidden; }}
.wc-bar > div {{ height:100%; border-radius:3px; }}
.wc-badge {{ display:inline-block; padding:0.12rem 0.55rem; border-radius:999px; font-size:0.72rem;
    font-weight:600; letter-spacing:0.02em; }}
.wc-section {{ color:{T['text']}; font-size:1.02rem; font-weight:600; margin:0.6rem 0 0.5rem;
    display:flex; align-items:center; gap:0.45rem; }}
.wc-alert {{ background:{T['card']}; border:1px solid {T['border']}; border-left:4px solid; border-radius:8px;
    padding:0.5rem 0.75rem; margin-bottom:0.45rem; font-size:0.86rem; color:{T['text']}; }}
.wc-alert small {{ color:{T['muted']}; }}
.wc-note {{ color:{T['muted']}; font-size:0.78rem; }}
div[data-testid="stDataFrame"] {{ border:1px solid {T['border']}; border-radius:10px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 0.4rem; }}
.stTabs [data-baseweb="tab"] {{ background:{T['card']}; border-radius:8px 8px 0 0; padding:0.4rem 1rem; }}
div[data-testid="stMetric"] {{ background:{T['card']}; border-radius:10px; padding:0.6rem 0.8rem; }}
iframe {{ border-radius: 12px; }}
#MainMenu, footer {{ visibility: hidden; }}
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str, as_of=None, extra: str = "") -> None:
    meta = f"Week ending <b>{as_of:%d %b %Y}</b>" if as_of is not None else ""
    st.markdown(f"""<div class="wc-header"><div><h1>{title}</h1><p>{subtitle}</p></div>
        <div class="wc-meta">{meta}<br>{extra}</div></div>""", unsafe_allow_html=True)


def sidebar(demo_mode: bool) -> str:
    with st.sidebar:
        st.markdown(f"""<div style="padding:0.2rem 0 0.9rem">
            <div style="font-size:1.25rem;font-weight:700;color:{T['text']};letter-spacing:0.02em">
            🌿 WILDCAST <span style="color:{T['green']}">INDIA</span></div>
            <div class="wc-note">Habitat stress intelligence · National Weather Big Data Platform</div>
            </div>""", unsafe_allow_html=True)
        keys = list(PAGES)
        page = st.radio("Navigation", keys, format_func=lambda k: f"{PAGES[k][1]} {PAGES[k][0]}",
                        label_visibility="collapsed", key="nav_page")
        st.divider()
        if demo_mode:
            st.markdown(f"""<div class="wc-card" style="padding:0.6rem 0.8rem">
                <span class="wc-badge" style="background:{T['yellow']}22;color:{T['yellow']}">DEMONSTRATION DATA</span>
                <div class="wc-note" style="margin-top:0.35rem">Simulated records are in use. Connect NASA
                sources on Research &amp; Administration → Admin.</div></div>""", unsafe_allow_html=True)
        st.markdown("""<div class="wc-note" style="margin-top:0.8rem">Habitat indicators describe conditions, not animals. Wildlife records show documented occurrences, not abundance.
            HSS is a screening index, not an officially validated ecological index.</div>""", unsafe_allow_html=True)
    return page
