"""Measurement: checking a declared transmission against history.

Two distinct reads, kept distinct on purpose:

- **Transmission measurement** (``measure_event_effect``) — the
  verifier's number. Per market, the ratio of ratios of mean
  modal price: the post/pre move across the event's own windows,
  divided by the same calendar windows one year earlier. The
  year-earlier leg differences out the harvest seasonality and
  the trend, leaving the event. The measured effect is the median
  across the commodity's markets, judged against the claim by the
  pack's stated band. This is the same seasonally-matched method
  the R1 eval gate grades the planted shocks with.
- **The impact view** (``event_impact``) — the desk's post-event
  review surface. The no-event baseline is the forecast engine's
  baseline method fitted on pre-window history ONLY, projected
  through the window and its decay tail; each observed day's log
  effect is measured against that projection.

Neither read ever creates or edits an event. A window that cannot
be measured — too little history before it, or not yet begun —
reads ``not_measurable`` with the reason named, never a guessed
number.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Protocol

import numpy as np

from fmcg_forecast.catalogue import BY_NAME
from fmcg_forecast.events.models import (
    EventImpact,
    EventImpactDay,
    MarketEvent,
    TransmissionVerification,
)
from fmcg_forecast.events.pack import EventPack
from fmcg_forecast.models import Observation


class SeriesSource(Protocol):
    """The read surface measurement is allowed: observations only."""

    def series(
        self,
        commodity: str,
        market: str,
        driver: str,
        start: date | None = None,
        end: date | None = None,
    ) -> list[Observation]: ...


def _mean(rows: list[Observation]) -> float | None:
    if not rows:
        return None
    return sum(r.value for r in rows) / len(rows)


def _market_measured_log_effect(
    source: SeriesSource, event: MarketEvent, market: str, pack: EventPack
) -> float | None:
    """One market's seasonally-matched measured log effect.

    None when any of the four measurement windows falls outside
    observed history for that market.
    """
    start = event.window_start
    shift = timedelta(days=pack.measurement_prior_year_shift_days)
    post_open = start + timedelta(days=pack.measurement_post_gap_days)
    post_close = post_open + timedelta(days=pack.measurement_post_span_days)
    if event.window_end is not None and event.window_end < post_close:
        post_close = event.window_end
    pre_open = start - timedelta(
        days=pack.measurement_pre_gap_days + pack.measurement_pre_span_days
    )
    pre_close = start - timedelta(days=pack.measurement_pre_gap_days)

    def window_mean(open_: date, close: date) -> float | None:
        return _mean(
            source.series(event.commodity, market, "modal_price", open_, close)
        )

    pre = window_mean(pre_open, pre_close)
    post = window_mean(post_open, post_close)
    pre_py = window_mean(pre_open - shift, pre_close - shift)
    post_py = window_mean(post_open - shift, post_close - shift)
    if None in (pre, post, pre_py, post_py):
        return None
    ratio = (post / pre) / (post_py / pre_py)  # type: ignore[operator]
    return math.log(ratio)


def measure_event_effect(
    source: SeriesSource, event: MarketEvent, pack: EventPack
) -> TransmissionVerification:
    """Judge the event's claimed transmission against history."""
    spec = BY_NAME[event.commodity]
    claimed = event.transmission.peak_log_price_effect
    per_market: dict[str, float | None] = {}
    for market in spec.markets:
        per_market[market.market] = _market_measured_log_effect(
            source, event, market.market, pack
        )
    measured_values = sorted(v for v in per_market.values() if v is not None)
    band = [pack.verified_band_low, pack.verified_band_high]
    if not measured_values:
        return TransmissionVerification(
            event_id=event.event_id,
            status="not_measurable",
            claimed_log_effect=claimed,
            measured_log_effect=None,
            measured_ratio=None,
            per_market_log_effects=per_market,
            ratio_to_claim=None,
            band=band,
            reason=(
                "no market of this commodity has all four measurement "
                "windows inside observed history — the event is too "
                "early, too recent, or still in its window; the claim "
                "stands on its stated basis alone"
            ),
            pack_version=pack.version,
        )
    mid = len(measured_values) // 2
    if len(measured_values) % 2 == 1:
        measured = measured_values[mid]
    else:
        measured = (measured_values[mid - 1] + measured_values[mid]) / 2
    ratio_to_claim = measured / claimed
    sign_agrees = (measured > 0) == (claimed > 0) and measured != 0.0
    if sign_agrees and band[0] <= ratio_to_claim <= band[1]:
        status = "verified"
        reason = (
            f"the seasonally-matched measurement (x{math.exp(measured):.3f} "
            f"median across markets) sits inside the pack's stated band "
            f"[{band[0]}, {band[1]}] of the claimed peak "
            f"({claimed:+.3f} log)"
        )
    else:
        status = "unverified"
        if not sign_agrees:
            reason = (
                f"the seasonally-matched measurement "
                f"(x{math.exp(measured):.3f} median across markets) moves "
                "against the claimed direction — the transmission is "
                "flagged unverified on the event's face"
            )
        else:
            reason = (
                f"the seasonally-matched measurement "
                f"(x{math.exp(measured):.3f} median across markets) is "
                f"{ratio_to_claim:.2f}x the claimed peak ({claimed:+.3f} "
                f"log), outside the pack's stated band [{band[0]}, "
                f"{band[1]}] — the transmission is flagged unverified "
                "on the event's face"
            )
    return TransmissionVerification(
        event_id=event.event_id,
        status=status,  # type: ignore[arg-type]
        claimed_log_effect=claimed,
        measured_log_effect=round(measured, 4),
        measured_ratio=round(math.exp(measured), 4),
        per_market_log_effects={
            k: (round(v, 4) if v is not None else None)
            for k, v in per_market.items()
        },
        ratio_to_claim=round(ratio_to_claim, 4),
        band=band,
        reason=reason,
        pack_version=pack.version,
    )


def event_impact(
    source: SeriesSource, event: MarketEvent, market: str, pack: EventPack
) -> EventImpact:
    """The what-happened view: measured path vs no-event baseline."""
    rows = source.series(event.commodity, market, "modal_price")
    fit = [r for r in rows if r.obs_date < event.window_start]
    fit_span = (fit[-1].obs_date - fit[0].obs_date).days + 1 if fit else 0
    base = {
        "event_id": event.event_id,
        "commodity": event.commodity,
        "market": market,
        "window_start": event.window_start,
        "fit_obs": len(fit),
        "fit_span_days": fit_span,
    }
    if not rows or event.window_start > rows[-1].obs_date:
        return EventImpact(
            **base,
            state="not_measurable",
            reason=(
                "the event window has not begun in observed history — "
                "there is no measured path to review yet"
            ),
            tail_end=None,
            days=[],
            mean_log_effect=None,
            peak_log_effect=None,
            mean_price_ratio=None,
        )
    if len(fit) < pack.impact_min_obs or fit_span < pack.impact_min_span_days:
        return EventImpact(
            **base,
            state="not_measurable",
            reason=(
                f"only {len(fit)} pre-window observations spanning "
                f"{fit_span} days — the impact baseline needs at least "
                f"{pack.impact_min_obs} spanning {pack.impact_min_span_days}; "
                "the view is named not measurable rather than fitted "
                "on too little history"
            ),
            tail_end=None,
            days=[],
            mean_log_effect=None,
            peak_log_effect=None,
            mean_price_ratio=None,
        )

    anchor = rows[0].obs_date

    def design(dates: list[date]) -> np.ndarray:
        years = np.array([(d - anchor).days / 365.25 for d in dates])
        angle = np.array(
            [2.0 * math.pi * d.timetuple().tm_yday / 365.25 for d in dates]
        )
        return np.column_stack(
            [np.ones(len(dates)), years, np.sin(angle), np.cos(angle)]
        )

    fit_dates = [r.obs_date for r in fit]
    y = np.log(np.array([float(r.value) for r in fit]))
    coef, *_ = np.linalg.lstsq(design(fit_dates), y, rcond=None)

    if event.window_end is not None:
        tail_end = event.window_end + timedelta(days=event.decay_days)
    else:
        tail_end = rows[-1].obs_date
    review = [
        r for r in rows if event.window_start <= r.obs_date <= tail_end
    ]
    projected = np.exp(design([r.obs_date for r in review]) @ coef)
    days: list[EventImpactDay] = []
    window_effects: list[float] = []
    for row, baseline in zip(review, projected):
        effect = math.log(float(row.value)) - math.log(float(baseline))
        days.append(
            EventImpactDay(
                obs_date=row.obs_date,
                observed=float(row.value),
                baseline_estimate=round(float(baseline), 2),
                log_effect=round(effect, 4),
            )
        )
        if event.window_end is None or row.obs_date <= event.window_end:
            window_effects.append(effect)
    mean_effect = sum(window_effects) / len(window_effects) if window_effects else None
    peak_effect = (
        max(window_effects, key=abs) if window_effects else None
    )
    return EventImpact(
        **base,
        state="measured",
        reason=(
            "baseline fitted on pre-window history only and projected "
            "through the window and its decay tail (the pack's impact "
            "rule); every figure is computed from observed rows"
        ),
        tail_end=tail_end,
        days=days,
        mean_log_effect=round(mean_effect, 4) if mean_effect is not None else None,
        peak_log_effect=round(peak_effect, 4) if peak_effect is not None else None,
        mean_price_ratio=(
            round(math.exp(mean_effect), 4) if mean_effect is not None else None
        ),
    )
