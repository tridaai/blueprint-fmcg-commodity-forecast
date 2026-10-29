"""The thin-data engine — coverage, driver states, tiers, in code.

Everything here is computed from the store and the pinned
forecast, under the pack's stated rules:

- **Windows.** For each of the pack's windows ending at the
  forecast's as_of, the operating days are the catalogue's
  reporting pattern for the commodity (Mon–Sat, or Tue/Fri for
  coffee); coverage is the share of those days carrying a
  modal-price observation, and every missing operating day is
  named by date.
- **Drivers.** Each catalogue driver is present, missing or
  stale, with its last observed date. Sentiment is judged as a
  driver too: from the forecast's own sentiment line (estimated
  or not-estimable, with the failing floors named there) and
  the last index week on record.
- **Volatility.** The realised width is the central-80% band
  the series' own price history implies: per-day variance is
  pooled from consecutive observed log returns, each return
  scaled by the square root of the days it spans, and widened
  to the horizon by the square-root rule. The forecast band's
  width is stated against it as a ratio.
- **Tiers.** Per horizon, exactly the pack's ladder: unproven
  without a record; a base tier from the measured bars; then
  the caps (unreported driver, stale driver, degraded record,
  not-estimable sentiment), never raising.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from fmcg_forecast.catalogue import ALL_DRIVERS, BY_NAME, CommoditySpec
from fmcg_forecast.forecast.models import Forecast
from fmcg_forecast.thin.models import (
    DriverState,
    HorizonConfidence,
    ThinAssessment,
    WindowCoverage,
    assessment_content_id,
)
from fmcg_forecast.thin.pack import TIER_RANK, ThinDataPack


class ThinDataError(RuntimeError):
    """The series or forecast cannot be assessed as asked."""


def operating_days(spec: CommoditySpec, start: date, end: date) -> list[date]:
    """The days the market reports between start and end,
    under the catalogue's reporting pattern for the commodity."""
    days: list[date] = []
    current = start
    while current <= end:
        weekday = current.weekday()  # Mon=0 .. Sun=6
        if spec.reporting == "tue_fri":
            if weekday in (1, 4):  # Tue, Fri
                days.append(current)
        elif weekday != 6:  # Mon-Sat
            days.append(current)
        current += timedelta(days=1)
    return days


def _realised_vol_width(
    price_rows, horizon_days: int, pack: ThinDataPack
) -> float | None:
    """The central-80% width (percent of price) the series' own
    realised daily volatility implies at this horizon."""
    squared_per_day: list[float] = []
    for previous, current in zip(price_rows, price_rows[1:]):
        gap = (current.obs_date - previous.obs_date).days
        if gap < 1 or previous.value <= 0 or current.value <= 0:
            continue
        log_return = math.log(current.value / previous.value)
        squared_per_day.append((log_return**2) / gap)
    if len(squared_per_day) < 2:
        return None
    sigma_day = math.sqrt(sum(squared_per_day) / len(squared_per_day))
    half = pack.band_z * sigma_day * math.sqrt(horizon_days)
    return round((math.exp(half) - math.exp(-half)) * 100.0, 4)


def compute_assessment(
    store, forecast: Forecast, pack: ThinDataPack
) -> ThinAssessment:
    """Compute the assessment for one pinned forecast."""
    spec = BY_NAME.get(forecast.commodity)
    if spec is None or forecast.market not in {m.market for m in spec.markets}:
        raise ThinDataError(
            f"no catalogue series {forecast.commodity}/{forecast.market} "
            "to assess — the thin-data pack judges catalogue series"
        )
    as_of = forecast.as_of

    price_rows = store.series(
        forecast.commodity, forecast.market, "modal_price", None, as_of
    )
    observed_price_dates = {r.obs_date for r in price_rows}

    windows: list[WindowCoverage] = []
    for window_days in pack.windows_days:
        start = as_of - timedelta(days=window_days - 1)
        expected = operating_days(spec, start, as_of)
        present = [d for d in expected if d in observed_price_dates]
        missing = [d for d in expected if d not in observed_price_dates]
        windows.append(
            WindowCoverage(
                window_days=window_days,
                start=start,
                end=as_of,
                operating_days=len(expected),
                observed_days=len(present),
                coverage=(
                    round(len(present) / len(expected), 4) if expected else 1.0
                ),
                missing_operating_dates=missing,
            )
        )
    by_window = {w.window_days: w for w in windows}
    history_coverage = by_window[365].coverage if 365 in by_window else 0.0

    # -- driver states ------------------------------------------------
    drivers: list[DriverState] = []
    for driver in ALL_DRIVERS:
        if driver not in spec.drivers:
            drivers.append(
                DriverState(
                    driver=driver,
                    status="missing",
                    last_observed_date=None,
                    age_days=None,
                    detail=(
                        f"the catalogue does not report {driver} for "
                        f"{spec.commodity} — a named gap, never zero-filled"
                    ),
                )
            )
            continue
        rows = store.series(forecast.commodity, forecast.market, driver, None, as_of)
        if not rows:
            drivers.append(
                DriverState(
                    driver=driver,
                    status="missing",
                    last_observed_date=None,
                    age_days=None,
                    detail=(
                        f"{driver} is reported for {spec.commodity} but no "
                        "observation stands in the store on or before as_of"
                    ),
                )
            )
            continue
        last = rows[-1].obs_date
        age = (as_of - last).days
        if age > pack.stale_after_days:
            drivers.append(
                DriverState(
                    driver=driver,
                    status="stale",
                    last_observed_date=last,
                    age_days=age,
                    detail=(
                        f"last observed {last.isoformat()}, {age} days "
                        f"before as_of — beyond the pack's "
                        f"{pack.stale_after_days}-day staleness bar"
                    ),
                )
            )
        else:
            drivers.append(
                DriverState(
                    driver=driver,
                    status="present",
                    last_observed_date=last,
                    age_days=age,
                    detail=f"last observed {last.isoformat()}",
                )
            )

    # Sentiment, judged as a driver from the forecast's own line
    # and the index weeks on record.
    indices = [
        idx for idx in store.list_indices(forecast.commodity)
        if idx.week_end <= as_of
    ]
    last_index_end = max((idx.week_end for idx in indices), default=None)
    sentiment_line = next(
        (line for line in forecast.lines if line.driver == "sentiment"), None
    )
    sentiment_state = (
        sentiment_line.input_summary.get("state")
        if sentiment_line is not None
        else None
    )
    if sentiment_line is None:
        drivers.append(
            DriverState(
                driver="sentiment",
                status="missing",
                last_observed_date=last_index_end,
                age_days=(
                    (as_of - last_index_end).days if last_index_end else None
                ),
                detail=(
                    "the forecast carries no sentiment line — the "
                    "corpus was not wired into this run"
                ),
            )
        )
    elif sentiment_state == "not_estimable":
        drivers.append(
            DriverState(
                driver="sentiment",
                status="missing",
                last_observed_date=last_index_end,
                age_days=(
                    (as_of - last_index_end).days if last_index_end else None
                ),
                detail=(
                    "sentiment is not estimable for this series — "
                    + str(sentiment_line.input_summary.get("reason", ""))
                ),
            )
        )
    elif last_index_end is None:
        drivers.append(
            DriverState(
                driver="sentiment",
                status="missing",
                last_observed_date=None,
                age_days=None,
                detail="no sentiment index week stands on record",
            )
        )
    else:
        age = (as_of - last_index_end).days
        drivers.append(
            DriverState(
                driver="sentiment",
                status="stale" if age > pack.sentiment_stale_after_days else "present",
                last_observed_date=last_index_end,
                age_days=age,
                detail=(
                    f"last index week ended {last_index_end.isoformat()}"
                    + (
                        f", {age} days before as_of — beyond the pack's "
                        f"{pack.sentiment_stale_after_days}-day bar"
                        if age > pack.sentiment_stale_after_days
                        else ""
                    )
                ),
            )
        )

    named_gaps: list[str] = []
    for state in drivers:
        if state.status == "present":
            continue
        if state.status == "stale":
            named_gaps.append(
                f"{state.driver}: stale — last observed "
                f"{state.last_observed_date.isoformat() if state.last_observed_date else 'never'} "
                f"({state.age_days} days before as_of)"
            )
        elif state.last_observed_date is not None:
            named_gaps.append(
                f"{state.driver}: missing — last observed "
                f"{state.last_observed_date.isoformat()} ({state.detail})"
            )
        else:
            named_gaps.append(f"{state.driver}: missing — {state.detail}")

    # -- caps from the driver states ----------------------------------
    caps: list[tuple[int, str]] = []
    for state in drivers:
        if state.driver == "sentiment":
            continue
        if state.status == "missing":
            caps.append(
                (
                    TIER_RANK["guarded"],
                    f"{state.driver} is not reported for "
                    f"{forecast.commodity} — an unreported driver caps "
                    "the tier at guarded",
                )
            )
        elif state.status == "stale":
            caps.append(
                (
                    TIER_RANK["thin"],
                    f"{state.driver} is stale — last observed "
                    f"{state.last_observed_date} ({state.age_days} days "
                    "before as_of); a stale driver caps the tier at thin",
                )
            )
    sentiment_driver = next(d for d in drivers if d.driver == "sentiment")
    if sentiment_driver.status == "missing":
        caps.append(
            (
                TIER_RANK["guarded"],
                "sentiment is not estimable for this series — the "
                "missing driver caps the tier at guarded",
            )
        )
    elif sentiment_driver.status == "stale":
        caps.append(
            (
                TIER_RANK["thin"],
                "the sentiment index is stale — its last week ended "
                f"{sentiment_driver.last_observed_date}; a stale driver "
                "caps the tier at thin",
            )
        )

    # -- per-horizon tiers ---------------------------------------------
    trailing = [
        r for r in price_rows if r.obs_date > as_of - timedelta(days=365)
    ]
    slices = {}
    if forecast.accuracy is not None:
        slices = {s.horizon_days: s for s in forecast.accuracy.per_horizon}
    summaries = {s.horizon_days: s for s in forecast.horizons_summary}
    horizons: list[HorizonConfidence] = []
    record_ids: dict[str, str | None] = {}
    for horizon in (7, 30, 90):
        slice_ = slices.get(horizon)
        record_id = slice_.record_id if slice_ is not None else None
        record_ids[str(horizon)] = record_id
        accuracy_state = slice_.state if slice_ is not None else "unmeasured"
        summary = summaries[horizon]
        interval_width = round(
            (summary.p90 - summary.p10) / summary.p50 * 100.0, 4
        ) if summary.p50 else 0.0
        realised = _realised_vol_width(trailing, horizon, pack)
        ratio = (
            round(interval_width / realised, 4)
            if realised not in (None, 0.0)
            else None
        )
        window_cov = by_window[horizon].coverage if horizon in by_window else 0.0
        reasons: list[str] = []
        if slice_ is None or record_id is None:
            tier = "unproven"
            reasons.append(
                f"no accuracy record stands behind the {horizon}-day "
                "horizon — the series is unmeasured there, so no "
                "confidence tier is earned"
            )
            reasons.extend(reason for _, reason in caps)
        else:
            established_failures: list[str] = []
            guarded_failures: list[str] = []

            def _bar(failures: list[str], ok: bool, text: str) -> None:
                if not ok:
                    failures.append(text)

            _bar(
                established_failures,
                window_cov >= pack.established_window_coverage,
                f"own-window coverage {window_cov} is below the "
                f"established bar {pack.established_window_coverage}",
            )
            _bar(
                guarded_failures,
                window_cov >= pack.guarded_window_coverage,
                f"own-window coverage {window_cov} is below the "
                f"guarded bar {pack.guarded_window_coverage}",
            )
            _bar(
                established_failures,
                history_coverage >= pack.established_history_coverage,
                f"365-day coverage {history_coverage} is below the "
                f"established bar {pack.established_history_coverage}",
            )
            _bar(
                guarded_failures,
                history_coverage >= pack.guarded_history_coverage,
                f"365-day coverage {history_coverage} is below the "
                f"guarded bar {pack.guarded_history_coverage}",
            )
            _bar(
                established_failures,
                (slice_.mape or 0.0) <= pack.established_max_mape_pct,
                f"pooled MAPE {slice_.mape}% is above the established "
                f"bar {pack.established_max_mape_pct}%",
            )
            _bar(
                guarded_failures,
                (slice_.mape or 0.0) <= pack.guarded_max_mape_pct,
                f"pooled MAPE {slice_.mape}% is above the guarded "
                f"bar {pack.guarded_max_mape_pct}%",
            )
            _bar(
                established_failures,
                (slice_.coverage or 0.0) >= pack.established_min_band_coverage,
                f"realised band coverage {slice_.coverage} is below "
                f"the established bar {pack.established_min_band_coverage}",
            )
            _bar(
                guarded_failures,
                (slice_.coverage or 0.0) >= pack.guarded_min_band_coverage,
                f"realised band coverage {slice_.coverage} is below "
                f"the guarded bar {pack.guarded_min_band_coverage}",
            )
            if ratio is None:
                note = (
                    "the forecast band cannot be judged against "
                    "realised volatility — the price history states "
                    "no realised width"
                )
                established_failures.append(note)
                guarded_failures.append(note)
            else:
                if not (pack.established_ratio_min <= ratio <= pack.established_ratio_max):
                    established_failures.append(
                        f"the band-width ratio {ratio} against the "
                        "series' realised volatility is outside the "
                        f"established range {pack.established_ratio_min}.."
                        f"{pack.established_ratio_max}"
                    )
                if not (pack.guarded_ratio_min <= ratio <= pack.guarded_ratio_max):
                    guarded_failures.append(
                        f"the band-width ratio {ratio} against the "
                        "series' realised volatility is outside the "
                        f"guarded range {pack.guarded_ratio_min}.."
                        f"{pack.guarded_ratio_max}"
                    )
            if not established_failures:
                tier = "established"
            elif not guarded_failures:
                tier = "guarded"
                reasons.extend(established_failures)
            else:
                tier = "thin"
                reasons.extend(guarded_failures)
            if accuracy_state == "degraded":
                caps_for_horizon = caps + [
                    (
                        TIER_RANK["thin"],
                        "the accuracy record is degraded — its pooled "
                        "MAPE is above the accuracy pack's bar; a "
                        "degraded record caps the tier at thin",
                    )
                ]
            else:
                caps_for_horizon = caps
            for cap_rank, cap_reason in caps_for_horizon:
                if TIER_RANK[tier] > cap_rank:
                    tier = next(
                        name for name, rank in TIER_RANK.items() if rank == cap_rank
                    )
                reasons.append(cap_reason)
        horizons.append(
            HorizonConfidence(
                horizon_days=horizon,
                tier=tier,
                accuracy_state=accuracy_state,
                accuracy_record_id=record_id,
                mape=slice_.mape if slice_ is not None else None,
                band_coverage=slice_.coverage if slice_ is not None else None,
                window_coverage=window_cov,
                history_coverage=history_coverage,
                interval_width_pct=interval_width,
                realised_vol_width_pct=realised,
                interval_to_realised_ratio=ratio,
                reasons=reasons,
            )
        )

    summary_tier = min(
        (h.tier for h in horizons), key=lambda t: TIER_RANK[t]
    )
    assessment = ThinAssessment(
        assessment_id="THN-pending",
        commodity=forecast.commodity,
        market=forecast.market,
        as_of=as_of,
        forecast_id=forecast.forecast_id,
        accuracy_record_ids=record_ids,
        pack_version=pack.version,
        windows=windows,
        drivers=drivers,
        horizons=horizons,
        named_gaps=named_gaps,
        summary_tier=summary_tier,
    )
    assessment.assessment_id = assessment_content_id(assessment)
    return assessment
