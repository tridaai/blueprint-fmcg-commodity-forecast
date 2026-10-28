"""The ingest workflow — a LangGraph state machine.

Round 1 wires the first leg of the blueprint's pipeline
(ingest -> compute -> explain -> scenario -> human gate -> publish):
dataset generation and loading as a graph whose every transition is
explicit state. Loading is idempotent at the workflow level: if the
store already carries a manifest for the same seed and digest, the
graph verifies and stops instead of re-inserting (the store itself
is insert-only and would refuse a duplicate load).

This module is part of the load path, so it may touch the truth
store — the generator's sealed future is written here, once. The
forecast package may not (see forecast/__init__.py).
"""

from __future__ import annotations

import logging
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from fmcg_forecast.generator import GeneratedData, generate_dataset
from fmcg_forecast.store import SqlStore
from fmcg_forecast.truth import TruthStore

log = logging.getLogger("fmcg.workflow")


class LoadState(TypedDict, total=False):
    seed: int
    data: GeneratedData
    already_loaded: bool
    history_rows_written: int
    truth_rows_written: int
    events_written: int
    digest: str


def build_load_graph(store: SqlStore, truth_store: TruthStore):
    def generate(state: LoadState) -> LoadState:
        data = generate_dataset(state["seed"])
        existing = store.get_manifest()
        already = bool(
            existing
            and existing.seed == data.manifest.seed
            and existing.history_digest == data.manifest.history_digest
        )
        log.info(
            "generated dataset seed=%s history_rows=%s future_rows=%s already_loaded=%s",
            data.manifest.seed,
            len(data.history),
            len(data.future),
            already,
        )
        return {"data": data, "already_loaded": already, "digest": data.manifest.history_digest}

    def persist(state: LoadState) -> LoadState:
        if state["already_loaded"]:
            return {"history_rows_written": 0, "truth_rows_written": 0, "events_written": 0}
        data = state["data"]
        history_n = store.insert_observations(data.history)
        truth_n = truth_store.insert_truth(data.future)
        events_n = store.insert_events(list(data.manifest.events))
        store.save_manifest(data.manifest)
        log.info(
            "persisted history=%s truth=%s events=%s", history_n, truth_n, events_n
        )
        return {
            "history_rows_written": history_n,
            "truth_rows_written": truth_n,
            "events_written": events_n,
        }

    def verify(state: LoadState) -> LoadState:
        manifest = store.get_manifest()
        assert manifest is not None, "manifest missing after load"
        assert manifest.history_digest == state["digest"], "digest mismatch after load"
        counts = store.row_counts()
        total = sum(counts.values())
        assert total == manifest.history_rows, (
            f"stored rows {total} != manifest {manifest.history_rows}"
        )
        return {}

    graph = StateGraph(LoadState)
    graph.add_node("generate", generate)
    graph.add_node("persist", persist)
    graph.add_node("verify", verify)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "persist")
    graph.add_edge("persist", "verify")
    graph.add_edge("verify", END)
    return graph.compile()


def load_dataset(store: SqlStore, truth_store: TruthStore, seed: int) -> LoadState:
    """Run the ingest graph once; return its final state."""
    app = build_load_graph(store, truth_store)
    return app.invoke({"seed": seed})
