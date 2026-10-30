"""The morning desk board (F20-OW1): the exception inbox.

One opening screen for the desk head: today's forecast
changes, degraded series, active events, data gaps and pending
human gates — ranked by the pack's section order, exceptions
first, not a chart gallery. Every row is derived from
artefacts of record and links the artefact behind it; a clean
series does not appear. The board is itself an artefact —
content-addressed over (date, rows), insert-only — so the
board a desk head opened in the morning is the board that can
be re-read in the evening.
"""

from __future__ import annotations

from datetime import date, timedelta

from fmcg_forecast.catalogue import BY_NAME, COMMODITIES
from fmcg_forecast.dashboards.assemble import head_forecast
from fmcg_forecast.dashboards.models import BoardRow, DeskBoard, board_content_id
from fmcg_forecast.dashboards.pack import DashboardPack
from fmcg_forecast.events.service import EventService
from fmcg_forecast.thin.engine import compute_assessment
from fmcg_forecast.thin.pack import load_thin_data_pack


def _series():
    for spec in COMMODITIES:
        for market in spec.markets:
            yield spec, market.market, market.display


def _display_for(commodity: str) -> tuple[str, bool]:
    """The catalogue's display name for a commodity, and whether
    the catalogue names it at all. The store holds series the
    catalogue does not — the signal engine's hand-computed
    fixture series is one, and the store takes any series key by
    design — while the sections below read the whole record. An
    artefact from such a series is named as recorded and badged
    not_in_catalogue: never a crash, and never a silent drop
    from the exception inbox."""
    spec = BY_NAME.get(commodity)
    if spec is None:
        return commodity, False
    return spec.display, True


def build_board(
    store, events: EventService, pack: DashboardPack, board_date: date
) -> DeskBoard:
    """Compute the board for one date from artefacts only."""
    rows: list[BoardRow] = []

    # -- degraded series (Law 2: flagged, never hidden) -----------
    for spec, market, market_display in _series():
        head = head_forecast(store, spec.commodity, market)
        if head is None or head.accuracy is None:
            continue
        if head.accuracy.state != "degraded":
            continue
        degraded = [
            s for s in head.accuracy.per_horizon if s.state == "degraded"
        ]
        figures: dict = {}
        record_ids: list[str] = []
        for slice_ in degraded:
            if slice_.mape is not None:
                figures[f"mape_{slice_.horizon_days}d"] = slice_.mape
            if slice_.record_id is not None:
                record_ids.append(slice_.record_id)
        horizons = "/".join(str(s.horizon_days) for s in degraded)
        rows.append(
            BoardRow(
                kind="degraded",
                commodity=spec.commodity,
                market=market,
                headline=(
                    f"{spec.display} at {market_display} is degraded "
                    f"at the {horizons}-day horizon(s) — pooled "
                    "backtest MAPE above the accuracy pack's bar; "
                    "the flag rides on every read of the forecast"
                ),
                artefact_id=head.forecast_id,
                artefact_ids=[head.forecast_id, *record_ids],
                figures=figures,
            )
        )

    # -- pending human gates ---------------------------------------
    # A draft a rejection act stands against (R13) is not pending:
    # it has been reviewed and sent back, and the desk's remedy is
    # a new run — the review queue carries it as a closed record,
    # not this inbox.
    pending: list[BoardRow] = []
    for forecast in store.list_forecasts():
        if forecast.status != "draft":
            continue
        if store.get_forecast_rejection(forecast.forecast_id) is not None:
            continue
        display, in_catalogue = _display_for(forecast.commodity)
        figures = {"accuracy_state": (
            forecast.accuracy.state if forecast.accuracy else "unmeasured"
        )}
        headline = (
            f"forecast {forecast.forecast_id} for "
            f"{display} at {forecast.market} (as of "
            f"{forecast.as_of.isoformat()}) awaits the "
            "approval act"
        )
        if not in_catalogue:
            figures["catalogue"] = "not_in_catalogue"
            headline += (
                " — a series outside the desk catalogue, "
                "named as recorded"
            )
        pending.append(
            BoardRow(
                kind="pending_gate",
                commodity=forecast.commodity,
                market=forecast.market,
                headline=headline,
                artefact_id=forecast.forecast_id,
                artefact_ids=[forecast.forecast_id],
                figures=figures,
            )
        )
    for run in store.list_scenarios():
        if run.status != "draft":
            continue
        display, in_catalogue = _display_for(run.commodity)
        figures = {"author": run.author}
        headline = (
            f"scenario {run.scenario_id} for {display} "
            f"at {run.market} (a pinned fork of "
            f"{run.base_forecast_id}) awaits the adoption "
            "gate"
        )
        if not in_catalogue:
            figures["catalogue"] = "not_in_catalogue"
            headline += (
                " — a series outside the desk catalogue, "
                "named as recorded"
            )
        pending.append(
            BoardRow(
                kind="pending_gate",
                commodity=run.commodity,
                market=run.market,
                headline=headline,
                artefact_id=run.scenario_id,
                artefact_ids=[run.scenario_id, run.base_forecast_id],
                figures=figures,
            )
        )
    rows.extend(sorted(pending, key=lambda r: r.artefact_id))

    # -- active declared events --------------------------------------
    active: list[BoardRow] = []
    for event in store.list_market_events():
        window_end = event.window_end
        tail_end = (
            window_end + timedelta(days=event.decay_days)
            if window_end is not None
            else None
        )
        in_window = event.window_start <= board_date and (
            window_end is None or board_date <= window_end
        )
        in_tail = (
            window_end is not None
            and board_date > window_end
            and tail_end is not None
            and board_date <= tail_end
        )
        if not (in_window or in_tail):
            continue
        verdict = events.verify_event(event.event_id)
        display, in_catalogue = _display_for(event.commodity)
        phase = "in its window" if in_window else "in its decay tail"
        figures = {
            "claimed_peak_log": event.transmission.peak_log_price_effect,
            "verification_status": verdict.status,
        }
        if not in_catalogue:
            figures["catalogue"] = "not_in_catalogue"
        if verdict.measured_ratio is not None:
            figures["measured_ratio"] = verdict.measured_ratio
        active.append(
            BoardRow(
                kind="active_event",
                commodity=event.commodity,
                market=None,
                headline=(
                    f"{event.event_class} for {display}: "
                    f"window {event.window_start.isoformat()}.."
                    f"{window_end.isoformat() if window_end else 'open'} "
                    f"is {phase} today — claimed peak "
                    f"{event.transmission.peak_log_price_effect:+.3f} "
                    f"log via {event.transmission.channel}, "
                    f"transmission {verdict.status}"
                    + (
                        " — a series outside the desk catalogue, "
                        "named as recorded"
                        if not in_catalogue
                        else ""
                    )
                ),
                artefact_id=event.event_id,
                artefact_ids=[event.event_id],
                figures=figures,
            )
        )
    rows.extend(
        sorted(active, key=lambda r: (r.figures.get("claimed_peak_log", 0), r.artefact_id))
    )

    # -- forecast changes ---------------------------------------------
    changes: list[BoardRow] = []
    for spec, market, market_display in _series():
        runs = [
            f
            for f in store.list_forecasts(spec.commodity, market)
            if f.as_of <= board_date
        ]
        by_as_of: dict[date, list] = {}
        for forecast in runs:
            by_as_of.setdefault(forecast.as_of, []).append(forecast)
        if len(by_as_of) < 2:
            continue
        dates = sorted(by_as_of)
        latest = max(
            by_as_of[dates[-1]],
            key=lambda f: (f.status == "official", f.forecast_id),
        )
        previous = max(
            by_as_of[dates[-2]],
            key=lambda f: (f.status == "official", f.forecast_id),
        )
        latest_30 = next(
            s for s in latest.horizons_summary if s.horizon_days == 30
        )
        previous_30 = next(
            s for s in previous.horizons_summary if s.horizon_days == 30
        )
        delta = round(latest_30.p50 - previous_30.p50, 2)
        if delta == 0:
            continue
        changes.append(
            BoardRow(
                kind="forecast_change",
                commodity=spec.commodity,
                market=market,
                headline=(
                    f"{spec.display} at {market_display}: the "
                    f"30-day P50 moved {delta:+.2f} INR/quintal "
                    f"between the {previous.as_of.isoformat()} run "
                    f"and the {latest.as_of.isoformat()} run"
                ),
                artefact_id=latest.forecast_id,
                artefact_ids=[latest.forecast_id, previous.forecast_id],
                figures={
                    "p50_30_before": previous_30.p50,
                    "p50_30_after": latest_30.p50,
                    "delta_p50_30": delta,
                },
            )
        )
    rows.extend(
        sorted(
            changes,
            key=lambda r: (-abs(float(r.figures["delta_p50_30"])), r.artefact_id),
        )
    )

    # -- named data gaps ------------------------------------------------
    # The row names the head forecast's own gaps and, since R10,
    # every thin gap the series' assessment names — missing and
    # stale drivers with their last observed dates — with the
    # earned confidence tiers on its face.
    thin_pack = load_thin_data_pack()
    for spec, market, market_display in _series():
        head = head_forecast(store, spec.commodity, market)
        if head is None:
            continue
        thin = compute_assessment(store, head, thin_pack)
        if not head.missing_drivers and not thin.named_gaps:
            continue
        tiers = ", ".join(
            f"{h.horizon_days}d {h.tier}" for h in thin.horizons
        )
        rows.append(
            BoardRow(
                kind="data_gap",
                commodity=spec.commodity,
                market=market,
                headline=(
                    f"{spec.display} at {market_display}: named "
                    "gaps on the head forecast — "
                    + ", ".join(head.missing_drivers)
                    + "; thin-data gaps: "
                    + ("; ".join(thin.named_gaps) if thin.named_gaps else "none")
                    + f"; confidence tiers {tiers} "
                    f"(thin-data pack {thin.pack_version}) "
                    "(wide bands and named gaps, never fake "
                    "precision)"
                ),
                artefact_id=head.forecast_id,
                artefact_ids=[head.forecast_id],
                figures={
                    "missing_drivers": ", ".join(head.missing_drivers),
                    "thin_named_gaps": "; ".join(thin.named_gaps),
                    "confidence_tiers": tiers,
                },
            )
        )

    # -- buy-window signals (R8) ------------------------------------
    # Appended after the pack's sections: the signal pack is its
    # own versioned pack, so its rows do not join the dashboard
    # pack's stated section list — the renderer and the board
    # view surface them under their own heading. A row exists
    # only where a signal has actually been computed for the
    # series' head forecast, and only when the call asks for
    # action (buy_now or phased — a wait is the absence of an
    # exception). Ranked: strong buys first, then by the size
    # of the move the call rests on.
    signal_rows: list[BoardRow] = []
    for spec, market, market_display in _series():
        head = head_forecast(store, spec.commodity, market)
        if head is None:
            continue
        signal = next(
            (
                s
                for s in store.list_buy_signals(spec.commodity, market)
                if s.forecast_id == head.forecast_id
            ),
            None,
        )
        if signal is None or signal.value == "wait":
            continue
        headline = (
            f"{signal.value} — {spec.display} at {market_display}: "
            f"{signal.horizon_days}-day drift "
            f"{signal.drift_pct:+.2f}% against spot, accuracy "
            f"{signal.accuracy_state}, under signal pack "
            f"{signal.pack_version}"
        )
        if signal.caps_applied:
            headline += f"; capped: {', '.join(signal.caps_applied)}"
        if signal.active_events:
            headline += (
                "; in declared event window: "
                + ", ".join(e.event_id for e in signal.active_events)
            )
        signal_rows.append(
            BoardRow(
                kind="signal",
                commodity=spec.commodity,
                market=market,
                headline=headline,
                artefact_id=signal.signal_id,
                artefact_ids=[signal.signal_id, signal.forecast_id],
                figures={
                    "drift_pct": signal.drift_pct,
                    "band_width_pct": signal.band_width_pct,
                    "accuracy_state": signal.accuracy_state,
                    "signal": signal.value,
                },
            )
        )
    rows.extend(
        sorted(
            signal_rows,
            key=lambda r: (
                0 if r.figures.get("signal") == "buy_now" else 1,
                -abs(float(r.figures["drift_pct"])),
                r.artefact_id,
            ),
        )
    )

    board = DeskBoard(
        board_id="BOARD-pending",
        board_date=board_date,
        pack_version=pack.version,
        rows=rows,
    )
    board.board_id = board_content_id(board)
    return board
