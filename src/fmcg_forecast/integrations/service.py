"""The integrations service: tokens, subscriptions,
dispatch, packs and jobs.

One service owns the layer's acts:

- **issue** a token: the secret is generated here,
  hashed, and returned to the caller exactly once —
  the artefact stores only the hash, so nothing that
  reads the store can ever present the secret;
- **revoke** a token by a named act, and **authenticate**
  a presented secret against the standing, unrevoked
  tokens;
- **strike** a webhook subscription (its secret is
  generated here, shown once, and stored on the
  artefact for signing — redacted on every read);
- **dispatch**: fold the event sources — alerts,
  forecast approvals, event triage acts — and strike
  one delivery attempt per (subscription, artefact)
  pair not already delivered, through the webhook
  port the caller hands in;
- **build** a board pack synchronously, and
  **request / run** export jobs whose completion act
  names the pack the one builder produced.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone

from fmcg_forecast.integrations.engine import build_board_pack
from fmcg_forecast.integrations.models import (
    BoardPack,
    ExportJob,
    ExportJobAct,
    IntegrationToken,
    TokenAct,
    WebhookDelivery,
    WebhookSubscription,
    canonical_payload,
    delivery_content_id,
    hash_secret,
    job_act_content_id,
    job_content_id,
    job_state,
    payload_hash,
    sign_payload,
    subscription_content_id,
    token_act_content_id,
    token_content_id,
)
from fmcg_forecast.integrations.pack import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    IntegrationsPack,
    load_integrations_pack,
)
from fmcg_forecast.integrations.port import WebhookPort
from fmcg_forecast.store import Store


class IntegrationError(RuntimeError):
    """A refused integration act, with the reason on it."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IntegrationsService:
    def __init__(self, store: Store, pack: IntegrationsPack | None = None):
        self.store = store
        self.pack = pack or load_integrations_pack()

    # -- tokens ---------------------------------------------------------

    def issue_token(
        self,
        name: str,
        scopes: list[str],
        issued_by: str,
        at: datetime | None = None,
    ) -> tuple[IntegrationToken, str]:
        """Strike a token; return it and its secret, once."""
        if not scopes:
            raise IntegrationError(
                "a token names at least one scope — a token scoped "
                "to nothing is not an integration credential"
            )
        unknown = [s for s in scopes if s not in self.pack.surfaces]
        if unknown:
            raise IntegrationError(
                f"scopes outside the pack's closed vocabulary: {unknown}"
            )
        if len(set(scopes)) != len(scopes):
            raise IntegrationError("a token's scopes may not repeat")
        secret = secrets.token_urlsafe(self.pack.token_secret_bytes)
        token = IntegrationToken(
            token_id="TOK-pending",
            name=name,
            scopes=sorted(scopes),
            secret_hash=hash_secret(secret),
            issued_by=issued_by,
            issued_at=at or _now(),
            pack_version=self.pack.version,
        )
        token = token.model_copy(update={"token_id": token_content_id(token)})
        self.store.insert_integration_token(token)
        return token, secret

    def list_tokens(self) -> list[IntegrationToken]:
        return self.store.list_integration_tokens()

    def get_token(self, token_id: str) -> IntegrationToken | None:
        return self.store.get_integration_token(token_id)

    def token_state(self, token: IntegrationToken) -> str:
        """The fold of the token's acts: standing or revoked."""
        acts = self.store.list_token_acts(token.token_id)
        return "revoked" if acts else "standing"

    def revoke_token(
        self,
        token_id: str,
        actor: str,
        reason: str,
        at: datetime | None = None,
    ) -> TokenAct:
        token = self.get_token(token_id)
        if token is None:
            raise IntegrationError(f"no integration token {token_id}")
        if self.token_state(token) == "revoked":
            raise IntegrationError(f"token {token_id} is already revoked")
        act = TokenAct(
            act_id="TOKA-pending",
            token_id=token_id,
            act="revoke",
            actor=actor,
            acted_at=at or _now(),
            reason=reason,
            pack_version=self.pack.version,
        )
        act = act.model_copy(update={"act_id": token_act_content_id(act)})
        self.store.insert_token_act(act)
        return act

    def authenticate(self, secret: str) -> IntegrationToken | None:
        """The standing token a presented secret belongs
        to — None for an unknown secret or a revoked
        token, and the caller cannot tell which."""
        digest = hash_secret(secret)
        for token in self.store.list_integration_tokens():
            if token.secret_hash == digest:
                if self.token_state(token) == "revoked":
                    return None
                return token
        return None

    # -- webhook subscriptions -------------------------------------------

    def create_subscription(
        self,
        name: str,
        endpoint_url: str,
        event_kinds: list[str],
        created_by: str,
        at: datetime | None = None,
    ) -> tuple[WebhookSubscription, str]:
        """Strike a subscription; return it and its secret, once."""
        if not endpoint_url.startswith(("http://", "https://")):
            raise IntegrationError(
                "a subscription's endpoint must be an http(s) URL — "
                "deliveries are HTTP posts"
            )
        unknown = [k for k in event_kinds if k not in self.pack.event_kinds]
        if unknown:
            raise IntegrationError(
                f"event kinds outside the pack's closed vocabulary: {unknown}"
            )
        if len(set(event_kinds)) != len(event_kinds):
            raise IntegrationError("a subscription's event kinds may not repeat")
        secret = secrets.token_urlsafe(self.pack.token_secret_bytes)
        subscription = WebhookSubscription(
            subscription_id="WHS-pending",
            name=name,
            endpoint_url=endpoint_url,
            event_kinds=sorted(event_kinds),
            secret=secret,
            created_by=created_by,
            created_at=at or _now(),
            pack_version=self.pack.version,
        )
        subscription = subscription.model_copy(
            update={"subscription_id": subscription_content_id(subscription)}
        )
        self.store.insert_webhook_subscription(subscription)
        return subscription, secret

    def list_subscriptions(self) -> list[WebhookSubscription]:
        return self.store.list_webhook_subscriptions()

    def get_subscription(
        self, subscription_id: str
    ) -> WebhookSubscription | None:
        return self.store.get_webhook_subscription(subscription_id)

    # -- event sources ------------------------------------------------------

    def event_sources(self) -> list[tuple[str, str, dict]]:
        """The deliverable moments, folded from artefacts:
        (event kind, source artefact id, the artefact's
        own read) in a stated order."""
        sources: list[tuple[str, str, dict]] = []
        for alert in self.store.list_alerts():
            sources.append(
                ("alert_raised", alert.alert_id, alert.model_dump(mode="json"))
            )
        for forecast in self.store.list_forecasts():
            approval = self.store.get_approval(forecast.forecast_id)
            if approval is not None:
                sources.append(
                    (
                        "forecast_approved",
                        approval.approval_id,
                        approval.model_dump(mode="json"),
                    )
                )
        for act in self.store.list_event_triage_acts():
            sources.append(
                ("event_triaged", act.act_id, act.model_dump(mode="json"))
            )
        sources.sort(key=lambda s: (s[0], s[1]))
        return sources

    def source_read(self, event_kind: str, source_id: str) -> dict | None:
        """The standing read of one source artefact, for
        the verifier's payload comparison."""
        for kind, artefact_id, read in self.event_sources():
            if kind == event_kind and artefact_id == source_id:
                return read
        return None

    # -- dispatch ----------------------------------------------------------

    def delivered_pairs(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for delivery in self.store.list_webhook_deliveries():
            if delivery.outcome == "delivered":
                pairs.add((delivery.subscription_id, delivery.source_artefact_id))
        return pairs

    def dispatch(
        self, port: WebhookPort, at: datetime | None = None
    ) -> list[WebhookDelivery]:
        """Strike one delivery attempt per (subscription,
        artefact) pair not already delivered.

        A pair whose earlier attempts all failed is
        attempted again — the new attempt is its own
        artefact and the fold decides the pair's state.
        """
        attempted_at = at or _now()
        served = self.delivered_pairs()
        attempts: dict[tuple[str, str], int] = {}
        for standing in self.store.list_webhook_deliveries():
            pair = (standing.subscription_id, standing.source_artefact_id)
            attempts[pair] = attempts.get(pair, 0) + 1
        struck: list[WebhookDelivery] = []
        sources = self.event_sources()
        for subscription in self.store.list_webhook_subscriptions():
            for kind, source_id, read in sources:
                if kind not in subscription.event_kinds:
                    continue
                pair = (subscription.subscription_id, source_id)
                if pair in served:
                    continue
                payload = canonical_payload(read)
                signature = sign_payload(subscription.secret, payload)
                delivery = WebhookDelivery(
                    delivery_id="WHD-pending",
                    subscription_id=subscription.subscription_id,
                    event_kind=kind,
                    source_artefact_id=source_id,
                    attempt=attempts.get(pair, 0) + 1,
                    payload=payload,
                    payload_sha256=payload_hash(read),
                    signature=signature,
                    attempted_at=attempted_at,
                    outcome="failed",
                    http_status=None,
                    error=None,
                    pack_version=self.pack.version,
                )
                delivery = delivery.model_copy(
                    update={"delivery_id": delivery_content_id(delivery)}
                )
                headers = {
                    "content-type": "application/json",
                    SIGNATURE_HEADER: signature,
                    EVENT_HEADER: kind,
                    DELIVERY_HEADER: delivery.delivery_id,
                }
                try:
                    status = port.post(
                        subscription.endpoint_url,
                        payload.encode("utf-8"),
                        headers,
                    )
                except Exception as error:  # the attempt is the record
                    delivery = delivery.model_copy(
                        update={
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
                else:
                    if 200 <= status < 300:
                        delivery = delivery.model_copy(
                            update={"outcome": "delivered", "http_status": status}
                        )
                    else:
                        delivery = delivery.model_copy(
                            update={
                                "http_status": status,
                                "error": f"endpoint answered HTTP {status}",
                            }
                        )
                self.store.insert_webhook_delivery(delivery)
                attempts[pair] = attempts.get(pair, 0) + 1
                struck.append(delivery)
        return struck

    def list_deliveries(self) -> list[WebhookDelivery]:
        return self.store.list_webhook_deliveries()

    # -- board packs ---------------------------------------------------------

    def build_pack(
        self, as_of: date, struck_at: datetime | None = None
    ) -> BoardPack:
        """The synchronous build. Idempotent: a pack whose
        address already stands is returned as it stands."""
        board = build_board_pack(
            self.store, self.pack, as_of, struck_at or _now()
        )
        standing = self.store.get_board_pack(board.pack_id)
        if standing is not None:
            return standing
        self.store.insert_board_pack(board)
        return board

    def get_pack(self, pack_id: str) -> BoardPack | None:
        return self.store.get_board_pack(pack_id)

    def list_packs(self) -> list[BoardPack]:
        return self.store.list_board_packs()

    # -- export jobs -----------------------------------------------------------

    def request_job(
        self, requested_by: str, as_of: date, at: datetime | None = None
    ) -> ExportJob:
        job = ExportJob(
            job_id="JOB-pending",
            requested_by=requested_by,
            requested_at=at or _now(),
            as_of=as_of,
            pack_version=self.pack.version,
        )
        job = job.model_copy(update={"job_id": job_content_id(job)})
        standing = self.store.get_export_job(job.job_id)
        if standing is not None:
            return standing
        self.store.insert_export_job(job)
        return job

    def get_job(self, job_id: str) -> ExportJob | None:
        return self.store.get_export_job(job_id)

    def list_jobs(self) -> list[ExportJob]:
        return self.store.list_export_jobs()

    def job_state(self, job: ExportJob) -> str:
        return job_state(job, self.store.list_export_job_acts(job.job_id))

    def run_job(
        self, job_id: str, at: datetime | None = None
    ) -> ExportJobAct:
        """Run a requested job once: the completion act
        names the pack produced, or the failure act
        names the error. A job already completed or
        failed is refused — its acts are its record."""
        job = self.get_job(job_id)
        if job is None:
            raise IntegrationError(f"no export job {job_id}")
        state = self.job_state(job)
        if state != "requested":
            raise IntegrationError(
                f"export job {job_id} is already {state}; a job runs once"
            )
        acted_at = at or _now()
        try:
            board = self.build_pack(job.as_of, struck_at=acted_at)
        except Exception as error:  # the failure is the record
            act = ExportJobAct(
                act_id="JOBA-pending",
                job_id=job_id,
                act="fail",
                acted_at=acted_at,
                board_pack_id=None,
                error=f"{type(error).__name__}: {error}",
                pack_version=self.pack.version,
            )
            act = act.model_copy(update={"act_id": job_act_content_id(act)})
            self.store.insert_export_job_act(act)
            return act
        act = ExportJobAct(
            act_id="JOBA-pending",
            job_id=job_id,
            act="complete",
            acted_at=acted_at,
            board_pack_id=board.pack_id,
            error=None,
            pack_version=self.pack.version,
        )
        act = act.model_copy(update={"act_id": job_act_content_id(act)})
        self.store.insert_export_job_act(act)
        return act


def public_subscription(subscription: WebhookSubscription) -> dict:
    """A subscription's read surface: the secret redacted
    to the prefix of its hash, as the pack states."""
    read = subscription.model_dump(mode="json")
    read["secret"] = None
    read["secret_set"] = True
    read["secret_hash_prefix"] = hash_secret(subscription.secret)[:12]
    return read
