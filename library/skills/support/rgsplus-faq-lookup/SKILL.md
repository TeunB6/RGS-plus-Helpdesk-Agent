---
name: rgsplus-faq-lookup
description: Search the public RGS+ FAQ (rgsplus.com/faq) as a second knowledge source — which questions it owns, how it ranks against Confluence, and what may and may not be quoted from published marketing copy.
version: 1.0.0
author: UPPR
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Support, FAQ, Knowledge Base, RGS+]
---

# RGS+ FAQ lookup

A **second** source, alongside the Confluence knowledge base: the ~36
questions RGS+ publishes at <https://rgsplus.com/faq/>. Read
`confluence-knowledge-lookup` for the primary source; this skill is only
about what the FAQ adds and where it must not be used.

Both are still bound by the rule that governs everything:

> Answer from a source. Not from what you happen to know about the
> product, the industry, or software in general.

The FAQ widens what counts as a source. It does not weaken the rule.

## Tools

| Tool | Use |
| --- | --- |
| `faq_search` | Score the customer's question against every FAQ entry. Returns full answers and a citable link. |
| `faq_list` | The whole index of questions, grouped by category. Cheap. Use it when search comes back empty or weak. |

## Which source owns which question

The two sources barely overlap, and picking the wrong one wastes a turn.

| The question is about | Source |
| --- | --- |
| How to do something in the app, a screen, a field, a menu path | **Confluence** |
| An error, a bug, something not behaving as expected | **Confluence** |
| Configuration, imports/exports, RGS-codes, DMJOPs, scenarios | **Confluence** |
| What RGS+ costs, licence model, what's in a package | **FAQ** |
| Security, hosting, data ownership, GDPR-adjacent "where is our data" | **FAQ** |
| Which systems RGS+ integrates with, whether an API exists, SSO | **FAQ** |
| Implementation, onboarding, "how fast can we start", training | **FAQ** |
| Whether extra users cost money, roles and permissions in general | **FAQ** |
| Helpdesk availability and response times | **FAQ** |
| "Can RGS+ do X at all" — capability, not procedure | **FAQ** first, then Confluence for the how |

Rules of thumb when it isn't obvious:

- **"Can it?" is usually the FAQ. "How do I?" is usually Confluence.**
- A **prospect-shaped** question (pricing, security, integrations, what
  the product is for) is the FAQ. A **user-shaped** question (I clicked
  this and it broke) is Confluence.
- If genuinely unsure, search both. They are cheap and small.

## Procedure

1. **`faq_search`** with key nouns from the question — Dutch works best,
   the FAQ is written in Dutch. `kosten licentie per jaar`, not
   `ik zou graag willen weten wat het kost`.

   **One thing per search.** A customer asking *"wie is eigenaar van
   onze data, en waar staat die opgeslagen?"* is asking two questions
   that live in two different entries. Searched together, the combined
   wording scores *below* both — you get one weak hit, answer half the
   question, and escalate a half that was documented all along. Split
   it: `eigenaar data`, then `waar staat data opgeslagen`.
2. **Read the `relevance` score, but trust the questions more.** The
   score is 0.0–1.0 and normalised, so it means the same thing on every
   query. Below `0.55` the tool says so — at that point read the
   returned questions and decide yourself whether any is actually what
   was asked.
3. **Empty or weak? Call `faq_list`. Not optional.** The whole index is
   ~36 questions and costs almost nothing. A lexical search miss must
   never become a false "the FAQ doesn't cover this" — with a corpus
   this small you can simply read all of it and be certain.

   This is the single most likely way to get a FAQ question wrong: one
   weak hit comes back, it answers part of what was asked, and the rest
   gets escalated as undocumented when it was two entries away. If the
   tool's `note` says the matches are weak, read the index before you
   escalate anything.
4. **Still nothing?** It's a Confluence question, or a genuine gap.
   Continue with `confluence-knowledge-lookup`.

## When both sources answer

Rare, but it happens around users, roles and permissions.

- **Confluence wins on detail and on anything procedural.** It is
  maintained by the people who build the product; the FAQ is website
  copy that gets updated far less often.
- Use the FAQ for the *whether*, Confluence for the *how*: "Ja, je kunt
  zelf gebruikers aanmaken en dat kost niets [FAQ] — je doet dat via
  ... [Confluence page]."
- **If they contradict each other, say so.** Follow Confluence, tell the
  customer the public FAQ says something different, and draft a ticket
  flagging the discrepancy. Do not quietly pick one — a wrong public FAQ
  is worth someone knowing about.

## Citing it

The FAQ is public, so the customer can open the link and check you. Cite
the question title and its URL; the URL is a deep link that opens on the
right entry.

```
Gebruikers aanmaken kun je zelf doen als je administrator-rechten hebt,
en daar zijn geen extra kosten aan verbonden.

Bron: "Kan ik zelf gebruikers aanmaken en kost dat geld?" —
https://rgsplus.com/faq/#faq-918
```

Never present a FAQ answer as if it came from the knowledge base, and
never merge the two into one unattributed claim. If you used both, cite
both.

## Prices, timelines and other published numbers

This is the part that needs care, because the FAQ publishes numbers that
you are otherwise forbidden to state.

The distinction is **quoting** versus **committing**:

- ✅ **Quoting what RGS+ publishes**, with the link, is fine. The FAQ
  states a licence range of €1.400–€40.000 per year depending on
  organisation size. If someone asks what RGS+ costs, saying that *and
  linking it* is a better answer than refusing — it is public
  information they could read themselves.
- ❌ **A price for their situation is not yours to give.** "What would
  three extra users cost us?", "can we get a quote?", "is there a
  discount?" → out of scope, route to their contact person or sales.
  The published range does not become a quote because someone asked
  nicely.
- ❌ **Never interpolate.** Do not reason from the range to where a
  specific organisation would land. The FAQ gives endpoints, not a
  formula.
- ⚠️ **Response times are aspirations, not promises.** The FAQ says RGS+
  aims to respond within one working day. You may quote that as *what
  RGS+ publishes*. You may not promise it for the ticket you just
  drafted — that ticket has no key, no assignee and no SLA.

Same shape for everything else the FAQ states: helpdesk opening hours,
which integrations exist, how implementation runs. Quote it as published,
attribute it, and don't extend it.

Everything in `SOUL.md`'s out-of-scope list still holds. The FAQ lets you
*inform* about commercial topics; it does not put you in charge of them.
A question that needs a decision, a change or a commitment goes to a
human, even when the FAQ discusses the subject.

## Freshness

Every response carries a `freshness` block — `live`, `cache` or
`snapshot`, with an age.

The tool re-fetches rgsplus.com by itself and falls back to a cached or
committed copy when the site is unreachable, so this is not something you
manage. It matters in exactly one case: if `source` is `snapshot` or the
age is large **and** the customer is asking about a price, quote the
answer and add that they should confirm current pricing with their
contact person. For everything else, ignore it.

A `warning` field means the live page could not be reached. The content
is still valid — it is RGS+'s own published copy, just not re-checked
today. This is **not** the Confluence 401/403 case: it is not a broken
integration and it must not turn into an escalation ticket.
