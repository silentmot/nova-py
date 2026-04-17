"""Application settings.

Loaded from environment variables (optionally sourced from a local `.env`
file via python-dotenv). All knobs that vary between environments live here;
nothing else in the codebase should read `os.environ` directly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DmPolicy = Literal["pairing", "allowlist", "open", "disabled"]
GroupPolicy = Literal["open", "allowlist", "disabled"]
ReplyMode = Literal["off", "first", "all", "batched"]
StreamingMode = Literal["off", "partial", "block", "progress"]
Environment = Literal["development", "production"]


class Settings(BaseSettings):
    """Runtime configuration for Nova.

    See `.env.example` for the full list of variables and their
    descriptions. Unknown env vars are ignored so the same process can
    be deployed alongside unrelated services.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Discord ------------------------------------------------------
    discord_bot_token: str = Field(..., min_length=1, alias="DISCORD_BOT_TOKEN")
    discord_dev_guild_id: int | None = Field(None, alias="DISCORD_DEV_GUILD_ID")
    # NoDecode: skip pydantic-settings' built-in JSON decode so our CSV
    # validator below receives the raw string.
    discord_owner_ids: Annotated[list[int], NoDecode] = Field(
        default_factory=list, alias="DISCORD_OWNER_IDS"
    )
    command_prefix: str = Field("!", alias="COMMAND_PREFIX")

    # --- OpenClaw channel --------------------------------------------
    openclaw_agent_id: str = Field("main", alias="OPENCLAW_AGENT_ID")
    openclaw_dm_policy: DmPolicy = Field("pairing", alias="OPENCLAW_DM_POLICY")
    openclaw_group_policy: GroupPolicy = Field("allowlist", alias="OPENCLAW_GROUP_POLICY")
    openclaw_allow_from: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="OPENCLAW_ALLOW_FROM"
    )
    openclaw_history_limit: int = Field(20, ge=0, alias="OPENCLAW_HISTORY_LIMIT")
    openclaw_reply_mode: ReplyMode = Field("batched", alias="OPENCLAW_REPLY_MODE")
    openclaw_streaming: StreamingMode = Field("off", alias="OPENCLAW_STREAMING")

    # --- Runtime ------------------------------------------------------
    log_level: str = Field("INFO", alias="LOG_LEVEL")
    environment: Environment = Field("development", alias="ENVIRONMENT")

    # --- Music --------------------------------------------------------
    ffmpeg_path: str = Field("ffmpeg", alias="FFMPEG_PATH")
    music_max_queue: int = Field(100, ge=1, alias="MUSIC_MAX_QUEUE")

    # ------------------------------------------------------------------
    # Validators — tolerate CSV strings for list-typed env vars since
    # env values are always strings at the wire level.
    # ------------------------------------------------------------------
    @field_validator("discord_owner_ids", mode="before")
    @classmethod
    def _split_owner_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(p.strip()) for p in value.split(",") if p.strip()]
        return value

    @field_validator("openclaw_allow_from", mode="before")
    @classmethod
    def _split_allow_from(cls, value: object) -> object:
        if isinstance(value, str):
            if value.strip() == "*":
                return ["*"]
            return [p.strip() for p in value.split(",") if p.strip()]
        return value

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def is_owner(self, user_id: int) -> bool:
        """Return True if the given Discord user id is an owner."""
        return user_id in self.discord_owner_ids

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


def load_settings() -> Settings:
    """Load settings from .env (if present) and the process environment.

    Cached so repeated calls inside the same process are cheap. Call
    `load_settings.cache_clear()` after mutating env vars in tests.
    """
    # Load .env before pydantic reads os.environ so CLI invocations pick
    # up local overrides without needing shell exports.
    load_dotenv(override=False)
    return _cached_settings()


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return Settings()  # type: ignore[call-arg, unused-ignore]


def reset_settings_cache() -> None:
    """Clear the settings cache; primarily useful for tests."""
    _cached_settings.cache_clear()


__all__ = [
    "DmPolicy",
    "GroupPolicy",
    "ReplyMode",
    "Settings",
    "StreamingMode",
    "load_settings",
    "reset_settings_cache",
]
