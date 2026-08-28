---
name: confluence-knowledge-lookup
description: Search and read the Confluence knowledge base to answer customer questions, with source citation and honest "not covered" reporting.
version: 1.0.0
author: UPPR
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Support, Confluence, Knowledge Base, Research]
required_environment_variables:
  - name: ATLASSIAN_EMAIL
    prompt: "Atlassian account email"
    help: "The email address that owns the API token. Atlassian Cloud REST uses Basic auth (email:token), so a wrong email fails with 401 even with a valid token."
    required_for: "Confluence and Jira access"
  - name: JIRA_API_KEY
    prompt: "Atlassian API token"
    help: "Create at https://id.atlassian.com/manage/api-tokens. One token covers both Confluence and Jira."
    required_for: "Confluence and Jira access"
  - name: ATLASSIAN_SITE_URL
    prompt: "Atlassian site URL"
    help: "https://<site>.atlassian.net -- for a classic API token. If the token is scoped, set ATLASSIAN_CLOUD_ID instead."
    required_for: "Resolving the Confluence/Jira base URL"
---

# Confluence knowledge lookup

The knowledge base in Confluence is the **only** source you answer
customer questions from. This skill covers how to search it, how to read
what you find, and — just as important — how to recognise and report
that it does not have the answer.

## The rule that matters most

> You answer from what the knowledge base says. You do not answer from
> what you happen to know about the product, the industry, or software
> in general.

A plausible-sounding answer that is not in the knowledge base is worse
than no answer, because the customer cannot tell the difference and
nobody reviews it. If the knowledge base does not cover the question,
that is a finding, not a failure — hand it to the
`jira-ticket-create` skill.

## Tools

| Tool | Use |
| --- | --- |
| `confluence_search` | Full-text (CQL) search. Returns page ids + excerpts. |
| `confluence_get_page` | Full text of one page by id, plus a citable URL. |
| `confluence_list_spaces` | Discover space keys. Run once, not per question. |
| `atlassian_whoami` | Auth smoke test. Only when something returns 401/403. |

## Search procedure

### 1. Turn the question into search terms

Customers write sentences; CQL search wants key nouns. Strip filler.

| Customer asks | Search |
| --- | --- |
| "Hoe kan ik mijn wachtwoord opnieuw instellen in de app?" | `wachtwoord reset app` |
| "Why does the invoice export fail when I have orders in dollars?" | `invoice export currency` |
| "Is there a limit on how many users I can invite?" | `user limit invite` |

Two to four terms. If the knowledge base is Dutch and the question is
English (or vice versa), **search both languages** before concluding
nothing exists — this is the single most common cause of a false
"not covered".

### 2. Search, then widen once

- First search: the specific terms.
- Nothing useful? **One** broader search — drop the most specific term,
  or try a synonym / the other language.
- Still nothing? Stop. It's not there. Escalate.

Do not run six increasingly desperate searches. Two or three
well-chosen ones settle it, and looping wastes the customer's time.

### 3. Read the actual page

Search excerpts are fragments and routinely mislead. Before answering,
call `confluence_get_page` on the pages that look right. Answer from
the page text, not the excerpt.

If `truncated: true` came back, the page was long and you have the
first part only — say so if the answer might live further down.

### 4. Judge whether it actually answers the question

Be strict. A page that is *adjacent* to the question is not an answer.

- ✅ The page states the answer → answer, and cite it.
- ⚠️ The page covers the topic but not this case (e.g. it documents
  single-currency invoice export, customer asked about
  multi-currency) → say exactly that, then escalate. Partial answers
  are useful to the customer *and* to the engineer.
- ❌ Nothing relevant → escalate.

## Answering with a citation

Every claim that came from the knowledge base gets its page title and
URL. The customer can then verify you, and a colleague reviewing the
conversation can see where it came from.

```
Je kunt je wachtwoord resetten via Instellingen → Account → Wachtwoord.
De resetlink is 24 uur geldig.

Bron: "Wachtwoord opnieuw instellen" — https://<site>.atlassian.net/wiki/...
```

Two or three pages combined into one answer: cite all of them.

## Scoping the search

`CONFLUENCE_SPACE_KEYS` (comma-separated) restricts searches to the
knowledge-base spaces so internal or archived spaces don't pollute
results. When it's unset, `confluence_search` covers everything this
account can read — usable, but noisier. Run
`confluence_list_spaces` once at setup to find the right keys and ask
the operator to set the variable.

## When search fails for technical reasons

A 401/403/404 is **not** "the knowledge base has no answer" — it's a
broken connection, and it must not turn into an escalation ticket
saying the KB is missing a page.

1. Run `atlassian_whoami`.
2. If that also fails, tell the user the knowledge base is unreachable
   and report the error verbatim. Do not answer from your own
   knowledge as a fallback, and do not draft a ticket about the
   customer's question.

Common causes, in order of likelihood:

- `ATLASSIAN_EMAIL` isn't the account that owns the token (401).
- The API token expired. Unscoped Atlassian API tokens expired between
  2026-03-14 and 2026-05-12; a scoped replacement needs
  `ATLASSIAN_CLOUD_ID` set instead of `ATLASSIAN_SITE_URL` (401).
- The account can't see that space (403).
- Wrong site URL or cloud id (404).
