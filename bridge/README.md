# rgsplus-bridge

The callable agent module. One stable HTTP contract in front of the Hermes
agent, plus a registry of other agent modules this one can call.

## Why it exists

The Hermes web UI is a chat application. The RGS+ application needs a
*function*: text in, text out, behind auth RGS+ controls, with a shape that
doesn't move when the UI upstream does. The bridge is that seam — and the only
place in this repo that knows how Hermes is reached.

## API

All `/v1` routes require `Authorization: Bearer $BRIDGE_API_KEY`.
Health routes are open so a load balancer can probe them.
Interactive docs while running: <http://localhost:8081/docs>.

### `POST /v1/chat`

```jsonc
// request
{
  "message": "Hoe koppel ik een grootboekrekening aan een RGS-code?",
  "session_id": "rgsplus-7f3a…",        // omit on the first turn
  "user":    {"name": "Jan de Vries", "email": "jan@klant.nl", "organisation": "Gemeente X"},
  "context": {"screen": "Grootboek", "version": "2026.2"}
}

// 200
{
  "session_id": "rgsplus-7f3a…",
  "reply": "Ga naar Instellingen > Koppelingen…",
  "peer": null
}
```

Reuse the returned `session_id` for every following turn — that is what keeps
conversation context. `user` and `context` are optional; they save the bot a
round of questions when a ticket needs filing.

**`"ephemeral": true`** makes the bridge delete the session on the agent once
the answer is out — for one-shot callers (a test run, a batch) that will never
send a second turn and would otherwise leave a session behind per question.
It applies only to a session the bridge opened itself: pass your own
`session_id` and it is ignored, because that conversation is yours to end. A
chat in the RGS+ widget must leave it `false`, or every turn forgets the one
before it. The returned `session_id` still names the (now deleted) session,
which is what makes it usable as a per-question handle in logs.

A turn that the agent aborts — truncated output, a stream that dropped mid
tool-call — comes back as a `502`, not as an answer. The agent reports those
in the same `200` it uses for real replies, with the error text where the
answer goes; relaying that verbatim would show an RGS+ user an internal error
as if the bot had said it.

**`user` is trusted as given.** The bridge does not verify identity — the RGS+
application is the authority, and whatever it sends can end up in a Jira
ticket. Send the authenticated user's details, never a value the browser
supplied unchecked.

Status codes: `401` bad or missing token · `422` malformed body · `502` the
agent is unreachable, timed out, or returned an error. A `502` detail is
written for RGS+'s logs; show users something friendlier.

### `GET /v1/peers` · `POST /v1/peers/{name}/chat`

Other agent modules speaking this same contract. Configured by the operator:

```bash
AGENT_PEERS=ict=http://ict-agent-bridge:8081,sales=https://sales.internal
AGENT_PEER_KEY_ICT=…      # per-peer bearer, name uppercased, non-alnum → _
AGENT_PEER_KEY_SALES=…
```

`POST /v1/peers/{name}/chat` takes the same body as `/v1/chat` and returns the
peer's answer with `"peer": "<name>"` set. Only names already in `AGENT_PEERS`
resolve — an unknown name is a `404`, never a fetch, so this cannot be turned
into an open proxy.

### `GET /healthz` · `GET /readyz`

`/healthz` is liveness (this process serves). `/readyz` also pings the agent
and reports `agent_reachable`; it returns `200` with `"status": "degraded"`
rather than failing, so a probe can distinguish "bridge is broken" from "agent
is still booting".

## Configuration

| Var | Required | Default | Meaning |
| --- | --- | --- | --- |
| `BRIDGE_API_KEY` | **yes** | — | Inbound bearer token. Min 16 chars. Refuses to start without it. |
| `HERMES_BASE_URL` | no | `http://rgsplus-agent:80` | Where the agent container is. |
| `HERMES_SEND_PATH` | no | `/api/chat` | Route that accepts a message. Takes the session in the body; a `{session_id}` placeholder is substituted if the path has one. **Verify — see below.** |
| `HERMES_SESSION_PATH` | no | `/api/session/new` | Route that opens a session. |
| `HERMES_DELETE_PATH` | no | `/api/session/delete` | Route that discards a session, for `ephemeral` requests. |
| `HERMES_TIMEOUT` | no | `120` | Seconds to wait for an answer. |
| `AGENT_PEERS` | no | — | `name=url,name=url`. |
| `AGENT_PEER_KEY_<NAME>` | no | — | Bearer token for one peer. |
| `CORS_ALLOW_ORIGINS` | no | — | Browser origins allowed to call directly. Leave empty if calls go through the RGS+ backend. |
| `LOG_LEVEL` | no | `info` | |

Misconfiguration fails at import, before the port is bound — a broken bridge
never comes up looking healthy.

## The one thing to verify

`hermes-webui`'s HTTP routes are not a published API — there is no route
table to read, only an `if parsed.path == …` dispatcher — so they can move
between versions. All three defaults are verified against the agent image this
repo builds on, and should be re-checked after bumping it:

```bash
scripts/probe-hermes-api.sh    # lists the routes, then exercises all three
```

It creates a session, asks it something, and deletes it, printing what each
route answered. Probe **without an `Origin` header**: hermes-webui runs a CSRF
gate that 403s a request whose Origin doesn't match its own host, and the
bridge — not being a browser — sends none.

`/api/chat` is hermes-webui's synchronous chat endpoint, described in its own
source as a fallback that the frontend does not use. That is what makes it the
right one here: the browser drives `/api/chat/start` plus an SSE stream and
several polling routes, which is a streaming contract, and this is a
request/response one.

A wrong path shows up as a `502` whose detail says exactly that. Nothing else
in the repo needs to change when it's corrected — that's the point of the seam.

## Local development

```bash
cd bridge
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

export BRIDGE_API_KEY=$(openssl rand -hex 32)
export HERMES_BASE_URL=http://localhost:8080
uvicorn app.main:app --reload --port 8081
```
