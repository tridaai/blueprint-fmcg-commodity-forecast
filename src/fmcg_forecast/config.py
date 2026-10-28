"""Environment-only configuration.

Profiles for the model port lead the .env.example: ``offline`` is the
deterministic default; ``anthropic`` / ``bedrock`` / ``nim`` are
fail-closed until their credentials are configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    model_profile: str = "offline"
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-4-5"
    bedrock_model_id: str | None = None
    aws_region: str = "us-east-1"
    nim_base_url: str | None = None
    nim_api_key: str | None = None
    nim_model: str | None = None
    sqlite_path: str = "./data/fmcg.db"
    database_url: str | None = None
    port: int = 8000
    dataset_seed: int = 20261027

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model_profile=os.environ.get("FMCG_MODEL_PROFILE", "offline"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID"),
            aws_region=os.environ.get("AWS_REGION", "us-east-1"),
            nim_base_url=os.environ.get("NIM_BASE_URL"),
            nim_api_key=os.environ.get("NIM_API_KEY"),
            nim_model=os.environ.get("NIM_MODEL"),
            sqlite_path=os.environ.get("FMCG_SQLITE_PATH", "./data/fmcg.db"),
            database_url=os.environ.get("DATABASE_URL"),
            port=int(os.environ.get("FMCG_PORT", "8000")),
            dataset_seed=int(os.environ.get("FMCG_DATASET_SEED", "20261027")),
        )

    @property
    def use_postgres(self) -> bool:
        return bool(self.database_url and self.database_url.startswith("postgres"))
