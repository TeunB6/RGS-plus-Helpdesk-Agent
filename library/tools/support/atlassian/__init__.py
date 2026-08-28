"""atlassian -- Confluence knowledge lookup + Jira for the customer-service bundle.

READ tools hit the live Atlassian Cloud REST API. The ticket-creation tool is
DRY-RUN ONLY: it validates and renders the exact payload it would POST, writes
it to a dry-run log, and returns it -- it never mutates Jira. See the
"Write path" section below.

  atlassian_whoami           GET  /rest/api/3/myself
  confluence_list_spaces     GET  /wiki/api/v2/spaces
  confluence_search          GET  /wiki/rest/api/search             (CQL)
  confluence_get_page        GET  /wiki/api/v2/pages/{id}
  jira_list_projects         GET  /rest/api/3/project/search
  jira_get_create_meta       GET  /rest/api/3/issue/createmeta
  jira_search_issues         POST /rest/api/3/search/jql
  jira_get_issue             GET  /rest/api/3/issue/{key}
  jira_create_ticket         (DRY RUN -- no HTTP call)

Auth -- Atlassian Cloud REST uses HTTP Basic auth, NOT Bearer. The username is
the Atlassian account email and the password is the API token:
    Authorization: Basic base64("<ATLASSIAN_EMAIL>:<JIRA_API_KEY>")
Docs: developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/

Base URL -- two modes, because Atlassian is migrating from unscoped to scoped
API tokens (unscoped tokens expire between 2026-03-14 and 2026-05-12):
  * classic/unscoped token -> ATLASSIAN_SITE_URL (https://<site>.atlassian.net)
  * scoped token           -> ATLASSIAN_CLOUD_ID (https://api.atlassian.com/ex/...)
ATLASSIAN_CLOUD_ID wins when both are set.

Confluence search uses the v1 `/wiki/rest/api/search` endpoint on purpose: the
v2 API has no CQL full-text search, so v1 remains the only way to query the
knowledge base by text. Page bodies are read via v2.

Write path -- deliberately NOT implemented. The operator's API token carries
read/write access, so a bug or a prompt injection in a customer question could
create real tickets in a live project. jira_create_ticket therefore has no HTTP
code path at all (_WRITES_IMPLEMENTED = False); it produces a reviewed draft
that a human submits. To enable real writes later, implement the POST behind
that constant and require ATLASSIAN_ALLOW_WRITES=true.

Required env: ATLASSIAN_EMAIL, JIRA_API_KEY,
              and one of ATLASSIAN_SITE_URL / ATLASSIAN_CLOUD_ID.
Optional env: JIRA_PROJECT_KEY (default project for drafts),
              CONFLUENCE_SPACE_KEYS (comma-separated search scope),
              JIRA_DRYRUN_DIR (default ~/.hermes/jira-dryrun).
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 2
_MAX_SLEEP = 10.0

_MAX_BODY_CHARS = 20000
_MAX_EXCERPT_CHARS = 500


# ---------------------------------------------------------------------------
# Auth + transport
# ---------------------------------------------------------------------------

def _err(message: str) -> str:
    return json.dumps({"success": False, "error": message})


def _auth_header() -> tuple[str | None, str | None]:
    email = (os.environ.get("ATLASSIAN_EMAIL") or "").strip()
    token = (os.environ.get("JIRA_API_KEY") or "").strip()
    if not email:
        return None, (
            "ATLASSIAN_EMAIL is not set. Atlassian Cloud REST uses Basic auth "
            "with the account email as the username -- set it to the email "
            "address that owns the API token."
        )
    if not token:
        return None, (
            "JIRA_API_KEY is not set. Create an API token at "
            "https://id.atlassian.com/manage/api-tokens and add it to the "
            "client's .env."
        )
    raw = f"{email}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii"), None


def _bases() -> tuple[str | None, str | None, str | None]:
    """Return (jira_base, confluence_base, error).

    Scoped API tokens address a site by cloud id; classic tokens address it by
    site URL. Prefer the cloud id when present.
    """
    cloud_id = (os.environ.get("ATLASSIAN_CLOUD_ID") or "").strip()
    if cloud_id:
        return (
            f"https://api.atlassian.com/ex/jira/{cloud_id}",
            f"https://api.atlassian.com/ex/confluence/{cloud_id}",
            None,
        )
    site = (os.environ.get("ATLASSIAN_SITE_URL") or "").strip().rstrip("/")
    if not site:
        return None, None, (
            "Neither ATLASSIAN_CLOUD_ID nor ATLASSIAN_SITE_URL is set. Set "
            "ATLASSIAN_SITE_URL=https://<site>.atlassian.net for a classic API "
            "token, or ATLASSIAN_CLOUD_ID=<uuid> for a scoped token."
        )
    if not site.startswith("http"):
        site = "https://" + site
    return site, f"{site}/wiki", None


def _http_err(e: urllib.error.HTTPError) -> str:
    body = e.read().decode("utf-8", errors="replace") if e.fp else ""
    detail = body[:500]
    try:
        parsed = json.loads(body)
        messages = parsed.get("errorMessages") or []
        if messages:
            detail = "; ".join(str(m) for m in messages)
        elif parsed.get("message"):
            detail = parsed["message"]
        elif parsed.get("errors"):
            detail = json.dumps(parsed["errors"])
    except (json.JSONDecodeError, AttributeError):
        pass
    message = f"Atlassian HTTP {e.code}: {detail}"
    if e.code == 401:
        message += (
            " -- Basic auth rejected. Check that ATLASSIAN_EMAIL is the exact "
            "account that owns the token, and that the token has not expired "
            "(unscoped API tokens expired between 2026-03-14 and 2026-05-12; "
            "a scoped replacement needs ATLASSIAN_CLOUD_ID instead of "
            "ATLASSIAN_SITE_URL)."
        )
    elif e.code == 403:
        message += (
            " -- authenticated but not permitted. The token's account (or its "
            "scopes) lacks access to this project/space."
        )
    elif e.code == 404:
        message += (
            " -- not found. Verify the site URL/cloud id, and that the "
            "space/project/page key exists and is visible to this account."
        )
    return _err(message)


def _request(method: str, url: str, auth: str, payload: dict | None = None,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _safe_call(method: str, url: str, auth: str, payload: dict | None = None,
               _attempt: int = 0) -> tuple[dict | None, str | None]:
    """Call Atlassian, retrying briefly on 429. Returns (data, error_json)."""
    try:
        return _request(method, url, auth, payload), None
    except urllib.error.HTTPError as e:
        if e.code == 429 and _attempt < _MAX_RETRIES:
            try:
                wait = float(e.headers.get("Retry-After", "1"))
            except (TypeError, ValueError):
                wait = 1.0
            time.sleep(min(max(wait, 0.0), _MAX_SLEEP))
            return _safe_call(method, url, auth, payload, _attempt + 1)
        return None, _http_err(e)
    except (urllib.error.URLError, TimeoutError) as e:
        return None, _err(f"Atlassian network error: {e}")
    except json.JSONDecodeError as e:
        return None, _err(f"Atlassian returned non-JSON: {e}")


def _ready(product: str) -> tuple[tuple[str, str] | None, str | None]:
    """Resolve (base_url, auth_header) for 'jira' or 'confluence'."""
    auth, err = _auth_header()
    if err:
        return None, _err(err)
    jira_base, conf_base, err = _bases()
    if err:
        return None, _err(err)
    return ((jira_base if product == "jira" else conf_base), auth), None


def _qs(params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    return urllib.parse.urlencode(clean, doseq=True)


# ---------------------------------------------------------------------------
# Confluence body handling
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def _storage_to_text(markup: str) -> str:
    """Flatten Confluence storage-format XHTML into readable plain text.

    Not a full parser -- it drops macro internals and keeps the prose, which
    is what the agent needs to answer a question and quote a source.
    """
    if not markup:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|table)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _WS_RE.sub("\n\n", text).strip()


def _page_url(conf_base: str, page: dict) -> str:
    links = page.get("_links") or {}
    webui = links.get("webui") or ""
    if webui:
        # v2 returns a site-relative path; classic mode already includes /wiki.
        if conf_base.endswith("/wiki"):
            return conf_base[: -len("/wiki")] + "/wiki" + webui
        return conf_base + webui
    page_id = page.get("id")
    return f"{conf_base}/pages/{page_id}" if page_id else ""


# ---------------------------------------------------------------------------
# Tool 1: whoami (auth smoke test)
# ---------------------------------------------------------------------------

_WHOAMI_SCHEMA = {
    "name": "atlassian_whoami",
    "description": (
        "Verify Atlassian credentials and report which account the API token "
        "belongs to. Call this first when any other Atlassian tool returns a "
        "401/403, or once at setup to confirm the connection works."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}


def _handle_whoami(params, **kwargs):
    ready, err = _ready("jira")
    if err:
        return err
    base, auth = ready
    data, err = _safe_call("GET", f"{base}/rest/api/3/myself", auth)
    if err:
        return err
    return json.dumps({
        "success": True,
        "account_id": data.get("accountId"),
        "email": data.get("emailAddress"),
        "display_name": data.get("displayName"),
        "mode": "cloud_id" if os.environ.get("ATLASSIAN_CLOUD_ID") else "site_url",
        "writes_enabled": False,
    })


# ---------------------------------------------------------------------------
# Tool 2: list Confluence spaces
# ---------------------------------------------------------------------------

_LIST_SPACES_SCHEMA = {
    "name": "confluence_list_spaces",
    "description": (
        "List the Confluence spaces this account can read, with their keys. "
        "Call this once to discover which space holds the knowledge base, then "
        "pass that key as confluence_search's space_keys argument."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max spaces to return (1-250, default 50).",
                "default": 50,
            },
        },
        "required": [],
    },
}


def _handle_list_spaces(params, **kwargs):
    ready, err = _ready("confluence")
    if err:
        return err
    base, auth = ready
    limit = max(1, min(int(params.get("limit") or 50), 250))
    data, err = _safe_call("GET", f"{base}/api/v2/spaces?{_qs({'limit': limit})}", auth)
    if err:
        return err
    spaces = [
        {"key": s.get("key"), "name": s.get("name"), "id": s.get("id"), "type": s.get("type")}
        for s in (data.get("results") or [])
    ]
    return json.dumps({"success": True, "count": len(spaces), "spaces": spaces})


# ---------------------------------------------------------------------------
# Tool 3: search Confluence (the knowledge lookup)
# ---------------------------------------------------------------------------

_SEARCH_SCHEMA = {
    "name": "confluence_search",
    "description": (
        "Full-text search the Confluence knowledge base and return matching "
        "pages with a short excerpt each. This is the FIRST tool to use for any "
        "customer question -- always search before answering. Returns page ids; "
        "pass promising ones to confluence_get_page to read the full text. "
        "Searches with 2-4 word key terms work better than whole sentences."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search terms taken from the customer's question, e.g. "
                    "'password reset mobile app'. Keep it to key nouns; drop "
                    "filler words."
                ),
            },
            "space_keys": {
                "type": "string",
                "description": (
                    "Optional comma-separated space keys to restrict the search, "
                    "e.g. 'KB,SUPPORT'. Defaults to CONFLUENCE_SPACE_KEYS from "
                    "the environment, or all readable spaces."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (1-50, default 10).",
                "default": 10,
            },
        },
        "required": ["query"],
    },
}


def _cql_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _handle_search(params, **kwargs):
    ready, err = _ready("confluence")
    if err:
        return err
    base, auth = ready
    query = (params.get("query") or "").strip()
    if not query:
        return _err("query is required")
    limit = max(1, min(int(params.get("limit") or 10), 50))

    spaces_raw = (params.get("space_keys")
                  or os.environ.get("CONFLUENCE_SPACE_KEYS")
                  or "").strip()
    cql = f'type=page AND text ~ "{_cql_escape(query)}"'
    keys = [k.strip() for k in spaces_raw.split(",") if k.strip()]
    if keys:
        joined = ",".join(f'"{_cql_escape(k)}"' for k in keys)
        cql += f" AND space.key IN ({joined})"

    # v1 search: the v2 API has no CQL full-text endpoint.
    url = f"{base}/rest/api/search?{_qs({'cql': cql, 'limit': limit})}"
    data, err = _safe_call("GET", url, auth)
    if err:
        return err

    results = []
    for item in data.get("results") or []:
        content = item.get("content") or {}
        excerpt = _storage_to_text(item.get("excerpt") or "")[:_MAX_EXCERPT_CHARS]
        results.append({
            "page_id": content.get("id"),
            "title": content.get("title") or item.get("title"),
            "space": ((item.get("resultGlobalContainer") or {}).get("title")),
            "excerpt": excerpt,
            "last_modified": item.get("lastModified"),
            "url": _page_url(base, {"_links": item.get("_links") or {},
                                    "id": content.get("id")}),
        })
    return json.dumps({
        "success": True,
        "query": query,
        "cql": cql,
        "count": len(results),
        "results": results,
        "note": (
            "No results is a real answer: it means the knowledge base does not "
            "cover this. Try one broader search, then escalate via "
            "jira_create_ticket." if not results else None
        ),
    })


# ---------------------------------------------------------------------------
# Tool 4: read a Confluence page
# ---------------------------------------------------------------------------

_GET_PAGE_SCHEMA = {
    "name": "confluence_get_page",
    "description": (
        "Read the full text of one Confluence page by id (from "
        "confluence_search). Use this before answering so the answer is based "
        "on the actual page content, not the search excerpt. Returns the page "
        "title, body text, and a URL to cite to the customer."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "page_id": {
                "type": "string",
                "description": "The Confluence page id, as returned by confluence_search.",
            },
        },
        "required": ["page_id"],
    },
}


def _handle_get_page(params, **kwargs):
    ready, err = _ready("confluence")
    if err:
        return err
    base, auth = ready
    page_id = str(params.get("page_id") or "").strip()
    if not page_id:
        return _err("page_id is required")
    url = f"{base}/api/v2/pages/{urllib.parse.quote(page_id)}?body-format=storage"
    data, err = _safe_call("GET", url, auth)
    if err:
        return err
    storage = ((data.get("body") or {}).get("storage") or {}).get("value") or ""
    text = _storage_to_text(storage)
    truncated = len(text) > _MAX_BODY_CHARS
    return json.dumps({
        "success": True,
        "page_id": data.get("id"),
        "title": data.get("title"),
        "space_id": data.get("spaceId"),
        "version": (data.get("version") or {}).get("number"),
        "url": _page_url(base, data),
        "text": text[:_MAX_BODY_CHARS],
        "truncated": truncated,
    })


# ---------------------------------------------------------------------------
# Tool 5: list Jira projects
# ---------------------------------------------------------------------------

_LIST_PROJECTS_SCHEMA = {
    "name": "jira_list_projects",
    "description": (
        "List the Jira projects this account can see, with their keys. Call "
        "this once to discover the project key that customer-service tickets "
        "belong in, then reuse it -- don't guess a key."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Max projects to return (1-50, default 50).",
                "default": 50,
            },
        },
        "required": [],
    },
}


def _handle_list_projects(params, **kwargs):
    ready, err = _ready("jira")
    if err:
        return err
    base, auth = ready
    limit = max(1, min(int(params.get("limit") or 50), 50))
    url = f"{base}/rest/api/3/project/search?{_qs({'maxResults': limit})}"
    data, err = _safe_call("GET", url, auth)
    if err:
        return err
    projects = [
        {"key": p.get("key"), "name": p.get("name"), "id": p.get("id"),
         "type": p.get("projectTypeKey")}
        for p in (data.get("values") or [])
    ]
    return json.dumps({
        "success": True,
        "count": len(projects),
        "projects": projects,
        "default_project_key": os.environ.get("JIRA_PROJECT_KEY") or None,
    })


# ---------------------------------------------------------------------------
# Tool 6: create-meta (valid issue types + required fields)
# ---------------------------------------------------------------------------

_CREATE_META_SCHEMA = {
    "name": "jira_get_create_meta",
    "description": (
        "List the issue types a Jira project accepts and which fields are "
        "required for each. Call this before drafting a ticket so the draft "
        "uses an issue type that actually exists in the project (e.g. 'Bug' vs "
        "'Support Request') and fills every required field."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "project_key": {
                "type": "string",
                "description": (
                    "The project key, e.g. 'SUP'. Defaults to JIRA_PROJECT_KEY "
                    "from the environment."
                ),
            },
        },
        "required": [],
    },
}


def _handle_create_meta(params, **kwargs):
    ready, err = _ready("jira")
    if err:
        return err
    base, auth = ready
    project_key = (params.get("project_key")
                   or os.environ.get("JIRA_PROJECT_KEY") or "").strip()
    if not project_key:
        return _err(
            "project_key is required (or set JIRA_PROJECT_KEY). Use "
            "jira_list_projects to discover the available keys."
        )
    url = (f"{base}/rest/api/3/issue/createmeta?"
           f"{_qs({'projectKeys': project_key, 'expand': 'projects.issuetypes.fields'})}")
    data, err = _safe_call("GET", url, auth)
    if err:
        return err

    projects = data.get("projects") or []
    if not projects:
        return _err(
            f"Jira returned no create metadata for project '{project_key}' -- "
            "the key may be wrong or this account cannot create issues there."
        )
    issue_types = []
    for it in projects[0].get("issuetypes") or []:
        fields = it.get("fields") or {}
        issue_types.append({
            "id": it.get("id"),
            "name": it.get("name"),
            "subtask": it.get("subtask"),
            "required_fields": sorted(
                key for key, spec in fields.items() if spec.get("required")
            ),
        })
    return json.dumps({
        "success": True,
        "project_key": projects[0].get("key"),
        "project_name": projects[0].get("name"),
        "issue_types": issue_types,
    })


# ---------------------------------------------------------------------------
# Tool 7: search Jira issues (dedup before escalating)
# ---------------------------------------------------------------------------

_SEARCH_ISSUES_SCHEMA = {
    "name": "jira_search_issues",
    "description": (
        "Search existing Jira issues with JQL. Call this BEFORE drafting a new "
        "ticket to check whether the same question is already open -- if it is, "
        "tell the customer it's being tracked and reference the key instead of "
        "drafting a duplicate. Example JQL: "
        "project = SUP AND status != Done AND text ~ \"password reset\"."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "jql": {
                "type": "string",
                "description": (
                    "A JQL query. Quote free-text terms, e.g. "
                    "'project = SUP AND text ~ \"invoice export\"'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max issues to return (1-50, default 10).",
                "default": 10,
            },
        },
        "required": ["jql"],
    },
}

_ISSUE_FIELDS = ["summary", "status", "issuetype", "priority", "created", "updated", "labels"]


def _handle_search_issues(params, **kwargs):
    ready, err = _ready("jira")
    if err:
        return err
    base, auth = ready
    jql = (params.get("jql") or "").strip()
    if not jql:
        return _err("jql is required")
    limit = max(1, min(int(params.get("limit") or 10), 50))
    # /rest/api/3/search was removed; /search/jql is the current endpoint.
    payload = {"jql": jql, "maxResults": limit, "fields": _ISSUE_FIELDS}
    data, err = _safe_call("POST", f"{base}/rest/api/3/search/jql", auth, payload)
    if err:
        return err
    issues = []
    for issue in data.get("issues") or []:
        f = issue.get("fields") or {}
        issues.append({
            "key": issue.get("key"),
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "issue_type": (f.get("issuetype") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "updated": f.get("updated"),
            "labels": f.get("labels"),
        })
    return json.dumps({
        "success": True, "jql": jql, "count": len(issues), "issues": issues,
    })


# ---------------------------------------------------------------------------
# Tool 8: read one Jira issue
# ---------------------------------------------------------------------------

_GET_ISSUE_SCHEMA = {
    "name": "jira_get_issue",
    "description": (
        "Read one Jira issue by key (e.g. 'SUP-142'), including its "
        "description and comments. Use it to tell a customer the current state "
        "of a ticket they're asking about."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "issue_key": {
                "type": "string",
                "description": "The issue key, e.g. 'SUP-142'.",
            },
        },
        "required": ["issue_key"],
    },
}


def _adf_to_text(node) -> str:
    """Flatten Atlassian Document Format into plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return node.get("text") or ""
    if node_type == "hardBreak":
        return "\n"
    inner = _adf_to_text(node.get("content"))
    if node_type in ("paragraph", "heading", "listItem", "blockquote", "codeBlock"):
        return inner + "\n"
    return inner


def _handle_get_issue(params, **kwargs):
    ready, err = _ready("jira")
    if err:
        return err
    base, auth = ready
    key = (params.get("issue_key") or "").strip()
    if not key:
        return _err("issue_key is required")
    url = (f"{base}/rest/api/3/issue/{urllib.parse.quote(key)}?"
           f"{_qs({'fields': 'summary,status,issuetype,priority,description,comment,created,updated,labels'})}")
    data, err = _safe_call("GET", url, auth)
    if err:
        return err
    f = data.get("fields") or {}
    comments = [
        {
            "author": (c.get("author") or {}).get("displayName"),
            "created": c.get("created"),
            "body": _adf_to_text(c.get("body")).strip()[:2000],
        }
        for c in ((f.get("comment") or {}).get("comments") or [])
    ]
    return json.dumps({
        "success": True,
        "key": data.get("key"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "issue_type": (f.get("issuetype") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "labels": f.get("labels"),
        "created": f.get("created"),
        "updated": f.get("updated"),
        "description": _adf_to_text(f.get("description")).strip()[:_MAX_BODY_CHARS],
        "comments": comments,
    })


# ---------------------------------------------------------------------------
# Tool 9: draft a Jira ticket -- DRY RUN ONLY
# ---------------------------------------------------------------------------

_CREATE_TICKET_SCHEMA = {
    "name": "jira_create_ticket",
    "description": (
        "Draft the Jira ticket for a customer question the knowledge base could "
        "not answer. THIS IS A DRY RUN: it validates the ticket, renders the "
        "exact payload Jira would receive, saves it for a human to submit, and "
        "returns it -- it does NOT create the issue. Tell the customer their "
        "question has been escalated and is awaiting a human; never claim a "
        "ticket key was assigned, because none is. Only call this after "
        "confluence_search found no answer AND jira_search_issues found no "
        "existing ticket."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "One-line ticket title, under ~120 chars, written for a "
                    "support engineer -- not a copy of the customer's sentence. "
                    "E.g. 'Invoice PDF export fails for multi-currency orders'."
                ),
            },
            "customer_question": {
                "type": "string",
                "description": "The customer's question, verbatim, for the record.",
            },
            "context": {
                "type": "string",
                "description": (
                    "What you established while triaging: what the customer is "
                    "trying to do, what they already tried, product/version/"
                    "environment, error messages, and anything that narrows it "
                    "down. This is the field that decides whether the ticket is "
                    "actionable -- be specific."
                ),
            },
            "searched": {
                "type": "string",
                "description": (
                    "What you searched in Confluence and what came back, so a "
                    "human doesn't repeat the work. E.g. 'searched \"invoice "
                    "export currency\" in KB -- 3 pages on invoicing, none "
                    "cover multi-currency'."
                ),
            },
            "project_key": {
                "type": "string",
                "description": "Jira project key. Defaults to JIRA_PROJECT_KEY.",
            },
            "issue_type": {
                "type": "string",
                "description": (
                    "Issue type name, validated against the project via "
                    "jira_get_create_meta. Default 'Task'."
                ),
                "default": "Task",
            },
            "priority": {
                "type": "string",
                "description": (
                    "Priority name, e.g. 'Highest', 'High', 'Medium', 'Low'. "
                    "Omit unless the customer is blocked."
                ),
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Labels for routing/reporting. 'customer-service' and "
                    "'ai-drafted' are added automatically."
                ),
            },
            "reporter_email": {
                "type": "string",
                "description": "The customer's email, if known, for follow-up.",
            },
        },
        "required": ["summary", "customer_question", "context", "searched"],
    },
}

_AUTO_LABELS = ["customer-service", "ai-drafted"]


def _adf_doc(sections: list[tuple[str, str]]) -> dict:
    """Build an ADF document from (heading, body) pairs. Jira v3 requires ADF
    for the description field -- plain strings are rejected."""
    content: list[dict] = []
    for heading, body in sections:
        if not (body or "").strip():
            continue
        content.append({
            "type": "heading",
            "attrs": {"level": 3},
            "content": [{"type": "text", "text": heading}],
        })
        for para in re.split(r"\n\s*\n", body.strip()):
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": para.strip()}],
            })
    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": "(no detail)"}]}]
    return {"type": "doc", "version": 1, "content": content}


def _dryrun_dir() -> Path:
    configured = (os.environ.get("JIRA_DRYRUN_DIR") or "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes") / "jira-dryrun"


def _slug(text: str, limit: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (cleaned[:limit] or "ticket").strip("-")


def _handle_create_ticket(params, **kwargs):
    # There is deliberately no POST in this function -- see "Write path" in the
    # module docstring. It cannot create an issue even if misconfigured.
    summary = (params.get("summary") or "").strip()
    question = (params.get("customer_question") or "").strip()
    context = (params.get("context") or "").strip()
    searched = (params.get("searched") or "").strip()

    missing = [
        name for name, value in (
            ("summary", summary), ("customer_question", question),
            ("context", context), ("searched", searched),
        ) if not value
    ]
    if missing:
        return _err(
            f"missing required field(s): {', '.join(missing)}. A ticket without "
            "these is not actionable for the engineer who picks it up."
        )
    if len(summary) > 255:
        return _err("summary must be 255 characters or fewer (Jira's limit)")

    project_key = (params.get("project_key")
                   or os.environ.get("JIRA_PROJECT_KEY") or "").strip()
    if not project_key:
        return _err(
            "project_key is required (or set JIRA_PROJECT_KEY). Use "
            "jira_list_projects to find the customer-service project."
        )

    labels = list(params.get("labels") or [])
    for auto in _AUTO_LABELS:
        if auto not in labels:
            labels.append(auto)
    # Jira rejects labels containing whitespace.
    labels = [re.sub(r"\s+", "-", str(l).strip()) for l in labels if str(l).strip()]

    reporter_email = (params.get("reporter_email") or "").strip()
    sections = [
        ("Customer question", question),
        ("Triage context", context),
        ("Knowledge base searched", searched),
    ]
    if reporter_email:
        sections.append(("Customer contact", reporter_email))
    sections.append((
        "Provenance",
        "Drafted by the AI customer-service agent because the Confluence "
        "knowledge base did not cover this question. Not yet reviewed by a human.",
    ))

    fields: dict = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": (params.get("issue_type") or "Task").strip() or "Task"},
        "description": _adf_doc(sections),
        "labels": labels,
    }
    priority = (params.get("priority") or "").strip()
    if priority:
        fields["priority"] = {"name": priority}

    payload = {"fields": fields}

    # Persist the draft so a human can review and submit it, and so there's an
    # audit trail of what the agent would have created.
    saved_to = None
    save_error = None
    try:
        target_dir = _dryrun_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = target_dir / f"{stamp}-{project_key}-{_slug(summary)}.json"
        record = {
            "created_at": stamp,
            "dry_run": True,
            "submitted": False,
            "would_post_to": "/rest/api/3/issue",
            "payload": payload,
        }
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
        saved_to = str(path)
    except OSError as e:
        save_error = f"could not write the dry-run file: {e}"

    return json.dumps({
        "success": True,
        "dry_run": True,
        "created": False,
        "issue_key": None,
        "project_key": project_key,
        "summary": summary,
        "labels": labels,
        "would_post_to": "POST /rest/api/3/issue",
        "payload": payload,
        "saved_to": saved_to,
        "save_error": save_error,
        "next_step": (
            "No Jira issue exists yet. Tell the customer their question has been "
            "escalated to a human and that they will hear back -- do NOT invent "
            "or promise a ticket key. A human reviews the saved draft and submits it."
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx):
    for name, schema, handler in (
        ("atlassian_whoami", _WHOAMI_SCHEMA, _handle_whoami),
        ("confluence_list_spaces", _LIST_SPACES_SCHEMA, _handle_list_spaces),
        ("confluence_search", _SEARCH_SCHEMA, _handle_search),
        ("confluence_get_page", _GET_PAGE_SCHEMA, _handle_get_page),
        ("jira_list_projects", _LIST_PROJECTS_SCHEMA, _handle_list_projects),
        ("jira_get_create_meta", _CREATE_META_SCHEMA, _handle_create_meta),
        ("jira_search_issues", _SEARCH_ISSUES_SCHEMA, _handle_search_issues),
        ("jira_get_issue", _GET_ISSUE_SCHEMA, _handle_get_issue),
        ("jira_create_ticket", _CREATE_TICKET_SCHEMA, _handle_create_ticket),
    ):
        ctx.register_tool(name=name, toolset="atlassian", schema=schema, handler=handler)
