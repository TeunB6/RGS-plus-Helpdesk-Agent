#!/usr/bin/env python3
"""Snapshot the RGS+ Confluence manual into a skill the agent always has loaded.

    python3 scripts/fetch-manual.py             # show what changed, write nothing
    python3 scripts/fetch-manual.py --write     # update the snapshot
    python3 scripts/fetch-manual.py --stdout    # dump the markdown, write nothing

WHY THIS EXISTS — measured, not assumed
---------------------------------------
An eval run of evals/helpdesk-nl.txt on 2026-08-28 took **28.5 minutes for 33
questions**: mean 51.8s, median 51.8s, range 11.6-97.4s.

The instinct was that Confluence is slow. It is not. Measured against the live
site, a CQL search plus four page reads is **~1.0 second total**:

    confluence_search   313 ms
    confluence_get_page 174 / 182 / 178 / 168 ms

The time goes on the tool loop. Every tool call is a separate round trip to the
model, so `search -> think -> read -> think -> read -> think -> answer` is five
to seven sequential inferences. The eval data shows the shape plainly:

    te-vaag / sla-vraag / instructie-overschrijven      11-15s   (no lookup)
    import-formaat / alles-tegelijk / mjob-export       72-97s   (searched)

**~12 seconds is the floor** — one turn, reading the question and replying.
Everything above it is extra round trips, and Confluence is 1s of the ~52s
average.

So the fix is to delete the lookup, not to cache it. The whole HELP space is
**17 pages, ~48.000 characters, ~13.000 tokens** (measured 2026-08-28). That
fits in a prompt many times over, so the agent can simply *have* the manual
instead of fetching it. Expected effect: lookup questions collapse toward the
11-25s band the no-lookup questions already achieve.

Worth noting what else this fixes: several of the slowest answers cited nothing
at all (`voortgang-97-procent` 81s, `gebruiker-toevoegen-rechten` 80s). They
spent a minute searching and came back empty — maximum latency, zero value.
With the manual in context the agent knows immediately that something is not
documented.

⚠️ THE THRESHOLD. This works *because* the manual is tiny. If the HELP space
grows past roughly 150 pages / 100k tokens, preloading stops being sensible and
retrieval has to come back. The script warns when the snapshot crosses
WARN_TOKENS so that day is noticed rather than discovered.

The confluence_* tools stay registered. They are the escape hatch for a page
added since the last snapshot, and the honest answer to "is this current?" —
they are just no longer on the path of every single answer.

Same shape as fetch-faq.py: a committed snapshot, refreshed deliberately, whose
**git diff is the record of what RGS+ changed in their manual**. Stdlib only.

Env (same as the atlassian plugin, read from .env or the environment):
    ATLASSIAN_EMAIL, JIRA_API_KEY, ATLASSIAN_SITE_URL, CONFLUENCE_SPACE_KEYS
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "library" / "skills" / "support" / "rgsplus-handleiding" / "SKILL.md"
TIMEOUT = 60
WARN_TOKENS = 100_000          # past this, preloading is the wrong design
CHARS_PER_TOKEN = 3.6          # Dutch prose, rough


# --------------------------------------------------------------------------- env

def load_env(path: Path) -> dict:
    """Minimal .env reader: KEY=VALUE, # comments, optional quotes."""
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def api(env: dict):
    email = (env.get("ATLASSIAN_EMAIL") or "").strip()
    token = (env.get("JIRA_API_KEY") or "").strip()
    site = (env.get("ATLASSIAN_SITE_URL") or "").strip().rstrip("/")
    missing = [n for n, v in (("ATLASSIAN_EMAIL", email), ("JIRA_API_KEY", token),
                              ("ATLASSIAN_SITE_URL", site)) if not v]
    if missing:
        sys.exit(f"!! not set: {', '.join(missing)}. See docs/DAY-OF-CHECKLIST.md.")
    # Atlassian Cloud REST is HTTP Basic (email:token), not Bearer.
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    def get(path: str):
        req = urllib.request.Request(
            site + path,
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            hint = ""
            if e.code in (401, 403):
                hint = ("  Basic auth needs BOTH the token and the e-mail of the account "
                        "that owns it; a wrong e-mail is a 401 with a valid token.")
            sys.exit(f"!! HTTP {e.code} on {path}{hint}")
        except urllib.error.URLError as e:
            sys.exit(f"!! could not reach {site}: {e.reason}")

    return get


# ------------------------------------------------------------------ storage -> md

def to_markdown(storage: str) -> str:
    """Confluence storage format (XHTML) -> readable markdown.

    Deliberately lossy and simple. The agent needs the words, the headings and
    the links; it does not need layout macros, colours or panel chrome.
    """
    s = storage

    # Structural macros carry no content the agent needs, but their BODIES do.
    s = re.sub(r"<ac:structured-macro[^>]*ac:name=\"(info|note|warning|tip|panel)\"[^>]*>",
               "\n> ", s, flags=re.I)
    s = re.sub(r"</?ac:[^>]+>", "", s)
    s = re.sub(r"</?ri:[^>]+>", "", s)

    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", s)

    # links: keep the target, it is what gets cited to the customer
    s = re.sub(r'(?is)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", s)

    # Page titles are `##`, so page-internal headings start at `###`. Confluence
    # pages here lean on h5/h6, which would run off the end of markdown's six
    # levels — clamp rather than emit `########`, which renders as literal hashes.
    for lvl in range(1, 7):
        depth = min(lvl + 2, 6)
        s = re.sub(rf"(?is)<h{lvl}[^>]*>(.*?)</h{lvl}>", "\n" + "#" * depth + r" \1\n", s)

    s = re.sub(r"(?is)<li[^>]*>(.*?)</li>", r"- \1\n", s)
    s = re.sub(r"(?i)</?(ul|ol)[^>]*>", "\n", s)

    # tables -> pipes; several manual pages are field tables and the columns matter
    s = re.sub(r"(?is)<th[^>]*>(.*?)</th>", r"| \1 ", s)
    s = re.sub(r"(?is)<td[^>]*>(.*?)</td>", r"| \1 ", s)
    s = re.sub(r"(?i)</tr>", "|\n", s)
    s = re.sub(r"(?i)</?(table|tbody|thead|tr|colgroup|col)[^>]*>", "\n", s)

    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>", "\n\n", s)
    s = re.sub(r"(?is)<(strong|b)>(.*?)</\1>", r"**\2**", s)
    s = re.sub(r"(?is)<(em|i)>(.*?)</\1>", r"*\2*", s)
    s = re.sub(r"(?is)<code>(.*?)</code>", r"`\1`", s)

    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)

    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


FRONTMATTER = """---
name: rgsplus-handleiding
description: The complete RGS+ Confluence manual (space HELP), inlined. Consult THIS before any confluence_* tool — the answer is almost certainly already here, and reading it costs no round trip.
version: {version}
author: UPPR
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [Support, Knowledge Base, RGS+]
---

# RGS+ handleiding — volledige kennisbank

> **Generated by `scripts/fetch-manual.py` from Confluence space `{space}` on
> {stamp}. Do not edit by hand — rerun the script.**
>
> This is the entire knowledge base: {pages} pages, {chars:,} characters.
> It is here rather than behind a search tool because fetching it cost ~40
> seconds per answer in round trips while being worth ~1 second of network
> time. See the script's header for the measurements.

## How to use this

- **Answer from the text below.** It is the same content the "?" button in the
  RGS+ application shows, and the same pages `confluence_search` would return.
- **Cite the page you used**, by its heading and URL, exactly as you would a
  search result. The customer learning where the manual lives is the point.
- **If it is not below, it is not in the manual.** Say so and escalate. Do not
  fall back on general knowledge about property-maintenance software.
- **Only reach for `confluence_search`** if you have positive reason to think a
  page was added or changed after the generation date above — not as a matter
  of routine. It is the escape hatch, not the path.

---

"""


def build(get, space_key: str) -> tuple[str, int, int]:
    spaces = get("/wiki/api/v2/spaces?limit=250").get("results", [])
    space = next((s for s in spaces if s.get("key") == space_key), None)
    if not space:
        sys.exit(f"!! space {space_key!r} not readable. Visible: "
                 f"{', '.join(s['key'] for s in spaces) or 'none'}")

    pages = get(f"/wiki/api/v2/spaces/{space['id']}/pages?limit=250").get("results", [])
    base = f"{(get('/wiki/rest/api/space/' + space_key) or {}).get('_links', {}).get('base', '')}"

    parts, chars = [], 0
    for p in sorted(pages, key=lambda x: x.get("title", "")):
        body = get(f"/wiki/api/v2/pages/{p['id']}?body-format=storage")
        raw = ((body.get("body") or {}).get("storage") or {}).get("value") or ""
        text = to_markdown(raw)
        if not text:
            continue  # empty pages (F.A.Q., Bedrijfsdata, Changelog-Mobile) add nothing
        url = f"{base}/spaces/{space_key}/pages/{p['id']}" if base else ""
        head = f"## {p['title']}"
        if url:
            head += f"\n\n*Bron: {url}*"
        parts.append(f"{head}\n\n{text}\n")
        chars += len(text)
    return "\n---\n\n".join(parts), len(parts), chars


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="update the snapshot on disk")
    ap.add_argument("--stdout", action="store_true", help="print the markdown, write nothing")
    ap.add_argument("--env-file", default=str(ROOT / ".env"))
    ap.add_argument("--space", default=None, help="override CONFLUENCE_SPACE_KEYS")
    args = ap.parse_args()

    env = {**load_env(Path(args.env_file)), **os.environ}
    space = (args.space or (env.get("CONFLUENCE_SPACE_KEYS") or "").split(",")[0]).strip()
    if not space:
        sys.exit("!! no space key. Set CONFLUENCE_SPACE_KEYS or pass --space.")

    get = api(env)
    body, n_pages, chars = build(get, space)
    if not n_pages:
        sys.exit(f"!! space {space} returned no pages with content — refusing to write an "
                 f"empty manual over a good one.")

    tokens = int(chars / CHARS_PER_TOKEN)
    stamp = (get("/rest/api/3/serverInfo") or {}).get("serverTime", "")[:10] or "unknown date"

    doc = FRONTMATTER.format(version="1.0.0", space=space, stamp=stamp,
                             pages=n_pages, chars=chars) + body + "\n"

    print(f"space   : {space}")
    print(f"pages   : {n_pages} with content")
    print(f"size    : {chars:,} chars  (~{tokens:,} tokens)")

    if tokens > WARN_TOKENS:
        print(f"\n!! {tokens:,} tokens is past the {WARN_TOKENS:,} threshold this design "
              f"assumes.\n   Preloading the whole manual is no longer the right call — "
              f"bring retrieval back.")

    if args.stdout:
        print("\n" + "-" * 60 + "\n")
        sys.stdout.write(doc)
        return 0

    old = SKILL.read_text(encoding="utf-8") if SKILL.is_file() else ""
    if old:
        strip = lambda t: re.sub(r"^> \*\*Generated by.*?---\n\n", "", t, flags=re.S)
        if strip(old) == strip(doc):
            print("\nunchanged — RGS+ have not edited the manual since the last snapshot.")
            return 0
        print(f"\nCHANGED: {len(old):,} -> {len(doc):,} chars. "
              f"`git diff` after --write shows exactly what RGS+ altered.")
    else:
        print("\nno snapshot yet.")

    if not args.write:
        print("(dry run — pass --write to update)")
        return 0

    SKILL.parent.mkdir(parents=True, exist_ok=True)
    SKILL.write_text(doc, encoding="utf-8")
    print(f"wrote {SKILL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
