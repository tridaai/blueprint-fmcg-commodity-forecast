"""The signal workflow every surface shares.

Compute is idempotent: the artefact is content-addressed over its
inputs, so computing the same series twice lands on the stored
artefact rather than a duplicate. Computing pins the series' head
forecast under the dashboard pack's stated head rule — the same
head every other surface reads — so a signal always names the
forecast the desk is actually looking at.
"""

from __future__ import annotations

from fmcg_forecast.dashboards.assemble import head_forecast
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.signals.engine import SignalError, compute_signal
from fmcg_forecast.signals.models import BuySignal
from fmcg_forecast.signals.pack import SignalPack, load_signal_pack
from fmcg_forecast.signals.verify import verify_signal
from fmcg_forecast.store import Store


class SignalNotFoundError(LookupError):
    """A named signal (or a series' head forecast) does not exist."""


class SignalService:
    def __init__(self, store: Store, pack: SignalPack | None = None):
        self.store = store
        self.pack = pack or load_signal_pack()

    # -- compute ---------------------------------------------------------

    def compute_for_forecast(self, forecast: Forecast) -> BuySignal:
        """The signal for one pinned forecast, stored if new."""
        signal = compute_signal(self.store, forecast, self.pack)
        if self.store.get_buy_signal(signal.signal_id) is None:
            self.store.insert_buy_signal(signal)
        return signal

    def compute_for_series(self, commodity: str, market: str) -> BuySignal:
        """The signal for a series' current head forecast."""
        head = head_forecast(self.store, commodity, market)
        if head is None:
            raise SignalNotFoundError(
                f"no forecast exists for {commodity} at {market} — "
                "run a forecast before asking for its signal"
            )
        return self.compute_for_forecast(head)

    def current_signal(
        self, commodity: str, market: str
    ) -> BuySignal | None:
        """The stored signal pinned to the series' head, if computed."""
        head = head_forecast(self.store, commodity, market)
        if head is None:
            return None
        for signal in self.store.list_buy_signals(commodity, market):
            if signal.forecast_id == head.forecast_id:
                return signal
        return None

    # -- reads -------------------------------------------------------------

    def get_signal(self, signal_id: str) -> BuySignal:
        signal = self.store.get_buy_signal(signal_id)
        if signal is None:
            raise SignalNotFoundError(f"no buy signal {signal_id}")
        return signal

    def list_signals(
        self, commodity: str | None = None, market: str | None = None
    ) -> list[BuySignal]:
        return self.store.list_buy_signals(commodity, market)

    def verify_stored(self, signal_id: str) -> list[str]:
        return verify_signal(self.store, self.get_signal(signal_id))

    def signal_view(self, signal_id: str) -> dict:
        """One signal, with its reasoning on the face of the read."""
        signal = self.get_signal(signal_id)
        view = signal.model_dump(mode="json")
        view["problems"] = verify_signal(self.store, signal)
        return view


__all__ = [
    "SignalError",
    "SignalNotFoundError",
    "SignalService",
]
