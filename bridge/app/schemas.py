"""Request and response models — the contract the RGS+ application codes against.

Keep these stable. When the Hermes side changes, adapt hermes_client.py; this
file is what other teams depend on.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

#: How the front end should render this reply. See bridge/app/agent_meta.py for
#: how it is produced and why it is not inferred from the prose.
AnswerState = Literal[
    "answer",           # grounded answer; render `citations`
    "partial",          # answered in part, gap named, escalation offered
    "clarify",          # the agent is asking a question, not answering
    "refuse",           # out of scope (billing, fiscal advice, another tenant)
    "unknown",          # KB reachable but has no answer -> offer escalation
    "kb_unreachable",   # KB could NOT be read -> system banner, NOT "ik weet het niet"
    "safety",           # credentials / personal data pasted -> warn, do not store
]


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
            "'organisation': 'Gemeente X', 'role': 'gebruiker', 'licence': 'GEM-X'}. "
            "Used for ticket attribution and for scoping the answer. The RGS+ "
            "application is the authority on identity here — the agent never "
            "verifies it, so do not send anything you would not want in a Jira ticket."
            "\n\n"
            "`role` and `licence` are read by the agent and matter more than they "
            "look. RGS+ is one database partitioned by licence, and a normal user "
            "may not see the Stamgegevens menu at all — so an answer that is "
            "correct for an administrator is *wrong* for them, and pointing "
            "someone at a menu they do not have creates the ticket it was meant to "
            "prevent. Send `role` whenever the application knows it.\n\n"
            "⚠️ Trust boundary: the bridge authenticates the RGS+ *application*, "
            "not the end user, so `role` is whatever the caller asserts. That is "
            "fine when the call is made server-side by RGS+'s backend. It is NOT "
            "fine from the browser — a user could set their own role. Do not call "
            "/v1/chat directly from the front end when role scoping matters."
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


class Citation(BaseModel):
    """A Confluence page the answer rests on. Render it — the customer learning
    where the manual lives is the actual fix for their discovery problem."""

    title: str
    url: str
    space: str | None = None
    excerpt: str | None = Field(None, description="The passage the answer was drawn from.")


class TicketDraft(BaseModel):
    """A ticket the agent has PREPARED, not filed.

    Ticket creation is a dry run: the draft is written under `.jira-dryrun/` and
    a human submits it. Render this as something the user confirms — the user
    presses send, the agent never decides to. Do not show a ticket key or an
    SLA; neither exists yet.
    """

    summary: str
    description: str = ""
    draft_id: str | None = Field(None, description="Filename under .jira-dryrun/.")
    project_key: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    peer: str | None = Field(None, description="Set when the answer came from a peer module.")

    # --- Added 2026-08-28. All optional with safe defaults, so callers written
    # against the earlier shape keep working unchanged. ---

    state: AnswerState = Field(
        "answer",
        description=(
            "What KIND of reply this is, so the UI can render it. Defaults to "
            "'answer' when the agent said nothing about it.\n\n"
            "Treat 'kb_unreachable' as distinct from 'unknown': the first means "
            "the knowledge base could not be read (bad token, Confluence down) "
            "and deserves a system banner with a retry; the second means it was "
            "read and had no answer. Collapsing them tells a customer their "
            "question is undocumented when in fact the integration broke."
        ),
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "Pages the answer is grounded in. An empty list on state='answer' "
            "means the model answered without citing anything — treat as unverified."
        ),
    )
    draft: TicketDraft | None = Field(
        None, description="Present when the agent prepared a ticket for the user to confirm."
    )
    confidence: float | None = Field(
        None, ge=0.0, le=1.0, description="Agent's own estimate, when it offers one."
    )


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
