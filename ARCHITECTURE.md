# Architecture

Two independent things live here, and they are deliberately not merged:

1. **The agent module** — a Hermes agent in Docker, plus the RGS+ extensions
   that give it Confluence and Jira capability.
2. **The bridge** — a small, boring HTTP service that makes that agent
   *callable* by the RGS+ application, and lets it *call other agent modules*.

```
┌────────────────────────────────────────────────────────────┐
│ RGS+ application                                           │
│   widget/rgsplus-chat.js  ──iframe──┐                      │
│   or the app's own UI  ──REST──┐    │                      │
└────────────────────────────────┼────┼──────────────────────┘
                                 ▼    ▼
                    ┌─────────────────────────────┐
                    │ rgsplus-bridge  :8081       │  ← callable module
                    │  POST /v1/chat              │
                    │  GET  /v1/peers             │
                    │  POST /v1/peers/{n}/chat ───┼──▶ other agent modules
                    └──────────────┬──────────────┘     (same /v1/chat contract)
                                   ▼
                    ┌─────────────────────────────┐
                    │ rgsplus-agent   :8080       │  ← Hermes + webui
                    │  confluence_* → the KB (ro) │
                    │  faq_*        → rgsplus.com │
                    │                 /faq (ro,   │
                    │                  public)    │
                    │  jira_*       → Jira Cloud  │
                    │                 (create =   │
                    │                  dry run)   │
                    └─────────────────────────────┘
```

## Why a separate bridge container

The Hermes web UI is a *chat application*. The RGS+ application needs a
*function*: text in, text out, with an auth model RGS+ controls and a shape
that doesn't change when the UI upstream does. The bridge is that seam:

- **One stable contract.** `POST /v1/chat` is the only thing the RGS+ app
  codes against. When hermes-webui's internal routes move, the bridge adapts
  and the RGS+ app doesn't notice.
- **RGS+ owns the auth.** The bridge takes a bearer token RGS+ issues. The
  agent container never gets exposed to the internet directly.
- **Peers.** Any other agent module that speaks `/v1/chat` can be registered as
  a peer, so this module can hand work sideways instead of growing.
- **It's cheap to keep.** ~200 lines of FastAPI, no state, no database.

## Layering the agent's capabilities

Same three-level model as `uppr_hermes`, whose base image is vendored under
[agent/](agent/) — that directory carries nothing RGS+-specific, and everything
below is what makes this deployment RGS+.

```
library/          catalog   -- RGS+ building blocks (atlassian plugin, support skills)
   │
   ▼  (selection)
bundles/rgsplus   template  -- the helpdesk vertical: which items a deployment gets
   │
   ▼  (provision-client.py: bundle + branding)
clients/rgsplus/  instance  -- manifest + brand.env + SOUL.md
   │
   ▼  (docker build -f agent/Dockerfile --build-arg UPPR_CLIENT=rgsplus .)
~/.hermes/        runtime   -- the live container's volume
```

### Why the build context is the repository root

`agent/Dockerfile` does `COPY clients/ …` and `COPY library/ …` **from its own
build context**, because the manifest-to-`~/.hermes` seeding runs at build time
(`agent/scripts/apply-library.sh`). There is no runtime overlay that would pick
those two directories up from a bind mount instead.

So the base and the RGS+ half have to sit in one context. They do, because both
are in this repo: the context is the root, and the Dockerfile is one directory
down. `.dockerignore` keeps the context to what is actually COPYed, and keeps
`.env` and `.jira-dryrun/` out of it.

This is a **fork of the base**, and that is the trade. Referencing a sibling
`uppr_hermes` checkout kept the base single-owner, but meant a fresh clone of
this repo could build nothing and named no commit to clone — the deployment was
not reproducible from its own source. [agent/README.md](agent/README.md) records
the upstream commit, the three local edits, and how to diff and re-sync.

Seeding is **first-write only** in the base image: anything already in the
volume is never overwritten, so edits made through the web UI survive
restarts. To pick up a library change, delete that item from the volume and
restart the container.

## Horizontal: which extension type to reach for

| Type | Used here for | Lives in |
| --- | --- | --- |
| **skill** | Markdown instructions: the flow, source routing, search-and-cite rules, escalation policy | `library/skills/support/<name>/SKILL.md` |
| **tool** (plugin) | Python that talks to something remote: `atlassian`, `rgsplus-faq` | `library/tools/support/<name>/` |
| **mcp** | An external tool server. *Not used for Atlassian* — see below | `library/mcp/<name>.yaml` |
| **profile** | Nothing. This deployment has **no specialists** — see below | `library/profiles/<category>/<name>/` |

### Why there are no profiles

An earlier shape had a `jira-ticket-agent` specialist that the main agent
delegated ticket intake to. It was dropped: the whole flow is search → judge →
answer or draft, all of it inside one conversation with one customer, and the
facts a good ticket needs are exactly the facts already in that conversation.
Delegating means serialising that context into a prompt, paying a round trip,
and getting back a ticket written by something that never spoke to the
customer. `clients/rgsplus/manifest.yaml` therefore lists `profiles: []`.

### Why the Atlassian integration is a plugin, not the Atlassian MCP server

The customer gives us an API token, an account e-mail, a site identifier and a
project key — exactly the inputs Atlassian Cloud REST takes with Basic auth.
A plugin using those values:

- needs no OAuth app, no consent screen, no Atlassian-side admin work on the day,
- exposes a **deliberately small surface** — Confluence read, Jira search and
  read, and a ticket-drafting call that never POSTs. There is no tool for
  transitioning, closing, deleting or reassigning, so the bot *cannot* do
  those things even if a user talks it into trying,
- returns token-light summaries instead of Atlassian's very large raw payloads.

The Atlassian MCP server is the right call later, if RGS+ wants per-user
identity (each customer acting as themselves) instead of one shared service
account. That's a swap of `library/tools/support/atlassian/` for a
`library/mcp/atlassian.yaml`, with the skills unchanged.

### Why ticket creation is a dry run

The API token carries read/write. Reads are safe; a write is a real issue in
the customer's live helpdesk project, which means a bug — or a prompt
injection inside a customer's question — files real tickets. So
`jira_create_ticket` validates, renders the payload it *would* POST, saves it
under `~/.hermes/jira-dryrun/` (bind-mounted to `.jira-dryrun/`), and returns
it. There is no HTTP call in that code path, which is a stronger guarantee
than any instruction in a skill.

The cost is that the escalation isn't finished until a human files the draft.
That trade is deliberate for a first deployment and should be revisited once
the ticket quality has been watched for a while — behind an explicit
`ATLASSIAN_ALLOW_WRITES=true` gate, not by deleting the check.

### Why the knowledge base is Confluence, not a local corpus

It's where RGS+'s documentation already lives. An earlier shape in this repo
kept the handleiding and FAQ as markdown under `knowledge/` and searched it
with a local TF-IDF plugin; that's gone, because a copy of documentation that
someone else maintains is stale the day after it's made, and keeping it in
sync is a pipeline nobody signed up to run.

Search is Confluence's own CQL full-text endpoint (`/wiki/rest/api/search` —
the v1 API, deliberately: v2 has no full-text search), with page bodies read
through v2. `CONFLUENCE_SPACE_KEYS` scopes it to the knowledge-base spaces so
internal and archived pages don't surface as answers.

### Why the FAQ is cached when the knowledge base is not

The public FAQ at rgsplus.com/faq is a second source, and it *is* copied into
this repo — `library/tools/support/rgsplus-faq/faq-snapshot.json` — which
looks like exactly the thing the section above rejects. The difference is that
Confluence has a search API and the FAQ does not.

The FAQ is a WordPress page whose custom post type is not exposed over
`/wp-json` (it 404s), so there is no query endpoint. The only way to read it is
to fetch the page and parse it — the whole page, every time. There is no
"leave it where it lives and query it" option to prefer. Given that, the choice
is not *copy vs. don't copy*, it's *where the copy lives and how it's refreshed*:

- The plugin re-fetches the live page whenever its cache is older than
  `RGSPLUS_FAQ_TTL` (24h default) and writes it to `~/.hermes/faq-cache/`, so
  the running bot tracks the website by itself. Nobody maintains it.
- The committed snapshot is the cold-start and offline fallback. Without it,
  the first customer after a deploy — or any customer while rgsplus.com is
  down — gets nothing.
- Its git diff is the only record of what RGS+ changed on their public FAQ,
  which matters because those answers quote prices and response times the bot
  repeats to customers. `scripts/fetch-faq.py` prints that diff.

Every tool response reports which of the three it served (`live`, `cache`,
`snapshot`) and how old it is, so staleness is visible to the agent rather
than silent.

Parsing targets `article.faq[id=faq-NNNN]` and the `faq-block__title` category
headings. The `id` is a WordPress post id, stable across edits, and gives every
answer a citable deep link. Six entries are cross-listed under two categories,
so 42 article elements collapse to 36 items with a `categories` list.

The page also carries Yoast JSON-LD `FAQPage` data, which would be the more
obvious target. It isn't used: it omits categories and disagrees with the
rendered page about which entries exist. Its question count is kept only as a
canary — a large gap means the markup moved and the parser is dropping
entries silently.

**Search is IDF-weighted, and that is load-bearing.** Every second entry
contains "RGS+", so a plain term-overlap score answers "hoe koppel ik een
grootboekrekening aan een RGS-code" with "Hoe veilig is RGS+?" — a confident
citation of an unrelated answer, which is the worst failure this bot has.
Weighting terms by rarity drives the product name to nearly zero without a
hand-maintained stopword list, and scores are normalised to 0.0–1.0 so one
threshold works across queries. `scripts/test-faq-plugin.py` pins that
behaviour with negative cases; run it after touching the scorer.

## Where things end up at runtime

```
image                                container volume
─────────                            ─────────────────
/etc/uppr-soul.md         ──seed──▶  ~/.hermes/SOUL.md
/etc/uppr-library/
  skills/                 ──seed──▶  ~/.hermes/skills/
  tools/                  ──seed──▶  ~/.hermes/plugins/ + config.yaml (plugins.enabled:)
  profiles/               ──seed──▶  ~/.hermes/profiles/   (empty here)
.jira-dryrun/             ◀─mount──  ~/.hermes/jira-dryrun/ (ticket drafts out)

                                     ~/.hermes/faq-cache/   (written at runtime
                                       by the rgsplus-faq plugin; not seeded,
                                       not mounted, safe to delete)
```

`.jira-dryrun/` is mounted **outwards**: the drafts are the deliverable of an
escalation, so they must be readable without `docker exec` and must survive
`docker compose down -v`.

## Decision tree

| Question | Answer |
| --- | --- |
| New helpdesk behaviour, expressible as instructions? | New **skill** in `library/skills/support/`, add to `bundles/rgsplus.yaml` and the client manifest |
| New Atlassian operation the bot needs? | New tool in `library/tools/support/atlassian/__init__.py` — and think hard about whether the bot should be able to do it, especially if it writes |
| Answer quality problem? | Almost always the Confluence knowledge base, or `CONFLUENCE_SPACE_KEYS` scoping — not code |
| Bot cites the FAQ for a product question, or misses one it covers? | The scorer or the routing table in `rgsplus-faq-lookup`. Add the case to `scripts/test-faq-plugin.py` first, then fix |
| RGS+ changed their public FAQ? | Nothing — the plugin re-fetches within 24h. Run `scripts/fetch-faq.py --write` to refresh the committed fallback and see the diff |
| Another public page worth answering from? | Another plugin like `rgsplus-faq`, not a second source inside it — one plugin per source keeps the citation honest |
| Another system to reach (e.g. RGS+'s own API)? | New **plugin** if it's a handful of endpoints; **mcp** fragment if a server already exists |
| Another agent module should handle it? | Register it as a **peer** on the bridge |
| Edited a skill/plugin and nothing changed? | `docker compose up -d --build` (seeding is at build time, so a restart is not enough), then delete the item from the `hermes-data` volume — seeding is first-write-only |
