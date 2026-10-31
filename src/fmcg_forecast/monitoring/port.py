"""The recording model port: every completed call,
priced and entered in the run ledger.

A wrapper, not a new port: it delegates each of the
model port's four methods to the port it wraps, and on
the call's completion strikes exactly one run record —
the profile the wrapped port names, the purpose the
pack maps the method to, hashes of the canonical
request and response payloads, their character counts,
the estimator's token figures and the pack-priced cost.
The response returns to the caller byte-identical: the
wrapper observes, it never edits.

A call that raises strikes no record. That is the
pack's stated rule, not an oversight: the ledger prices
work done, a refusal (a hosted profile unconfigured, a
transport down) consumes nothing the ledger prices, and
the error propagates to the caller exactly as the
wrapped port raised it.

The wrapper carries the profile name of the port it
wraps, so a service holding it cannot tell — and does
not need to tell — that its calls are being ledgered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from fmcg_forecast.modelport import ModelPort
from fmcg_forecast.monitoring.engine import estimate_tokens, price_call
from fmcg_forecast.monitoring.models import (
    RunRecord,
    canonical_payload,
    payload_hash,
    run_content_id,
)
from fmcg_forecast.monitoring.pack import PURPOSE_BY_METHOD, MonitoringPack
from fmcg_forecast.store import Store


class RecordingModelPort:
    """A ModelPort that ledgers every completed call."""

    def __init__(
        self,
        inner: ModelPort,
        store: Store,
        pack: MonitoringPack,
        clock: Callable[[], datetime] | None = None,
    ):
        self._inner = inner
        self._store = store
        self._pack = pack
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.profile_name = inner.profile_name

    # -- the ledger strike -------------------------------------------

    def _record(self, method: str, request, response) -> None:
        request_text = canonical_payload(request)
        response_text = canonical_payload(response)
        request_tokens = estimate_tokens(len(request_text), self._pack)
        response_tokens = estimate_tokens(len(response_text), self._pack)
        cost, basis = price_call(
            self.profile_name, request_tokens, response_tokens, self._pack
        )
        record = RunRecord(
            run_id="",
            called_at=self._clock(),
            profile=self.profile_name,
            purpose=PURPOSE_BY_METHOD[method],
            request_hash=payload_hash(request),
            response_hash=payload_hash(response),
            request_chars=len(request_text),
            response_chars=len(response_text),
            request_tokens=request_tokens,
            response_tokens=response_tokens,
            cost_nano_usd=cost,
            cost_basis=basis,
            pack_version=self._pack.version,
        )
        record = record.model_copy(update={"run_id": run_content_id(record)})
        self._store.insert_model_run(record)

    # -- the port's four methods --------------------------------------

    def draft_commentary(self, *, subject: str, figures: dict[str, str]) -> str:
        response = self._inner.draft_commentary(subject=subject, figures=figures)
        self._record(
            "draft_commentary",
            {"subject": subject, "figures": figures},
            response,
        )
        return response

    def extract_sentiment(self, *, headline: str) -> dict:
        response = self._inner.extract_sentiment(headline=headline)
        self._record("extract_sentiment", {"headline": headline}, response)
        return response

    def parse_scenario(self, *, text: str, events: list[dict]) -> dict:
        response = self._inner.parse_scenario(text=text, events=events)
        self._record(
            "parse_scenario", {"text": text, "events": events}, response
        )
        return response

    def parse_dashboard(self, *, text: str, context: dict) -> dict:
        response = self._inner.parse_dashboard(text=text, context=context)
        self._record(
            "parse_dashboard", {"text": text, "context": context}, response
        )
        return response
