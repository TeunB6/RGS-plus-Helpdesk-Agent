"""rgsplus-faq -- the public RGS+ FAQ (https://rgsplus.com/faq/) as a second source.

A companion to the `atlassian` plugin, not a replacement. Confluence holds the
product knowledge base (how-to, errors, configuration); this holds the ~36
public Q&As RGS+ publishes on its website, which skew commercial and
general: pricing, licensing, security, data ownership, implementation.

  faq_search   score the customer's question against every FAQ entry
  faq_list     the full index of questions (cheap), optionally with answers

WHY A LOCAL COPY, when ARCHITECTURE.md rejects one for Confluence
----------------------------------------------------------------
Confluence has a search API, so the bot queries it live and never needs a
copy. The public FAQ has none: the FAQ post type is not exposed over
/wp-json (404), so the only way to read it is to fetch the page and parse it.
There is no "query it live" alternative -- you fetch the whole thing or you
have nothing.

So this is a cache, not a fork. At runtime the plugin re-fetches the live page
whenever its cache is older than RGSPLUS_FAQ_TTL (default 24h) and falls back,
in order, to the on-disk cache and then the snapshot committed next to this
file. Every response reports which of the three it used and how old it is.
The committed snapshot exists so the bot works on first boot and when
rgsplus.com is unreachable; refresh it with `scripts/fetch-faq.py`, whose diff
doubles as a changelog of what RGS+ changed on their public FAQ.

PARSING
-------
The page is server-rendered WordPress. Content lives in
`article.faq[id=faq-NNNN]` with `h2.faq__question` and `div.faq__answer`,
grouped by `h2.faq-block__title` category headings. The `id` is stable and
gives every answer a citable deep link (https://rgsplus.com/faq/#faq-923).

Six entries are cross-listed under two categories, so 42 article elements
collapse to 36 items with a `categories` list. Dedup is by id.

The page also carries a Yoast JSON-LD FAQPage block. It is NOT the source --
it omits categories and disagrees with the rendered page on which entries
exist -- but its question count is a useful canary that the markup changed
under us. scripts/fetch-faq.py checks it; see _jsonld_question_count.

Env (all optional):
  RGSPLUS_FAQ_URL        page to fetch      (default https://rgsplus.com/faq/)
  RGSPLUS_FAQ_TTL        cache seconds      (default 86400)
  RGSPLUS_FAQ_OFFLINE    "true" -> never fetch, use the committed snapshot
  RGSPLUS_FAQ_CACHE_DIR  cache location     (default ~/.hermes/faq-cache)
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_URL = "https://rgsplus.com/faq/"
DEFAULT_TTL = 86400.0
FETCH_TIMEOUT = 20.0
USER_AGENT = "RGSPlusHelpdeskBot/1.0 (+https://rgsplus.com/faq/)"

_MAX_ANSWER_CHARS = 4000
_MAX_ITEMS = 500
_SNAPSHOT = Path(__file__).with_name("faq-snapshot.json")


def _err(message: str) -> str:
    return json.dumps({"success": False, "error": message}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# HTML -> structured Q&A
# ---------------------------------------------------------------------------

class _FaqParser(HTMLParser):
    """Collect (category, id, question, answer-markdown) from the FAQ page.

    Answers are captured as a small event stream rather than raw text so that
    links survive as markdown -- an answer that says "mail info@rgsplus.com"
    is useless to a customer if the mailto is dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict] = []
        self._category = ""
        self._mode: str | None = None      # 'cat' | 'q' | 'a'
        self._buf: list = []
        self._depth = 0
        self._cur: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()

        if self._mode == "a":
            # Track nesting so the answer ends on its own closing tag.
            if tag not in _VOID_TAGS:
                self._depth += 1
            self._buf.append(("start", tag, a))
            return

        if "faq-block__title" in cls:
            self._mode, self._buf = "cat", []
        elif tag == "article" and "faq" in cls:
            if len(self.items) < _MAX_ITEMS:
                self._cur = {"id": (a.get("id") or "").strip(),
                             "category": self._category}
        elif "faq__question" in cls:
            self._mode, self._buf = "q", []
        elif "faq__answer" in cls:
            self._mode, self._buf, self._depth = "a", [], 1

    def handle_endtag(self, tag):
        if self._mode == "a":
            if tag in _VOID_TAGS:
                return
            self._depth -= 1
            if self._depth <= 0:
                if self._cur is not None:
                    self._cur["answer"] = _events_to_markdown(self._buf)
                    self.items.append(self._cur)
                    self._cur = None
                self._mode, self._buf = None, []
            else:
                self._buf.append(("end", tag, None))
            return

        if self._mode == "cat":
            self._category = _collapse("".join(self._buf))
            self._mode, self._buf = None, []
        elif self._mode == "q":
            if self._cur is not None:
                self._cur["question"] = _collapse("".join(self._buf))
            self._mode, self._buf = None, []

    def handle_data(self, data):
        if self._mode == "a":
            self._buf.append(("text", data, None))
        elif self._mode:
            self._buf.append(data)


_VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}
_HEADING_RE = re.compile(r"h[1-6]\Z")


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _events_to_markdown(events: list) -> str:
    out: list[str] = []
    href_stack: list[str] = []
    for kind, name, attrs in events:
        if kind == "text":
            out.append(name.replace("\xa0", " "))
        elif kind == "start":
            if name == "br":
                out.append("\n")
            elif name in ("p", "div"):
                out.append("\n\n")
            elif name in ("ul", "ol"):
                out.append("\n")
            elif name == "li":
                out.append("\n- ")
            elif name in ("strong", "b"):
                out.append("**")
            elif name in ("em", "i"):
                out.append("*")
            elif name == "a":
                href_stack.append(((attrs or {}).get("href") or "").strip())
                out.append("[")
            elif _HEADING_RE.match(name):
                out.append("\n\n**")
        elif kind == "end":
            if name == "a":
                href = href_stack.pop() if href_stack else ""
                # A bare anchor or empty href adds nothing -- unwrap it.
                if href and not href.startswith("#"):
                    out.append(f"]({href})")
                else:
                    for i in range(len(out) - 1, -1, -1):
                        if out[i] == "[":
                            out.pop(i)
                            break
            elif name in ("strong", "b"):
                out.append("**")
            elif name in ("em", "i"):
                out.append("*")
            elif _HEADING_RE.match(name):
                out.append("**\n")
            elif name in ("p", "div", "li", "ul", "ol"):
                out.append("\n")

    text = "".join(out).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:_MAX_ANSWER_CHARS]


def _jsonld_question_count(markup: str) -> int | None:
    """Questions declared in the page's Yoast JSON-LD, or None if absent.

    Only a canary: it disagrees with the rendered page (it has carried a
    question the page does not render) and has no categories, so it is never
    used as content. A large gap means the markup changed and the parser is
    silently dropping entries.
    """
    for block in re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', markup, re.S
    ):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        graph = data.get("@graph") if isinstance(data, dict) else None
        if not isinstance(graph, list):
            continue
        n = sum(1 for node in graph
                if isinstance(node, dict) and node.get("@type") == "Question")
        if n:
            return n
    return None


def parse_faq(markup: str, source_url: str = DEFAULT_URL) -> list[dict]:
    """Parse the FAQ page into deduplicated items with merged categories."""
    parser = _FaqParser()
    parser.feed(markup)

    merged: dict[str, dict] = {}
    for raw in parser.items:
        question = (raw.get("question") or "").strip()
        answer = (raw.get("answer") or "").strip()
        if not question or not answer:
            continue
        key = raw.get("id") or "q-" + _slug(question)
        if key in merged:
            cat = raw.get("category")
            if cat and cat not in merged[key]["categories"]:
                merged[key]["categories"].append(cat)
            continue
        anchor = key if key.startswith("faq-") else ""
        merged[key] = {
            "id": key,
            "question": question,
            "answer": answer,
            "categories": [raw["category"]] if raw.get("category") else [],
            "url": f"{source_url}#{anchor}" if anchor else source_url,
        }
    return list(merged.values())


def _slug(text: str, limit: int = 40) -> str:
    s = _strip_accents(text.lower())
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")[:limit]


# ---------------------------------------------------------------------------
# Fetch / cache / snapshot
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    raw = (os.environ.get("RGSPLUS_FAQ_CACHE_DIR") or "").strip()
    base = Path(raw).expanduser() if raw else Path.home() / ".hermes" / "faq-cache"
    return base / "faq.json"


def _source_url() -> str:
    return (os.environ.get("RGSPLUS_FAQ_URL") or "").strip() or DEFAULT_URL


def _ttl() -> float:
    try:
        return max(0.0, float(os.environ.get("RGSPLUS_FAQ_TTL") or DEFAULT_TTL))
    except ValueError:
        return DEFAULT_TTL


def fetch_live(url: str | None = None) -> tuple[dict | None, str | None]:
    """Fetch and parse the live FAQ page. Returns (payload, error)."""
    url = url or _source_url()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT,
                 "Accept": "text/html,application/xhtml+xml"},
    )
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            markup = resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"{url} returned HTTP {e.code} {e.reason}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, f"could not reach {url}: {e}"
    except (UnicodeDecodeError, ValueError) as e:
        return None, f"could not decode {url}: {e}"

    items = parse_faq(markup, url)
    if not items:
        return None, (
            f"fetched {url} but parsed 0 FAQ entries -- the page markup has "
            f"probably changed. Check library/tools/support/rgsplus-faq/."
        )
    return {
        "source_url": url,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "fetched_epoch": time.time(),
        "item_count": len(items),
        "jsonld_question_count": _jsonld_question_count(markup),
        "items": items,
    }, None


def _read_json(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return data if data.get("items") else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _write_cache(payload: dict) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        tmp.replace(path)
    except OSError:
        pass  # A read-only volume degrades to re-fetching; it is not an error.


_MEMO: dict | None = None


def load_faq(force_refresh: bool = False) -> tuple[dict | None, str, str | None]:
    """Return (payload, source, warning) where source is live|cache|snapshot.

    Order of preference: fresh cache, live fetch, stale cache, snapshot. The
    bot must never be left with nothing to answer from just because
    rgsplus.com is down.
    """
    global _MEMO
    offline = (os.environ.get("RGSPLUS_FAQ_OFFLINE") or "").strip().lower() in (
        "1", "true", "yes")

    if _MEMO is not None and not force_refresh:
        payload, source = _MEMO["payload"], _MEMO["source"]
        if source == "live" and time.time() - _MEMO["at"] < _ttl():
            return payload, source, None

    if offline:
        snap = _read_json(_SNAPSHOT)
        if snap:
            return snap, "snapshot", "RGSPLUS_FAQ_OFFLINE is set; using the committed snapshot."
        return None, "none", "RGSPLUS_FAQ_OFFLINE is set but the snapshot is missing or unreadable."

    cache = _read_json(_cache_path())
    if cache and not force_refresh:
        age = time.time() - float(cache.get("fetched_epoch") or 0)
        if 0 <= age < _ttl():
            _MEMO = {"payload": cache, "source": "cache", "at": time.time()}
            return cache, "cache", None

    live, err = fetch_live()
    if live:
        _write_cache(live)
        _MEMO = {"payload": live, "source": "live", "at": time.time()}
        return live, "live", None

    if cache:
        _MEMO = {"payload": cache, "source": "cache", "at": time.time()}
        return cache, "cache", f"Serving a stale cached copy: {err}"

    snap = _read_json(_SNAPSHOT)
    if snap:
        return snap, "snapshot", f"Serving the committed snapshot: {err}"
    return None, "none", f"The RGS+ FAQ is unavailable: {err}"


def _freshness(payload: dict, source: str) -> dict:
    info = {"source": source, "fetched_at": payload.get("fetched_at")}
    epoch = payload.get("fetched_epoch")
    if isinstance(epoch, (int, float)) and epoch > 0:
        info["age_hours"] = round((time.time() - epoch) / 3600.0, 1)
    return info


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

# Dutch + English filler. Removing these stops "kan ik" and "hoe" from
# matching every entry on the page.
_STOPWORDS = {
    "de", "het", "een", "en", "of", "maar", "want", "dus", "als", "dan", "die",
    "dat", "deze", "dit", "er", "ik", "je", "jij", "u", "we", "wij", "ze",
    "zij", "hij", "het", "mijn", "jouw", "uw", "ons", "onze", "hun", "is",
    "zijn", "was", "waren", "ben", "bent", "wordt", "worden", "werd", "heb",
    "heeft", "hebben", "had", "hadden", "kan", "kun", "kunt", "kunnen", "kon",
    "zal", "zou", "moet", "moeten", "mag", "magen", "wil", "willen", "doe",
    "doen", "gaat", "gaan", "in", "op", "aan", "van", "voor", "met", "bij",
    "naar", "uit", "over", "om", "te", "ook", "niet", "geen", "wel", "nog",
    "al", "hoe", "wat", "waar", "wanneer", "waarom", "wie", "welke", "welk",
    "the", "a", "an", "of", "to", "in", "is", "it", "for", "on", "with",
    "how", "what", "can", "i", "do", "does", "my", "and", "or",
}


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))


def _tokens(text: str) -> set[str]:
    norm = _strip_accents((text or "").lower()).replace("’", "'")
    words = re.findall(r"[a-z0-9]+", norm)
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _stem(word: str) -> str:
    """Crude Dutch suffix trim, enough to tie 'gebruikers' to 'gebruiker'."""
    for suffix in ("ingen", "eren", "en", "es", "s", "e"):
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _index(payload: dict) -> tuple[list[dict], dict[str, float]]:
    """Tokenise every entry and weight terms by inverse document frequency.

    IDF is not a refinement here, it is the thing that makes the search safe.
    Every second entry contains "RGS+", so without it a product question like
    "hoe koppel ik een grootboekrekening aan een RGS-code" scores a confident
    match against "Hoe veilig is RGS+?" on the product name alone -- and the
    bot cites a irrelevant answer instead of searching Confluence. Weighting a
    term by how rare it is drives ubiquitous words to roughly zero without
    anyone maintaining a per-corpus stopword list.
    """
    items = payload["items"]
    idf = payload.get("_idf")
    if idf is not None:
        return items, idf

    doc_freq: dict[str, int] = {}
    for item in items:
        qt = _tokens(item["question"])
        at = _tokens(item["answer"])
        item["_qt"] = qt | {_stem(t) for t in qt}
        item["_at"] = at | {_stem(t) for t in at}
        item["_qn"] = _strip_accents(item["question"].lower())
        for term in item["_qt"] | item["_at"]:
            doc_freq[term] = doc_freq.get(term, 0) + 1

    total = max(1, len(items))
    idf = {t: math.log((total + 1) / (d + 0.5)) for t, d in doc_freq.items()}
    payload["_idf"] = idf
    return items, idf


# A term the corpus has never seen still counts against the query: it is the
# strongest possible evidence that the FAQ does not cover what was asked.
_UNSEEN_IDF = math.log(41.0)


def _relevance(item: dict, terms: set[str], phrase: str,
               idf: dict[str, float]) -> float:
    """Fraction of the query's weight this entry accounts for, 0.0-1.0.

    Normalising by the query's own total weight makes the number comparable
    across questions, so one threshold works for every query instead of a
    raw score that only means something relative to its own result set.
    """
    earned = 0.0
    possible = 0.0
    for term in terms:
        stem = _stem(term)
        weight = idf.get(term) or idf.get(stem) or _UNSEEN_IDF
        possible += weight
        if term in item["_qt"] or stem in item["_qt"]:
            earned += weight
        elif any(t.startswith(stem) for t in item["_qt"] if len(stem) > 3):
            earned += 0.5 * weight
        elif term in item["_at"] or stem in item["_at"]:
            earned += 0.6 * weight
    if possible <= 0:
        return 0.0
    score = earned / possible
    if phrase and len(phrase) > 8 and phrase in item["_qn"]:
        score += 0.25
    return min(score, 1.0)


# Below this, an entry is noise -- report it as no match rather than let the
# agent cite something that merely shares a common word.
_MIN_RELEVANCE = 0.30
_WEAK_RELEVANCE = 0.55


# ---------------------------------------------------------------------------
# Tool 1: search the FAQ
# ---------------------------------------------------------------------------

_SEARCH_SCHEMA = {
    "name": "faq_search",
    "description": (
        "Search the public RGS+ FAQ (rgsplus.com/faq) and return matching "
        "questions with their full published answers and a citable link. "
        "This is a SECOND source alongside confluence_search, and it is the "
        "better one for commercial and general questions: pricing and "
        "licensing, security, data ownership, who owns the data, integrations, "
        "implementation and onboarding, user accounts and permissions, helpdesk "
        "response times. Confluence remains the source for how-to steps, error "
        "messages and configuration. The FAQ is small (about 36 entries), so if "
        "this returns nothing useful, call faq_list and read the index yourself "
        "before concluding the FAQ does not cover it. "
        "SEARCH ONE THING AT A TIME: a customer asking two things ('who owns "
        "our data, and where is it stored?') needs two searches, because the "
        "combined wording matches neither entry well and you will answer half "
        "the question and wrongly escalate the other half."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Key terms from the customer's question, e.g. 'kosten "
                    "licentie per jaar' or 'data eigenaar'. Dutch works best -- "
                    "the FAQ is written in Dutch."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max entries to return (1-20, default 5).",
                "default": 5,
            },
        },
        "required": ["query"],
    },
}


def _handle_search(params, **kwargs):
    query = (params.get("query") or "").strip()
    if not query:
        return _err("query is required")
    try:
        limit = max(1, min(int(params.get("limit") or 5), 20))
    except (TypeError, ValueError):
        limit = 5

    payload, source, warning = load_faq()
    if not payload:
        return _err(warning or "The RGS+ FAQ is unavailable.")

    items, idf = _index(payload)
    terms = _tokens(query)
    if not terms:
        return _err(
            "The query reduced to nothing but filler words. Use key nouns, "
            "e.g. 'kosten licentie' rather than 'kan ik weten hoe het zit'."
        )
    phrase = _strip_accents(query.lower())

    scored = sorted(
        ((_relevance(i, terms, phrase, idf), i) for i in items),
        key=lambda pair: pair[0],
        reverse=True,
    )
    hits = [(s, i) for s, i in scored if s >= _MIN_RELEVANCE][:limit]
    top = hits[0][0] if hits else 0.0

    results = [{
        "id": item["id"],
        "question": item["question"],
        "answer": item["answer"],
        "categories": item["categories"],
        "url": item["url"],
        "relevance": round(score, 2),
    } for score, item in hits]

    note = None
    if not hits:
        note = (
            "No FAQ entry matched, which usually means this is a product "
            "question rather than a general one -- search Confluence. The FAQ "
            "is only about 36 mostly-commercial entries; call faq_list to read "
            "the whole index if you want to be certain before escalating."
        )
    elif top < _WEAK_RELEVANCE:
        note = (
            "Weak matches only — do NOT conclude from this alone that the FAQ "
            "lacks an answer. Call faq_list (the whole index is ~36 questions "
            "and costs almost nothing) and read it yourself before escalating. "
            "If the customer asked two things, search each separately: a "
            "combined query routinely scores below both entries it should have "
            "found. Whatever you do, don't stretch one of these results to fit."
        )

    return json.dumps({
        "success": True,
        "query": query,
        "count": len(results),
        "results": results,
        "freshness": _freshness(payload, source),
        "warning": warning,
        "note": note,
        "citation_rule": (
            "This is RGS+'s own public FAQ, so quoting it to a customer is "
            "fine -- cite the question title and its url. It is published "
            "marketing copy, not the product knowledge base: it does not "
            "commit RGS+ to anything for this specific customer."
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool 2: list the FAQ index
# ---------------------------------------------------------------------------

_LIST_SCHEMA = {
    "name": "faq_list",
    "description": (
        "List every question in the public RGS+ FAQ, grouped by category. "
        "Cheap -- the whole index is about 36 questions. Use it when "
        "faq_search returns nothing or only weak matches, so that a lexical "
        "search miss never becomes a false 'the FAQ does not cover this'. "
        "Set include_answers to read the full text of one category."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "Optional category filter, matched case-insensitively, "
                    "e.g. 'Helpdesk', 'Pakketten', 'Inspectie', 'Algemeen', "
                    "'Planvorming'. Omit for the whole index."
                ),
            },
            "include_answers": {
                "type": "boolean",
                "description": (
                    "Include the full answer text. Combine with a category to "
                    "keep the response small; the entire FAQ with answers is "
                    "roughly 9 KB."
                ),
                "default": False,
            },
        },
        "required": [],
    },
}


def _handle_list(params, **kwargs):
    payload, source, warning = load_faq()
    if not payload:
        return _err(warning or "The RGS+ FAQ is unavailable.")

    wanted = (params.get("category") or "").strip().lower()
    include = bool(params.get("include_answers"))

    grouped: dict[str, list[dict]] = {}
    matched = 0
    for item in payload["items"]:
        cats = item["categories"] or ["Overig"]
        if wanted and not any(wanted == c.lower() for c in cats):
            continue
        matched += 1
        entry = {"id": item["id"], "question": item["question"], "url": item["url"]}
        if include:
            entry["answer"] = item["answer"]
        for cat in cats:
            if wanted and wanted != cat.lower():
                continue
            grouped.setdefault(cat, []).append(entry)

    if wanted and not matched:
        known = sorted({c for i in payload["items"] for c in i["categories"]})
        return _err(
            f"No FAQ category matches '{params.get('category')}'. "
            f"Known categories: {', '.join(known)}."
        )

    return json.dumps({
        "success": True,
        "category": params.get("category") or None,
        "total_questions": matched,
        "categories": grouped,
        "freshness": _freshness(payload, source),
        "warning": warning,
        "note": (
            "Questions cross-listed under two categories appear under both; "
            "the id is the same entry. Pass include_answers with a category "
            "to read full text, or use faq_search."
            if not include else None
        ),
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register(ctx):
    for name, schema, handler in (
        ("faq_search", _SEARCH_SCHEMA, _handle_search),
        ("faq_list", _LIST_SCHEMA, _handle_list),
    ):
        ctx.register_tool(name=name, toolset="rgsplus-faq", schema=schema,
                          handler=handler)
