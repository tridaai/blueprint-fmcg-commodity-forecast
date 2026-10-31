"""The webhook port: one stated way out of the system.

A delivery is an HTTP POST of the payload bytes with
the pack's three headers — the signature, the event
kind and the delivery id. The port answers with the
HTTP status the endpoint returned; a transport failure
raises, and the service records the attempt as failed
with the error named. The default implementation is
stdlib urllib with a stated timeout — no dependency
stands between a deployment and its endpoints, and a
deployment with its own HTTP stack hands the service
any object with this shape.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from typing import Protocol

DELIVERY_TIMEOUT_SECONDS = 10


class WebhookPort(Protocol):
    def post(
        self, url: str, body: bytes, headers: dict[str, str]
    ) -> int: ...


class UrllibWebhookPort:
    """The stated default: urllib POST, 10s timeout."""

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        request = urllib.request.Request(
            url, data=body, method="POST", headers=headers
        )
        try:
            with urllib.request.urlopen(
                request, timeout=DELIVERY_TIMEOUT_SECONDS
            ) as response:
                return int(response.status)
        except urllib.error.HTTPError as error:
            # An endpoint that answers with an error
            # status still answered: the status is the
            # outcome, not a transport failure.
            return int(error.code)


class RecordingWebhookPort:
    """The offline double: answers with its stated
    status and keeps every call for inspection, so the
    tests, the eval gate and the demo can grade the
    exact bytes and headers a real endpoint would have
    received. No network call happens through it, and
    the surfaces that use it say so."""

    def __init__(self, status: int = 200):
        self.status = status
        self.calls: list[dict] = []

    def post(self, url: str, body: bytes, headers: dict[str, str]) -> int:
        self.calls.append(
            {"url": url, "body": body, "headers": dict(headers)}
        )
        return self.status
