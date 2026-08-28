"""Calling other agent modules.

A peer is any service that speaks this same `/v1/chat` contract — another
Hermes module behind its own bridge, most likely. Registering one here lets
the RGS+ module hand a question sideways ("this is an ICT question, not an
RGS+ question") instead of growing tools for every adjacent domain.

Peers are configured by the operator via AGENT_PEERS, never chosen by a model
and never taken from a request body: a caller can only name a peer that is
already on the list, so this cannot become an open proxy.
"""

from __future__ import annotations

import logging

import httpx

from .config import Peer, Settings

log = logging.getLogger("bridge.peers")


class PeerError(RuntimeError):
    """The peer could not be reached or refused the call."""


class PeerRegistry:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._peers = settings.peers
        self._client = client

    def all(self) -> list[Peer]:
        return list(self._peers.values())

    def get(self, name: str) -> Peer | None:
        return self._peers.get(name)

    async def chat(self, peer: Peer, message: str, session_id: str,
                   user: dict | None = None, context: dict | None = None) -> str:
        headers = {"Content-Type": "application/json"}
        if peer.api_key:
            headers["Authorization"] = f"Bearer {peer.api_key}"

        payload = {"message": message, "session_id": session_id}
        if user:
            payload["user"] = user
        if context:
            payload["context"] = context

        try:
            response = await self._client.post(
                peer.chat_url, json=payload, headers=headers, timeout=120.0
            )
        except httpx.TimeoutException as e:
            raise PeerError(f"peer {peer.name!r} timed out") from e
        except httpx.HTTPError as e:
            raise PeerError(f"could not reach peer {peer.name!r} at {peer.chat_url}: {e}") from e

        if response.status_code in (401, 403):
            raise PeerError(
                f"peer {peer.name!r} rejected our credentials (HTTP {response.status_code}). "
                f"Check the {peer.name} entry's token env var."
            )
        if response.status_code >= 400:
            raise PeerError(
                f"peer {peer.name!r} returned HTTP {response.status_code}: "
                f"{response.text[:300] or 'no body'}"
            )

        try:
            payload = response.json()
        except ValueError as e:
            raise PeerError(f"peer {peer.name!r} returned non-JSON") from e

        reply = (payload or {}).get("reply")
        if not isinstance(reply, str) or not reply.strip():
            raise PeerError(f"peer {peer.name!r} returned no reply field")
        return reply.strip()
