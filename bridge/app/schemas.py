"""Request and response models — the contract the RGS+ application codes against.

Keep these stable. When the Hermes side changes, adapt hermes_client.py; this
file is what other teams depend on.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=8000,
        description="The user's question, verbatim.",
    )
    session_id: str | None = Field(
        None,
        max_length=128,
        description=(
            "Conversation id. Pass the same value for every turn of one "
            "conversation so the agent keeps context. Omit to start a fresh "
            "conversation; the id is returned so the caller can reuse it."
        ),
    )
    user: dict[str, Any] | None = Field(
        None,
        description=(
            "Who is asking, e.g. {'name': 'Jan de Vries', 'email': 'jan@klant.nl', "
            "'organisation': 'Gemeente X'}. Used for ticket attribution. The RGS+ "
            "application is the authority on identity here — the agent never "
            "verifies it, so do not send anything you would not want in a Jira ticket."
        ),
    )
    context: dict[str, Any] | None = Field(
        None,
        description=(
            "Where in RGS+ the user is, e.g. {'screen': 'Grootboek', 'version': "
            "'2026.2'}. Saves a round trip when a ticket needs filing."
        ),
    )
    ephemeral: bool = Field(
        False,
        description=(
            "Delete the session on the agent once this answer has been given. "
            "For one-shot callers — a test run, a batch — that will never send a "
            "second turn, so sessions don't pile up in the agent. Ignored when "
            "`session_id` is supplied: the bridge only deletes a session it "
            "opened itself. A conversation in the RGS+ widget must leave this "
            "false, or every turn forgets the one before it."
        ),
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    peer: str | None = Field(None, description="Set when the answer came from a peer module.")


class PeerInfo(BaseModel):
    name: str
    url: str
    authenticated: bool = Field(description="Whether a bearer token is configured for this peer.")


class PeersResponse(BaseModel):
    peers: list[PeerInfo]


class HealthResponse(BaseModel):
    status: str
    agent_reachable: bool | None = None
    detail: str | None = None
