"""Forecast commentary: drafted by the model, disciplined by figures.

The agent step (Law 1): the model port drafts prose around a forecast
artefact, but the only figures it may state are figures the artefact
carries. Before a draft may be stored, every decimal figure in the
text is extracted and checked against the artefact's values; a draft
that states a number the engine did not compute is refused
wholesale — never edited into compliance, never stored.
"""

from __future__ import annotations

import re

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.forecast.models import HORIZONS, Forecast

# Decimal figures only: prices and factors carry decimals in this
# system, while counts and calendar dates are integers — the rule is
# that every *figure* (a measured quantity) must trace to the
# artefact.
FIGURE_RE = re.compile(r"-?\d{1,3}(?:,\d{3})+\.\d+|-?\d+\.\d+")
FIGURE_TOLERANCE = 0.005


def allowed_figures(forecast: Forecast) -> set[float]:
    """Every decimal figure the artefact itself states."""
    values: set[float] = set()
    for day in forecast.days:
        values.update(
            [day.baseline, day.p10, day.p50, day.p90, day.events_adjustment]
        )
        values.update(day.contributions.values())
    for line in forecast.lines:
        values.update(line.at_horizon.values())
        if line.driver == "sentiment":
            latest = line.input_summary.get("latest_index_value")
            if isinstance(latest, (int, float)):
                values.add(float(latest))
    values.add(forecast.method.sparsity.multiplier)
    if forecast.accuracy is not None:
        for slice_ in forecast.accuracy.per_horizon:
            for value in (slice_.mae, slice_.mape, slice_.bias, slice_.coverage):
                if value is not None:
                    values.add(value)
    return values


def verify_commentary(text: str, forecast: Forecast) -> list[str]:
    """Return the figures in ``text`` that the artefact does not carry."""
    allowed = allowed_figures(forecast)
    problems: list[str] = []
    for token in FIGURE_RE.findall(text):
        value = float(token.replace(",", ""))
        if not any(abs(value - a) <= FIGURE_TOLERANCE for a in allowed):
            problems.append(
                f"figure {token} does not appear in forecast {forecast.forecast_id}"
            )
    return problems


def commentary_subject(forecast: Forecast) -> str:
    spec = BY_NAME[forecast.commodity]
    market_display = next(
        m.display for m in spec.markets if m.market == forecast.market
    )
    return (
        f"{spec.display} at {market_display} — desk forecast as of "
        f"{forecast.as_of.isoformat()}"
    )


def commentary_figures(forecast: Forecast) -> dict[str, str]:
    """The figures handed to the model port — all read off the artefact."""
    by_horizon = {s.horizon_days: s for s in forecast.horizons_summary}
    figures: dict[str, str] = {}
    for h in HORIZONS:
        figures[f"P50 at {h} days (INR/quintal)"] = f"{by_horizon[h].p50:.2f}"
    figures["P10 at 30 days (INR/quintal)"] = f"{by_horizon[30].p10:.2f}"
    figures["P90 at 30 days (INR/quintal)"] = f"{by_horizon[30].p90:.2f}"
    figures["Baseline at 30 days (INR/quintal)"] = f"{by_horizon[30].baseline:.2f}"
    for name in sorted(by_horizon[30].contributions):
        figures[f"{name} contribution at 30 days (INR/quintal)"] = (
            f"{by_horizon[30].contributions[name]:.2f}"
        )
    figures["Sparsity widening factor"] = f"{forecast.method.sparsity.multiplier:.4f}"
    sentiment = next(
        (line for line in forecast.lines if line.driver == "sentiment"), None
    )
    if sentiment is not None and sentiment.input_summary.get("state") == "estimated":
        latest = sentiment.input_summary.get("latest_index_value")
        cited = sentiment.input_summary.get("cited_item_ids") or []
        if isinstance(latest, (int, float)):
            figures["Sentiment index (latest week)"] = f"{latest:.4f}"
            # A sentiment reading is handed to the model only with
            # its provenance attached: the direction word and the
            # items behind it travel together, and the claim
            # verifier checks the pairing against the stored
            # extractions before the draft may be stored.
            if cited and latest >= 0.05:
                figures["Sentiment reading (direction per cited items)"] = (
                    f"supportive — items {', '.join(cited)}"
                )
            elif cited and latest <= -0.05:
                figures["Sentiment reading (direction per cited items)"] = (
                    f"headwind — items {', '.join(cited)}"
                )
    if forecast.accuracy is not None:
        figures["Backtest accuracy state"] = forecast.accuracy.state
        for slice_ in forecast.accuracy.per_horizon:
            if slice_.mape is None:
                continue
            h = slice_.horizon_days
            figures[f"Backtest MAPE at {h} days (%)"] = f"{slice_.mape:.2f}"
            figures[f"Backtest interval coverage at {h} days"] = (
                f"{slice_.coverage:.4f}"
            )
    return figures
