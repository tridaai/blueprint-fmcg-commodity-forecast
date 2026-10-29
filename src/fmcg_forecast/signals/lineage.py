"""Provenance walks for signal artefacts (R8, extending F20-DR3).

A signal figure walks figure -> signal artefact -> the pinned
forecast artefact -> that forecast's own input facts, terminating
at stored facts exactly as the R7 walks do. The signal fact kind
is an artefact kind, never a terminal one: the walk must pass
through it to the forecast behind the call.
"""

from __future__ import annotations

from fmcg_forecast.dashboards.lineage import forecast_lineage
from fmcg_forecast.dashboards.models import LineageFact
from fmcg_forecast.signals.models import BuySignal
from fmcg_forecast.store import Store


def signal_lineage(store: Store, signal: BuySignal) -> list[LineageFact]:
    """The walk behind a signal figure: signal, then its forecast."""
    facts = [
        LineageFact(
            kind="buy_signal",
            ref=signal.signal_id,
            detail=(
                f"buy-window signal {signal.value} (base "
                f"{signal.base_value}) from forecast "
                f"{signal.forecast_id} as of "
                f"{signal.as_of.isoformat()}, drift "
                f"{signal.drift_pct:+.2f}% at "
                f"{signal.horizon_days} days, accuracy "
                f"{signal.accuracy_state}, under signal pack "
                f"{signal.pack_version}"
            ),
            source=f"signal engine, pack {signal.pack_version}",
            fact_date=signal.as_of,
        )
    ]
    forecast = store.get_forecast(signal.forecast_id)
    if forecast is not None:
        facts.extend(forecast_lineage(store, forecast))
    return facts
