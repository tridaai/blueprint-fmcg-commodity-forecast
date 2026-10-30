"""Rendering the console: one desktop page, one phone page.

Both pages are pure functions of the console view — the same
composed read the JSON surface returns — so what the desk
sees is exactly what the record supports, on either surface.

The desktop page is the working console: the morning board's
exceptions, the review queue with its side-by-side figures
and approval blockers, the triage lanes, the open alerts and
the pre-flight table. The phone page (F20-MF2) is the same
exception inbox phone-first: stacked cards, large type, and
an action form on every card. The forms post to the
console's single action door, which strikes the same acts
the canonical endpoints strike — the act artefact is the
same because the service method and the inputs are the same.
"""

from __future__ import annotations

import html
import json

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
.mono { font-family: ui-monospace, monospace; font-size: 12px; }
footer { display: flex; justify-content: space-between; gap: 24px;
  border-top: 1px solid var(--line); padding-top: 18px;
  padding-bottom: 28px; margin-top: 28px; flex-wrap: wrap; }
.footer-brand { display: flex; align-items: center; gap: 8px; }
.footer-brand img { width: 28px; height: 28px; }
footer a { color: var(--indigo); text-decoration: none;
  margin-left: 16px; }
"""

_PHONE_CSS = """
:root { --ink: #0A0A0A; --muted: #5D6472; --line: #E4E4EC;
  --indigo: #4F46E5; --indigo-dark: #3730A3; --lavender: #EEF0FF;
  --warn: #B54708; --bad: #B42318; }
* { box-sizing: border-box; }
body { margin: 0; background: #FFFFFF; color: var(--ink);
  font-family: "Plus Jakarta Sans", system-ui, sans-serif;
  font-size: 17px; }
header, main, footer { padding: 0 14px; }
h1 { font-size: 22px; margin: 10px 0 4px; }
h2 { font-size: 18px; margin: 18px 0 8px; }
.muted { color: var(--muted); font-size: 15px; }
.card { border: 1px solid var(--line); border-radius: 12px;
  padding: 14px; margin: 12px 0; }
.card.blocked { border-color: var(--bad); }
.badge { display: inline-block; background: var(--lavender);
  color: var(--indigo-dark); border-radius: 999px; padding: 2px 10px;
  font-size: 14px; margin-right: 4px; }
.badge.bad { background: #FEF3F2; color: var(--bad); }
.badge.stale { background: #FEF3E2; color: var(--warn); }
.mono { font-family: ui-monospace, monospace; font-size: 13px; }
form.act { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 8px; }
form.act input, form.act select { font-size: 16px; padding: 10px;
  border: 1px solid var(--line); border-radius: 8px; flex: 1 1 40%; }
form.act button { font-size: 17px; padding: 12px 18px; min-height: 48px;
  border: 0; border-radius: 10px; background: var(--indigo);
  color: #FFFFFF; flex: 1 1 100%; }
form.act button.reject { background: var(--bad); }
.result { font-size: 15px; color: var(--indigo-dark); }
footer { border-top: 1px solid var(--line); margin-top: 24px;
  padding-top: 14px; padding-bottom: 24px; }
footer a { color: var(--indigo); text-decoration: none; }
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, float):
        return f"{value:,.2f}"
    if value is None:
        return "—"
    return str(value)


def _footer() -> list[str]:
    return [
        "<footer>",
        "<div>",
        '<div class="footer-brand">'
        '<img src="https://trida.ai/logos-rounded/trida-rounded.png" '
        'alt="Trida AI"><strong>Trida AI</strong></div>',
        '<p class="muted">Every figure on this page is read from '
        "an artefact of record; the console composes reads and "
        "records acts — it computes no forecast and invents no "
        "number.</p>",
        "</div>",
        '<div><a href="https://trida.ai/">Visit Trida AI →</a>'
        '<a href="https://github.com/tridaai">View all blueprints →</a>'
        "</div>",
        "</footer>",
    ]


def _state_badge(state: str) -> str:
    if state == "degraded":
        return '<span class="badge bad">degraded</span>'
    if state in ("unverified", "retired", "superseded", "gapped"):
        return f'<span class="badge bad">{_esc(state)}</span>'
    if state in ("unmeasured", "not_measurable", "stale"):
        return f'<span class="badge stale">{_esc(state)}</span>'
    return f'<span class="badge">{_esc(state)}</span>'


# ---------------------------------------------------------------------------
# Desktop
# ---------------------------------------------------------------------------


def render_console(view: dict) -> str:
    """The desktop console page — a pure function of the view."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Operator console — Verdanta Foods trading desk</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="muted">Verdanta Foods — trading desk</p>',
        "<h1>Operator console</h1>",
        f'<p class="muted">For {_esc(view["board_date"])} · console '
        f'pack {_esc(view["pack_version"])} · the morning board, '
        "the review queue, event triage, open alerts and "
        "pre-flights in one read — every row names the artefact "
        "behind it.</p>",
        "</header>",
        "<main>",
    ]

    board = view["morning_board"]
    out.append('<section class="panel"><h2>Morning board — exceptions</h2>')
    out.append(
        f'<p class="muted">Board <span class="mono">'
        f'{_esc(board["board_id"])}</span> · {board["row_count"]} '
        "exception row(s). The full board renders at /board/html.</p>"
    )
    for section, rows in board["sections"].items():
        if not rows:
            continue
        out.append(f"<h3>{_esc(section)}</h3><table><tbody>")
        for row in rows:
            out.append(
                f"<tr><td>{_esc(row['headline'])}</td>"
                f'<td class="mono">{_esc(row["artefact_id"])}</td></tr>'
            )
        out.append("</tbody></table>")
    out.append("</section>")

    queue = view["review_queue"]
    out.append('<section class="panel"><h2>Forecast review queue</h2>')
    if not queue["rows"]:
        out.append("<p>No draft forecasts await review.</p>")
    else:
        out.append(
            "<table><thead><tr><th>Forecast</th><th>Series</th>"
            "<th>Accuracy</th><th>P50 7/30/90</th>"
            "<th>Prior official (Δ30d)</th><th>Events</th>"
            "<th>Blockers</th></tr></thead><tbody>"
        )
        for row in queue["rows"]:
            p50 = " / ".join(
                _fmt(row["p50_by_horizon"].get(h))
                for h in ("7", "30", "90")
            )
            prior = (
                f'{_esc(row["prior_official_id"])} '
                f'({row["delta_p50_30"]:+,.2f})'
                if row["prior_official_id"]
                else "none stands"
            )
            events = "; ".join(
                f"{flag['event_id']}: {flag['verification_status']}/"
                f"{flag['triage_state']}"
                for flag in row["events"]
            ) or "none"
            blockers = "; ".join(row["blockers"]) or "none"
            out.append(
                f'<tr><td class="mono">{_esc(row["forecast_id"])}'
                f'<br><span class="muted">as of '
                f'{_esc(row["as_of"])}</span></td>'
                f"<td>{_esc(row['commodity'])} / {_esc(row['market'])}</td>"
                f"<td>{_state_badge(row['accuracy_state'])}</td>"
                f"<td>{_esc(p50)}</td><td>{prior}</td>"
                f"<td>{_esc(events)}</td><td>{_esc(blockers)}</td></tr>"
            )
        out.append("</tbody></table>")
    if view["rejections"]:
        out.append('<p class="note">Rejected and closed:</p><table><tbody>')
        for rejection in view["rejections"]:
            out.append(
                f'<tr><td class="mono">{_esc(rejection["forecast_id"])}</td>'
                f"<td>rejected by {_esc(rejection['rejected_by'])} "
                f"({_esc(rejection['reason'])}) on "
                f"{_esc(rejection['decided_on'])}</td></tr>"
            )
        out.append("</tbody></table>")
    out.append("</section>")

    lanes = view["triage_queue"]
    out.append('<section class="panel"><h2>Event triage queue</h2>')
    if not lanes["rows"]:
        out.append("<p>No declared event awaits triage.</p>")
    else:
        for lane in ("unverified", "not_measurable", "verified"):
            rows = [r for r in lanes["rows"] if r["lane"] == lane]
            if not rows:
                continue
            out.append(
                f"<h3>{_esc(lane)} transmission</h3><table><tbody>"
            )
            for row in rows:
                out.append(
                    f'<tr><td class="mono">{_esc(row["event_id"])}</td>'
                    f"<td>{_esc(row['event_class'])} — "
                    f"{_esc(row['commodity'])}, window "
                    f"{_esc(row['window_start'])}.."
                    f"{_esc(row['window_end'] or 'open')}, claimed peak "
                    f"{_fmt(row['claimed_peak_log'])} log on "
                    f"{_esc(row['basis'])}, declared by "
                    f"{_esc(row['declared_by'])}</td></tr>"
                )
            out.append("</tbody></table>")
    out.append(
        '<p class="note">Acts: POST /market-events/{id}/triage/'
        "confirm|amend|retire — insert-only and attributed.</p>"
        "</section>"
    )

    alerts = view["open_alerts"]
    out.append('<section class="panel"><h2>Open alerts</h2>')
    if not alerts["rows"]:
        out.append("<p>No alert stands open.</p>")
    else:
        out.append("<table><tbody>")
        for alert in alerts["rows"]:
            state = alert["state"]
            out.append(
                f'<tr><td class="mono">{_esc(alert["alert_id"])}</td>'
                f"<td>{_esc(alert['kind'])} — {_esc(alert['commodity'])}"
                f" / {_esc(alert['market'] or '')}, severity "
                f"{_esc(alert['severity'])}, state "
                f"{_esc(state['state'])}, escalation rung "
                f"{_esc(state.get('rung') or '—')}</td></tr>"
            )
        out.append("</tbody></table>")
    out.append("</section>")

    out.append('<section class="panel"><h2>Coverage pre-flights</h2>')
    out.append(
        "<table><thead><tr><th>Series</th><th>State</th>"
        "<th>Last price</th><th>Sentiment</th><th>Gaps</th></tr>"
        "</thead><tbody>"
    )
    for row in view["preflights"]:
        gaps = "; ".join(row["gaps"]) or "none"
        out.append(
            f"<tr><td>{_esc(row['commodity'])} / {_esc(row['market'])}"
            f'<br><span class="mono">{_esc(row["report_id"])}</span></td>'
            f"<td>{_state_badge(row['state'])}</td>"
            f"<td>{_esc(row['last_observation_date'] or '—')}</td>"
            f"<td>{_esc(row['sentiment']['state'])}</td>"
            f"<td>{_esc(gaps)}</td></tr>"
        )
    out.append("</tbody></table></section>")

    if view["problems"]:
        out.append('<section class="panel"><h2>Record problems</h2>')
        for problem in view["problems"]:
            out.append(f"<p>{_esc(problem)}</p>")
        out.append("</section>")

    out.append("</main>")
    out.extend(_footer())
    out += ["</body>", "</html>"]
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Phone (F20-MF2)
# ---------------------------------------------------------------------------

_ACTION_JS = """
document.querySelectorAll('form.act').forEach(function (form) {
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var data = {kind: form.dataset.kind};
    new FormData(form).forEach(function (value, key) {
      if (value !== '') { data[key] = value; }
    });
    var target = form.parentElement.querySelector('.result');
    fetch('/console/actions', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    }).then(function (response) {
      return response.json().then(function (body) {
        target.textContent = response.ok
          ? 'Act recorded: ' + JSON.stringify(body)
          : 'Refused: ' + (body.detail || response.status);
      });
    }).catch(function (error) {
      target.textContent = 'Failed: ' + error;
    });
  });
});
"""


def _field(name: str, value: str, *, hidden: bool = False,
           placeholder: bool = False) -> tuple[str, str, bool, bool]:
    """One form field: (name, value, hidden, is_placeholder)."""
    return (name, value, hidden, placeholder)


def _act_form(kind: str, fields: list[tuple[str, str, bool, bool]],
              label: str, css: str = "") -> str:
    inputs = ""
    for name, value, hidden, placeholder in fields:
        if hidden:
            inputs += (
                f'<input type="hidden" name="{name}" '
                f'value="{_esc(value)}">'
            )
        elif placeholder:
            inputs += (
                f'<input name="{name}" placeholder="{_esc(value)}">'
            )
        else:
            inputs += (
                f'<input name="{name}" value="{_esc(value)}">'
            )
    return (
        f'<form class="act" data-kind="{_esc(kind)}">{inputs}'
        f'<button type="submit" class="{css}">{_esc(label)}</button>'
        '</form><p class="result"></p>'
    )


def render_console_phone(view: dict) -> str:
    """The phone-first exception inbox — a pure function of the view."""
    out = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, '
        'initial-scale=1">',
        "<title>Desk inbox — Verdanta Foods</title>",
        f"<style>{_PHONE_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        '<p class="muted">Verdanta Foods — trading desk</p>',
        "<h1>Desk inbox</h1>",
        f'<p class="muted">For {_esc(view["board_date"])} · '
        "exceptions first. Every action below records the same "
        "act the desktop path records.</p>",
        "</header>",
        "<main>",
    ]

    out.append("<h2>Review queue</h2>")
    queue = view["review_queue"]["rows"]
    if not queue:
        out.append('<div class="card"><p>No draft awaits review.</p></div>')
    for row in queue:
        blocked = bool(row["blockers"])
        out.append(f'<div class="card{" blocked" if blocked else ""}">')
        out.append(
            f"<p><strong>{_esc(row['commodity'])} / "
            f"{_esc(row['market'])}</strong> "
            f"{_state_badge(row['accuracy_state'])}</p>"
            f'<p class="mono">{_esc(row["forecast_id"])}</p>'
            f'<p class="muted">as of {_esc(row["as_of"])} · P50 30d '
            f"{_fmt(row['p50_by_horizon'].get('30'))}"
        )
        if row["prior_official_id"]:
            out.append(
                f" · prior official Δ {row['delta_p50_30']:+,.2f}"
            )
        out.append("</p>")
        for flag in row["events"]:
            out.append(
                f"<p>{_esc(flag['event_id'])}: "
                f"{_esc(flag['verification_status'])} / "
                f"{_esc(flag['triage_state'])}</p>"
            )
        for blocker in row["blockers"]:
            out.append(f'<p class="badge bad">{_esc(blocker)}</p>')
        out.append(
            _act_form(
                "approve_forecast",
                [
                    _field("forecast_id", row["forecast_id"], hidden=True),
                    _field("approver", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("decided_on", view["board_date"]),
                ],
                "Approve as official",
            )
        )
        out.append(
            _act_form(
                "reject_forecast",
                [
                    _field("forecast_id", row["forecast_id"], hidden=True),
                    _field("rejected_by", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("decided_on", view["board_date"]),
                    _field("reason", "Reason (pack vocabulary)",
                           placeholder=True),
                    _field("note", "Note", placeholder=True),
                ],
                "Reject draft",
                css="reject",
            )
        )
        out.append("</div>")

    out.append("<h2>Event triage</h2>")
    lanes = view["triage_queue"]["rows"]
    if not lanes:
        out.append('<div class="card"><p>No event awaits triage.</p></div>')
    for row in lanes:
        out.append('<div class="card">')
        out.append(
            f"<p><strong>{_esc(row['event_class'])} — "
            f"{_esc(row['commodity'])}</strong> "
            f"{_state_badge(row['lane'])}</p>"
            f'<p class="mono">{_esc(row["event_id"])}</p>'
            f'<p class="muted">window {_esc(row["window_start"])}..'
            f"{_esc(row['window_end'] or 'open')} · claimed peak "
            f"{_fmt(row['claimed_peak_log'])} log · declared by "
            f"{_esc(row['declared_by'])}</p>"
        )
        out.append(
            _act_form(
                "confirm_event",
                [
                    _field("event_id", row["event_id"], hidden=True),
                    _field("actor", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("acted_on", view["board_date"]),
                    _field("note", "Note", placeholder=True),
                ],
                "Confirm for official view",
            )
        )
        out.append(
            _act_form(
                "retire_event",
                [
                    _field("event_id", row["event_id"], hidden=True),
                    _field("actor", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("acted_on", view["board_date"]),
                    _field("note", "Note", placeholder=True),
                ],
                "Retire event",
                css="reject",
            )
        )
        out.append("</div>")

    out.append("<h2>Open alerts</h2>")
    alerts = view["open_alerts"]["rows"]
    if not alerts:
        out.append('<div class="card"><p>No alert stands open.</p></div>')
    for alert in alerts:
        state = alert["state"]
        out.append('<div class="card">')
        out.append(
            f"<p><strong>{_esc(alert['kind'])} — "
            f"{_esc(alert['commodity'])}</strong> "
            f"{_state_badge(alert['severity'])}</p>"
            f'<p class="mono">{_esc(alert["alert_id"])}</p>'
            f'<p class="muted">state {_esc(state["state"])} · rung '
            f"{_esc(state.get('rung') or '—')} · raised "
            f"{_esc(alert['raised_on'])}</p>"
        )
        out.append(
            _act_form(
                "acknowledge_alert",
                [
                    _field("alert_id", alert["alert_id"], hidden=True),
                    _field("actor", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("acted_at", view["board_date"] + "T09:00:00"),
                    _field("note", "Note", placeholder=True),
                ],
                "Acknowledge",
            )
        )
        out.append(
            _act_form(
                "close_alert",
                [
                    _field("alert_id", alert["alert_id"], hidden=True),
                    _field("actor", "Your name", placeholder=True),
                    _field("role", "Your role", placeholder=True),
                    _field("acted_at", view["board_date"] + "T09:00:00"),
                    _field("reason", "Close reason (pack vocabulary)",
                           placeholder=True),
                    _field("note", "Note", placeholder=True),
                ],
                "Close alert",
                css="reject",
            )
        )
        out.append("</div>")

    board = view["morning_board"]
    out.append("<h2>Morning board</h2>")
    out.append(
        f'<div class="card"><p>{board["row_count"]} exception '
        "row(s) on today's board — the full board renders on the "
        "desktop console.</p></div>"
    )
    out.append("</main>")
    out.extend(_footer())
    out.append(f"<script>{_ACTION_JS}</script>")
    out += ["</body>", "</html>"]
    return "\n".join(out)
