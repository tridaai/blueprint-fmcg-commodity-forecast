"""Re-performance verification for buy-signal artefacts.

The verifier trusts nothing stored: it recomputes the signal from
the pinned forecast artefact and the store under the signal's own
pack version — spot, drift, band, accuracy state, event overlaps,
the decision table, the caps, the reasoning lines — and compares
field for field, content address included. It also runs the
forecast verifier over the pinned artefact, so a signal resting
on a tampered forecast fails here too. The hard rules are checked
on their own lines: a degraded or unmeasured series carrying
``buy_now`` is a problem even if everything else re-performs.
"""

from __future__ import annotations

from fmcg_forecast.forecast.verify import verify_forecast
from fmcg_forecast.signals.engine import SignalError, compute_signal
from fmcg_forecast.signals.models import BuySignal, signal_content_id
from fmcg_forecast.signals.pack import load_signal_pack
from fmcg_forecast.store import Store


def verify_signal(store: Store, signal: BuySignal) -> list[str]:
    """Return the list of problems with a stored signal artefact."""
    problems: list[str] = []
    if signal_content_id(signal) != signal.signal_id:
        problems.append(
            f"content id mismatch: stored {signal.signal_id}, recomputed "
            f"{signal_content_id(signal)} — the artefact was altered "
            "after computation"
        )
    forecast = store.get_forecast(signal.forecast_id)
    if forecast is None:
        problems.append(
            f"pinned forecast {signal.forecast_id} is not in the store"
        )
        return problems
    problems.extend(
        f"pinned forecast: {p}" for p in verify_forecast(forecast)
    )
    try:
        pack = load_signal_pack(signal.pack_version)
    except ValueError as exc:
        problems.append(str(exc))
        return problems
    try:
        fresh = compute_signal(store, forecast, pack)
    except SignalError as exc:
        problems.append(f"signal no longer re-performs: {exc}")
        return problems
    stored = signal.model_dump(mode="json")
    recomputed = fresh.model_dump(mode="json")
    for key in sorted(stored):
        if stored[key] != recomputed[key]:
            problems.append(
                f"field {key} differs on re-performance: stored "
                f"{stored[key]!r}, recomputed {recomputed[key]!r}"
            )
    if signal.accuracy_state == "degraded" and signal.value == "buy_now":
        problems.append(
            "hard rule breached: a degraded series carries a strong "
            "buy signal — the pack caps it at phased"
        )
    if signal.accuracy_state == "unmeasured" and signal.value == "buy_now":
        problems.append(
            "hard rule breached: an unmeasured series carries a strong "
            "buy signal — the pack caps it at phased"
        )
    return problems
