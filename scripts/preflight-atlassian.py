#!/usr/bin/env python3
"""Verify the day-of Atlassian values before anything is built.

    python3 scripts/preflight-atlassian.py             # reads ./.env, or the environment
    python3 scripts/preflight-atlassian.py --env-file /path/to/.env

Checks, in order, stopping at the first failure with an explanation of what to
fix:

  1. The values are present and shaped plausibly.
  2. The credentials authenticate (GET /rest/api/3/myself).
  3. Confluence is readable, and the configured spaces exist.
  4. The Jira project exists and is visible, and which issue types it has.

Then prints the .env block to paste. Stdlib only — no install step needed on
a customer's laptop.

Base URL resolution mirrors library/tools/support/atlassian/__init__.py
exactly: ATLASSIAN_CLOUD_ID wins if set (scoped tokens), otherwise
ATLASSIAN_SITE_URL (classic tokens). Getting these two out of sync between
the preflight and the plugin would make the preflight worthless, so change
them together.

Nothing here writes. Ticket creation in the running bot is a dry run — see
bundles/rgsplus.yaml — so there is no create-permission check and no test
ticket: the issue-type list below is informational, for when writes are
turned on later.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

JIRA_API = "/rest/api/3"
TIMEOUT = 30

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    ("\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 6
)


def ok(msg: str) -> None:
    print(f"{GREEN}  ✓{RESET} {msg}")


def fail(msg: str, *hints: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"{RED}  ✗ {msg}{RESET}")
    for hint in hints:
        print(f"    {DIM}→ {hint}{RESET}")
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"{YELLOW}  !{RESET} {msg}")


def load_env_file(path: Path) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE, # comments, optional quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def request(auth: str, base: str, path: str, query=None):
    """Return (status, parsed_body_or_text). GET only — this script never writes."""
    url = base + path
    if query:
        url += "?" + urllib.parse.urlencode(query)

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = response.read().decode("utf-8")
            return response.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"_raw": body[:500]}
    except (urllib.error.URLError, TimeoutError) as e:
        fail(
            f"Could not reach {base}: {e}",
            "Check ATLASSIAN_SITE_URL / ATLASSIAN_CLOUD_ID for typos.",
            "Check that this machine has outbound HTTPS access.",
        )


def atlassian_error(payload) -> str:
    if not isinstance(payload, dict):
        return str(payload)[:300]
    parts = list(payload.get("errorMessages") or [])
    parts += [f"{k}: {v}" for k, v in (payload.get("errors") or {}).items()]
    if payload.get("message"):
        parts.append(str(payload["message"]))
    return "; ".join(parts) or payload.get("_raw", "")[:300] or "no detail returned"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=".env", help="Defaults to ./.env")
    args = parser.parse_args()

    env = {**load_env_file(Path(args.env_file)), **os.environ}

    print(f"\n{BOLD}RGS+ Atlassian preflight{RESET}\n")

    # ── 1. Configuration ──
    print(f"{BOLD}1. Configuration{RESET}")
    email = (env.get("ATLASSIAN_EMAIL") or "").strip()
    token = (env.get("JIRA_API_KEY") or "").strip()
    cloud_id = (env.get("ATLASSIAN_CLOUD_ID") or "").strip()
    site = (env.get("ATLASSIAN_SITE_URL") or "").strip().rstrip("/")
    project = (env.get("JIRA_PROJECT_KEY") or "").strip()
    spaces = [s.strip() for s in (env.get("CONFLUENCE_SPACE_KEYS") or "").split(",") if s.strip()]

    missing = [n for n, v in (("ATLASSIAN_EMAIL", email), ("JIRA_API_KEY", token),
                              ("JIRA_PROJECT_KEY", project)) if not v]
    if missing:
        fail(
            f"not set: {', '.join(missing)}",
            f"Copy .env.example to {args.env_file} and fill these in.",
            "docs/DAY-OF-CHECKLIST.md explains where each one comes from.",
        )
    if not cloud_id and not site:
        fail(
            "neither ATLASSIAN_CLOUD_ID nor ATLASSIAN_SITE_URL is set",
            "Classic (unscoped) token → ATLASSIAN_SITE_URL=https://klant.atlassian.net",
            "Scoped token             → ATLASSIAN_CLOUD_ID=<uuid>",
        )

    if "@" not in email:
        fail(f"ATLASSIAN_EMAIL does not look like an address — got {email!r}")
    if not token.startswith(("ATATT", "ATCTT")):
        warn("JIRA_API_KEY starts with neither ATATT (classic) nor ATCTT (scoped). "
             "Check you pasted an API token and not a password.")
    if not project.isupper():
        warn(f"JIRA_PROJECT_KEY {project!r} is normally uppercase (e.g. HELP).")

    # Same precedence as the plugin: cloud id wins.
    if cloud_id:
        if site:
            warn("Both ATLASSIAN_CLOUD_ID and ATLASSIAN_SITE_URL are set. "
                 "The cloud id wins, here and in the plugin — the site URL is ignored.")
        jira_base = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        conf_base = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
        ok(f"site      cloud id {cloud_id}")
    else:
        if not site.startswith("https://"):
            fail(f"ATLASSIAN_SITE_URL must start with https:// — got {site!r}")
        if site.endswith("/jira") or site.endswith("/wiki") or "/browse/" in site:
            fail(f"ATLASSIAN_SITE_URL should be the site root, not a path — got {site!r}",
                 "Correct form: https://klant.atlassian.net")
        jira_base = site
        conf_base = f"{site}/wiki"
        ok(f"site      {site}")

    ok(f"account   {email}")
    ok(f"token     {token[:9]}… ({len(token)} chars)")
    ok(f"project   {project}")
    ok(f"spaces    {', '.join(spaces) if spaces else '(unscoped — searches everything readable)'}")

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    # ── 2. Authentication ──
    print(f"\n{BOLD}2. Authentication{RESET}")
    status, body = request(auth, jira_base, f"{JIRA_API}/myself")
    if status == 401:
        fail("Atlassian rejected the credentials (401)",
             "The token is wrong, revoked, expired, or belongs to a different account.",
             "Unscoped API tokens expired between 2026-03-14 and 2026-05-12. If this "
             "token predates that, issue a scoped one and set ATLASSIAN_CLOUD_ID.",
             "ATLASSIAN_EMAIL must be the account that owns the token.")
    if status == 403:
        fail("Atlassian refused the request (403)",
             "The account exists but is blocked from the REST API — often a site "
             "access or product-licence issue. Ask the customer's Atlassian admin.")
    if status != 200:
        fail(f"Unexpected status {status} from {JIRA_API}/myself: {atlassian_error(body)}")

    ok(f"authenticated as {body.get('displayName') or '(no display name)'} "
       f"<{body.get('emailAddress') or email}>")
    if body.get("accountType") != "atlassian":
        warn(f"Account type is {body.get('accountType')!r}, not 'atlassian'. "
             "A customer (portal) account cannot read a Confluence knowledge base.")

    # ── 3. Confluence: the knowledge base ──
    # This is the half that decides whether the bot can answer anything at all.
    # A Jira-only licence authenticates fine and then returns 403 here.
    print(f"\n{BOLD}3. Confluence knowledge base{RESET}")
    status, body = request(auth, conf_base, "/api/v2/spaces", query=[("limit", "100")])
    if status in (401, 403):
        fail(f"Confluence refused the request ({status})",
             "The account authenticates against Jira but cannot read Confluence — "
             "usually a missing Confluence product licence for this account.",
             "Without this the bot has no knowledge base and can only draft tickets.")
    if status == 404:
        fail("Confluence not found (404)",
             f"Tried {conf_base}/api/v2/spaces.",
             "Check ATLASSIAN_SITE_URL / ATLASSIAN_CLOUD_ID, and that the site has "
             "Confluence at all.")
    if status != 200:
        fail(f"Could not list Confluence spaces: {atlassian_error(body)}")

    visible = {s.get("key"): s.get("name") for s in (body.get("results") or [])}
    if not visible:
        fail("Confluence is reachable but this account can see no spaces",
             "Ask the admin to grant it read access to the knowledge-base space.")
    ok(f"{len(visible)} readable space(s): "
       + ", ".join(sorted(k for k in visible if k)[:15])
       + (" …" if len(visible) > 15 else ""))

    if spaces:
        unknown = [s for s in spaces if s not in visible]
        if unknown:
            fail(f"CONFLUENCE_SPACE_KEYS names space(s) this account cannot see: "
                 f"{', '.join(unknown)}",
                 "Searches scoped to them return nothing, and the bot escalates "
                 "every question as 'not documented'.",
                 "Use a key from the list above, or clear CONFLUENCE_SPACE_KEYS.")
        for key in spaces:
            ok(f"{key} — {visible[key]}")
    else:
        warn("CONFLUENCE_SPACE_KEYS is empty. Search covers every space above, "
             "including internal or archived ones. Set it once the knowledge-base "
             "space keys are known.")

    # ── 4. The Jira project ──
    print(f"\n{BOLD}4. Jira escalation project{RESET}")
    status, body = request(auth, jira_base, f"{JIRA_API}/project/{urllib.parse.quote(project)}")
    if status == 404:
        _, listing = request(auth, jira_base, f"{JIRA_API}/project/search",
                             query=[("maxResults", "50")])
        keys = [p.get("key") for p in (listing.get("values") or [])]
        fail(
            f"project {project!r} not found, or not visible to this account",
            "Projects this account can see: " + (", ".join(filter(None, keys)) or "none at all"),
            "Either the key is wrong, or the account needs Browse Projects on it.",
        )
    if status != 200:
        fail(f"Could not read project {project}: {atlassian_error(body)}")

    ok(f"{body.get('key')} — {body.get('name')} ({body.get('projectTypeKey')})")

    # Informational only: the bot's create path is a dry run, so it needs no
    # create permission today. Knowing the types now means the drafts name a
    # type that exists, and that turning writes on later is a config change
    # rather than a discovery exercise.
    status, meta = request(
        auth, jira_base,
        f"{JIRA_API}/issue/createmeta/{urllib.parse.quote(project)}/issuetypes",
    )
    if status == 200:
        names = [t.get("name") for t in (meta.get("issueTypes") or meta.get("values") or [])
                 if not t.get("subtask")]
        if names:
            ok(f"issue types: {', '.join(filter(None, names))}")
            print(f"    {DIM}The agent picks one of these per ticket via "
                  f"jira_get_create_meta.{RESET}")
        else:
            warn("No non-subtask issue types visible. Harmless while ticket creation "
                 "is a dry run; blocking once writes are enabled.")
    elif status == 403:
        warn("This account may browse the project but not create issues in it (403). "
             "Harmless while ticket creation is a dry run; ask for 'Create Issues' "
             "before enabling writes.")

    # ── Summary ──
    print(f"\n{GREEN}{BOLD}All checks passed.{RESET}\n")
    print(f"{DIM}.env block:{RESET}\n")
    print(f"ATLASSIAN_EMAIL={email}")
    print("JIRA_API_KEY=<the token you just verified>")
    if cloud_id:
        print(f"ATLASSIAN_CLOUD_ID={cloud_id}")
    else:
        print(f"ATLASSIAN_SITE_URL={site}")
    print(f"JIRA_PROJECT_KEY={project}")
    print(f"CONFLUENCE_SPACE_KEYS={','.join(spaces)}\n")
    print(f"{DIM}Next: mkdir -p .jira-dryrun && docker compose up -d --build{RESET}\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
