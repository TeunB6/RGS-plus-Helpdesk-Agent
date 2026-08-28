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
| `HERMES_SEND_PATH` | no | `/api/session/{session_id}/message` | Route that accepts a message. **Verify — see below.** |
| `HERMES_SESSION_PATH` | no | `/api/session/new` | Route that opens a session. |
| `HERMES_TIMEOUT` | no | `120` | Seconds to wait for an answer. |
| `AGENT_PEERS` | no | — | `name=url,name=url`. |
| `AGENT_PEER_KEY_<NAME>` | no | — | Bearer token for one peer. |
| `CORS_ALLOW_ORIGINS` | no | — | Browser origins allowed to call directly. Leave empty if calls go through the RGS+ backend. |
| `LOG_LEVEL` | no | `info` | |

Misconfiguration fails at import, before the port is bound — a broken bridge
never comes up looking healthy.

## The one thing to verify

`hermes-webui`'s HTTP routes are not a published API. `/api/session/new` is
confirmed; the message route is a **default that must be checked**:

```bash
scripts/probe-hermes-api.sh          # lists the routes the container serves
# then set HERMES_SEND_PATH in .env to the one that takes a chat message
```

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
