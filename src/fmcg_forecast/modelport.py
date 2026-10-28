"""The model port: one interface, four profiles, fail-closed hosted.

The model's job in this blueprint is language — drafting commentary,
structuring sentiment, parsing scenarios. It never originates a
number (Law 1). Profiles:

- ``offline`` (default): a deterministic composer used by tests,
  evals and the demo. No key, no network.
- ``anthropic`` / ``bedrock`` / ``nim``: hosted profiles that REFUSE
  LOUDLY until configured — a missing key or model id is an error at
  port construction, never a silent fall back to offline. The live
  clients wire into this same port in later rounds.
"""

from __future__ import annotations

from typing import Protocol

from fmcg_forecast.config import Settings


class ModelNotConfiguredError(RuntimeError):
    """A hosted profile was selected without its configuration."""


class ModelPort(Protocol):
    profile_name: str

    def draft_commentary(self, *, subject: str, figures: dict[str, str]) -> str:
        """Draft prose around figures computed elsewhere.

        ``figures`` are strings the caller computed; the port may
        quote them but the verifier disciplines arrive with the
        explanation round — the port itself never invents values.
        """
        ...

    def extract_sentiment(self, *, headline: str) -> dict:
        """Read one headline into the pack's structured shape.

        Returns the raw reading (status, score, direction,
        strength, aspects, matched phrases, reason). The offline
        profile performs the pack's stated lexicon rule; hosted
        profiles produce the same schema through structured
        outputs. Either way the caller wraps the reading in the
        content-addressed artefact and the verifier disciplines it.
        """
        ...

    def parse_scenario(self, *, text: str, events: list[dict]) -> dict:
        """Read a desk what-if into the scenario pack's lever set.

        Returns the raw parse (status, levers) or a refusal
        (status, clause, reason) naming the part that does not
        fit the bounded catalogue. ``events`` is the resolution
        context for event references (event_id + event_class
        dicts). The offline profile performs the pack's stated
        deterministic grammar; hosted profiles produce the same
        schema through structured outputs. Either way the caller
        wraps the lever set in the content-addressed request
        artefact and validates it against the pack again.
        """
        ...


class OfflineModel:
    """Deterministic default: templated commentary from the figures."""

    profile_name = "offline"

    def draft_commentary(self, *, subject: str, figures: dict[str, str]) -> str:
        lines = [f"{subject}."]
        for key in sorted(figures):
            lines.append(f"{key}: {figures[key]}.")
        return " ".join(lines)

    def extract_sentiment(self, *, headline: str) -> dict:
        """The pack's stated lexicon rule, performed deterministically."""
        from fmcg_forecast.sentiment.extract import extract_headline
        from fmcg_forecast.sentiment.pack import load_sentiment_pack

        return extract_headline(headline, load_sentiment_pack())

    def parse_scenario(self, *, text: str, events: list[dict]) -> dict:
        """The scenario pack's stated grammar, performed deterministically."""
        from fmcg_forecast.scenarios.pack import load_scenario_pack
        from fmcg_forecast.scenarios.parse import ParseRefusal, parse_request_text

        try:
            levers = parse_request_text(
                text, events=events, pack=load_scenario_pack()
            )
        except ParseRefusal as refusal:
            return {
                "status": "refused",
                "clause": refusal.clause,
                "reason": refusal.reason,
            }
        return {
            "status": "parsed",
            "levers": [lever.model_dump(mode="json") for lever in levers],
        }


class _HostedRefusal:
    """Base for hosted profiles: configured-or-refuse, no fake calls."""

    profile_name = "hosted"

    def __init__(self, detail: str):
        self._detail = detail

    def draft_commentary(self, *, subject: str, figures: dict[str, str]) -> str:
        raise ModelNotConfiguredError(
            f"model profile '{self.profile_name}' is configured but its live "
            f"client is not wired in this round ({self._detail}); refusing "
            "rather than faking a model call"
        )

    def extract_sentiment(self, *, headline: str) -> dict:
        raise ModelNotConfiguredError(
            f"model profile '{self.profile_name}' is configured but its live "
            f"client is not wired in this round ({self._detail}); refusing "
            "rather than faking a model call"
        )

    def parse_scenario(self, *, text: str, events: list[dict]) -> dict:
        raise ModelNotConfiguredError(
            f"model profile '{self.profile_name}' is configured but its live "
            f"client is not wired in this round ({self._detail}); refusing "
            "rather than faking a model call"
        )


def build_model_port(settings: Settings) -> ModelPort:
    profile = settings.model_profile
    if profile == "offline":
        return OfflineModel()
    if profile == "anthropic":
        if not settings.anthropic_api_key:
            raise ModelNotConfiguredError(
                "model profile 'anthropic' selected but ANTHROPIC_API_KEY is "
                "not set; refusing to fall back silently"
            )
        port = _HostedRefusal(f"model {settings.anthropic_model}")
        port.profile_name = "anthropic"
        return port
    if profile == "bedrock":
        if not settings.bedrock_model_id:
            raise ModelNotConfiguredError(
                "model profile 'bedrock' selected but BEDROCK_MODEL_ID is "
                "not set; refusing to fall back silently"
            )
        port = _HostedRefusal(
            f"model {settings.bedrock_model_id} in {settings.aws_region}"
        )
        port.profile_name = "bedrock"
        return port
    if profile == "nim":
        if not (settings.nim_base_url and settings.nim_model):
            raise ModelNotConfiguredError(
                "model profile 'nim' selected but NIM_BASE_URL / NIM_MODEL "
                "are not set; refusing to fall back silently"
            )
        port = _HostedRefusal(f"model {settings.nim_model} at {settings.nim_base_url}")
        port.profile_name = "nim"
        return port
    raise ModelNotConfiguredError(f"unknown model profile: {profile!r}")
