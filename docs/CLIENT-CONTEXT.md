# RGS+ — client context

Everything we know about RGS+, their helpdesk, their users and their constraints, and
everything we still need from them.

**Provenance.** Sourced from the RGS+ / UPPR working session of **2026-08-28** (10:00–12:00),
captured as 17 Dutch voice notes and transcribed with **Whisper large-v3-turbo**; three
forwarded e-mail screenshots; the RGS+ Desktop changelog v3.1.3 → v3.3.1; the six `.xlsx`
import templates Brian sent; and `rgsplus.com` / `rgsplus.com/faq/` as published.

> ⚠️ Every Dutch quote below is from the Whisper transcripts. **Telegram's own
> auto-transcription of these recordings was unusable** — it produced fluent-looking nonsense
> ("verkoopmodel" for "goedkoop model") and rendered Dutch as German in places. Two claims
> were misread from it before re-transcription. Never quote the client from an auto-transcript.

**Status.** This is discovery, not agreement. Where something has been decided it is marked
**DECIDED**. Everything else is our reading and should be checked with Brian or Arjan.

---

## 1. Who

| Name | Org | Role |
| --- | --- | --- |
| **Brian Bergman** | RGS+ | Consultant. Runs the helpdesk. The domain expert — nearly everything below comes from him. `brian@rgsplus.com`, 0546-87 12 95 |
| **Arjan Engbers** | RGS+ | Owns the changelogs, sent the Atlassian API token |
| **Teun Boersma** | UPPR | Builds the agent |
| **Kian Horsmeier** | UPPR | Sent the OpenRouter key |
| **Juan Sebastián Burgos** | Blocktank, with UPPR | Scoping and design |
| **Joep** | ? | RGS+ spoke to him about this before; UPPR wants him on the technical side |

**Working name for the assistant: Sam.** Brian: *"Ik zat te denken aan Sam. Samenwerken met AI."*

⚠️ **Mitfavo** appears in the transcripts as a cost example only — 300 developers × ~€1.000/month
in tokens. That is where a UPPR compagnon works. **It is not RGS+'s situation** and should not
be cited as if it were.

---

## 2. The product being supported

**RGS+** — *"registrerend softwarepakket voor vastgoedonderhoud"*. Dutch software for planned
property maintenance (MJOP). Web, desktop and mobile. One shared database, partitioned by
licence. Hosted, per their own FAQ, in *"twee groene tier3 datacenters in EU"*.

**Domain vocabulary the agent must speak** (Dutch, and it must not translate these):

> objecten (woningen / utiliteit, met Vhe) · complexen · structuren · elementen · inspecties ·
> inspectielijsten · inspectie-items · labels · meetplaatsen · stadia · methode (o.a. **NEN 2767**) ·
> categorie (ernstig / serieus / gering) · maxomvang & **KPI** · scenario's (MJOP: lagen →
> elementen → maatregelen → uitvoeringsjaar) · prijzenboek · maatregelen · eenheid ·
> BTW (H/L/N/V) · **NL-SfB** · **CO₂ / MKI** · stamgegevens · regievoerder ·
> opdrachtgever / opdrachtnemer · borging · rayon · Aedes-benchmark

**Modules** (from the changelog): Rechten en rollen · Team · Structuren · Inspectie ·
Inspectielijsten · Scenario · Object documenten · Strategie/borging · Data-analyse ·
Rapporten · Prijzenboek.

**Interop:** XML import/export; imports from **Gilde**, **IBIS** and **O-Prognose**.

**Their users are not technical.** Brian, on how many are:
> *"dat is 10% van de markt, als het al 10% is."*

Answers must be plain, one step at a time, in Dutch.

---

## 3. How support works today

### Channels
- **E-mail → Jira, already automated.** *"Als mail komt op de helpdesk… die hebben we al
  geautomatiseerd, omdat die ook een Jira-ticket wordt."*
- **Phone** (0546-49 26 68, weekdays 08:30–17:00). Brian answers application questions
  himself; technical ones he redirects: *"Stuur een mail naar de helpdesk, en dan komt die bij
  ons in Jira."*
- **WhatsApp / mobile** straight to Brian, off the record.

### Volume
**1–2 tickets per day**, *"soms iets meer"*.

> This is the design point, not a problem to engineer around. It means **quality per answer
> matters far more than throughput**, latency is not a constraint, and a small model on modest
> hardware is more than enough. It also means live traffic will never produce a large
> evaluation set — see §11.

### The knowledge base
- The manual lives in **Confluence**, one page per topic.
- The RGS+ application shows a **"?" icon** on each screen whose pop-up renders **that same
  Confluence text**:
  > *"Dit is Confluence. En hier kun je pagina's aanmaken… Wat je dan in de applicatie kunt:
  > die handleiding raadplegen — is eigenlijk die Confluence-teksten raadplegen. Dan krijg je
  > in de pop-up de tekst. Dit is dan diezelfde tekst die hier staat bij Strategie."*
- Access is inherited: *"Als jij toegang hebt tot Confluence, dan heb je eigenlijk ook toegang
  tot deze data."*
- **Nothing AI exists in the product today.** *"Hebben jullie hier al AI standaard
  geïntegreerd? Nee, helemaal niet."* / *"Er is dus nu nog geen… plek van."*

### 🔑 Their real problem is discovery, not content
> *"Klanten weten alleen heel vaak niet dat het überhaupt inzit. Dus je krijgt heel veel
> onnodige vragen."*

The answer is usually already written. The customer never found it.

**Consequence for this project, and it should be said to RGS+ out loud:** a chatbot that
answers *tickets* does not fix discovery, because by the time a ticket exists the customer has
already failed to find the manual and already mailed. Fixing discovery means putting the
assistant where the **"?"** already is. So the realistic win for a first version is
**answer quality and Brian's time — not ticket deflection.** Agreeing that up front avoids
being measured later against a number this design cannot move.

### ⚠️ The Jira board is mixed
> *"Die oranje, dat zijn vragen. En die groene en die rode, dat zijn dingen die ik zelf heb
> ingeschoven. Het is een beetje een mengelmoes tussen enerzijds klantvragen en anderzijds
> dingen die in de sprint bezig zijn. En dan hebben we nog weer andere dingen die puur heel
> technisch zijn — dat is onze programmeur met de developers."*

Grounding on the whole board mixes customer Q&A with sprint chatter. We need a label, issue
type or request type that isolates customer questions.

**Likely shortcut:** customer tickets are auto-created from helpdesk e-mail, so their
**reporter is an external address**, while Brian's own items and developer issues come from
internal accounts. That may separate them without anyone having to define a filter.

---

## 4. What customers actually ask

Four classes, from Brian's own examples.

### a. Discovery — the answer was in the manual
Biggest volume. Fixed by putting the answer where the "?" already is.

### b. Trivial UI — one sentence and a pointer at a button
> *"Hoe kan je ook alweer een status wisselen?" — "Dubbelklik op status." — "Oh ja, nu weet ik het weer."*
> *"Hoe maak ik ook alweer een kopie?" — "In die actiekolom zie je zo'n icoontje met twee van die blaadjes."*
> *"Hoe kan ik een rapportje genereren?"*

⚠️ These answers are **visual**. Text may not be enough — an open question is whether
Confluence holds usable screenshots we can cite or embed.

### c. Import failures — the hard class
> *"Ik ben zelf aan het puzzelen en ik krijg mijn import niet voor elkaar."*
> *"Je hebt een Excel en dan heb je een bepaalde kolom die is numeriek. Maar in de Excel staat
> knippen/plakken ofzo en dan is het als tekst, en dan pak je dat weer niet."*
> *"Soms heb je een bepaalde kolom met een verplicht veld en een verplichte waarde, en dat
> staat ook netjes in de uitleg. Dan doe je dat met een hoofdletter en dan… dat staat ook bij:
> hoofdlettergevoelig."*

And the doubt he stated directly, which this project can answer:
> *"Ik heb geen idee of een AI-agent dat soort dingen eruit kan filteren."*

See §5 — it can, and not with an LLM.

### d. Scope / process — probably should not be answered at all
> *"Ik wil dit en dit — dat is eigenlijk meer een soort uitbreiding van functionaliteit, of:
> ergens in het proces moet ik iets doen voor een bepaalde klant. Kan dat met jullie software?
> Of hoe kan dat?"*

These are commercial conversations. Route to a human.

**We do not know the mix.** How many of the 1–2/day fall in each class is the single most
useful thing Brian could tell us, and it decides where effort goes.

---

## 5. The import templates — and why this is the best first win

Six templates: `adressen`, `objects`, `pricebook`, `inspectionlist`, `scenario`, `structure`.

### They document themselves
Every template ships a data sheet **plus an `uitleg` sheet with a literal field table**. Two
layouts exist:

- **A** — `Header | Type | Verplicht | Uitleg` (adressen, objects, pricebook, inspectionlist)
- **B** — `header | import | omschrijving` (scenario only; no type column, and it uses `n.v.t.`
  for fields that appear in an export but are **ignored on import** — which is not the same
  thing as optional)

**The template is the spec.** Validation rules can be derived from the file rather than
hand-written, so a new template validates for free.

### 🚨 The importer fails silently, by design
From `objects.xlsx`'s own uitleg sheet:
> *"Bij ontbrekende waarde of een tekst bij vhe in de cel wordt de regel **overgeslagen** met import."*
> *"De kolom [type] is verplicht. Bij ontbrekende of foutieve waarde wordt de invoer **'utiliteit'**."*
> *"Bij een ontbrekende waarde of foutief geschreven naam wordt het veld **niet gewijzigd**."*

No error is ever shown. Rows vanish, types silently become `utiliteit`, links never happen.
**That is precisely why users cannot say why their import failed.**

Also: **the importer reads only the first sheet.** Every template warns
*"zorg dat het import tabblad vooraan staat !!!"* — a user who reorders the tabs silently
imports the instructions as data.

A support ticket is literally written into one of the templates: `inspectionlist.xlsx` has an
`uitleg KPI` sheet opening with
> *"We krijgen herhaaldelijk vragen waarom de KPI check niet het verwachte resultaat geeft."*

### Field constraints found in the uitleg prose
`Type` ∈ {woningen, utiliteit} · `Vhe` ≥ 1 · `categorie` ∈ {ernstig, serieus, gering} ·
`maxomvang` 0–100 · BTW ∈ {H,L,N,V} in **pricebook** but only {N,H,L} in **scenario**
(*"een import met BTW verdelen is niet mogelijk"*) · opdrachtgever/opdrachtnemer names are
**hoofdlettergevoelig**.

Note the trap: same field name, different rules per template.

### 🔑 The design consequence
**Import failures are not an LLM problem.** A deterministic validator reads the template's own
`uitleg` sheet, derives the schema, and finds the fault; the model's only job is to explain it
in plain Dutch and say what will happen — *"rij 47 wordt overgeslagen omdat vhe leeg is; RGS+
meldt dit niet."*

That is a better answer to Brian's doubt than "yes, AI can do that", and it is the strongest
demo available: a customer drops in a broken file and gets a specific, correct, non-obvious
diagnosis.

**A working validator already exists** at `~/rgsplus/validate_import.py` (Blocktank side),
verified across all six templates. It catches text-where-numeric, missing mandatory values,
bad enums, below-minimum, out-of-range, wrong tab order and documented case-sensitivity, and
reports the *consequence* rather than just the error. Two behaviours in it are deliberate and
worth keeping if it is ported: it **refuses to run** if it cannot parse a spec rather than
reporting a broken file as clean, and it only treats quoted values as a **closed** enum when
the wording says so — `scenario`'s `laag` reads *"laag van element OF "inspectie" /
"staartkosten""*, which is free text with two special values, and reading it as an enum flags
every correct row.

This maps directly onto the second of the three endpoints sketched in `notes/plan.md` at
`9dfdcd5` — *"xlsx sjabloon invullen en versturen, human in the loop"*. That file was removed
in `9c2442f`.

**Now ported**, as `library/tools/support/import_check/`, with both deliberate behaviours
above intact. It landed as an agent **tool** rather than the third bridge endpoint that was
sketched: the agent calls it mid-conversation, so RGS+ does not have to build an upload flow
before this is worth anything. The file still has to reach the container — `docker-compose`
bind-mounts `./.uploads`, and the tool refuses any path outside it. What is *not* built is a
customer-facing upload path in the RGS+ application itself; today a human puts the workbook in
that directory.

---

## 6. The permission model — this is the product's shape

> *"Ook bedrijf heeft zijn eigen licentie. En daarin beheren we ook zijn eigen stamgegevens en
> zijn eigen objecten. En als er een paar mensen aangehaakt worden om toegang te krijgen tot
> dat object, dan krijgen ze alleen leesrecht."*
> *"Maar je hebt ook gebruikers die bijvoorbeeld helemaal geen stamgegevens zien."*
> *"Als jij gebruiker bent, dan zie je alleen objecten en je inspecties/scenario's. Maar je
> ziet bijvoorbeeld niet de hele stamgegevens-inrichting."*

One shared database, partitioned by licence. Object documents can be set **privé** —
*"volledig onzichtbaar voor andere bedrijven"* (3.3.0). And *"het wijzigen van een object is
alleen mogelijk als u zelf de regievoerder bent"*.

**DECIDED** — Brian, unprompted:
> *"Eigenlijk moet je die agent koppelen aan de rol die de gebruiker heeft."*

### Why this matters more than it first appears
**An answer that is correct for an administrator is wrong for a normal user who cannot see
that menu at all.** Telling someone to open Stamgegevens when their role has no Stamgegevens
menu is not a partial answer — it is a wrong one, and it generates the support ticket it was
meant to prevent.

Cross-tenant leakage would be a contractual problem, not an embarrassing one.

### 🔑 But it is a *rendering* problem, not a retrieval problem
Confluence is **not partitioned by role** — it is one generic product manual. So this does not
need per-role indexes or an access-control layer over the knowledge base. It needs:

1. the caller's **role** and **licence** available at answer time, and
2. a **role → visible-menus map** from RGS+,

so the answer can say *"dat staat onder Stamgegevens; jouw rol heeft daar geen toegang toe —
vraag je beheerder om…"* instead of confidently pointing at a menu that isn't there.

That is one table from Brian, not an authorization system.

**Open:** does the in-app "?" pop-up already respect role? If it does, part of this is solved
for free. If everyone sees the same page, the assistant has to do the scoping itself.

---

## 7. Versioning

The changelog spans **3.1.3 → 3.3.1**, and behaviour changed *and then reverted*: priority
(laag/middel/hoog) could not be fully removed, and in 3.3.1 *"kan nu weer volledig verwijderd
worden, i.p.v. de oude waarde geen."*

**A flat knowledge base will give a 3.2 customer the 3.3.1 answer with full confidence.**

Same shape as roles: don't build version-partitioned knowledge. Tag changelog entries with
their version, put the customer's version in the request context, and let the answer carry a
qualifier.

**Open:** do all customers run the same version, and does RGS+ know who runs what? They host
it, so almost certainly yes — but it has never been confirmed.

Changelogs come from development. **Arjan** owns them.

---

## 8. Decisions the client already made

Do not relitigate these.

| Decision | Their words |
| --- | --- |
| **Read-only. No writes, no actions.** | *"Agent mag toch nog niets aanmaken. Mag alleen output geven."* |
| **Scoped to the user's role.** | *"Eigenlijk moet je die agent koppelen aan de rol die de gebruiker heeft."* |
| **No e-mail sending in v1.** | *"Dat sluit ik sowieso in eerste instantie niet aan — dat is wat veel."* |
| **Start with a cheap model.** | *"We beginnen gewoon even met een hartstikke goedkoop model."* |
| **Build in UPPR's existing cloud.** | *"We kunnen in onze cloudomgeving die UPPR al heeft, gewoon gaan bouwen."* |
| **Corpus = Confluence + Jira + changelogs + FAQ + importsjablonen. Not source code.** | *"Toch niet die code enzo? Nee."* |
| **It is a customer service agent for the RGS+ helpdesk itself** — not a module resold to RGS+'s own customers | confirmed 2026-08-28 |

### The guardrail reasoning — preserve it, it is good
They talked themselves out of giving the agent e-mail access:

> *"Hij heeft geen skill om een mailtje te versturen. Dan zou hij kunnen zeggen: oké, ik moet
> een mailtje versturen, ik heb geen skills… ik ga nu zelf een scriptje maken om via die API
> een mail te versturen."*
> *"Om dat scriptje te runnen moet je toestemming krijgen van de gebruiker. En dat scheelt. Ik
> kan het ook uitzetten — ik zet het zelf nooit uit. Maar sommige mensen doen dat wel."*
> *"Die voorwaarden moeten wel goed."*

**Conclusion: an agent that can improvise around a missing capability does not really have
permissions.** This is exactly why `jira_create_ticket` in this repo is a dry run with no
`POST` in the code path rather than a prompt instruction — a capability boundary, not a rule.

### One distinction to write down before it gets re-argued
An **escalation button that files a ticket is a write** — but it does not violate
*"agent mag niets aanmaken"*, because **the user presses it; the agent does not decide to.**
The agent's output is still only text. Worth stating in these words now.

---

## 9. Hard constraints

### a. Data residency is a sales blocker, not a preference
> *"Als wij data opslaan ergens beveiligd in Amerika, dan is het al een verhaal."*
> *"Ik heb laatst een vragenlijstje gekregen van 58 vragen waar je aan moest voldoen."*

Some RGS+ customers refuse cloud outright. **And RGS+ already publish a written commitment**
on `rgsplus.com/faq/`: *"De data staat in beveiligde database in twee groene tier3 datacenters
in EU met monitoring en back-up."*

⚠️ **This repo's `.env.example` currently defaults to `LLM_PROVIDER=openrouter` with
`anthropic/claude-sonnet-4-5`.** OpenRouter is US and routes to US providers. That is a fine
default for a scaffold and **must not survive into anything a customer touches** — nor be
pointed at real Confluence content during development without explicit written permission.
Decide the inference path before the first real run.

### b. Token-metered pricing is dead
Brian ran the numbers on his own customers:
> *"Zeker mijn klanten die om de AI vragen, dat zijn ook gelijk de absolute hoofdgebruikers.
> Ik heb daar een rekensom tegenaan gehouden… zij gaan ongeveer drie keer aan tokengebruik
> betalen voor wat ze voor licentie betalen."*
> *"Wat ik wil is gewoon: licentie module AI."*

A subscription line, not pass-through. He noted OpenRouter is now owned by Stripe, which would
make margin-billing easy, **and explicitly rejected it**.

### c. Local inference is wanted, and affordable
UPPR's pitch: NVIDIA **DGX Spark** 128 GB ≈ €7–8k (*"voor de meeste use cases al perfect"*);
**DGX Station** 760 GB up to €90k. One-off cost, then *"daarna is het gebruik van AI gratis —
alleen een beetje stroom."* Brian: *"die 10.000 euro kom ik helemaal een keer te boven."*

RGS+ have the space: *"we hebben echt forse overcapaciteit bij beide pods"*, office-hours load
only.

⚠️ **A coupling to watch:** "small cheap local model" and "skip retrieval, put the whole manual
in context" are **incompatible**. If the corpus turns out to fit in a large context window,
that is the simplest good architecture — but it needs a big context window, which a small local
box will not give you comfortably. Pick one; do not promise both.

**Not decided:** whether v1 is EU-hosted cloud with local later, or local from day one.

### d. Concurrency
> *"Piekbelasting kan wel in de honderden"* — but prefaced with *"dat kan ik helemaal niet
> inschatten."* Treat as unverified. Office hours only, no weekend load.

---

## 10. Suggested method — measure before building

At 1–2 tickets a day, **live traffic will never produce a meaningful evaluation set.** The
Jira back-catalogue is the only real evidence available about whether this works.

**The one number that decides what this project is:**

> Of the resolved customer tickets in Jira, **what fraction were answerable from Confluence
> alone?**

- **~80%** → this is an AI project. The assistant retrieves and phrases.
- **~30%** → this is a **documentation** project with an AI front end. The answers live in
  Brian's head, and no model choice, no retrieval tuning and no GPU will change that.

Nobody knows this number, and it is cheap to get: split each resolved ticket into the
customer's question and Brian's resolution — a gold-standard Q&A set written by the domain
expert, for free — hold it out, and check coverage.

**Free byproduct, and it is commercially useful:** every ticket whose answer was *not* in
Confluence is a page RGS+ should write, ranked by how often it has been asked. That is a
deliverable RGS+ gain value from even if the assistant underperforms.

⚠️ **This conflicts with a deliberate decision in this repo.** `ARCHITECTURE.md` removed the
local corpus on the grounds that *"a copy of documentation that someone else maintains is stale
the day after it's made"* — which is correct for **serving**. But live CQL search answers one
question at a time and tells you nothing about aggregate coverage. **Resolution: a one-off
offline snapshot purely for measurement, never shipped, never served, deleted afterwards.**
Live search stays the serving path.

### How this relates to `evals/` (added in `9c2442f`)
`scripts/eval-questions.py` plus `evals/helpdesk-nl.txt` already do the harder half of this
well: 28 cases sent on **independent sessions** — no `session_id`, so every question is a cold
first turn, and the run aborts if two answers ever share a session id. Three are real helpdesk
mails; the rest are built around them, weighted deliberately toward the cases where **not
answering is the right answer** — out of scope, too little information, a pasted password, a
prompt injection, another customer's data, a request for an SLA.

Two things it is not, and both are worth being explicit about rather than assuming they are
covered:

- **It is a behaviour checklist, not a coverage measurement.** 28 hand-written cases tell you
  whether the bot behaves; they cannot tell you what fraction of the *real* ticket population
  Confluence can answer. That number needs the back-catalogue (§11 items 5–6). The two are
  complementary — keep both.
- **Nothing exercises role or licence.** The file format supports `# user.<veld>`, but only
  `# context.screen` is used, three times. So the single requirement Brian stated most
  directly (§6) is currently untested. Cheap fix with high value: add paired cases — the same
  question asked as an administrator and as a plain user who has no Stamgegevens menu, where
  the correct answers **differ**. Until a case like that exists, nothing will catch the
  failure mode.

There is also no case that submits an actual broken `.xlsx` (`import-formaat` is a
how-question). That *followed* from the validator not existing; with `import_check` in the
bundle it no longer does. A case that puts a deliberately broken workbook in the upload
directory and checks the bot names the skipped row — rather than searching Confluence and
declaring it undocumented — is now the obvious next eval to write.

**On model choice.** Establish the quality ceiling first on a strong (EU-hosted) model, measure,
*then* descend to cheaper and local until quality drops. Starting cheap makes every bad answer
ambiguous — model, knowledge base, or retrieval? Doing it this way turns Brian's
*"hoe goedkoop kan het model zijn"* into evidence instead of an opinion, which is what he
actually wants.

---

## 11. What we still need from RGS+

### 🔴 Blocking
| # | What | Who | Why |
| --- | --- | --- | --- |
| 1 | **The Atlassian account e-mail that owns the API token** | Arjan | Atlassian Cloud REST is HTTP **Basic** auth (email:token). The token alone is a 401. `arjan@rgsplus.com` has been tried and **did not work** |
| 2 | **A rotated API token**, ideally on a dedicated **"RGS+ Helpdesk Bot" service account** | Arjan | The current one travelled through plaintext e-mail and chat screenshots. A service account also means nothing breaks when someone leaves |
| 3 | **Jira project key** for the helpdesk project | Arjan | `JIRA_PROJECT_KEY` — where drafts are addressed |
| 4 | **Confluence space key(s)** holding the knowledge base | Arjan | `CONFLUENCE_SPACE_KEYS` — unscoped search drags in internal and archived pages |

Site URL is already known: **`https://rgsplus.atlassian.net`** (verified; Jira and Confluence
on the same Cloud site). Run `scripts/preflight-atlassian.py` the moment 1–4 arrive — it checks
auth, confirms Confluence is readable, resolves the project and lists issue types in one command.

⚠️ Unscoped Atlassian API tokens expired between **2026-03-14 and 2026-05-12**. The token we
were given is classic/unscoped and was issued **22 July 2026**, so plausibly alive — but a
scoped replacement addresses the site by **cloud id**, which is why `ATLASSIAN_CLOUD_ID` exists
alongside `ATLASSIAN_SITE_URL`.

### 🟠 Shapes the design
| # | What | Who |
| --- | --- | --- |
| 5 | **5–10 ticket numbers that are typical customer questions.** Easier to answer than "define a JQL filter", and better for us — we reverse-engineer the filter from real examples | Brian |
| 6 | A **CSV/JSON export of the Jira back-catalogue** — one round trip instead of a permissions debugging loop | Arjan |
| 7 | The **ticket mix**: of the 1–2/day, how many are discovery / trivial-UI / import / scope | Brian |
| 8 | **Does the in-app "?" already respect the user's role?** | Brian |
| 9 | **Do all customers run the same version**, and does RGS+ know who runs what? | Brian / Arjan |
| 10 | The **role → visible-menus map** — which roles see which menus | Brian |
| 11 | Can RGS+ **mint a signed token** carrying licence + role + version when a user opens the assistant? | Arjan |
| 12 | Does Confluence hold **usable screenshots** for the visual trivial-UI answers? | Brian |
| 13 | May we process Confluence/Jira content through an **EU-hosted cloud model** during development, or must everything be local from day one? | Brian |
| 14 | Does RGS+'s **Font Awesome Pro** licence cover an assistant subdomain? Their site uses FA6 Pro, which is paid and per-domain | Arjan |
| 15 | **Screenshots of the RGS+ application itself** — the brand tokens we have were extracted from the marketing site, which may differ | Brian |

### Also worth resolving internally
- **Who picks drafts out of `.jira-dryrun/`?** A draft nobody files is an escalation that never
  happened: the customer was told *"een collega kijkt ernaar"* and nothing occurred. At 1–2
  tickets a day the manual path is genuinely viable — but it has to be assigned to a person,
  not left implied.
- **What happens when the assistant does not know?** Silence, "ik weet het niet", or hand off?
  And which classes should it *refuse* — the scope/process ones are commercial conversations.
- **Who maintains the knowledge base, and who notices when it goes stale?** This is Brian's
  *"hoe snel is het gedateerd?"* fear in operational form.

---

## 12. Branding

RGS+'s design system is published as CSS custom properties on `rgsplus.com`. These are their
actual values, not an approximation — but they came off the **marketing site**, and have not
been approved by RGS+.

| | |
| --- | --- |
| **Brand blue** | `#297ACC` (hover `#2163A6`) — identity, links, secondary |
| **Primary CTA** | **`#23C477` green** (hover `#1A9158`) — *their primary button is green; blue is secondary* |
| **Page background** | `#E0F0FF` — a cool blue-white, not pure white |
| **Body text / ink** | `#2D3B59` |
| **Borders** | `#CBDFEC` · **Muted** `#B8C5D4` · **Surface** `#FFFFFF` |
| **Error / success** | `#EA2D2D` / `#38BD48` |
| **Fonts** | **Outfit** (body/UI) + **Kanit** (headings), **self-hosted woff2 — no Google Fonts CDN call anywhere on their site**. Both are SIL OFL, free to self-host |
| **Radii** | 4px small / 16px large · **stroke** 1.5px · **base** 16px |
| **Breakpoints** | 480 / 780 / 1024 / 1280 |

⚠️ **The logo has its own 7-colour palette** (`#9AC31C`, `#5D367C`, `#4B8AC9`, `#EF7D00`,
`#FFE000`, `#E40E20`, `#A3C5D2`). Those are artwork colours. Using them for UI chrome is the
most common way a "branded" build looks wrong.

⚠️ **Font Awesome 6 Pro** is what their site uses — paid, per-domain. We cannot copy their kit.
Either get the licence extended, or use FA Free or Lucide (which matches the 1.5px stroke token
better). Decide before component work; swapping icon sets late touches everything.

`clients/rgsplus/brand.env` currently holds a placeholder marked PROVISIONAL. Correct replacement:

```
SKIN_COLORS="#2D3B59,#297ACC,#E0F0FF"   # ink, brand blue, page background
```

Logo assets (SVG + PNG, extracted from the site) are available on the Blocktank side at
`~/rgsplus/brand/`. Still worth asking RGS+ for: a mono / white-on-dark variant, the favicon
set, and whether the written form is "RGS+" or "RGSplus" — their site uses both.

---

## 13. Where the assistant should live

Not decided. Three candidates, not mutually exclusive:

1. **In-app at the existing "?"** — the strongest fix for the discovery problem, which is the
   biggest ticket class. Needs RGS+ frontend work; Brian called deeper integration
   *"doorontwikkeling naar de toekomst"*. **This is what `widget/` targets today.**
2. **`rgsplus.com/helpcentrum`** — the page already exists and currently just lists a phone
   number, `helpdesk@rgsplus.com`, office hours and a short FAQ. Changing their *website* is
   far cheaper than changing their *application*, and it is where a customer with a question
   already lands.
3. **Standalone** (e.g. `sam.rgsplus.nl`) — simplest to deploy, weakest on discovery: a
   customer who does not know the manual exists will not know the assistant exists either.

**A separate axis, and the more useful one: who sees it first.** Pointing it at **Brian and the
RGS+ team before any customer** has four advantages that are hard to get any other way:

- it has **no permission problem at all** — internal users see everything, so licence/role
  scoping can be deferred without blocking anything;
- **wrong answers hit a domain expert, not a customer**, which matters enormously at a volume
  where trust is the scarce resource;
- **every draft Brian edits before sending is a labelled example**, produced by the person who
  knows the right answer, at zero cost — the only evaluation signal this ticket volume can
  realistically generate;
- it requires **nothing from RGS+'s application team**, so it is not blocked on anyone.

---

## 14. Known gaps between this context and the repo as it stands

Not criticism of a scaffold — just the delta, so nothing is assumed to be handled.

| Gap | Detail |
| --- | --- |
| **No role / licence / tenant handling anywhere** | The bridge's `context` object carries `screen` and `version` — so version was anticipated — but no `role` and no `licence`. §6 is not implemented, and `evals/helpdesk-nl.txt` does not test it either (only `context.screen`, 3×). The hook exists: add the fields, have RGS+ populate them, add paired admin/user eval cases |
| **Trust boundary on `context`** | The bridge authenticates the *RGS+ application*, not the end user, so `context.role` is whatever RGS+'s backend asserts. Acceptable if calls go **backend → bridge**; not acceptable if the browser calls the bridge directly, which `CORS_ALLOW_ORIGINS` allows for. Insist on the backend path |
| **The xlsx endpoint is unbuilt** | Sketched in `notes/plan.md` at `9dfdcd5` (file since removed); §5 describes what it should do, and a verified validator already exists to port |
| **Default LLM config is US-routed** | §9a. Contradicts a written public commitment by the client |
| **No coverage measurement** | §10. `evals/` checks behaviour on 28 hand-written cases; it cannot tell you what fraction of the real ticket population Confluence can answer. That needs the back-catalogue |
| **Nobody owns `.jira-dryrun/`** | §11 |
| **Branding is placeholder** | §12 — real values available now |

---

*Maintained on the Blocktank side as `~/rgsplus/RGSPLUS-SAM-0{1..8}-*.md`, which carry the
longer-form reasoning, the full transcripts, and the design discussion behind the summaries
here.*
