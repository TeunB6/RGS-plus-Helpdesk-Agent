# RGS+ — helpdesk chatbot on Confluence + Jira

A chatbot that lives **inside the RGS+ application**, answers questions from
the RGS+ **Confluence knowledge base**, and — when the knowledge base doesn't
cover something — **drafts a Jira ticket** on the customer's helpdesk project
for a human to submit.

No mail access is needed anywhere: RGS+ customers already mail the helpdesk
address and Jira turns that into a ticket automatically. The chatbot is the
*other* front door to the same Jira project.

```
RGS+ web app
   │  (embedded widget / REST call)
   ▼
rgsplus-bridge          ← the callable agent module (this repo, bridge/)
   │  ├── /v1/chat            one question in, one answer out
   │  ├── /v1/peers           call other agent modules
   │  └── bearer auth
   ▼
rgsplus-agent           ← Hermes agent in Docker (uppr_hermes image + this repo's library/)
   ├── confluence_*  → the RGS+ knowledge base   (read-only)
   └── jira_*        → customer's Jira Cloud site (search + read; create = DRY RUN)
```

## Read-only by design

One Atlassian API token covers both halves, and it carries read/write access.
So the write half is deliberately not implemented: `jira_create_ticket`
**validates** a ticket, renders the exact payload Jira would receive, saves it
under `.jira-dryrun/` for a human to review and submit, and returns it. There
is no `POST` in that code path.

Consequences, and they matter:

- The agent is instructed **never to quote a ticket key**, because none is
  assigned. Its response carries `created: false`, `issue_key: null`.
- The escalation only completes when a human picks the draft out of
  `.jira-dryrun/` and files it. Nothing does that automatically yet.
- There is no transition, assign, close or delete tool either, so the bot
  cannot touch the helpdesk's workflow no matter what a user talks it into.
  That is a capability boundary, not a prompt instruction — keep it that way.

Turning writes on later means implementing `POST /rest/api/3/issue` in
[library/tools/support/atlassian/\_\_init\_\_.py](library/tools/support/atlassian/__init__.py)
behind an explicit `ATLASSIAN_ALLOW_WRITES=true` gate, then revisiting the
"no ticket key" rules in the `jira-ticket-create` skill.

## What's in this repo

| Path | What it is |
| --- | --- |
| [bridge/](bridge/) | The callable agent module. FastAPI, own container, bearer-auth REST API, peer registry so it can reach other agent modules. |
| [library/skills/support/](library/skills/support/) | The three skills that drive the bot: `customer-service` (the flow), `confluence-knowledge-lookup` (search + cite), `jira-ticket-create` (escalation + dry-run rules). |
| [library/tools/support/atlassian/](library/tools/support/atlassian/) | The one plugin: Confluence read, Jira search/read, dry-run ticket drafting. Atlassian Cloud REST v3 / Confluence v2, Basic auth. |
| [bundles/rgsplus.yaml](bundles/rgsplus.yaml) | The helpdesk vertical: which library items an RGS+ deployment gets. |
| [clients/rgsplus/](clients/rgsplus/) | This client's manifest, branding and `SOUL.md`. No specialist profiles — the main agent runs the whole flow. |
| [widget/](widget/) | Drop-in `<script>` chat launcher for the RGS+ application. |
| [scripts/](scripts/) | `stage-build-context.sh` (assemble the Docker build context — **run before every build**), `preflight-atlassian.py` (verify the day-of credentials), `eval-questions.py` (ask the running bot a list of questions), `probe-hermes-api.sh`. |
| [evals/](evals/) | Question files to run the bot against — real helpdesk mails plus the cases where it should decline or escalate. |
| [docs/DAY-OF-CHECKLIST.md](docs/DAY-OF-CHECKLIST.md) | What to collect on the day, and what to do with it. |

Architecture rationale — why library/bundle/client and not one monolith — is in
[ARCHITECTURE.md](ARCHITECTURE.md).

There is no `knowledge/` directory and no local corpus. The knowledge base
lives in Confluence — that is where RGS+ already maintains it, and a copy here
would be stale the day after it was made.

## What we need from the customer on the day

Full context in [docs/DAY-OF-CHECKLIST.md](docs/DAY-OF-CHECKLIST.md).

| # | Value | Env var | Looks like |
| --- | --- | --- | --- |
| 1 | Atlassian API **token** | `JIRA_API_KEY` | `ATATT3xFfGF0…` (classic) or `ATCTT…` (scoped) — id.atlassian.com → Security → API tokens |
| 2 | Atlassian **account e-mail** | `ATLASSIAN_EMAIL` | `helpdesk@klant.nl` — the account the token belongs to |
| 3 | **Site URL** *or* **cloud id** | `ATLASSIAN_SITE_URL` / `ATLASSIAN_CLOUD_ID` | `https://klant.atlassian.net` for a classic token; a uuid for a scoped one (cloud id wins if both are set) |
| 4 | Target **project** key | `JIRA_PROJECT_KEY` | `HELP` / `SUP` — where ticket drafts are addressed |
| 5 | Knowledge-base **space keys** *(optional)* | `CONFLUENCE_SPACE_KEYS` | `KB,FAQ` — scopes search so internal/archived spaces don't pollute results |

Atlassian Cloud REST uses **HTTP Basic auth, not Bearer**: the username is the
account e-mail, the password is the API token. A valid token with the wrong
e-mail is a `401`, so #1 and #2 are a pair — one without the other is useless.

Verify them in one command before building anything:

```bash
python3 scripts/preflight-atlassian.py
```

It checks auth, confirms Confluence is readable and the configured spaces
exist, resolves the Jira project, lists its issue types, and prints the exact
`.env` block to paste.

⚠️ **Token expiry.** Unscoped Atlassian API tokens expired between 2026-03-14
and 2026-05-12. A token issued before that window may already be dead; its
scoped replacement addresses the site by cloud id, which is why
`ATLASSIAN_CLOUD_ID` exists alongside `ATLASSIAN_SITE_URL`.

## Quick start

```bash
cp .env.example .env          # fill in the Atlassian values + an LLM key
$EDITOR .env

python3 scripts/preflight-atlassian.py   # don't skip this

# Assemble the build context: the uppr_hermes checkout at $HERMES_CONTEXT,
# overlaid with this repo's library/ and clients/. Re-run after every change
# to a skill, plugin, manifest or SOUL.md.
scripts/stage-build-context.sh

docker compose up -d --build

open http://localhost:8080    # chat UI (the widget iframes this)
curl -s localhost:8081/healthz
```

The staging step is not optional and not a convenience: the agent's Dockerfile
lives in `uppr_hermes` and `COPY`s `clients/` and `library/` from *its own*
build context, seeding them at build time. Docker has no way to read those two
directories from a second repo, so they are copied into one context first.
Rationale in the script's header comment.

Ask the bridge a question the way the RGS+ app will:

```bash
curl -s localhost:8081/v1/chat \
  -H "Authorization: Bearer $BRIDGE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"Hoe koppel ik een grootboekrekening aan een RGS-code?"}' | jq
```

## Testing what it actually answers

```bash
python3 scripts/eval-questions.py evals/helpdesk-nl.txt
```

Every question in the file is sent **without a `session_id`**, so the bridge
opens a fresh Hermes session for each one. No question can see another's
answer, and each is a first turn — the same cold start a user gets when they
open the widget and paste a mail. The run aborts with a non-zero exit if two
answers ever come back on the same session id, because then they are not
independent and the results mean nothing.

Answers land in `evals/runs/<file>-<n>/` — `results.json` to diff against the
previous run, `transcript.md` to read. Useful flags: `--repeat 3` (how much
does the same question move?), `--only <id>`, `--concurrency 4`, `--dry-run`.

[evals/helpdesk-nl.txt](evals/helpdesk-nl.txt) holds real helpdesk mails plus
the cases the bot is supposed to *refuse*: billing, fiscal advice, another
customer's ticket, a pasted password, an instruction to ignore its rules. Each
carries a `# note:` saying what the right behaviour is — the file is the
checklist, the tool only collects the answers. Judging them is still a human
reading `transcript.md`.

Ticket creation is a dry run, so escalations in a test run leave drafts under
`.jira-dryrun/` and touch nothing in Jira.

## Embedding in the RGS+ application

```html
<script
  src="https://agent.rgsplus.nl/widget/rgsplus-chat.js"
  data-agent-url="https://agent.rgsplus.nl"
  data-title="RGS+ Helpdesk"
  defer></script>
```

The widget renders a launcher bubble and iframes the agent UI. The agent
container must allow being framed by the RGS+ origin — set
`EMBED_FRAME_ANCESTORS` in `.env` (see [.env.example](.env.example)); the
Hermes image regenerates its frame-ancestors CSP from it at boot.

For a fully custom UI (RGS+'s own chat components), skip the iframe and call
`POST /v1/chat` on the bridge instead — see [bridge/README.md](bridge/README.md).

## How the bot decides to escalate

Encoded in
[library/skills/support/customer-service/SKILL.md](library/skills/support/customer-service/SKILL.md);
in short:

1. **Understand the question** — one round of clarifying questions if what
   happened, what was expected, or the exact error is missing.
2. **Search Confluence** (`confluence_search`, then `confluence_get_page` on
   the pages that look right — excerpts mislead). Search **both languages**
   before concluding the KB has nothing; that is the most common cause of a
   false "not documented".
3. **Answer if the KB covers it**, citing page title and URL. Partial answers
   count: answer the covered part, name the gap, escalate just that.
4. **Check for an existing ticket** (`jira_search_issues`) before drafting —
   an open ticket with a status beats a duplicate.
5. **Draft** (`jira_create_ticket`, dry run) with a summary written for an
   engineer, the customer's verbatim question, the context established while
   triaging, and what was searched. Tell the customer it's with a colleague —
   **no ticket key, no SLA**.

The hard rule underneath all of it: answer from the knowledge base, not from
general knowledge. A `401`/`403`/`404` from Confluence means the KB is
*unreachable*, not that it lacks an answer — the bot says so instead of
falling back on itself or filing a ticket about a documentation gap that
doesn't exist.

## Status

Scaffolding is real and runnable; the deployment specifics are not yet filled in:

- [ ] Atlassian credentials not yet collected — run `scripts/preflight-atlassian.py`
      the moment they arrive.
- [ ] `CONFLUENCE_SPACE_KEYS` unset. Run `confluence_list_spaces` (or the
      preflight) once against the real site and pin the knowledge-base spaces.
- [ ] `clients/rgsplus/brand.env` uses provisional colours — replace with RGS+'s.
- [ ] The bridge's Hermes chat endpoint is set from `HERMES_SEND_PATH`; confirm the
      real route with `scripts/probe-hermes-api.sh` against a running container.
- [ ] Nobody picks drafts out of `.jira-dryrun/` yet. Decide who does, or decide
      to enable real writes.
