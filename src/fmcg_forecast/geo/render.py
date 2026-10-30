"""Rendering the market map: one static page.

The page is a pure function of the map artefact — what the
desk sees is exactly what the record supports, and the
verifier re-renders it byte-for-byte from the stored cells.
The grid is the pack's schematic geography: rows north to
south, columns west to east. A market with no current data
renders as a named gap in its cell, never a zero; a market
whose spread is not classified renders its band state, not
an invented class.
"""

from __future__ import annotations

import html

_CSS = """
:root { --ink: #0A0A0A; --muted: #5D6472; --line: #E4E4EC;
  --panel: #F7F7FA; --indigo: #4F46E5; --indigo-dark: #3730A3;
  --lavender: #EEF0FF; --warn: #B54708; --bad: #B42318; }
* { box-sizing: border-box; }
body { margin: 0; background: #FFFFFF; color: var(--ink);
  font-family: "Plus Jakarta Sans", system-ui, sans-serif; }
header, main, footer { max-width: 1080px; margin: 0 auto; padding: 0 20px; }
header { padding-top: 28px; }
h1 { font-size: 24px; margin: 8px 0 4px; }
h2 { font-size: 17px; margin: 0 0 10px; }
.muted { color: var(--muted); }
.panel { border: 1px solid var(--line); border-radius: 12px;
  padding: 18px; margin: 18px 0; background: #FFFFFF; }
table.grid { border-collapse: separate; border-spacing: 8px; width: 100%; }
td.cell { border: 1px solid var(--line); border-radius: 12px;
  padding: 12px; width: 20%; vertical-align: top; background: #FFFFFF; }
td.cell.gap { background: var(--panel); color: var(--muted); }
td.empty { border: none; }
.cell h3 { font-size: 15px; margin: 0 0 2px; }
.cell .region { color: var(--muted); font-size: 12px; margin-bottom: 8px; }
.cell .price { font-size: 17px; font-weight: 700; }
.badge { display: inline-block; background: var(--lavender);
  color: var(--indigo-dark); border-radius: 999px; padding: 1px 8px;
  font-size: 12px; margin: 2px 4px 2px 0; }
.badge.bad { background: #FEF3F2; color: var(--bad); }
.badge.stale { background: #FEF3E2; color: var(--warn); }
.note { color: var(--muted); font-size: 13px; margin-top: 8px; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
footer { display: flex; justify-content: space-between; gap: 24px;
  border-top: 1px solid var(--line); padding-top: 18px;
  padding-bottom: 28px; margin-top: 28px; flex-wrap: wrap; }
.footer-brand { display: flex; align-items: center; gap: 8px; }
.footer-brand img { width: 28px; height: 28px; }
footer a { color: var(--indigo); text-decoration: none;
  margin-left: 16px; }
"""

_FOOTER = (
    '<footer><div class="footer-brand">'
    '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
    'alt="Trida AI">'
    "<span>Trida AI — FMCG Commodity Forecast blueprint</span></div>"
    '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
    '<a href="https://github.com/tridaai">View all blueprints →</a>'
    "</div></footer>"
)


def inr(paise: int) -> str:
    """Integer paise as an INR string, sign carried."""
    sign = "-" if paise < 0 else ""
    absolute = abs(paise)
    return f"{sign}₹{absolute // 100:,}.{absolute % 100:02d}"


def signed_inr(paise: int) -> str:
    if paise > 0:
        return "+" + inr(paise)
    return inr(paise)


def _cell_html(cell) -> str:
    badges: list[str] = []
    if cell.data_state == "no_current_data":
        price = '<div class="price">No current data</div>'
        badges.append('<span class="badge bad">named gap</span>')
    else:
        price = (
            f'<div class="price">{inr(cell.price_paise)}</div>'
            f'<div class="muted">modal price, '
            f"{cell.price_date.isoformat()}</div>"
        )
        if cell.data_state == "stale":
            badges.append('<span class="badge stale">stale price</span>')
    if cell.basis_classification == "reference":
        badges.append('<span class="badge">reference market</span>')
    elif cell.basis_classification in ("wide", "narrow"):
        badges.append(
            f'<span class="badge bad">basis {cell.basis_classification} '
            f"{signed_inr(cell.current_spread_paise)}</span>"
        )
    elif cell.basis_classification == "within":
        badges.append(
            f'<span class="badge">basis within band '
            f"{signed_inr(cell.current_spread_paise)}</span>"
        )
    else:
        badges.append(
            f'<span class="badge stale">basis '
            f"{html.escape(cell.basis_classification.replace('_', ' '))}"
            "</span>"
        )
    if cell.open_alerts:
        badges.append(
            f'<span class="badge bad">{cell.open_alerts} open '
            f"alert(s), top {html.escape(cell.top_severity or '')}</span>"
        )
    weather = cell.weather
    if weather.state == "deviating":
        badges.append(
            f'<span class="badge stale">weather deviating '
            f"(z {weather.z:+.2f})</span>"
        )
    elif weather.state in ("insufficient_history", "no_current_data"):
        badges.append(
            '<span class="badge stale">weather '
            f"{weather.state.replace('_', ' ')}</span>"
        )
    gap_class = " gap" if cell.data_state == "no_current_data" else ""
    return (
        f'<td class="cell{gap_class}"><h3>'
        f'<a href="{html.escape(cell.series_href)}">'
        f"{html.escape(cell.display)}</a></h3>"
        f'<div class="region">{html.escape(cell.region)}</div>'
        f"{price}{''.join(badges)}</td>"
    )


def render_market_map(market_map) -> str:
    cells = {(c.grid_row, c.grid_col): c for c in market_map.cells}
    max_row = max(c.grid_row for c in market_map.cells)
    max_col = max(c.grid_col for c in market_map.cells)
    rows_html: list[str] = []
    for row in range(max_row + 1):
        tds: list[str] = []
        for col in range(max_col + 1):
            cell = cells.get((row, col))
            tds.append(
                _cell_html(cell) if cell is not None else '<td class="empty"></td>'
            )
        rows_html.append("<tr>" + "".join(tds) + "</tr>")
    if market_map.active_events:
        events = "".join(
            f'<div><span class="badge">{html.escape(e.event_class)}</span> '
            f'<span class="mono">{html.escape(e.event_id)}</span> '
            f'<span class="muted">{e.window_start.isoformat()} → '
            f"{e.window_end.isoformat() if e.window_end else 'open'}"
            "</span></div>"
            for e in market_map.active_events
        )
        events_panel = (
            '<section class="panel"><h2>Active event windows</h2>'
            f"{events}</section>"
        )
    else:
        events_panel = (
            '<section class="panel"><h2>Active event windows</h2>'
            '<div class="muted">No registry event window covers '
            "this date for this commodity.</div></section>"
        )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>Market map — {html.escape(market_map.commodity)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"<header><h1>Market map — {html.escape(market_map.commodity)}</h1>"
        f'<div class="muted">As of {market_map.as_of.isoformat()} · '
        f"geo pack {html.escape(market_map.pack_version)} · basis "
        f'reading <span class="mono">'
        f"{html.escape(market_map.basis_reading_id)}</span></div>"
        '<div class="note">Schematic grid — positions carry the '
        "country's shape for reading; they are not coordinates and "
        "no figure derives from them. Clicking a market opens its "
        "series board.</div></header>"
        f'<main><table class="grid">{"".join(rows_html)}</table>'
        f"{events_panel}</main>"
        f"{_FOOTER}</body></html>"
    )
