"""Adapter between the bridge's stable /v1/chat contract and hermes-webui's
internal HTTP API.

This is the only file that knows anything about how Hermes is reached. When
the upstream routes change, they change here and the RGS+ application does not
notice — that is the entire reason the bridge exists.

The routes are configurable (HERMES_SESSION_PATH / HERMES_SEND_PATH /
HERMES_DELETE_PATH) because hermes-webui's HTTP API is not published and moves
between versions. The defaults are the ones verified against the image this
repo builds on:

    POST /api/session/new      -> {"session": {"session_id": "…"}}
    POST /api/chat             -> {"answer": "…", "status": "done"}
    POST /api/session/delete   -> {"ok": true}

`/api/chat` is hermes-webui's synchronous chat endpoint — its own source calls
it a "fallback … not used by frontend". That is exactly why the bridge wants
it: the browser drives `/api/chat/start` plus an SSE stream and a pile of
polling routes, and a request/response bridge should not reimplement that.
Nothing else in this repo may depend on `/api/chat` being unused upstream; if
it disappears, this file changes and the RGS+ contract does not.

There is no `{session_id}` in the send path any more — `/api/chat` takes the
session in its body. The placeholder is still honoured if a path contains one,
so a version serving `/api/session/{session_id}/message` still works.

`_extract_reply` is deliberately permissive about the response shape for the
same reason. Re-check the routes against a running container with
`scripts/probe-hermes-api.sh` after any agent-image bump.
"""

from __future__ import annotations

import logging
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
        """Open a session and return the agent's own id for it.

        Failure raises. An earlier version invented a `local-…` id here when the
        call failed, which made a broken session route look like a working one
        right up until the send 404'd on an id the agent had never heard of —
        the error then named the wrong problem. If the session cannot be opened,
        that is the error worth reporting.
        """
        url = self._settings.hermes_base_url + self._settings.hermes_session_path
        try:
            response = await self._client.post(url, json={}, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise HermesError(f"could not open a session at {url}: {e}") from e

        session_id = _extract_session_id(_json_or_empty(response))
        if not session_id:
            raise HermesError(
                f"{self._settings.hermes_session_path} returned no session id: "
                f"{response.text[:200] or 'empty body'}"
            )
        return session_id

    async def send(self, session_id: str, message: str) -> str:
        # The default route (/api/chat) carries the session in the body; older
        # per-session routes carry it in the path. Support both — replace() is
        # a no-op when there is no placeholder.
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

        payload = _json_or_empty(response)

        failure = _turn_failure(payload)
        if failure:
            raise HermesError(failure)

        reply = _extract_reply(payload, response.text)
        if not reply:
            raise HermesError("the agent returned an empty reply")
        return reply

    async def delete_session(self, session_id: str) -> bool:
        """Discard a session on the agent. Returns whether it went.

        Best-effort by design: this runs after the caller already has its
        answer, so a failure here is logged and swallowed rather than turned
        into an error for a request that succeeded. The cost of not deleting is
        a session left in the agent's sidebar, not a wrong answer.
        """
        url = self._settings.hermes_base_url + self._settings.hermes_delete_path
        try:
            response = await self._client.post(
                url, json={"session_id": session_id}, timeout=30.0
            )
        except httpx.HTTPError as e:
            log.warning("could not delete session %s: %s", session_id, e)
            return False

        if response.status_code >= 400:
            log.warning(
                "could not delete session %s: HTTP %s %s",
                session_id, response.status_code, response.text[:200],
            )
            return False
        return True


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _turn_failure(payload: dict[str, Any]) -> str:
    """Describe an aborted turn, or "" if the turn completed.

    A turn can end badly and still answer HTTP 200 with a `answer` field: the
    agent puts its own failure text there — "Response truncated due to output
    length limit", "Stream repeatedly dropped mid tool-call" — and flags it as
    `status: "partial"` with `completed: false` alongside.

    Relaying that as if it were the agent's answer is the worst option
    available: the RGS+ user reads an internal error as a reply, and a test run
    records it as a successful answer. So it becomes a 502 like any other
    agent failure. The bridge does not retry — whether to ask again is the
    caller's call, and a truncation usually repeats.
    """
    result = payload.get("result")
    result = result if isinstance(result, dict) else {}

    if result.get("completed") is False or result.get("failed") or result.get("partial"):
        detail = str(result.get("error") or payload.get("answer") or "").strip()
        return f"the agent did not finish its turn: {detail or 'no reason given'}"

    if str(payload.get("status") or "").strip().lower() == "partial":
        detail = str(result.get("error") or payload.get("answer") or "").strip()
        return f"the agent returned a partial turn: {detail or 'no reason given'}"

    return ""


def _extract_session_id(payload: dict[str, Any]) -> str:
    """Find the session id in whatever shape /api/session/new answered with.

    The current image nests it: {"session": {"session_id": "…"}}. Flat shapes
    are accepted too — the nesting is not a documented guarantee either.
    """
    session = payload.get("session")
    if isinstance(session, dict):
        for key in ("session_id", "id"):
            value = session.get(key)
            if isinstance(value, str) and value:
                return value

    for key in ("session_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_reply(payload: dict[str, Any], raw_text: str) -> str:
    """Pull the assistant's text out of whatever shape came back.

    `answer` first: that is what /api/chat returns. Then the other common
    single-field shapes, then a messages list (last assistant turn), then the
    raw body if it was plain text. Permissive by design: an unfamiliar-but-valid
    response should still reach the user.
    """
    for key in ("answer", "reply", "response", "message", "content", "text", "output"):
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
