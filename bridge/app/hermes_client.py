"""Adapter between the bridge's stable /v1/chat contract and hermes-webui's
internal HTTP API.

This is the only file that knows anything about how Hermes is reached. When
the upstream routes change, they change here and the RGS+ application does not
notice — that is the entire reason the bridge exists.

VERIFY BEFORE PRODUCTION: the session and send paths are configurable
(HERMES_SESSION_PATH / HERMES_SEND_PATH) because hermes-webui's routes are not
a published API. `/api/session/new` is confirmed; the message route is a
default that must be checked against a running container. Run

    scripts/probe-hermes-api.sh

which lists the routes the container actually serves, and set HERMES_SEND_PATH
accordingly. `_extract_reply` is deliberately permissive about the response
shape for the same reason.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("bridge.hermes")


class HermesError(RuntimeError):
    """The agent could not answer. Message is safe to show an operator, not a user."""


class HermesClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    async def ping(self) -> tuple[bool, str | None]:
        """Cheap reachability check for /readyz. Any HTTP answer counts as up —
        we are checking the container is serving, not that a route exists."""
        try:
            response = await self._client.get(self._settings.hermes_base_url + "/", timeout=5.0)
            return response.status_code < 500, None
        except httpx.HTTPError as e:
            return False, str(e)

    async def new_session(self) -> str:
        url = self._settings.hermes_base_url + self._settings.hermes_session_path
        try:
            response = await self._client.post(url, json={}, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            # A locally-generated id still gives the caller a stable handle for
            # its own logs even when the agent is down; the send below will
            # surface the real failure.
            log.warning("session/new failed (%s); falling back to a local id", e)
            return f"local-{uuid.uuid4().hex[:16]}"

        payload = _json_or_empty(response)
        for key in ("session_id", "id", "session"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                return value["id"]
        return f"local-{uuid.uuid4().hex[:16]}"

    async def send(self, session_id: str, message: str) -> str:
        path = self._settings.hermes_send_path.replace("{session_id}", session_id)
        url = self._settings.hermes_base_url + path

        try:
            response = await self._client.post(
                url,
                json={"message": message, "session_id": session_id},
                timeout=self._settings.hermes_timeout,
            )
        except httpx.TimeoutException as e:
            raise HermesError(
                f"the agent did not respond within {self._settings.hermes_timeout:.0f}s"
            ) from e
        except httpx.HTTPError as e:
            raise HermesError(f"could not reach the agent at {url}: {e}") from e

        if response.status_code == 404:
            raise HermesError(
                f"the agent has no route at {path}. HERMES_SEND_PATH is wrong for this "
                "hermes-webui version — run scripts/probe-hermes-api.sh to find the "
                "real one."
            )
        if response.status_code >= 400:
            raise HermesError(
                f"the agent returned HTTP {response.status_code}: "
                f"{response.text[:300] or 'no body'}"
            )

        reply = _extract_reply(_json_or_empty(response), response.text)
        if not reply:
            raise HermesError("the agent returned an empty reply")
        return reply


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_reply(payload: dict[str, Any], raw_text: str) -> str:
    """Pull the assistant's text out of whatever shape came back.

    Tries the common single-field shapes, then a messages list (last assistant
    turn), then falls back to the raw body if it was plain text. Permissive by
    design: an unfamiliar-but-valid response should still reach the user.
    """
    for key in ("reply", "response", "message", "content", "text", "output"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            inner = value.get("content") or value.get("text")
            if isinstance(inner, str) and inner.strip():
                return inner.strip()

    messages = payload.get("messages")
    if isinstance(messages, list):
        for entry in reversed(messages):
            if not isinstance(entry, dict):
                continue
            if entry.get("role") not in (None, "assistant"):
                continue
            content = entry.get("content") or entry.get("text")
            if isinstance(content, str) and content.strip():
                return content.strip()
            # Anthropic-style content blocks.
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") in (None, "text")
                ]
                joined = "".join(parts).strip()
                if joined:
                    return joined

    if not payload and raw_text.strip():
        return raw_text.strip()
    return ""
