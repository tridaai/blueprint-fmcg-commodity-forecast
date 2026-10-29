"""The dashboard pack — what a dashboard may state, as data.

Law 6's mechanics are stated here, versioned, never buried in
code: the panel catalogue (which panels exist, which figures
each states, which artefact family each figure is read from),
the prompt grammar's vocabulary (commodity aliases, market
words, kind keywords, and the subjects the catalogue honestly
cannot state), the head-resolution rule that picks a series'
current artefact, and the morning board's section order. A
request outside the catalogue becomes a named gap panel — the
catalogue is the dashboard's whole vocabulary, never a
suggestion. A change to any of it is a new pack version, and
every spec, assembly and board names the version it was made
under.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# The panel kinds a prompt may ask for. ``gap`` is not askable —
# it is what a request the catalogue or the data cannot answer
# becomes, on the page, named.
PANEL_KINDS: tuple[str, ...] = (
    "forecast",
    "accuracy",
    "sentiment",
    "events",
    "scenario_diff",
    "gap",
)

# Lineage fact kinds that end a walk: stored facts a figure can
# rest on — observation rows, sentiment items, event declarations
# and the dataset manifest itself. Every other kind names an
# artefact that must exist in the store.
TERMINAL_FACT_KINDS: tuple[str, ...] = (
    "observation_series",
    "sentiment_item",
    "event_declaration",
    "manifest",
    # R8: a desk-entered requirement plan is a terminal fact of
    # its own class — the desk's stated need, never a market
    # fact. Walks that rest on it terminate here, labelled.
    "desk_entered",
)


class PanelSpec(BaseModel):
    """One panel kind, as the pack states it."""

    kind: str
    title_template: str = Field(
        description="The panel's title, with {display} / {market} "
        "/ {scenario_id} slots filled from the scope"
    )
    figures: list[str] = Field(
        description="The figures this panel states, named — the "
        "assembler may state exactly these, nothing else"
    )
    source_family: str = Field(
        description="The artefact family the figures are read from"
    )
    rule: str = Field(description="How the panel is resolved, stated")


class DashboardPack(BaseModel):
    version: str
    panels: dict[str, PanelSpec]
    head_rule: str = Field(
        description="How a series' current forecast artefact is "
        "picked from the store, stated"
    )
    board_sections: list[str] = Field(
        description="The morning board's sections, in the order "
        "the desk reads them — exceptions first"
    )
    board_section_titles: dict[str, str]
    # The prompt grammar's vocabulary, stated as data.
    commodity_aliases: dict[str, list[str]] = Field(
        description="Commodity -> the words a prompt may name it "
        "by, longest phrase first when matching"
    )
    market_words: dict[str, list[str]] = Field(
        description="Market -> the words a prompt may name it by"
    )
    unstateable_subjects: dict[str, str] = Field(
        description="Prompt subjects the catalogue cannot state "
        "-> the named gap each becomes (what would answer it)"
    )
    default_market_rule: str = Field(
        description="What happens when a prompt names a commodity "
        "but no market, stated"
    )


DASHBOARD_PACK_V1 = DashboardPack(
    version="2026.10.1",
    panels={
        "forecast": PanelSpec(
            kind="forecast",
            title_template="Forecast — {display} at {market}",
            figures=[
                "p50_7d", "p50_30d", "p50_90d",
                "band_30d_low", "band_30d_high",
                "accuracy_state", "mape_30d",
            ],
            source_family="forecast artefact (the series' head forecast)",
            rule="Resolve the series' head forecast under the "
            "pack's head rule and state its horizon summaries "
            "and its pinned accuracy. The degraded state rides "
            "on the panel exactly as the artefact carries it — "
            "no read offers the panel without it.",
        ),
        "accuracy": PanelSpec(
            kind="accuracy",
            title_template="Measured accuracy — {display} at {market}",
            figures=[
                "mape_7d", "mape_30d", "mape_90d",
                "mae_30d", "coverage_30d",
                "state_7d", "state_30d", "state_90d",
            ],
            source_family="accuracy ledger records",
            rule="State the ledger's records for the series, one "
            "figure set per horizon of record. A horizon with no "
            "record is named unmeasured in the panel's note, "
            "never interpolated; a series with no records at "
            "all is a gap panel.",
        ),
        "sentiment": PanelSpec(
            kind="sentiment",
            title_template="Sentiment — {display}",
            figures=["index_value", "week_start", "n_items"],
            source_family="sentiment index artefact (latest week of record)",
            rule="State the commodity's latest stored weekly "
            "index and its aspect sub-indices. A week whose "
            "window holds no classified item has no index — "
            "absent, never zero — so a commodity with no index "
            "of record is a gap panel, and an old index is "
            "stated with its week on its face.",
        ),
        "events": PanelSpec(
            kind="events",
            title_template="Declared events — {display}",
            figures=["claimed_peak", "verification_status", "measured_ratio"],
            source_family="event registry declarations",
            rule="State every declared event for the commodity "
            "with its claimed peak and its transmission verdict "
            "on its face — verified, unverified or not "
            "measurable, named. A commodity with no declared "
            "event is a gap panel.",
        ),
        "scenario_diff": PanelSpec(
            kind="scenario_diff",
            title_template="Scenario — {scenario_id}",
            figures=[
                "view_kind", "p50_diff_7d", "p50_diff_30d",
                "p50_diff_90d", "events_total", "p50_total",
            ],
            source_family="scenario run artefact + its computed diff",
            rule="State a pinned fork's diff against its base. "
            "Rendered ONLY when the prompt names the scenario "
            "(by id, or as the adopted scenario for a series) — "
            "hypothetical discipline: no other panel, and no "
            "forecast panel, ever carries a fork's figures. "
            "The panel is badged with the run's view kind "
            "(scenario_draft / adopted_scenario / "
            "superseded_scenario) so a draft never dresses up "
            "as the desk's view.",
        ),
    },
    head_rule=(
        "the head forecast for a series is the desk's current "
        "artefact for it: an official forecast outranks a draft; "
        "among equals, the greatest as_of; ties break on the "
        "greatest content address (forecast_id). Deterministic "
        "from the store alone"
    ),
    board_sections=[
        "degraded",
        "pending_gate",
        "active_event",
        "forecast_change",
        "data_gap",
    ],
    board_section_titles={
        "degraded": "Degraded series — accuracy over the bar",
        "pending_gate": "Awaiting a human gate",
        "active_event": "Active declared events",
        "forecast_change": "Forecast changes",
        "data_gap": "Named data gaps",
    },
    commodity_aliases={
        "wheat": ["wheat"],
        "basmati_rice": ["basmati rice", "basmati", "rice"],
        "soybean": ["soybean", "soyabean", "soya"],
        "groundnut": ["groundnut", "peanut"],
        "chili": ["chili", "chilli"],
        "cumin": ["cumin"],
        "coffee": ["coffee"],
    },
    market_words={
        "delhi_khari_baoli": ["khari baoli", "delhi"],
        "indore": ["indore"],
        "kanpur": ["kanpur"],
        "karnal": ["karnal"],
        "nagpur": ["nagpur"],
        "rajkot": ["rajkot"],
        "gondal": ["gondal"],
        "guntur": ["guntur"],
        "warangal": ["warangal"],
        "unjha": ["unjha"],
        "jodhpur": ["jodhpur"],
        "bengaluru": ["bengaluru", "bangalore"],
    },
    unstateable_subjects={
        "rainfall": (
            "a rainfall figure — rainfall is not a stored series "
            "in this dataset; the weather driver is a stated "
            "index carried on the forecast artefact, not a "
            "rainfall reading"
        ),
        "monsoon": (
            "a monsoon figure — the monsoon is not a stored "
            "series; the weather driver is a stated index "
            "carried on the forecast artefact"
        ),
        "stock position": (
            "a standalone stock figure — stock cover is a "
            "contribution line inside the forecast artefact, "
            "not a standalone panel figure"
        ),
        "inventory": (
            "an inventory figure — the desk's stock position is "
            "a contribution line inside the forecast artefact, "
            "not a standalone panel figure"
        ),
        "arrivals": (
            "a standalone arrivals figure — market arrivals are "
            "a contribution line inside the forecast artefact, "
            "not a standalone panel figure"
        ),
    },
    default_market_rule=(
        "a prompt that names a commodity but no market is read "
        "at the commodity's reference market (the first market "
        "in the catalogue); the default applied is recorded in "
        "the panel's parse provenance"
    ),
)


def load_dashboard_pack(version: str | None = None) -> DashboardPack:
    """Load the dashboard pack, fail-closed.

    An unknown version is an error, never a silent fallback — a
    spec made under one pack must never be quietly re-read under
    another.
    """
    if version is None or version == DASHBOARD_PACK_V1.version:
        return DASHBOARD_PACK_V1
    raise ValueError(f"unknown dashboard pack version: {version!r}")
