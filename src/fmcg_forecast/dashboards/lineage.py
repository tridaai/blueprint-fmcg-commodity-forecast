"""Figure lineage: the walk from a figure to stored facts.

Every figure a dashboard renders carries its lineage (F20-DR3):
figure -> the artefact it was read from -> the input facts that
artefact rests on -> source + date, terminating at stored facts
— observation rows, sentiment items, event declarations, the
dataset manifest. The builders here construct walks only from
what the store actually holds; the verifier (verify.py) then
re-checks every fact against the store, so a walk that names a
fact the store does not hold cannot survive verification, and a
figure without a complete walk cannot render.
"""

from __future__ import annotations

from datetime import date

from fmcg_forecast.dashboards.models import LineageFact
from fmcg_forecast.events.models import MarketEvent
from fmcg_forecast.forecast.models import AccuracyRecord, Forecast
from fmcg_forecast.scenarios.models import ScenarioRun
from fmcg_forecast.sentiment.models import SentimentIndex

# Which observation series each forecast driver line rests on.
_DRIVER_SERIES = {
    "arrivals": ("arrivals",),
    "stock_level": ("stock_level",),
    "trade_flow": ("import_flow", "export_flow"),
    "weather_index": ("weather_index",),
}


def manifest_fact(store) -> LineageFact | None:
    manifest = store.get_manifest()
    if manifest is None:
        return None
    return LineageFact(
        kind="manifest",
        ref=manifest.history_digest[:12],
        detail=(
            f"dataset manifest: {manifest.history_rows} history "
            f"rows, seed {manifest.seed}, generator "
            f"{manifest.generator_version}"
        ),
        source="dataset generator manifest, loaded at ingest",
        fact_date=manifest.history_end,
    )


def observation_fact(
    store, commodity: str, market: str, driver: str, end: date | None = None
) -> LineageFact | None:
    """The terminal fact for one observation series: its stored
    row count and last observed date, as the store holds them."""
    rows = store.series(commodity, market, driver, end=end)
    if not rows:
        return None
    return LineageFact(
        kind="observation_series",
        ref=f"{commodity}/{market}/{driver}",
        detail=(
            f"{len(rows)} {driver} observations for "
            f"{commodity}/{market}, "
            f"{rows[0].obs_date.isoformat()}.."
            f"{rows[-1].obs_date.isoformat()}"
        ),
        source="observation store",
        fact_date=rows[-1].obs_date,
        count=len(rows),
        last_date=rows[-1].obs_date,
    )


def forecast_fact(forecast: Forecast) -> LineageFact:
    return LineageFact(
        kind="forecast",
        ref=forecast.forecast_id,
        detail=(
            f"forecast artefact for {forecast.commodity}/"
            f"{forecast.market} as of {forecast.as_of.isoformat()} "
            f"(engine {forecast.engine_version}, status "
            f"{forecast.status})"
        ),
        source="forecast engine run, recorded in the store",
        fact_date=forecast.as_of,
    )


def forecast_lineage(store, forecast: Forecast) -> list[LineageFact]:
    """The walk behind a forecast panel's price figures: the
    artefact, the observation series its estimation read, the
    sentiment index and cited items behind an estimated
    sentiment line, the declared events it applied, and the
    dataset manifest."""
    facts: list[LineageFact] = [forecast_fact(forecast)]
    price = observation_fact(
        store, forecast.commodity, forecast.market, "modal_price",
        end=forecast.as_of,
    )
    if price is not None:
        facts.append(price)
    seen_drivers: set[str] = set()
    for line in forecast.lines:
        for driver in _DRIVER_SERIES.get(line.driver, ()):
            if driver in seen_drivers:
                continue
            seen_drivers.add(driver)
            fact = observation_fact(
                store, forecast.commodity, forecast.market, driver,
                end=forecast.as_of,
            )
            if fact is not None:
                facts.append(fact)
    sentiment_line = next(
        (line for line in forecast.lines if line.driver == "sentiment"), None
    )
    if (
        sentiment_line is not None
        and sentiment_line.input_summary.get("state") == "estimated"
    ):
        week_start_raw = sentiment_line.input_summary.get("latest_week_start")
        if week_start_raw:
            index = store.get_index(
                forecast.commodity, date.fromisoformat(str(week_start_raw))
            )
            if index is not None:
                facts.append(
                    LineageFact(
                        kind="sentiment_index",
                        ref=index.index_id,
                        detail=(
                            f"weekly sentiment index for "
                            f"{index.commodity}, week of "
                            f"{index.week_start.isoformat()}: "
                            f"value {index.value:+.4f} from "
                            f"{index.n_items} classified items"
                        ),
                        source="sentiment index computed in code "
                        "from stored extractions",
                        fact_date=index.week_start,
                    )
                )
                for item_id in sentiment_line.input_summary.get(
                    "cited_item_ids", []
                ):
                    item = store.get_sentiment_item(item_id)
                    if item is not None:
                        facts.append(
                            LineageFact(
                                kind="sentiment_item",
                                ref=item.item_id,
                                detail=(
                                    "news/policy item cited behind "
                                    f"the index: {item.headline}"
                                ),
                                source=item.source,
                                fact_date=item.item_date,
                            )
                        )
    for event_id in forecast.method.events_applied:
        event = store.get_market_event(event_id)
        if event is not None:
            facts.append(event_fact(event))
    manifest = manifest_fact(store)
    if manifest is not None:
        facts.append(manifest)
    return facts


def accuracy_lineage(store, record: AccuracyRecord) -> list[LineageFact]:
    """The walk behind an accuracy figure: the ledger record,
    and the realised price series its backtests scored against."""
    origins = ", ".join(d.isoformat() for d in record.origins)
    facts: list[LineageFact] = [
        LineageFact(
            kind="accuracy_record",
            ref=record.record_id,
            detail=(
                f"accuracy ledger record for {record.commodity}/"
                f"{record.market} at {record.horizon_days} days: "
                f"pooled over {record.n_results} origins "
                f"({origins}), {record.n_days} scored days, "
                f"degraded bar {record.degraded_threshold_mape_pct}% "
                f"(pack {record.pack_version})"
            ),
            source="accuracy ledger, rebuilt by the backtest harness",
            fact_date=record.origins[-1] if record.origins else None,
        )
    ]
    price = observation_fact(
        store, record.commodity, record.market, "modal_price"
    )
    if price is not None:
        facts.append(price)
    return facts


def index_lineage(store, index: SentimentIndex) -> list[LineageFact]:
    """The walk behind a sentiment panel: the index artefact and
    every item whose stored extraction the value was computed
    from — each with its source and date."""
    facts: list[LineageFact] = [
        LineageFact(
            kind="sentiment_index",
            ref=index.index_id,
            detail=(
                f"weekly sentiment index for {index.commodity}, "
                f"week of {index.week_start.isoformat()}: value "
                f"{index.value:+.4f} from {index.n_items} "
                f"classified items (pack {index.pack_version})"
            ),
            source="sentiment index computed in code from stored "
            "extractions",
            fact_date=index.week_start,
        )
    ]
    by_extraction = {
        e.extraction_id: e for e in store.list_extractions(index.commodity)
    }
    for extraction_id in index.extraction_ids:
        extraction = by_extraction.get(extraction_id)
        if extraction is None:
            continue
        item = store.get_sentiment_item(extraction.item_id)
        if item is None:
            continue
        facts.append(
            LineageFact(
                kind="sentiment_item",
                ref=item.item_id,
                detail=(
                    f"news/policy item: {item.headline} "
                    f"(extraction {extraction.extraction_id}: "
                    f"direction {extraction.direction}, strength "
                    f"{extraction.strength})"
                ),
                source=item.source,
                fact_date=item.item_date,
            )
        )
    return facts


def event_fact(event: MarketEvent) -> LineageFact:
    window_end = (
        event.window_end.isoformat() if event.window_end else "open"
    )
    return LineageFact(
        kind="event_declaration",
        ref=event.event_id,
        detail=(
            f"declared {event.event_class} for {event.commodity}, "
            f"window {event.window_start.isoformat()}..{window_end}, "
            f"claimed peak "
            f"{event.transmission.peak_log_price_effect:+.3f} log "
            f"via {event.transmission.channel} "
            f"({event.transmission.basis})"
        ),
        source=f"declared by {event.declared_by}",
        fact_date=event.declared_on,
    )


def event_lineage(store, event: MarketEvent) -> list[LineageFact]:
    """The walk behind an event figure: the declaration itself,
    and the price series the transmission measurement reads."""
    facts: list[LineageFact] = [event_fact(event)]
    from fmcg_forecast.catalogue import BY_NAME

    spec = BY_NAME.get(event.commodity)
    if spec is not None:
        for market in spec.markets:
            fact = observation_fact(
                store, event.commodity, market.market, "modal_price"
            )
            if fact is not None:
                facts.append(fact)
    return facts


def scenario_lineage(store, run: ScenarioRun) -> list[LineageFact]:
    """The walk behind a scenario figure: the run (a pinned fork),
    its base forecast, and the base series' price facts."""
    facts: list[LineageFact] = [
        LineageFact(
            kind="scenario_run",
            ref=run.scenario_id,
            detail=(
                f"scenario run by {run.author}: a pinned fork of "
                f"{run.base_forecast_id} for {run.commodity}/"
                f"{run.market} under request {run.request_id} "
                f"(pack {run.pack_version})"
            ),
            source="scenario studio run, recorded in the store",
            fact_date=run.created_on,
        )
    ]
    base = store.get_forecast(run.base_forecast_id)
    if base is not None:
        facts.append(forecast_fact(base))
        price = observation_fact(
            store, base.commodity, base.market, "modal_price",
            end=base.as_of,
        )
        if price is not None:
            facts.append(price)
    manifest = manifest_fact(store)
    if manifest is not None:
        facts.append(manifest)
    return facts
