"""The offline scenario grammar: desk words -> bounded levers.

The scenario pack states the grammar; this module performs it.
A what-if is split into clauses, and each clause must match
exactly one catalogue shape (the patterns below). A clause that
matches nothing is refused with the clause named verbatim — the
parser never guesses, never silently reinterprets, and never
invents a lever the desk did not state. A value outside its
lever's pack bound is refused with the bound named. Event
keywords ('the tariff', 'the export ban', 'the drought') resolve
against the candidate events the caller supplies — the events
applied in the base forecast — and an ambiguous or absent match
is a refusal, not a pick.

The hosted model profiles produce the same lever schema through
structured outputs and the same pack validation downstream; this
deterministic grammar is the offline profile's performance of
the port, and the grammar the eval gate grades.
"""

from __future__ import annotations

import re

from fmcg_forecast.scenarios.models import LeverApplication
from fmcg_forecast.scenarios.pack import ScenarioPack

_NUM = r"(\d+(?:\.\d+)?)"
_SNUM = r"([+-]?\d+(?:\.\d+)?)"
_PCT = r"\s?(?:%|percent)"
_EVT = r"(evt-[a-z0-9]+(?:-[a-z0-9]+)?)"

_NUMBER_WORDS = {
    "another": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}

_KEYWORD_CLASSES = {
    "tariff": "tariff_change",
    "import duty": "tariff_change",
    "export ban": "export_restriction",
    "ban": "export_restriction",
    "drought": "weather_shock",
}

_CLASS_WORDS = {
    "tariff change": "tariff_change",
    "tariff": "tariff_change",
    "export restriction": "export_restriction",
    "export ban": "export_restriction",
    "import policy": "import_policy",
    "weather shock": "weather_shock",
    "logistics disruption": "logistics_disruption",
    "demand shock": "demand_shock",
}
_CLASS_ALT = "|".join(sorted(_CLASS_WORDS, key=len, reverse=True))
_KEYWORD_ALT = "|".join(sorted(_KEYWORD_CLASSES, key=len, reverse=True))
_MONTH_ALT = "|".join(list(_NUMBER_WORDS) + [r"\d+"])


class ParseRefusal(RuntimeError):
    """A what-if (or one clause of it) does not fit the catalogue."""

    def __init__(self, clause: str, reason: str):
        super().__init__(f"clause {clause!r} refused: {reason}")
        self.clause = clause
        self.reason = reason


def _bound_check(
    pack: ScenarioPack, lever: str, value: float, clause: str
) -> None:
    spec = pack.levers[lever]
    if not (spec.min_value <= value <= spec.max_value):
        raise ParseRefusal(
            clause,
            f"{lever} value {value:g} is outside the scenario "
            f"pack's bound [{spec.min_value:g}, {spec.max_value:g}] "
            f"({spec.unit}) — the desk may not move a lever past "
            "the bound the pack states",
        )


def _resolve_keyword_event(
    keyword: str,
    events: list[dict],
    clause: str,
) -> str:
    event_class = _KEYWORD_CLASSES[keyword]
    matches = [e for e in events if e.get("event_class") == event_class]
    if not matches:
        raise ParseRefusal(
            clause,
            f"no {event_class} event is in the resolution context "
            f"(the events applied in the base forecast) for "
            f"'{keyword}' to extend — name the event by id, or run "
            "the base with the event declared",
        )
    if len(matches) > 1:
        ids = ", ".join(sorted(e["event_id"] for e in matches))
        raise ParseRefusal(
            clause,
            f"'{keyword}' is ambiguous: {len(matches)} "
            f"{event_class} events are in the base forecast "
            f"({ids}) — extend one by id instead",
        )
    return matches[0]["event_id"]


def _canonical_event_id(raw: str, events: list[dict]) -> str:
    for event in events:
        if event["event_id"].lower() == raw.lower():
            return event["event_id"]
    return "EVT-" + raw[4:]


def _parse_clause(
    clause: str,
    events: list[dict],
    pack: ScenarioPack,
) -> LeverApplication:
    """Match one clause against exactly one catalogue shape."""

    def lever(name: str, **kwargs) -> LeverApplication:
        return LeverApplication(lever=name, clause=clause, **kwargs)

    m = re.fullmatch(
        rf"arrivals? (?:drop|drops|fall|falls|decline|declines|decrease|decreases) (?:by )?{_NUM}{_PCT}",
        clause,
    )
    if m:
        value = -float(m.group(1))
        _bound_check(pack, "arrivals_shift_pct", value, clause)
        return lever("arrivals_shift_pct", value=value)
    m = re.fullmatch(
        rf"arrivals? (?:rise|rises|increase|increases|grow|grows) (?:by )?{_NUM}{_PCT}",
        clause,
    )
    if m:
        value = float(m.group(1))
        _bound_check(pack, "arrivals_shift_pct", value, clause)
        return lever("arrivals_shift_pct", value=value)
    m = re.fullmatch(rf"arrivals? (up|down) {_NUM}{_PCT}", clause)
    if m:
        value = float(m.group(2)) * (1 if m.group(1) == "up" else -1)
        _bound_check(pack, "arrivals_shift_pct", value, clause)
        return lever("arrivals_shift_pct", value=value)

    m = re.fullmatch(
        rf"stock cover (?:rises|increases|grows) (?:by )?{_NUM} days?", clause
    )
    if m:
        value = float(m.group(1))
        _bound_check(pack, "stock_cover_days", value, clause)
        return lever("stock_cover_days", value=value)
    m = re.fullmatch(
        rf"stock cover (?:falls|drops|declines|decreases) (?:by )?{_NUM} days?",
        clause,
    )
    if m:
        value = -float(m.group(1))
        _bound_check(pack, "stock_cover_days", value, clause)
        return lever("stock_cover_days", value=value)
    m = re.fullmatch(rf"stock cover (up|down) {_NUM} days?", clause)
    if m:
        value = float(m.group(2)) * (1 if m.group(1) == "up" else -1)
        _bound_check(pack, "stock_cover_days", value, clause)
        return lever("stock_cover_days", value=value)

    m = re.fullmatch(
        rf"(?:trade flow|imports) (?:rise|rises|increase|increases|grow|grows) (?:by )?{_NUM}{_PCT}",
        clause,
    )
    if m:
        value = float(m.group(1))
        _bound_check(pack, "trade_flow_shift_pct", value, clause)
        return lever("trade_flow_shift_pct", value=value)
    m = re.fullmatch(
        rf"(?:trade flow|imports) (?:drop|drops|fall|falls|decline|declines|decrease|decreases) (?:by )?{_NUM}{_PCT}",
        clause,
    )
    if m:
        value = -float(m.group(1))
        _bound_check(pack, "trade_flow_shift_pct", value, clause)
        return lever("trade_flow_shift_pct", value=value)
    m = re.fullmatch(rf"(?:trade flow|imports) (up|down) {_NUM}{_PCT}", clause)
    if m:
        value = float(m.group(2)) * (1 if m.group(1) == "up" else -1)
        _bound_check(pack, "trade_flow_shift_pct", value, clause)
        return lever("trade_flow_shift_pct", value=value)

    m = re.fullmatch(rf"weather (?:index )?deviation (?:of )?{_SNUM}", clause)
    if m:
        value = float(m.group(1))
        _bound_check(pack, "weather_deviation", value, clause)
        return lever("weather_deviation", value=value)
    m = re.fullmatch(
        rf"weather index (?:rises|increases) (?:by )?{_NUM}", clause
    )
    if m:
        value = float(m.group(1))
        _bound_check(pack, "weather_deviation", value, clause)
        return lever("weather_deviation", value=value)
    m = re.fullmatch(
        rf"weather index (?:falls|drops|declines) (?:by )?{_NUM}", clause
    )
    if m:
        value = -float(m.group(1))
        _bound_check(pack, "weather_deviation", value, clause)
        return lever("weather_deviation", value=value)

    m = re.fullmatch(rf"sentiment (?:index )?override (?:to )?{_SNUM}", clause)
    if m:
        value = float(m.group(1))
        _bound_check(pack, "sentiment_override", value, clause)
        return lever("sentiment_override", value=value)
    m = re.fullmatch(rf"sentiment (?:index )?to {_SNUM}", clause)
    if m:
        value = float(m.group(1))
        _bound_check(pack, "sentiment_override", value, clause)
        return lever("sentiment_override", value=value)

    m = re.fullmatch(
        rf"(?:the )?({_KEYWORD_ALT}) (?:stays|holds|continues|lasts) "
        rf"(?:for )?({_MONTH_ALT}) (?:more )?months?",
        clause,
    )
    if m:
        token = m.group(2)
        months = _NUMBER_WORDS.get(token)
        if months is None:
            months = int(token)
        days = months * pack.days_per_month
        _bound_check(pack, "event_extension", float(days), clause)
        event_id = _resolve_keyword_event(m.group(1), events, clause)
        return lever("event_extension", event_id=event_id, extra_days=days)
    m = re.fullmatch(
        rf"(?:the )?({_KEYWORD_ALT}) (?:stays|holds|continues) (?:for )?(\d+) more days",
        clause,
    )
    if m:
        days = int(m.group(2))
        _bound_check(pack, "event_extension", float(days), clause)
        event_id = _resolve_keyword_event(m.group(1), events, clause)
        return lever("event_extension", event_id=event_id, extra_days=days)
    m = re.fullmatch(rf"extend event {_EVT} by (\d+) days", clause)
    if m:
        days = int(m.group(2))
        _bound_check(pack, "event_extension", float(days), clause)
        return lever(
            "event_extension",
            event_id=_canonical_event_id(m.group(1), events),
            extra_days=days,
        )
    m = re.fullmatch(rf"(?:add|include) event {_EVT}", clause)
    if m:
        return lever(
            "event", event_id=_canonical_event_id(m.group(1), events)
        )

    m = re.fullmatch(
        rf"(?:a |an )?(?:new )?({_CLASS_ALT}) (?:pushes|lifts|raises) prices "
        rf"(?:up )?(?:by )?{_NUM}{_PCT} for {_NUM} days?",
        clause,
    )
    if m:
        pct, duration = float(m.group(2)), int(float(m.group(3)))
        _bound_check(pack, "hypothetical_event", pct, clause)
        _duration_check(pack, duration, clause)
        return lever(
            "hypothetical_event",
            value=pct,
            event_class=_CLASS_WORDS[m.group(1)],
            start_offset_days=0,
            duration_days=duration,
        )
    m = re.fullmatch(
        rf"(?:a |an )?(?:new )?({_CLASS_ALT}) (?:cuts|lowers|drops) prices "
        rf"(?:down )?(?:by )?{_NUM}{_PCT} for {_NUM} days?",
        clause,
    )
    if m:
        pct, duration = -float(m.group(2)), int(float(m.group(3)))
        _bound_check(pack, "hypothetical_event", pct, clause)
        _duration_check(pack, duration, clause)
        return lever(
            "hypothetical_event",
            value=pct,
            event_class=_CLASS_WORDS[m.group(1)],
            start_offset_days=0,
            duration_days=duration,
        )

    raise ParseRefusal(
        clause,
        "it matches no shape in the scenario pack's lever "
        "catalogue — a what-if the catalogue cannot state is "
        "refused, never improvised",
    )


def _duration_check(pack: ScenarioPack, duration: int, clause: str) -> None:
    if not (1 <= duration <= pack.hypothetical_duration_max_days):
        raise ParseRefusal(
            clause,
            f"a hypothetical event's window of {duration} days is "
            f"outside the scenario pack's bound "
            f"[1, {pack.hypothetical_duration_max_days}] days",
        )


def parse_request_text(
    text: str,
    *,
    events: list[dict],
    pack: ScenarioPack,
) -> list[LeverApplication]:
    """Parse a typed what-if into the bounded lever set.

    ``events`` is the resolution context for event keywords and
    ids: dicts with ``event_id`` and ``event_class`` — the events
    applied in the base forecast, when a base is named.
    """
    cleaned = " ".join(text.strip().lower().split())
    cleaned = re.sub(r"^what if\s+", "", cleaned)
    cleaned = cleaned.rstrip("?").strip()
    if not cleaned:
        raise ParseRefusal(
            text.strip(),
            "the what-if is empty — there is nothing to parse",
        )
    clauses = [
        c.strip()
        for c in re.split(r"\s+and\s+|[,;]", cleaned)
        if c.strip()
    ]
    if not clauses:
        raise ParseRefusal(
            text.strip(), "the what-if carries no clause to parse"
        )
    levers: list[LeverApplication] = []
    moved_drivers: dict[str, str] = {}
    seen_events: dict[str, str] = {}
    seen_hypotheticals: set[tuple] = set()
    for clause in clauses:
        parsed = _parse_clause(clause, events, pack)
        driver = {
            "arrivals_shift_pct": "arrivals",
            "stock_cover_days": "stock_level",
            "trade_flow_shift_pct": "trade_flow",
            "weather_deviation": "weather_index",
            "sentiment_override": "sentiment",
        }.get(parsed.lever)
        if driver is not None:
            if driver in moved_drivers:
                raise ParseRefusal(
                    clause,
                    f"the {driver} driver is already moved by the "
                    f"clause {moved_drivers[driver]!r} — each driver "
                    "is moved by at most one clause, so the desk's "
                    "intent stays unambiguous",
                )
            moved_drivers[driver] = clause
        if parsed.lever in ("event", "event_extension"):
            if parsed.event_id in seen_events:
                raise ParseRefusal(
                    clause,
                    f"event {parsed.event_id} is already named by "
                    f"the clause {seen_events[parsed.event_id]!r}",
                )
            seen_events[parsed.event_id] = clause
        if parsed.lever == "hypothetical_event":
            key = (
                parsed.event_class,
                parsed.value,
                parsed.duration_days,
            )
            if key in seen_hypotheticals:
                raise ParseRefusal(
                    clause, "this hypothetical event is already stated"
                )
            seen_hypotheticals.add(key)
        levers.append(parsed)
    return levers
