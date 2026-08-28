"""Parse the machine-readable trailer the agent appends to its reply.

WHY THIS EXISTS
---------------
The agent's whole output is the user-visible reply — one text stream. That is
right for the chat UI, and useless for anything that has to *render* the answer,
because prose cannot tell a front end whether it is looking at

  * a grounded answer (show the source),
  * a refusal (show a route to a human, not an apology),
  * "I don't know" (offer escalation),
  * or the knowledge base being UNREACHABLE.

That last pair is the one that matters. `library/skills/.../customer-service`
already draws the distinction correctly -- a 401/403/404 from Confluence means
the KB could not be read, not that it lacks an answer -- but the bridge threw
that away, so a broken token rendered as "ik weet het niet" and told a customer
their question was undocumented.

Rather than change the agent into a JSON API (which would break the chat UI and
every other consumer), the agent appends one fenced block to the end of its
reply and this module strips it back off:

    Je kunt de status wisselen door te dubbelklikken op de statuskolom.

    ```sam-meta
    {"state": "answer",
     "citations": [{"title": "Objecten beheren", "url": "https://..."}]}
    ```

DEGRADES GRACEFULLY. No trailer, malformed JSON, an unknown state, a trailer in
the middle of the text -- all fall back to `state="answer"` with no citations
and the reply untouched. A missing trailer must never cost the user their
answer, so nothing here raises.

Note for the UI: `state="answer"` with an EMPTY `citations` list means the model
answered without grounding itself in a page. Treat that as unverified.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("bridge.meta")

#: The states the front end knows how to render. Anything else is coerced to
#: "answer" -- an unrecognised state must not become an unrenderable screen.
VALID_STATES: frozenset[str] = frozenset(
    {
        "answer",           # grounded answer; cite `citations`
        "partial",          # answered in part, gap named, escalation offered
        "clarify",          # the agent is asking, not telling
        "refuse",           # out of scope: billing, fiscal advice, other tenants
        "unknown",          # KB reachable, has no answer -> offer escalation
        "kb_unreachable",   # KB could NOT be read -> system banner, not a bubble
        "safety",           # pasted credentials / personal data -> warn, don't store
    }
)

DEFAULT_STATE = "answer"

# Only a trailer at the very END of the message counts. A fenced block earlier
# in the text is the agent quoting something, not annotating itself.
_TRAILER_RE = re.compile(
    r"\n*```sam-meta[ \t]*\r?\n(?P<body>.*?)\r?\n?```[ \t]*\r?\n*\Z",
    re.DOTALL | re.IGNORECASE,
)

_MAX_CITATIONS = 8


def split(reply: str) -> tuple[str, dict[str, Any]]:
    """Return (reply_without_trailer, meta).

    `meta` always has a valid `state` and a `citations` list, and carries
    `draft` only when the agent reported one. Never raises.
    """
    if not reply:
        return reply, _default_meta()

    match = _TRAILER_RE.search(reply)
    if not match:
        return reply.strip(), _default_meta()

    text = reply[: match.start()].strip()
    raw = match.group("body").strip()

    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("agent trailer was not valid JSON; ignoring it (%d chars)", len(raw))
        return text, _default_meta()

    if not isinstance(parsed, dict):
        log.warning("agent trailer was %s, not an object; ignoring it", type(parsed).__name__)
        return text, _default_meta()

    # An agent that emits ONLY a trailer has said nothing to the user. Keep the
    # original rather than handing back an empty bubble.
    if not text:
        log.warning("agent reply was a trailer and nothing else; keeping raw reply")
        return reply.strip(), _clean(parsed)

    return text, _clean(parsed)


def _default_meta() -> dict[str, Any]:
    return {"state": DEFAULT_STATE, "citations": [], "draft": None, "confidence": None}


def _clean(parsed: dict[str, Any]) -> dict[str, Any]:
    state = parsed.get("state")
    if not isinstance(state, str) or state.lower() not in VALID_STATES:
        if state is not None:
            log.warning("agent reported unknown state %r; using %r", state, DEFAULT_STATE)
        state = DEFAULT_STATE
    else:
        state = state.lower()

    return {
        "state": state,
        "citations": _citations(parsed.get("citations")),
        "draft": _draft(parsed.get("draft")),
        "confidence": _confidence(parsed.get("confidence")),
    }


def _citations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        title = _text(entry.get("title"))
        url = _text(entry.get("url"))
        # A citation the user cannot open is not a citation.
        if not title or not url:
            continue
        out.append(
            {
                "title": title,
                "url": url,
                "space": _text(entry.get("space")) or None,
                "excerpt": _text(entry.get("excerpt")) or None,
            }
        )
        if len(out) >= _MAX_CITATIONS:
            break
    return out


def _draft(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    summary = _text(value.get("summary"))
    if not summary:
        return None
    return {
        "summary": summary,
        "description": _text(value.get("description")),
        "draft_id": _text(value.get("draft_id")) or None,
        "project_key": _text(value.get("project_key")) or None,
    }


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
