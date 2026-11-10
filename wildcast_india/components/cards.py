"""Reusable KPI cards, badges, section titles and alert rows."""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from config.settings import THEME as T, category_for

SEV_COLOURS = {"Severe": T["red"], "High": T["orange"], "Moderate": T["yellow"], "Info": T["blue"]}
SOURCE_COLOURS = {"LIVE": T["green"], "HISTORICAL": T["blue"], "UPLOADED": T["yellow"],
                  "SIMULATED": "#8A9A94"}


def section(title: str, icon: str = "") -> None:
    st.markdown(f'<div class="wc-section">{icon} {title}</div>', unsafe_allow_html=True)


def badge(text: str, colour: str) -> str:
    return (f'<span class="wc-badge" style="background:{colour}26;color:{colour};'
            f'border:1px solid {colour}55">{html.escape(str(text))}</span>')


def category_badge(score) -> str:
    label, colour = category_for(score)
    return badge(label, colour)


def kpi_card(label: str, value, sub: str = "", icon: str = "", colour: str | None = None,
             bar: float | None = None) -> None:
    bar_html = ""
    if bar is not None:
        bar_html = (f'<div class="wc-bar"><div style="width:{max(0, min(100, bar)):.0f}%;'
                    f'background:{colour or T["green"]}"></div></div>')
    st.markdown(f"""<div class="wc-card wc-kpi"><div class="lbl">{icon} {label}</div>
        <div class="val" style="color:{colour or T['text']}">{value}</div>
        <div class="sub">{sub}</div>{bar_html}</div>""", unsafe_allow_html=True)


def kpi_row(items: list[dict]) -> None:
    cols = st.columns(len(items))
    for col, item in zip(cols, items):
        with col:
            kpi_card(**item)


def indicator_card(name: str, icon: str, score, weight: float, detail: str) -> None:
    if score is None or score != score:
        kpi_card(name, "—", f"Data unavailable · {detail}", icon, "#7D8C86", 0)
        return
    frac = score / weight if weight else 0
    colour = T["red"] if frac >= 0.8 else T["orange"] if frac >= 0.6 else T["yellow"] if frac >= 0.4 else T["green"]
    kpi_card(name, f"{score:.1f}<span style='font-size:0.95rem;color:{T['muted']}'> / {weight:g}</span>",
             detail, icon, colour, frac * 100)


def score_gauge_card(score, completeness: float, provisional: bool, week_end) -> None:
    label, colour = category_for(score)
    val = "—" if score is None or score != score else f"{score:.0f}"
    prov = badge("PROVISIONAL", T["yellow"]) if provisional else badge("COMPLETE", T["green"])
    st.markdown(f"""<div class="wc-card" style="text-align:center">
        <div class="lbl" style="justify-content:center">Habitat Stress Score</div>
        <div style="font-size:3.2rem;font-weight:700;color:{colour};line-height:1.1;margin-top:0.3rem">{val}
        <span style="font-size:1rem;color:{T['muted']}">/100</span></div>
        <div style="margin:0.35rem 0">{badge(label, colour)} {prov}</div>
        <div class="sub">Data completeness {completeness:.0%} · week ending {pd.Timestamp(week_end):%d %b %Y}</div>
        <div class="wc-bar"><div style="width:{0 if val == '—' else score:.0f}%;background:{colour}"></div></div>
        </div>""", unsafe_allow_html=True)


def alert_list(alerts: pd.DataFrame, limit: int = 6) -> None:
    if alerts.empty:
        st.markdown('<div class="wc-note">No active alerts.</div>', unsafe_allow_html=True)
        return
    for r in alerts.head(limit).itertuples():
        c = SEV_COLOURS.get(r.severity, T["blue"])
        st.markdown(f"""<div class="wc-alert" style="border-left-color:{c}">{badge(r.severity, c)}
            <b>{html.escape(r.reserve)}</b> · {html.escape(r.message)}<br>
            <small>{r.alert_type.replace('_', ' ').title()} · {r.period_key}</small></div>""",
                    unsafe_allow_html=True)


IUCN_COLOURS = {"CR": "#D95F59", "EN": "#E58B43", "VU": "#E5B65B", "NT": "#B9C46A", "LC": "#6FAF83",
                "DD": "#8A9A94", "NE": "#5E6E68", "EW": "#9C6ADE", "EX": "#555555"}
GROUP_ICONS = {"Mammals": "🐾", "Birds": "🪶", "Reptiles": "🦎", "Amphibians": "🐸", "Fish": "🐟",
               "Insects": "🦋", "Other invertebrates": "🐚", "Other": "🔹"}


def iucn_badge(code) -> str:
    from processing.wildlife import IUCN_LABELS
    if not isinstance(code, str):
        return badge("Not assessed / unknown", "#5E6E68")
    return badge(f"{code} · {IUCN_LABELS.get(code, code)}", IUCN_COLOURS.get(code, "#8A9A94"))


def species_card(sp: dict, extra: str = "", compact: bool = False) -> None:
    common = html.escape(str(sp.get("common_name") or "—"))
    sci = html.escape(str(sp.get("scientific_name")))
    icon = GROUP_ICONS.get(sp.get("taxon_group"), "🔹")
    sens = badge("Location generalised", T["blue"]) if sp.get("sensitive") else ""
    yr = sp.get("iucn_assessment_year")
    yr = f" · assessed {int(yr)}" if isinstance(yr, (int, float)) and yr == yr else ""
    if compact:
        st.markdown(f"""<div class="wc-card" style="padding:0.7rem 0.85rem">
            <div style="display:flex;justify-content:space-between;align-items:center">
            <div><span style="font-size:1.2rem">{icon}</span> <b style="color:{T['text']}">{common}</b><br>
            <i class="wc-note">{sci}</i></div><div>{iucn_badge(sp.get('iucn_category'))}</div></div>
            <div class="sub" style="margin-top:0.35rem">{extra}</div></div>""", unsafe_allow_html=True)
        return
    st.markdown(f"""<div class="wc-card" style="border-top:3px solid {IUCN_COLOURS.get(sp.get('iucn_category'), T['border'])}">
        <div style="display:flex;gap:0.9rem;align-items:center">
          <div style="font-size:2.4rem;background:#0E1714;border-radius:12px;padding:0.3rem 0.6rem">{icon}</div>
          <div><div style="font-size:1.35rem;font-weight:650;color:{T['text']}">{common}</div>
          <div style="color:{T['muted']};font-style:italic">{sci}</div>
          <div style="margin-top:0.35rem">{iucn_badge(sp.get('iucn_category'))} {sens}</div></div></div>
        <table style="width:100%;font-size:0.86rem;color:{T['text']};margin-top:0.7rem">
        <tr><td class="wc-note">Group</td><td>{sp.get('taxon_group') or '—'}</td>
            <td class="wc-note">Class</td><td>{sp.get('class_name') or '—'}</td></tr>
        <tr><td class="wc-note">Order</td><td>{sp.get('order_name') or '—'}</td>
            <td class="wc-note">Family</td><td>{sp.get('family') or '—'}</td></tr>
        <tr><td class="wc-note">IUCN source</td><td colspan=3>{html.escape(str(sp.get('iucn_source') or '—'))}{yr}</td></tr>
        </table>{extra}</div>""", unsafe_allow_html=True)


def empty_state(title: str, body: str, icon: str = "🛰️") -> None:
    st.markdown(f"""<div class="wc-card" style="text-align:center;padding:2rem 1rem">
        <div style="font-size:2.2rem">{icon}</div>
        <div style="font-size:1.1rem;font-weight:600;color:{T['text']};margin:0.4rem 0">{title}</div>
        <div class="wc-note" style="max-width:640px;margin:auto;font-size:0.88rem">{body}</div></div>""",
                unsafe_allow_html=True)
