"""Configuration, read once at import from the environment.

Everything the bridge needs is an env var — no config file, no secrets in the
image. Bad configuration fails at startup with a message naming the variable,
never at request time with a 500.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Raised at startup for configuration that cannot produce a working service."""


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _peer_env_key(name: str) -> str:
    """Peer 'ict-specialist' -> AGENT_PEER_KEY_ICT_SPECIALIST."""
    return "AGENT_PEER_KEY_" + "".join(
        c if c.isalnum() else "_" for c in name
    ).upper()


@dataclass(frozen=True)
class Peer:
    """Another agent module reachable over the same /v1/chat contract."""

    name: str
    url: str
    api_key: str | None = None

    @property
    def chat_url(self) -> str:
        return f"{self.url.rstrip('/')}/v1/chat"


@dataclass(frozen=True)
class Settings:
    api_key: str
    hermes_base_url: str
    hermes_send_path: str
    hermes_session_path: str
    hermes_timeout: float
    peers: dict[str, Peer] = field(default_factory=dict)
    cors_allow_origins: list[str] = field(default_factory=list)
    log_level: str = "info"

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = (os.environ.get("BRIDGE_API_KEY") or "").strip()
        if not api_key:
            raise ConfigError(
                "BRIDGE_API_KEY is not set. This service would otherwise accept "
                "unauthenticated requests to an agent that can create Jira tickets. "
                "Generate one with `openssl rand -hex 32` and put it in .env."
            )
        if len(api_key) < 16:
            raise ConfigError(
                f"BRIDGE_API_KEY is only {len(api_key)} characters. Use at least 16; "
                "`openssl rand -hex 32` gives a good one."
            )

        base = (os.environ.get("HERMES_BASE_URL") or "http://rgsplus-agent:80").strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            raise ConfigError(f"HERMES_BASE_URL must start with http:// or https:// — got {base!r}.")

        send_path = (os.environ.get("HERMES_SEND_PATH") or "/api/session/{session_id}/message").strip()
        if "{session_id}" not in send_path:
            raise ConfigError(
                "HERMES_SEND_PATH must contain the {session_id} placeholder — "
                f"got {send_path!r}."
            )

        return cls(
            api_key=api_key,
            hermes_base_url=base,
            hermes_send_path=send_path,
            hermes_session_path=(os.environ.get("HERMES_SESSION_PATH") or "/api/session/new").strip(),
            hermes_timeout=float(os.environ.get("HERMES_TIMEOUT") or 120),
            peers=_parse_peers(os.environ.get("AGENT_PEERS")),
            cors_allow_origins=_split(os.environ.get("CORS_ALLOW_ORIGINS")),
            log_level=(os.environ.get("LOG_LEVEL") or "info").lower(),
        )


def _parse_peers(raw: str | None) -> dict[str, Peer]:
    """AGENT_PEERS='ict=http://ict:8081,sales=https://sales.internal'

    Each peer's bearer token comes from its own env var so tokens never appear
    in the same string as the URLs (which get logged).
    """
    peers: dict[str, Peer] = {}
    for entry in _split(raw):
        name, sep, url = entry.partition("=")
        name, url = name.strip(), url.strip()
        if not sep or not name or not url:
            raise ConfigError(
                f"AGENT_PEERS entry {entry!r} is malformed. Expected 'name=url', "
                "comma-separated."
            )
        if not url.startswith(("http://", "https://")):
            raise ConfigError(f"AGENT_PEERS entry {name!r} has a URL without a scheme: {url!r}.")
        if name in peers:
            raise ConfigError(f"AGENT_PEERS lists {name!r} twice.")
        peers[name] = Peer(
            name=name,
            url=url,
            api_key=(os.environ.get(_peer_env_key(name)) or "").strip() or None,
        )
    return peers
