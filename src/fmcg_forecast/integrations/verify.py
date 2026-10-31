"""Re-performance verification for the integration layer.

Every check trusts nothing stored:

- a token re-performs: its content address re-derives,
  its scopes stay inside the pack's closed vocabulary,
  its stored secret hash is a hash (64 hex) and never
  a presentable secret; its acts re-derive and name
  only that token;
- a subscription re-performs: address, closed event
  kinds, a secret on the artefact (reads redact it;
  the store is the server side);
- a delivery re-performs: its address over the
  attempt's identity, its payload hash against its
  payload, its signature against the subscription's
  secret and the payload bytes, and its payload
  against the standing read of the source artefact —
  a delivery of an artefact that no longer reads as
  delivered is named; the pair fold is checked too
  (attempt ordinals gapless from one, no pair with
  two delivered attempts, no delivered attempt after
  a later failed one is fine — the fold is any);
- a board pack re-performs whole: its address, every
  file's hash and size against its stored bytes, the
  manifest against the addressed files (it must name
  the pack, the as-of and exactly those files with
  their hashes), and finally the build itself — the
  one builder folded over the standing store at the
  pack's as-of must render the identical file set, so
  every figure in every section is re-performed
  against the artefacts it was read from;
- a job re-performs: its address, its acts' addresses
  and fold, and a completed job's named pack exists
  and was struck for the job's as-of.
"""

from __future__ import annotations

import hashlib
import json

from fmcg_forecast.integrations.engine import build_board_pack, file_bytes
from fmcg_forecast.integrations.models import (
    board_pack_content_id,
    canonical_payload,
    delivery_content_id,
    job_act_content_id,
    job_content_id,
    sign_payload,
    subscription_content_id,
    token_act_content_id,
    token_content_id,
)
from fmcg_forecast.integrations.pack import IntegrationsPack, load_integrations_pack
from fmcg_forecast.integrations.service import IntegrationsService
from fmcg_forecast.store import Store


def verify_integrations(
    store: Store, pack: IntegrationsPack | None = None
) -> list[str]:
    pack = pack or load_integrations_pack()
    problems: list[str] = []
    service = IntegrationsService(store, pack)

    tokens = store.list_integration_tokens()
    token_ids = {t.token_id for t in tokens}
    for token in tokens:
        if token_content_id(token) != token.token_id:
            problems.append(
                f"content id mismatch on token {token.token_id} — "
                "the token was altered after it was issued"
            )
        if token.pack_version != pack.version:
            problems.append(
                f"token {token.token_id} was issued under pack "
                f"{token.pack_version}, cannot re-perform under "
                f"{pack.version}"
            )
        outside = [s for s in token.scopes if s not in pack.surfaces]
        if outside:
            problems.append(
                f"token {token.token_id} names scopes outside the "
                f"pack's closed vocabulary: {outside}"
            )
        if len(token.secret_hash) != 64 or any(
            c not in "0123456789abcdef" for c in token.secret_hash
        ):
            problems.append(
                f"token {token.token_id} stores a secret_hash that "
                "is not a SHA-256 hex digest"
            )
    for act in store.list_token_acts():
        if token_act_content_id(act) != act.act_id:
            problems.append(
                f"content id mismatch on token act {act.act_id}"
            )
        if act.token_id not in token_ids:
            problems.append(
                f"token act {act.act_id} names unknown token "
                f"{act.token_id}"
            )

    subscriptions = {
        s.subscription_id: s for s in store.list_webhook_subscriptions()
    }
    for subscription in subscriptions.values():
        if subscription_content_id(subscription) != subscription.subscription_id:
            problems.append(
                f"content id mismatch on subscription "
                f"{subscription.subscription_id} — it was altered "
                "after it was struck"
            )
        outside = [
            k for k in subscription.event_kinds if k not in pack.event_kinds
        ]
        if outside:
            problems.append(
                f"subscription {subscription.subscription_id} names "
                f"event kinds outside the pack's vocabulary: {outside}"
            )
        if not subscription.secret:
            problems.append(
                f"subscription {subscription.subscription_id} "
                "carries no secret — its deliveries cannot be signed"
            )

    deliveries = store.list_webhook_deliveries()
    by_pair: dict[tuple[str, str], list] = {}
    for delivery in deliveries:
        by_pair.setdefault(
            (delivery.subscription_id, delivery.source_artefact_id), []
        ).append(delivery)
        if delivery_content_id(delivery) != delivery.delivery_id:
            problems.append(
                f"content id mismatch on delivery {delivery.delivery_id}"
            )
        subscription = subscriptions.get(delivery.subscription_id)
        if subscription is None:
            problems.append(
                f"delivery {delivery.delivery_id} names unknown "
                f"subscription {delivery.subscription_id}"
            )
            continue
        if delivery.payload_sha256 != hashlib.sha256(
            delivery.payload.encode()
        ).hexdigest():
            problems.append(
                f"delivery {delivery.delivery_id} payload hash does "
                "not re-derive from its payload"
            )
        if delivery.signature != sign_payload(
            subscription.secret, delivery.payload
        ):
            problems.append(
                f"delivery {delivery.delivery_id} signature does "
                "not re-derive under its subscription's secret"
            )
        read = service.source_read(
            delivery.event_kind, delivery.source_artefact_id
        )
        if read is None:
            problems.append(
                f"delivery {delivery.delivery_id} names source "
                f"{delivery.source_artefact_id} ({delivery.event_kind}) "
                "which no longer reads as an artefact"
            )
        elif delivery.payload != canonical_payload(read):
            problems.append(
                f"delivery {delivery.delivery_id} payload differs "
                "from the standing read of "
                f"{delivery.source_artefact_id}"
            )
        if delivery.outcome == "delivered" and (
            delivery.http_status is None
            or not (200 <= delivery.http_status < 300)
        ):
            problems.append(
                f"delivery {delivery.delivery_id} reads delivered "
                f"with http_status {delivery.http_status}"
            )
        if delivery.outcome == "failed" and not delivery.error:
            problems.append(
                f"delivery {delivery.delivery_id} reads failed "
                "with no error named"
            )
    for pair, pair_deliveries in by_pair.items():
        ordinals = sorted(d.attempt for d in pair_deliveries)
        if ordinals != list(range(1, len(pair_deliveries) + 1)):
            problems.append(
                f"deliveries for {pair} carry attempt ordinals "
                f"{ordinals}, not a gapless run from one"
            )
        if sum(1 for d in pair_deliveries if d.outcome == "delivered") > 1:
            problems.append(
                f"pair {pair} was delivered more than once — "
                "dispatch is idempotent per pair"
            )

    for board in store.list_board_packs():
        if board_pack_content_id(board) != board.pack_id:
            problems.append(
                f"content id mismatch on board pack {board.pack_id} "
                "— the pack was altered after it was struck"
            )
        if board.integrations_pack_version != pack.version:
            problems.append(
                f"board pack {board.pack_id} was struck under "
                f"integrations pack {board.integrations_pack_version}, "
                f"cannot re-perform under {pack.version}"
            )
            continue
        by_name = {f.name: f for f in board.files}
        for file in board.files:
            data = file_bytes(file)
            if hashlib.sha256(data).hexdigest() != file.sha256:
                problems.append(
                    f"board pack {board.pack_id} file {file.name} "
                    "hashes differently than its manifest entry — "
                    "the stored file was altered"
                )
            if len(data) != file.size_bytes:
                problems.append(
                    f"board pack {board.pack_id} file {file.name} "
                    "states a size its bytes do not have"
                )
        manifest_file = by_name.get("manifest.json")
        if manifest_file is None:
            problems.append(
                f"board pack {board.pack_id} carries no manifest.json"
            )
        else:
            manifest = json.loads(file_bytes(manifest_file).decode("utf-8"))
            if manifest.get("pack_id") != board.pack_id:
                problems.append(
                    f"board pack {board.pack_id} manifest names pack "
                    f"{manifest.get('pack_id')}"
                )
            if manifest.get("as_of") != board.as_of.isoformat():
                problems.append(
                    f"board pack {board.pack_id} manifest names "
                    f"as-of {manifest.get('as_of')}"
                )
            listed = {
                entry["name"]: entry for entry in manifest.get("files", [])
            }
            addressed = {
                name: f for name, f in by_name.items() if name != "manifest.json"
            }
            if set(listed) != set(addressed):
                problems.append(
                    f"board pack {board.pack_id} manifest lists "
                    f"{sorted(listed)}, the pack carries {sorted(addressed)}"
                )
            for name, entry in listed.items():
                held = addressed.get(name)
                if held is not None and (
                    entry["sha256"] != held.sha256
                    or entry["size_bytes"] != held.size_bytes
                ):
                    problems.append(
                        f"board pack {board.pack_id} manifest entry "
                        f"for {name} disagrees with the file's own "
                        "hash and size"
                    )
        rebuilt = build_board_pack(store, pack, board.as_of, board.struck_at)
        if rebuilt.pack_id != board.pack_id:
            problems.append(
                f"board pack {board.pack_id} does not re-perform — "
                "the fold of the standing artefacts at its as-of "
                "builds a different pack (the artefact set has "
                "moved on since it was struck, or the pack was "
                "altered)"
            )
        else:
            rebuilt_files = {f.name: f.sha256 for f in rebuilt.files}
            held_files = {f.name: f.sha256 for f in board.files}
            if rebuilt_files != held_files:
                problems.append(
                    f"board pack {board.pack_id} files differ from "
                    "the rebuilt set"
                )

    packs = {p.pack_id: p for p in store.list_board_packs()}
    for job in store.list_export_jobs():
        if job_content_id(job) != job.job_id:
            problems.append(
                f"content id mismatch on export job {job.job_id}"
            )
        acts = store.list_export_job_acts(job.job_id)
        for act in acts:
            if job_act_content_id(act) != act.act_id:
                problems.append(
                    f"content id mismatch on job act {act.act_id}"
                )
            if act.act == "complete":
                produced = packs.get(act.board_pack_id or "")
                if produced is None:
                    problems.append(
                        f"job {job.job_id} completed naming pack "
                        f"{act.board_pack_id}, which does not stand"
                    )
                elif produced.as_of != job.as_of:
                    problems.append(
                        f"job {job.job_id} asked for as-of "
                        f"{job.as_of} and completed with a pack for "
                        f"{produced.as_of}"
                    )
    return problems
