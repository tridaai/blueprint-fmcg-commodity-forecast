"""The offline dashboard grammar: desk words -> stated panels.

The dashboard pack states the grammar's vocabulary; this module
performs it. A prompt is split into clauses, and each clause
must become exactly one panel from the pack's catalogue — or a
named gap panel stating what would answer it. The parser never
guesses a figure the catalogue does not state, never silently
drops a clause, and never renders a scenario fork the prompt
did not name (hypothetical discipline, carried from R6).

Resolution rules, as the pack states them:

- a clause naming a subject the catalogue cannot state
  (rainfall, a standalone stock position) is a gap panel naming
  why;
- a scenario is a panel only when named — by id, or as the
  adopted scenario for a series; the bare word "scenario" is a
  gap panel naming what naming it takes;
- a commodity named without a market is read at the
  commodity's reference market, with the default recorded in
  the panel's provenance; a market the commodity does not
  trade in is a gap panel naming its real markets;
- a clause with a panel kind but no commodity inherits the
  previous clause's commodity; a bare commodity clause asks
  for its forecast;
- duplicate asks (same kind, same scope) fold into one panel.

The hosted model profiles produce the same panel schema
through structured outputs and the same pack validation
downstream; this deterministic grammar is the offline
profile's performance of the port, and the grammar the eval
gate grades.
"""

from __future__ import annotations

import re

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.dashboards.pack import DashboardPack

_SCENARIO_ID = re.compile(r"(?i)\b(scn-[0-9a-f]{12})\b")

_ACCURACY_WORDS = ("accuracy", "accurate", "backtest", "mape")
_FORECAST_WORDS = ("forecast", "outlook", "price")


class DashboardParseRefusal(RuntimeError):
    """The prompt cannot become a spec at all (it is empty)."""


def _word_re(phrase: str) -> re.Pattern:
    return re.compile(r"\b" + re.escape(phrase) + r"\b")


def _find_commodity(clause: str, pack: DashboardPack) -> str | None:
    """The commodity a clause names: the longest alias that
    matches, so 'basmati rice' wins over 'rice'."""
    best: tuple[int, str] | None = None
    for commodity, aliases in pack.commodity_aliases.items():
        for alias in aliases:
            if _word_re(alias).search(clause):
                if best is None or len(alias) > best[0]:
                    best = (len(alias), commodity)
    return best[1] if best else None


def _find_market(clause: str, pack: DashboardPack) -> str | None:
    best: tuple[int, str] | None = None
    for market, words in pack.market_words.items():
        for word in words:
            if _word_re(word).search(clause):
                if best is None or len(word) > best[0]:
                    best = (len(word), market)
    return best[1] if best else None


def _display(commodity: str) -> str:
    return BY_NAME[commodity].display


def _market_display(commodity: str, market: str) -> str:
    for spec in BY_NAME[commodity].markets:
        if spec.market == market:
            return spec.display
    return market


def _title(pack: DashboardPack, kind: str, scope: dict) -> str:
    template = pack.panels[kind].title_template
    return template.format(
        display=_display(scope["commodity"]) if scope.get("commodity") else "",
        market=(
            _market_display(scope["commodity"], scope["market"])
            if scope.get("commodity") and scope.get("market")
            else ""
        ),
        scenario_id=scope.get("scenario_id", ""),
    )


def _gap(clause: str, needed: str, rule: str) -> dict:
    return {
        "kind": "gap",
        "title": f"Not available — {clause}",
        "scope": {},
        "clause": clause,
        "origin": {"via": "grammar", "rule": rule},
        "gap_needed": needed,
    }


def _panel(
    pack: DashboardPack,
    kind: str,
    scope: dict,
    clause: str,
    rule: str,
    defaults: list[str] | None = None,
) -> dict:
    origin: dict = {"via": "grammar", "rule": rule}
    if defaults:
        origin["defaults_applied"] = defaults
    return {
        "kind": kind,
        "title": _title(pack, kind, scope),
        "scope": scope,
        "clause": clause,
        "origin": origin,
        "gap_needed": None,
    }


def _split_clauses(text: str) -> list[str]:
    parts = re.split(r";|,|\s+and\s+", text)
    return [p.strip() for p in parts if p and p.strip()]


def parse_prompt_text(text: str, pack: DashboardPack) -> list[dict]:
    """Parse a desk prompt into panel dicts (see module docstring).

    Raises DashboardParseRefusal only when there is nothing to
    parse — an empty prompt. Every non-empty clause becomes a
    panel or a named gap panel.
    """
    cleaned = " ".join((text or "").split()).rstrip("?").strip()
    if not cleaned:
        raise DashboardParseRefusal(
            "the prompt is empty — a dashboard spec needs at "
            "least one clause to state or to name as a gap"
        )
    clauses = _split_clauses(cleaned.lower())
    if not clauses:
        raise DashboardParseRefusal(
            "the prompt holds no clause — a dashboard spec needs "
            "at least one clause to state or to name as a gap"
        )

    covered = ", ".join(spec.display for spec in BY_NAME.values())
    panels: list[dict] = []
    last_commodity: str | None = None
    last_market: str | None = None

    for clause in clauses:
        # 1. A subject the catalogue cannot state -> named gap.
        unstateable = next(
            (phrase for phrase in pack.unstateable_subjects if phrase in clause),
            None,
        )
        if unstateable is not None:
            panels.append(
                _gap(clause, pack.unstateable_subjects[unstateable],
                     "unstateable_subject")
            )
            continue

        commodity = _find_commodity(clause, pack)
        market = _find_market(clause, pack)

        # 2. Scenarios: rendered only when named.
        scenario_match = _SCENARIO_ID.search(clause)
        if scenario_match is not None:
            scenario_id = "SCN-" + scenario_match.group(1)[4:].lower()
            panels.append(
                _panel(
                    pack, "scenario_diff", {"scenario_id": scenario_id},
                    clause, "scenario_named_by_id",
                )
            )
            continue
        if "adopted scenario" in clause:
            scoped_commodity = commodity or last_commodity
            scoped_market = market or (
                last_market if scoped_commodity == last_commodity else None
            )
            if scoped_commodity is None:
                panels.append(
                    _gap(
                        clause,
                        "the series whose adopted scenario to show "
                        f"— name a commodity ({covered})",
                        "scenario_adopted_without_series",
                    )
                )
                continue
            defaults: list[str] = []
            if scoped_market is None:
                scoped_market = BY_NAME[scoped_commodity].markets[0].market
                defaults.append(
                    f"market defaulted to the reference market "
                    f"({scoped_market}) per the pack's default rule"
                )
            adopted_panel = _panel(
                pack,
                "scenario_diff",
                {
                    "scenario_ref": "adopted",
                    "commodity": scoped_commodity,
                    "market": scoped_market,
                },
                clause,
                "scenario_named_as_adopted",
                defaults,
            )
            adopted_panel["title"] = (
                f"Scenario — the adopted scenario for "
                f"{_display(scoped_commodity)} at "
                f"{_market_display(scoped_commodity, scoped_market)}"
            )
            panels.append(adopted_panel)
            last_commodity, last_market = scoped_commodity, scoped_market
            continue
        if "scenario" in clause:
            panels.append(
                _gap(
                    clause,
                    "a named scenario — a scenario id (SCN-…) or "
                    "'the adopted scenario for <commodity> at "
                    "<market>'; a dashboard renders a fork only "
                    "when the prompt names it",
                    "scenario_unnamed",
                )
            )
            continue

        # 3. The panel kind the clause asks for.
        kind: str | None = None
        rule = ""
        if any(word in clause for word in _ACCURACY_WORDS):
            kind, rule = "accuracy", "accuracy_clause"
        elif "sentiment" in clause:
            kind, rule = "sentiment", "sentiment_clause"
        elif "event" in clause or "shock" in clause:
            kind, rule = "events", "events_clause"
        elif any(word in clause for word in _FORECAST_WORDS):
            kind, rule = "forecast", "forecast_clause"
        elif commodity is not None:
            kind, rule = "forecast", "bare_series_default"

        if kind is None:
            panels.append(
                _gap(
                    clause,
                    "a figure in the dashboard pack's catalogue "
                    "(forecast, accuracy, sentiment, events, "
                    "scenario diff) — this clause names none",
                    "unknown_clause",
                )
            )
            continue

        # 4. Scope resolution.
        scoped_commodity = commodity or last_commodity
        if scoped_commodity is None:
            panels.append(
                _gap(
                    clause,
                    f"a commodity the desk covers ({covered}) — "
                    "this clause names none",
                    "missing_commodity",
                )
            )
            continue
        if kind in ("forecast", "accuracy"):
            defaults = []
            scoped_market = market
            if scoped_market is not None and scoped_market not in {
                m.market for m in BY_NAME[scoped_commodity].markets
            }:
                real = ", ".join(
                    m.display for m in BY_NAME[scoped_commodity].markets
                )
                panels.append(
                    _gap(
                        clause,
                        f"a market {_display(scoped_commodity)} "
                        f"trades in ({real}) — the named market "
                        "is not one of them",
                        "market_not_in_commodity",
                    )
                )
                continue
            if scoped_market is None:
                if last_commodity == scoped_commodity and last_market is not None:
                    scoped_market = last_market
                    defaults.append("market inherited from the previous clause")
                else:
                    scoped_market = BY_NAME[scoped_commodity].markets[0].market
                    defaults.append(
                        f"market defaulted to the reference market "
                        f"({scoped_market}) per the pack's default rule"
                    )
            scope = {"commodity": scoped_commodity, "market": scoped_market}
            panels.append(_panel(pack, kind, scope, clause, rule, defaults))
            last_commodity, last_market = scoped_commodity, scoped_market
        else:  # sentiment / events are per-commodity panels
            scope = {"commodity": scoped_commodity}
            panels.append(_panel(pack, kind, scope, clause, rule))
            last_commodity = scoped_commodity

    # 5. Duplicate asks fold into the first panel.
    folded: list[dict] = []
    seen: dict[tuple, dict] = {}
    for panel in panels:
        key = (
            panel["kind"],
            tuple(sorted(panel["scope"].items())),
            panel["gap_needed"],
            # Gap panels are per-clause: two different unanswerable
            # clauses never fold into one another.
            panel["clause"] if panel["kind"] == "gap" else "",
        )
        if key in seen:
            seen[key]["origin"].setdefault("also_asked_as", []).append(
                panel["clause"]
            )
            continue
        seen[key] = panel
        folded.append(panel)
    return folded
