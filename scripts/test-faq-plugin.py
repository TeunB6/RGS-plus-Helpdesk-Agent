#!/usr/bin/env python3
"""Self-check for the rgsplus-faq plugin: parsing, then search relevance.

    python3 scripts/test-faq-plugin.py            # against the committed snapshot
    python3 scripts/test-faq-plugin.py --live     # re-fetch rgsplus.com first

Runs offline against the snapshot by default, so it works in CI and on a
laptop with no network. Exit code is non-zero on any failure.

The negative cases are the point of this file. The FAQ is small and every
second entry contains the product name, so a naive scorer answers "hoe koppel
ik een grootboekrekening aan een RGS-code" with "Hoe veilig is RGS+?" -- a
confident citation of a completely unrelated answer, which is the worst thing
this bot can do. That is what the IDF weighting in _relevance() exists to
prevent, and these cases are what stop someone from tuning it back out.

Expected ids come from the committed snapshot. If RGS+ rewrites a FAQ entry
the ids stay stable (they are WordPress post ids), but if they delete one this
file needs updating -- scripts/fetch-faq.py will show you what moved.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "library" / "tools" / "support" / "rgsplus-faq" / "__init__.py"

# (query, expected entry id, or None when the FAQ must NOT claim to answer it)
CASES: list[tuple[str, str | None]] = [
    # Commercial and general -- the FAQ is the right source.
    ("Wat kost RGS+ per jaar?", "faq-890"),
    ("Wie is eigenaar van onze data?", "faq-888"),
    ("kosten extra gebruikers aanmaken", "faq-918"),
    ("Is er single sign on?", "faq-903"),
    ("hoe snel wordt er gereageerd op een melding", "faq-926"),
    ("kunnen we koppelen met AFAS", "faq-898"),
    ("eigen inspectielijst gebruiken", "faq-907"),
    ("data uitwisselen met woningcorporatie", "faq-942"),
    ("waar staat onze data opgeslagen", "faq-452"),
    # One genuine support answer that happens to live in the FAQ.
    ("zwart scherm blijft draaien inspectie app", "faq-956"),
    # Product, how-to, and out-of-scope -- these belong to Confluence, and the
    # FAQ must not produce a plausible-looking match for them.
    ("Hoe koppel ik een grootboekrekening aan een RGS-code?", None),
    ("Foutmelding 500 bij het exporteren van een factuur", None),
    ("Welk deel van de btw mogen wij terugvorderen?", None),
    ("Waarom kan mijn opdrachtgever niet inloggen op het portaal?", None),
    ("Hoe stel ik een DMJOP op voor een gemengd complex?", None),
]


class _Ctx:
    def __init__(self) -> None:
        self.tools: dict = {}

    def register_tool(self, name, toolset, schema, handler):
        self.tools[name] = handler


def load_plugin():
    spec = importlib.util.spec_from_file_location("rgsplus_faq", PLUGIN)
    if spec is None or spec.loader is None:
        sys.exit(f"cannot load {PLUGIN}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_parse(faq, payload: dict) -> list[str]:
    fails = []
    items = payload["items"]
    if len(items) < 20:
        fails.append(f"only {len(items)} entries parsed — expected ~36")
    for item in items:
        if not item["question"] or not item["answer"]:
            fails.append(f"{item['id']}: empty question or answer")
        if item["answer"].count("[") != item["answer"].count("]"):
            fails.append(f"{item['id']}: unbalanced markdown link brackets")
        if "<" in item["answer"] and ">" in item["answer"]:
            fails.append(f"{item['id']}: raw HTML leaked into the answer")
        if not item["url"].startswith("http"):
            fails.append(f"{item['id']}: bad url {item['url']!r}")
    if not any(len(i["categories"]) > 1 for i in items):
        fails.append("no cross-listed entries — category merging may be broken")
    declared = payload.get("jsonld_question_count")
    if declared and abs(declared - len(items)) > 3:
        fails.append(f"JSON-LD declares {declared} questions, parsed {len(items)}")
    return fails


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="fetch rgsplus.com instead of using the snapshot")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    faq = load_plugin()

    if args.live:
        payload, err = faq.fetch_live()
        if err:
            print(f"FAIL fetch: {err}", file=sys.stderr)
            return 1
        source = "live"
    else:
        payload = faq._read_json(faq._SNAPSHOT)
        if not payload:
            print(f"FAIL: no snapshot at {faq._SNAPSHOT} — run scripts/fetch-faq.py --write",
                  file=sys.stderr)
            return 1
        source = "snapshot"

    print(f"Source: {source} — {len(payload['items'])} entries\n")

    failures = check_parse(faq, payload)
    for f in failures:
        print(f"FAIL parse: {f}")
    if not failures:
        print("PASS parse: structure, links, categories and urls all clean\n")

    # Drive the real tool handler, snapshot-pinned so the test never depends
    # on the network or on cache state.
    import os
    os.environ["RGSPLUS_FAQ_OFFLINE"] = "true"
    faq._MEMO = None
    ctx = _Ctx()
    faq.register(ctx)
    search = ctx.tools["faq_search"]

    passed = 0
    for query, expected in CASES:
        result = json.loads(search({"query": query, "limit": 3}))
        results = result.get("results", [])
        top = results[0] if results else None

        if expected is None:
            good = not results or top["relevance"] < faq._WEAK_RELEVANCE
            got = "no match" if not results else \
                  f"weak {top['relevance']} — {top['question'][:45]}"
        else:
            good = any(r["id"] == expected for r in results[:2])
            got = f"{top['relevance']} — {top['question'][:45]}" if top else "no match"

        passed += good
        if not good or args.verbose:
            print(f"{'PASS' if good else 'FAIL'} | {query[:50]:50} -> {got}")
        if not good:
            failures.append(f"search: {query!r} -> {got}")

    print(f"\nsearch: {passed}/{len(CASES)} cases passed")
    if failures:
        print(f"\n{len(failures)} failure(s).", file=sys.stderr)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
