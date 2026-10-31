"""The tool surface: the repo's reads in MCP shape.

The catalogue is data — each tool's name, stated
purpose, input schema and the surface it reads — so an
agent client can discover the surface the way the
design brief's MCP-shaped ports intend. A call answers
with figures only as (name, value, artefact id)
triples: every figure names the artefact it was read
from, and a figure the store cannot stand behind is
never produced — a tool asked for a missing artefact
refuses by name. The tools are reads of the same store
the API serves; calling one strikes nothing.
"""

from __future__ import annotations

from fmcg_forecast.integrations.service import IntegrationError
from fmcg_forecast.store import Store

TOOL_CATALOGUE: list[dict] = [
    {
        "name": "get_forecast",
        "description": "A forecast artefact's horizon "
        "figures: the P50 at each stated horizon, read "
        "from the forecast itself",
        "surface": "forecasts",
        "input_schema": {
            "type": "object",
            "properties": {"forecast_id": {"type": "string"}},
            "required": ["forecast_id"],
        },
    },
    {
        "name": "get_accuracy",
        "description": "The accuracy ledger's record for "
        "one series and horizon: MAPE, MAE, coverage and "
        "the degraded stamp, read from the record",
        "surface": "forecasts",
        "input_schema": {
            "type": "object",
            "properties": {
                "commodity": {"type": "string"},
                "market": {"type": "string"},
                "horizon_days": {"type": "integer"},
            },
            "required": ["commodity", "market", "horizon_days"],
        },
    },
    {
        "name": "get_signal",
        "description": "A buy signal's call and its "
        "deciding figures — drift, band width, the "
        "horizon P50 — read from the signal artefact",
        "surface": "signals",
        "input_schema": {
            "type": "object",
            "properties": {"signal_id": {"type": "string"}},
            "required": ["signal_id"],
        },
    },
    {
        "name": "get_event",
        "description": "A registry event's window and "
        "direction, read from the event artefact",
        "surface": "events",
        "input_schema": {
            "type": "object",
            "properties": {"event_id": {"type": "string"}},
            "required": ["event_id"],
        },
    },
    {
        "name": "get_dashboard_assembly",
        "description": "An assembled dashboard's figures, "
        "each carrying the artefact the assembler read "
        "it from",
        "surface": "dashboards",
        "input_schema": {
            "type": "object",
            "properties": {"assembly_id": {"type": "string"}},
            "required": ["assembly_id"],
        },
    },
]


def _figure(name: str, value, artefact_id: str) -> dict:
    return {"name": name, "value": value, "artefact_id": artefact_id}


def _required(args: dict, tool: dict) -> None:
    missing = [
        field
        for field in tool["input_schema"].get("required", [])
        if field not in args
    ]
    if missing:
        raise IntegrationError(
            f"tool {tool['name']} requires arguments {missing}"
        )


def call_tool(store: Store, name: str, args: dict) -> dict:
    """Run one catalogued read tool against the store.

    Refusals are named: an unknown tool, a missing
    argument, or an artefact that does not exist.
    """
    tool = next((t for t in TOOL_CATALOGUE if t["name"] == name), None)
    if tool is None:
        raise IntegrationError(f"no tool named {name!r} in the catalogue")
    _required(args, tool)

    if name == "get_forecast":
        forecast = store.get_forecast(args["forecast_id"])
        if forecast is None:
            raise IntegrationError(f"no forecast {args['forecast_id']}")
        figures = [
            _figure(
                f"p50_{summary.horizon_days}d_inr",
                summary.p50,
                forecast.forecast_id,
            )
            for summary in forecast.horizons_summary
        ]
        figures.append(
            _figure("status", forecast.status, forecast.forecast_id)
        )
        return {"tool": name, "figures": figures}

    if name == "get_accuracy":
        record = store.get_accuracy_record(
            args["commodity"], args["market"], int(args["horizon_days"])
        )
        if record is None:
            raise IntegrationError(
                "no accuracy record for "
                f"{args['commodity']}/{args['market']} at "
                f"{args['horizon_days']}d"
            )
        return {
            "tool": name,
            "figures": [
                _figure("mape_pct", record.mape, record.record_id),
                _figure("mae_inr", record.mae, record.record_id),
                _figure("coverage", record.coverage, record.record_id),
                _figure("degraded", record.degraded, record.record_id),
            ],
        }

    if name == "get_signal":
        signal = store.get_buy_signal(args["signal_id"])
        if signal is None:
            raise IntegrationError(f"no buy signal {args['signal_id']}")
        return {
            "tool": name,
            "figures": [
                _figure("value", signal.value, signal.signal_id),
                _figure("drift_pct", signal.drift_pct, signal.signal_id),
                _figure(
                    "band_width_pct", signal.band_width_pct, signal.signal_id
                ),
                _figure(
                    "p50_horizon_inr", signal.p50_horizon_inr, signal.signal_id
                ),
            ],
        }

    if name == "get_event":
        event = store.get_market_event(args["event_id"])
        if event is None:
            raise IntegrationError(f"no market event {args['event_id']}")
        return {
            "tool": name,
            "figures": [
                _figure("direction", event.direction, event.event_id),
                _figure(
                    "window_start", event.window_start.isoformat(), event.event_id
                ),
                _figure(
                    "window_end",
                    event.window_end.isoformat() if event.window_end else None,
                    event.event_id,
                ),
            ],
        }

    if name == "get_dashboard_assembly":
        assembly = store.get_dashboard_assembly(args["assembly_id"])
        if assembly is None:
            raise IntegrationError(
                f"no dashboard assembly {args['assembly_id']}"
            )
        figures = []
        for panel in assembly.panels:
            for figure in panel.figures:
                figures.append(
                    _figure(
                        f"panel_{panel.panel_no}:{figure.key}",
                        figure.value,
                        figure.artefact_id,
                    )
                )
        return {"tool": name, "figures": figures}

    raise IntegrationError(f"tool {name} is catalogued but not implemented")
