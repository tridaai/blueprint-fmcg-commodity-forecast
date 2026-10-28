"""Serve entrypoint: load the dataset if absent, then run the API."""

from __future__ import annotations

import logging

import uvicorn

from fmcg_forecast.api import create_app
from fmcg_forecast.config import Settings
from fmcg_forecast.logging_config import configure_logging
from fmcg_forecast.modelport import build_model_port
from fmcg_forecast.store import build_store
from fmcg_forecast.truth import build_truth_store
from fmcg_forecast.workflow import load_dataset

log = logging.getLogger("fmcg.serve")


def main() -> None:
    configure_logging()
    settings = Settings.from_env()
    store = build_store(settings.sqlite_path, settings.database_url)
    truth_store = build_truth_store(settings.sqlite_path, settings.database_url)
    state = load_dataset(store, truth_store, settings.dataset_seed)
    log.info(
        "dataset state: history=%s truth=%s already_loaded=%s",
        state.get("history_rows_written"),
        state.get("truth_rows_written"),
        state.get("already_loaded"),
    )
    app = create_app(store, build_model_port(settings))
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
