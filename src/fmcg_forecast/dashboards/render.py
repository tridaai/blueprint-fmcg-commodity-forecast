"""Rendering: one static HTML page per dashboard / board.

Portfolio console conventions — a single static file, inline
CSS, light theme, no JavaScript framework, so a non-technical
desk can open it anywhere. Rendering is a pure function of the
stored artefacts (spec + resolved panels; board + pack), which
is what lets the verifier re-render a stored page byte-for-byte.

Every figure renders with the artefact it came from; the
provenance appendix (F20-DR3) renders each figure's full
lineage walk — artefact, input facts, source + date — so a
desk head can defend any number on the page in a meeting.
"""

from __future__ import annotations

import html
import json

from fmcg_forecast.dashboards.models import (
    DashboardAssembly,
    DashboardSpec,
    DeskBoard,
)
from fmcg_forecast.dashboards.pack import DashboardPack

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
.panel.gap { background: var(--panel); border-style: dashed; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px;
  border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
.badge { display: inline-block; background: var(--lavender);
  color: var(--indigo-dark); border-radius: 999px; padding: 1px 8px;
  font-size: 12px; margin-right: 4px; }
.badge.bad { background: #FEF3F2; color: var(--bad); }
.badge.stale { background: #FEF3E2; color: var(--warn); }
.note { color: var(--muted); font-size: 13px; margin-top: 8px; }
.lineage { color: var(--muted); font-size: 12px; }
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
footer { display: flex; justify-content: space-between; gap: 24px;
  border-top: 1px solid var(--line); padding-top: 18px;
  padding-bottom: 28px; margin-top: 28px; flex-wrap: wrap; }
.footer-brand { display: flex; align-items: center; gap: 8px; }
.footer-brand img { width: 28px; height: 28px; }
footer a { color: var(--indigo); text-decoration: none;
  margin-left: 16px; }
"""


def _fmt(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e12:
            return f"{int(value):,}"
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if value is None:
        return "—"
    return str(value)


def _esc(value) -> str:
    return html.escape(_fmt(value) if not isinstance(value, str) else value)


def _footer() -> list[str]:
    return [
        "<footer>",
        "<div>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI"><strong>Trida AI</strong></div>',
        '<p class="muted">Figures on this page are artefact figures '
        "re-performed by the assembler before serving, each with "
        "its lineage to stored facts in the appendix. The "
        "dashboard selects and renders; it does not compute, and "
        "it never invents a figure for a part the data cannot "
        "answer.</p>",
        "</div>",
        '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
    ]


def _render_panel(panel) -> list[str]:
    if panel.state == "gap":
        return [
            '<section class="panel gap">',
            f"<h2>{_esc(panel.title)}</h2>",
            "<p><strong>Not available.</strong> "
            f"{_esc(panel.gap_needed or '')}.</p>",
            '<p class="note">A gap is stated, never filled in: no '
            "number is invented for a part the data cannot "
            "answer.</p>",
            "</section>",
        ]
    out = ['<section class="panel">', f"<h2>{_esc(panel.title)}</h2>"]
    badges: list[str] = []
    for figure in panel.figures:
        if figure.key == "accuracy_state" and figure.value == "degraded":
            badges.append('<span class="badge bad">degraded</span>')
        if figure.key == "view_kind":
            badges.append(
                f'<span class="badge stale">scenario: '
                f"{_esc(figure.value)}</span>"
            )
    if panel.superseded_from:
        badges.append(
            '<span class="badge stale">re-resolved: '
            + ", ".join(_esc(s) for s in panel.superseded_from)
            + " superseded</span>"
        )
    if badges:
        out.append("<p>" + "".join(badges) + "</p>")
    out.append(
        "<table><thead><tr><th>Figure</th><th>Value</th>"
        "<th>Unit</th><th>Artefact</th></tr></thead><tbody>"
    )
    for figure in panel.figures:
        out.append(
            f"<tr><td>{_esc(figure.label)}</td>"
            f"<td>{_esc(figure.value)}</td>"
            f"<td>{_esc(figure.unit)}</td>"
            f'<td class="mono">{_esc(figure.artefact_id)}</td></tr>'
        )
    out.append("</tbody></table>")
    if panel.note:
        out.append(f'<p class="note">{_esc(panel.note)}</p>')
    out.append("</section>")
    return out


def _render_appendix(assembly: DashboardAssembly) -> list[str]:
    out = [
        '<section class="panel">',
        "<h2>Provenance appendix — every figure, walked to its facts</h2>",
        "<p class=\"note\">Each figure below names the artefact it "
        "was read from and the input facts behind that artefact, "
        "with source and date. The walk terminates at stored "
        "facts: observation rows, sentiment items, event "
        "declarations, the dataset manifest.</p>",
    ]
    for panel in assembly.panels:
        if panel.state != "rendered":
            continue
        out.append(f"<h3>{_esc(panel.title)}</h3>")
        for figure in panel.figures:
            out.append(
                f"<p><strong>{_esc(figure.label)}</strong> "
                f"({_esc(figure.value)} {_esc(figure.unit)}) — "
                f'artefact <span class="mono">'
                f"{_esc(figure.artefact_id)}</span></p>"
            )
            out.append('<ul class="lineage">')
            for fact in figure.lineage:
                date_part = (
                    f" · {fact.fact_date.isoformat()}" if fact.fact_date else ""
                )
                out.append(
                    f"<li><strong>{_esc(fact.kind)}</strong> "
                    f'<span class="mono">{_esc(fact.ref)}</span> — '
                    f"{_esc(fact.detail)} · source: "
                    f"{_esc(fact.source)}{_esc(date_part)}</li>"
                )
            out.append("</ul>")
    out.append("</section>")
    return out


def _render_diff(assembly: DashboardAssembly) -> list[str]:
    if not assembly.diff:
        return []
    out = [
        '<section class="panel"><h2>What changed since the '
        "previous assembly</h2><table><tbody>"
    ]
    for entry in assembly.diff:
        if entry.kind == "figure_changed":
            text = (
                f"Panel {entry.panel_no} ({entry.panel_title}): "
                f"{entry.label} changed from {_fmt(entry.before)} "
                f"to {_fmt(entry.after)}"
            )
        elif entry.kind == "binding_superseded":
            text = (
                f"Panel {entry.panel_no} ({entry.panel_title}): "
                f"source artefacts superseded — "
                f"{', '.join(entry.before or [])} → "
                f"{', '.join(entry.after or [])}"
            )
        else:
            text = (
                f"Panel {entry.panel_no} ({entry.panel_title}): "
                f"panel state changed — {entry.before} → {entry.after}"
            )
        out.append(f"<tr><td>{_esc(text)}</td></tr>")
    out.append("</tbody></table></section>")
    return out


def render_dashboard(spec: DashboardSpec, assembly: DashboardAssembly) -> str:
    """The dashboard page — a pure function of the spec and the
    assembly's resolved panels, so a stored page re-renders
    byte-for-byte."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Dashboard — Verdanta Foods trading desk</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="muted">Verdanta Foods — trading desk</p>',
        "<h1>Dashboard</h1>",
        f'<p class="muted">Prompt: {_esc(spec.prompt)}</p>',
        f'<p class="muted">Asked by {_esc(spec.asked_by)} · spec '
        f'<span class="mono">{_esc(spec.spec_id)}</span> · assembly '
        f'<span class="mono">{_esc(assembly.assembly_id)}</span> '
        f"(#{assembly.seq}) · assembled "
        f"{_esc(assembly.assembled_on.isoformat())} · every figure "
        "names the artefact it came from, with its lineage in "
        "the appendix; a part the data cannot answer is shown "
        "as a gap, never filled in.</p>",
        "</header>",
        "<main>",
    ]
    for panel in assembly.panels:
        out.extend(_render_panel(panel))
    out.extend(_render_diff(assembly))
    out.extend(_render_appendix(assembly))
    out.append("</main>")
    out.extend(_footer())
    out += ["</body>", "</html>"]
    return "\n".join(out)


def render_board(board: DeskBoard, pack: DashboardPack) -> str:
    """The morning desk board page — a pure function of the
    board artefact and the pack's section titles."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Morning desk board — Verdanta Foods</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="muted">Verdanta Foods — trading desk</p>',
        "<h1>Morning desk board</h1>",
        f'<p class="muted">Board for '
        f"{_esc(board.board_date.isoformat())} · "
        f'<span class="mono">{_esc(board.board_id)}</span> · '
        "exceptions first, ranked by the pack's section order; "
        "every row names the artefact behind it. A series with "
        "nothing wrong does not appear.</p>",
        "</header>",
        "<main>",
    ]
    if not board.rows:
        out.append(
            '<section class="panel"><p>No exceptions on record '
            "for this date.</p></section>"
        )
    for section in pack.board_sections:
        rows = [r for r in board.rows if r.kind == section]
        if not rows:
            continue
        out.append('<section class="panel">')
        out.append(f"<h2>{_esc(pack.board_section_titles[section])}</h2>")
        out.append("<table><tbody>")
        for row in rows:
            figures = "; ".join(
                f"{key}: {_fmt(value)}"
                for key, value in sorted(row.figures.items())
            )
            figures_part = f' <span class="muted">{_esc(figures)}</span>' if figures else ""
            out.append(
                f"<tr><td>{_esc(row.headline)}{figures_part}</td>"
                f'<td class="mono">{_esc(row.artefact_id)}</td></tr>'
            )
        out.append("</tbody></table></section>")
    # Row kinds outside the pack's section list (R8 signal rows,
    # appended under their own pack) render after the pack's
    # sections under their own titles — never dropped, never
    # folded into a pack section they do not belong to.
    extra_titles = {"signal": "Buy-window signals — ranked for the desk"}
    rendered = set(pack.board_sections)
    for row in board.rows:
        if row.kind in rendered:
            continue
        rendered.add(row.kind)
        rows = [r for r in board.rows if r.kind == row.kind]
        out.append('<section class="panel">')
        out.append(
            f"<h2>{_esc(extra_titles.get(row.kind, row.kind))}</h2>"
        )
        out.append("<table><tbody>")
        for extra_row in rows:
            figures = "; ".join(
                f"{key}: {_fmt(value)}"
                for key, value in sorted(extra_row.figures.items())
            )
            figures_part = f' <span class="muted">{_esc(figures)}</span>' if figures else ""
            out.append(
                f"<tr><td>{_esc(extra_row.headline)}{figures_part}</td>"
                f'<td class="mono">{_esc(extra_row.artefact_id)}</td></tr>'
            )
        out.append("</tbody></table></section>")
    out.append("</main>")
    out.extend(_footer())
    out += ["</body>", "</html>"]
    return "\n".join(out)
