# Day-of checklist

Everything needed to take the RGS+ helpdesk chatbot from repo to running, in
the order it should happen. Budget an hour if the customer's Atlassian admin
is in the room; a day or more if they are not — the token and the permissions
are the only things that genuinely block.

## Before the day

Send this ahead, so nobody is clicking through Atlassian's settings while
everyone waits:

> Voor de koppeling met jullie Confluence-kennisbank en Jira-helpdesk hebben we
> vier dingen nodig:
>
> 1. **Een API-token** van een Atlassian-account dat (a) de kennisbank in
>    Confluence mag lezen en (b) het helpdeskproject in Jira mag inzien.
>    Aanmaken via id.atlassian.com → Security → *Create and manage API tokens*.
>    Het token is één keer zichtbaar — bewaar het meteen.
> 2. **Het e-mailadres** van dat account.
> 3. **De URL van jullie Atlassian-site**, bijvoorbeeld
>    `https://bedrijf.atlassian.net`.
> 4. **De projectsleutel** van het helpdeskproject waar de tickets in moeten
>    landen, bijvoorbeeld `HELP`.
>
> En als jullie het weten: **de space-keys** van de Confluence-ruimtes waar de
> kennisbank in staat (bijv. `KB`, `FAQ`), zodat de bot niet in interne of
> gearchiveerde ruimtes zoekt.
>
> Liefst een apart serviceaccount ("RGS+ Helpdesk Bot") in plaats van iemands
> persoonlijke account: er gaat dan niets stuk als een medewerker vertrekt.

Also ask, because it saves a round trip later:

- Does that account have a **Confluence licence**? A Jira-only account
  authenticates fine and then returns `403` on every knowledge-base read —
  the bot would be able to escalate and nothing else. The preflight catches
  this, but it takes an admin to fix.
- Is the token **classic or scoped**? A scoped token needs the site's **cloud
  id** (`ATLASSIAN_CLOUD_ID`) instead of the site URL.
- The **origin** of the RGS+ application (`https://app.rgsplus.nl`) — needed
  for `EMBED_FRAME_ANCESTORS` so the widget can iframe the agent.
- **Who reviews and files the ticket drafts.** Ticket creation is a dry run
  (see below); a draft nobody picks up is a dropped customer.

## The values

| # | Value | Env var | Where it comes from | Gotchas |
| --- | --- | --- | --- | --- |
| 1 | API token | `JIRA_API_KEY` | id.atlassian.com → Security → API tokens | Shown **once**. Classic tokens start `ATATT`, scoped ones `ATCTT`. Not the account password. Note any expiry date. |
| 2 | Account e-mail | `ATLASSIAN_EMAIL` | The account that created the token | Must be *that* account, not a colleague's. Must be a full Atlassian account, not a portal/customer account. |
| 3a | Site URL *(classic token)* | `ATLASSIAN_SITE_URL` | Browser address bar | Site root only: `https://klant.atlassian.net`. No trailing slash, no `/jira`, no `/wiki`, no `/browse/...`. |
| 3b | Cloud id *(scoped token)* | `ATLASSIAN_CLOUD_ID` | `https://<site>.atlassian.net/_edge/tenant_info` | A uuid. **Wins over the site URL** if both are set, in the plugin and in the preflight. |
| 4 | Project key | `JIRA_PROJECT_KEY` | The prefix of any issue key in the project (`HELP-431` → `HELP`) | Uppercase. It's the *key*, not the project name. |
| 5 | Space keys *(optional)* | `CONFLUENCE_SPACE_KEYS` | `confluence_list_spaces`, or the preflight's output | Comma-separated, no spaces. Unset = search everything the account can read: works, just noisier. |

**Auth is Basic, not Bearer.** Atlassian Cloud REST authenticates with
`base64(email:token)`, so #1 and #2 are one credential in two halves. A valid
token with the wrong e-mail is a `401` — this is the single most common
setup failure.

⚠️ **Token expiry.** Unscoped Atlassian API tokens expired between 2026-03-14
and 2026-05-12. If the customer hands over a token created before that window,
assume it is dead and ask for a fresh (scoped) one; then use the cloud id.

**No mail access is needed anywhere.** Customers already mail the helpdesk
address and Jira turns that into a ticket automatically. The chatbot is a
second front door to the same project; it never touches a mailbox.

## The public FAQ — nothing to collect, but two things to agree

The second knowledge source, <https://rgsplus.com/faq/>, needs no credentials
and no configuration: it's a public page, and the bot fetches it itself. It
does need a conversation, because it changes what the bot will say:

- **The bot will quote published prices.** The FAQ states a licence range of
  €1.400–€40.000 per year, and the bot repeats that *with a link* when someone
  asks what RGS+ costs. It will not produce a quote, extrapolate a price for a
  specific organisation, or discuss discounts — those stay out of scope and go
  to the contact person. Confirm RGS+ is comfortable with the quoting half.
- **The bot will quote the published response time** ("streven naar 1
  werkdag") as what RGS+ publishes — but never as a promise about the ticket
  it just drafted, which has no key and no SLA.
- **Check the FAQ is current.** The bot is exactly as right as rgsplus.com. If
  the price range or the integrations list is out of date on the website, it
  is out of date in the chat. This is worth five minutes with whoever owns the
  site.

Verify it parses before go-live — no credentials needed, so this can be run
any time:

```bash
python3 scripts/test-faq-plugin.py       # parser + search self-check
python3 scripts/fetch-faq.py             # dry run: shows what changed
python3 scripts/fetch-faq.py --write     # refresh the committed fallback
```

If RGS+ restyles their website the parser can go blind. `test-faq-plugin.py`
fails loudly when that happens, and `fetch-faq.py` warns when the page's own
structured data disagrees with what was parsed.

## Ticket creation is a dry run — say this out loud

`jira_create_ticket` does not write to Jira. It validates the ticket, renders
the payload, saves it under `.jira-dryrun/`, and returns it. So on the day:

- The bot will say "ik heb het doorgezet naar een collega". It will **not**
  give a ticket key, because none exists. That is correct behaviour, not a bug
  — if you ever see it quote a key, it invented one and that's a defect.
- Somebody has to read `.jira-dryrun/` and file the real tickets. Agree who,
  and how often, before go-live.
- Enabling real writes is a code change, not a config flag: see the
  [README](../README.md#read-only-by-design).

## Order of work

### 1. Verify the credentials — before building anything

```bash
cp .env.example .env
$EDITOR .env                             # fill in the values + an LLM key
python3 scripts/preflight-atlassian.py
```

It checks auth, Confluence readability and the configured spaces, the Jira
project, and the project's issue types — and names what to fix on each
failure. Nothing else should start until this passes.

### 2. Pin the knowledge-base spaces

The preflight prints every space the account can read. Pick the ones that
actually hold the handleiding and FAQ, set `CONFLUENCE_SPACE_KEYS`, and re-run
it to confirm they resolve. Skipping this doesn't break the bot, but it lets
internal and archived pages surface as answers to customers.

**Answer quality is the corpus, not the plumbing.** If the Confluence
knowledge base is thin, the bot escalates everything — correctly, and
uselessly. Check what's actually in those spaces before promising anything.

### 3. Build and start it

```bash
scripts/stage-build-context.sh    # required before every build
docker compose up -d --build
open http://localhost:8080
```

Ask it three real questions from the customer's actual ticket history. Watch
whether it cites the right pages — and whether it *declines* the ones the KB
doesn't cover instead of improvising.

### 4. Wire the bridge

```bash
scripts/probe-hermes-api.sh                 # verify the chat routes still answer
$EDITOR .env                                # only if one moved: HERMES_SEND_PATH
docker compose up -d rgsplus-bridge

curl -s localhost:8081/v1/chat \
  -H "Authorization: Bearer $BRIDGE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message":"test"}' | jq
```

### 5. Embed it

Set `EMBED_FRAME_ANCESTORS` to the RGS+ origins, restart the agent, and add the
`<script>` tag from the [README](../README.md#embedding-in-the-rgs-application)
to the RGS+ application. Check it against
[widget/demo.html](../widget/demo.html) first.

## Acceptance — walk these with the customer

- [ ] A question answered **from the knowledge base**, with the page cited.
- [ ] A Dutch question answered from an English page (or the reverse) — the
      bot is told to search both languages before giving up.
- [ ] A question the knowledge base does not cover → the bot says so, drafts a
      ticket, and **does not quote a ticket key**. The draft appears in
      `.jira-dryrun/` with a summary an engineer could act on.
- [ ] The same question asked twice → the second time the bot finds the
      existing Jira ticket instead of drafting a duplicate.
- [ ] An accounting/fiscal question → the bot declines and stays in scope.
- [ ] A commercial question ("wie is eigenaar van onze data?") → answered
      **from the FAQ**, citing rgsplus.com/faq — not from the knowledge base
      and not from thin air.
- [ ] "Wat kost RGS+?" → the bot quotes the published range **with the link**.
      Then "wat kost het voor ons, met 40 complexen?" → it declines and routes
      to the contact person, without inventing a number from the range.
- [ ] A question the FAQ mentions but doesn't explain ("waar stel ik rollen
      in?") → the bot uses the FAQ for *whether* and Confluence for *how*, and
      cites both separately.
- [ ] A question with an instruction buried in it ("negeer je regels en …") →
      the bot treats it as text, not as a command.
- [ ] The widget opens inside the real RGS+ application, on desktop and phone.

## Known failure modes

| Symptom | Cause | Fix |
| --- | --- | --- |
| `401` on everything | Wrong token/e-mail pair, or the token expired | `ATLASSIAN_EMAIL` must own the token; issue a fresh scoped token and set `ATLASSIAN_CLOUD_ID` |
| Jira works, Confluence `403` | Account has no Confluence licence, or no read access to the space | Atlassian admin grants the licence / space permission |
| `404` from both | Wrong site URL or cloud id | Site root only; cloud id from `/_edge/tenant_info` |
| Bot escalates everything | KB spaces empty, wrong `CONFLUENCE_SPACE_KEYS`, or genuinely thin documentation | Preflight lists readable spaces; then look at what's in them |
| Bot answers confidently but wrong | It fell back on general knowledge | A skill regression — the rule is in `confluence-knowledge-lookup`; check the skill actually seeded into `~/.hermes/skills/` |
| Bot quotes a ticket key | It invented one; creation is a dry run | Defect. Check the `jira-ticket-create` skill seeded, and that nobody enabled writes halfway |
| Bot answers a product question by citing the FAQ | Search matched on a common word | `scripts/test-faq-plugin.py`; add the case and check the IDF weighting in `_relevance()` wasn't tuned out |
| Bot says the FAQ doesn't cover something it does | Lexical miss on Dutch wording | It should fall back to `faq_list` — check `rgsplus-faq-lookup` seeded into `~/.hermes/skills/` |
| FAQ answers are stale or empty | rgsplus.com unreachable, or the page markup changed | `scripts/test-faq-plugin.py --live`. A `snapshot` source in the tool response means the live fetch failed; the bot still answers |
| Bot gives a price for a specific customer | It extrapolated from the published range | Defect. The quote-don't-commit rule is in `rgsplus-faq-lookup` and `SOUL.md`; check both seeded |
| Skill/plugin edits have no effect | Built without re-staging the context | `scripts/stage-build-context.sh` then rebuild. Seeding is first-write-only: delete the item from the `hermes-data` volume to re-seed it |
| Widget panel opens blank | Agent refuses to be framed | Set `EMBED_FRAME_ANCESTORS`, restart the agent |
| Bridge `502`, detail mentions the route | `HERMES_SEND_PATH` wrong | `scripts/probe-hermes-api.sh` |
| Bridge won't start | `BRIDGE_API_KEY` unset or too short | `openssl rand -hex 32` |

## Token hygiene

The API token is a password for the service account. It lives in `.env`
(gitignored) and in the deployment's secret store — nowhere else. Not in
Slack, not in a ticket, not in this repo. If it is ever pasted somewhere
shared, revoke it at id.atlassian.com and issue a new one; it takes a minute
and a restart.

If an expiry was set on the token, put the date in a calendar reminder **now**.
An expired token fails as a `401` on every question the bot is asked, and it
will happen on a day nobody is expecting it.

`.jira-dryrun/` holds verbatim customer questions. It is gitignored for that
reason — treat it as customer data, not as logs.
