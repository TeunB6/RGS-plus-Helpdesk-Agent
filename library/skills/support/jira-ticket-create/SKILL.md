---
name: jira-ticket-create
description: Escalate an unanswerable customer question into a Jira ticket draft — what a good ticket contains, duplicate checking, and the dry-run contract (no issue is actually created).
version: 1.0.0
author: UPPR
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Support, Jira, Escalation, Approval]
required_environment_variables:
  - name: ATLASSIAN_EMAIL
    prompt: "Atlassian account email"
    help: "The email address that owns the API token (Basic auth username)."
    required_for: "Jira access"
  - name: JIRA_API_KEY
    prompt: "Atlassian API token"
    help: "Create at https://id.atlassian.com/manage/api-tokens."
    required_for: "Jira access"
  - name: JIRA_PROJECT_KEY
    prompt: "Jira project key for customer-service tickets"
    help: "e.g. SUP. Run jira_list_projects to see the available keys."
    required_for: "Drafting tickets without passing a project key every time"
---

# Jira ticket creation (dry run)

When the Confluence knowledge base cannot answer a customer's question,
the question becomes a Jira ticket. This skill covers when to escalate,
how to write a ticket an engineer can act on, and what "dry run"
means for what you tell the customer.

## ⚠️ Dry run: no ticket is actually created

`jira_create_ticket` **does not write to Jira.** It validates the
ticket, renders the exact payload Jira would receive, saves it for a
human to review and submit, and returns it to you. There is no POST in
the code path.

This changes what you may say to the customer:

- ✅ "I've escalated this to our team — someone will get back to you."
- ✅ "This isn't covered in our documentation, so I've passed it on to a
  colleague."
- ❌ "I've created ticket SUP-142." — **there is no SUP-142.** No key
  exists, and inventing one means the customer chases a ticket nobody
  can find.
- ❌ "Your ticket is now in the queue and will be picked up in 24 hours."
  — you don't know that; a human hasn't looked at it yet.

The tool's response has `created: false` and `issue_key: null`. Believe
it. If you ever find yourself about to quote a ticket key, stop — you
are about to make one up.

## Before you escalate: two checks

### 1. Did you actually search?

Escalation is the step *after* the knowledge base came up empty, not a
shortcut around it. Follow `confluence-knowledge-lookup` first —
including the widen-once search and, where relevant, the other-language
search. An escalation for a question the KB answers on page one wastes
an engineer's time and makes the agent look useless.

### 2. Is it already an open ticket?

Always run `jira_search_issues` before drafting:

```
project = SUP AND status != Done AND text ~ "invoice export currency"
```

If a matching open issue exists, **don't draft a duplicate.** Read it
with `jira_get_issue` and tell the customer it's already being tracked
— that's a better answer than a new ticket, and you can often share the
current status.

## Before drafting: check the project accepts your issue type

`jira_get_create_meta` lists the issue types a project actually has and
which fields each requires. Projects differ — one has `Support
Request`, the next only has `Task` and `Bug`. Run it once per project
and reuse the answer; don't guess `issue_type` and don't assume `Bug`
exists.

Pick by what the question *is*:

| The question is | Issue type |
| --- | --- |
| Something is broken / errors / wrong output | `Bug` (if the project has it) |
| A how-do-I the docs don't cover | `Task` |
| A request for something that doesn't exist yet | `Story` / `Task` |

When unsure, `Task`. Getting the type slightly wrong is recoverable;
a vague description is not.

## What makes a ticket actionable

Four fields are required, and the tool rejects the draft without them.
This is deliberate — a ticket missing them gets bounced back to
support, and the customer waits twice as long.

### `summary`
One line, under ~120 characters, written **for an engineer** — not a
copy of the customer's sentence.

- ❌ "Klant vraagt waarom het niet werkt"
- ❌ "Question about invoices"
- ✅ "Invoice PDF export returns 500 for multi-currency orders"

State the observable problem. If you know the component and the
symptom, both belong in the summary.

### `customer_question`
The customer's words, **verbatim**. Don't clean it up, translate it, or
summarise it. The engineer may spot something in the original phrasing
that you filtered out.

### `context`
The field that decides whether the ticket is actionable. Everything you
established while triaging:

- what the customer was trying to do,
- what they expected vs. what happened,
- **exact error messages** if any (verbatim, not paraphrased),
- product area, version, environment, browser/app if relevant,
- what they already tried,
- how many users/how often, if it came up.

If you didn't establish these, **ask the customer before escalating**.
One round of questions beats a ticket that an engineer has to reopen
just to ask them. Only skip the questions if the customer has
disengaged or is clearly frustrated — then say plainly in `context`
what you don't know.

Write what you know and mark what you don't:

```
Customer on v4.2 (web, Chrome). Creating an invoice for an order with
both EUR and USD line items; clicking "Export PDF" returns
"500 Internal Server Error" (verbatim). Single-currency orders export
fine — customer confirmed. Started ~2 weeks ago per customer.
Unknown: whether it affects all multi-currency combinations or only
EUR+USD; customer had not tried other pairs.
```

### `searched`
What you searched and what came back, so a human doesn't repeat your
work — and so a genuine documentation gap becomes visible:

```
Confluence KB, space SUP: searched "invoice export currency",
"factuur export valuta", "multi-currency". 3 pages on invoice export,
all single-currency only. No page covers multi-currency export.
```

This also flags when the fix is a *docs* fix rather than a code fix.

## Optional fields

- `priority` — set it only when the customer is genuinely blocked with
  no workaround. Everything is not `High`; inflating priority makes the
  field meaningless.
- `labels` — for routing (`billing`, `mobile`, `onboarding`).
  `customer-service` and `ai-drafted` are added automatically, so the
  team can always see which tickets an agent drafted.
- `reporter_email` — the customer's email, so a human can follow up
  directly. Include it whenever you have it.

## After drafting

1. The tool returns the payload and a `saved_to` path. **Show the
   customer a short summary** of what you escalated — the summary line
   and the gist — so they can correct you if you misunderstood. This is
   often where a misdiagnosis gets caught.
2. Tell them a human will follow up. No ticket key, no SLA promise.
3. If `save_error` is set, the draft was returned but **not persisted**
   — say so explicitly to whoever is watching, because the escalation
   would otherwise be silently lost.

## Enabling real writes later

Deliberately out of scope for this build: the API token has read/write
access, so a bug or a prompt injection inside a customer question could
create real issues in a live project. Reads are safe; writes wait for a
human.

To turn writes on, someone implements the `POST /rest/api/3/issue` call
in `library/tools/support/atlassian/__init__.py` behind an explicit
`ATLASSIAN_ALLOW_WRITES=true` env gate, and the "no ticket key" rules
above get revisited. Until then the dry-run contract holds, and you
should not tell users otherwise.
