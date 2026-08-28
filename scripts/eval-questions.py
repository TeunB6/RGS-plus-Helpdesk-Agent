#!/usr/bin/env python3
"""Ask the agent a list of questions, one independent session each, and save
what it answered.

    python3 scripts/eval-questions.py evals/helpdesk-nl.txt
    python3 scripts/eval-questions.py evals/helpdesk-nl.txt --concurrency 4
    python3 scripts/eval-questions.py evals/helpdesk-nl.txt --repeat 3

Independence is the point of this tool. Every question is sent with **no
`session_id`**, so the bridge opens a fresh Hermes session for it — nothing a
question says can reach the next one. Nothing is shared between requests
except the process itself, and the run refuses to report success if two
answers came back on the same session id (see `--allow-shared-sessions`).

That also means each answer is a *first turn*: the agent has no history to
lean on, which is exactly the condition the RGS+ widget puts it in when a user
opens the chat and pastes a mail.

Output goes to `evals/runs/<name>-<n>/` — one `results.json` for diffing
between runs, one `transcript.md` to read. Stdlib only, so this runs on a
laptop with no install step.

Nothing here writes to Jira: ticket creation in this deployment is a dry run
(see bundles/rgsplus.yaml), so a question that escalates leaves a draft under
`.jira-dryrun/` and nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "evals" / "runs"

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    ("\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")
    if sys.stdout.isatty() else ("",) * 6
)


# ---------------------------------------------------------------- questions


@dataclass
class Question:
    id: str
    text: str
    user: dict[str, str] = field(default_factory=dict)
    context: dict[str, str] = field(default_factory=dict)
    note: str = ""


def load_questions(path: Path) -> list[Question]:
    """Read a question file.

    `.json` — a list of objects: {"id", "question", "user"?, "context"?, "note"?}

    Anything else — plain text, blocks separated by a line of `---`. A block may
    open with `#` header lines before its body:

        # id: opdrachtgever-geen-login
        # note: verwacht: escalatie, geen verzonnen menupad
        # user.name: Jan de Vries
        # context.screen: Opdrachtgevers
        Goedemorgen, ...

    The text format exists so a helpdesk mail can be pasted in whole. Only the
    leading `#` lines are metadata; a `#` inside the body is body.
    """
    raw = path.read_text(encoding="utf-8")

    if path.suffix == ".json":
        entries = json.loads(raw)
        if not isinstance(entries, list):
            die(f"{path} must contain a JSON list, got {type(entries).__name__}.")
        return [
            Question(
                id=str(e.get("id") or f"q{i + 1:02d}"),
                text=(e.get("question") or e.get("text") or "").strip(),
                user=e.get("user") or {},
                context=e.get("context") or {},
                note=e.get("note") or "",
            )
            for i, e in enumerate(entries)
            if isinstance(e, dict)
        ]

    questions: list[Question] = []
    for i, block in enumerate(re.split(r"^---+\s*$", raw, flags=re.MULTILINE)):
        question = _parse_block(block, i)
        if question is not None:
            questions.append(question)
    return questions


def _parse_block(block: str, index: int) -> Question | None:
    lines = block.strip("\n").splitlines()
    meta: dict[str, str] = {}

    # Blank lines between header lines are allowed — the header ends at the
    # first line that is neither blank nor a `#` comment. A `#` after that is
    # body, because a user's mail may well contain one.
    while lines and (not lines[0].strip() or lines[0].lstrip().startswith("#")):
        line = lines.pop(0).lstrip()
        if not line:
            continue
        key, sep, value = line.lstrip("#").strip().partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        # Repeating a key continues it rather than replacing it, so a long
        # `# note:` can be wrapped over several lines the way a comment is.
        meta[key] = f"{meta[key]} {value}".strip() if key in meta else value

    text = "\n".join(lines).strip()
    if not text:
        return None  # separator noise or a comment-only block

    return Question(
        id=meta.get("id") or f"q{index + 1:02d}",
        text=text,
        user={k[5:]: v for k, v in meta.items() if k.startswith("user.")},
        context={k[8:]: v for k, v in meta.items() if k.startswith("context.")},
        note=meta.get("note", ""),
    )


# ---------------------------------------------------------------- the bridge


@dataclass
class Answer:
    id: str
    attempt: int
    question: str
    note: str
    reply: str | None
    session_id: str | None
    error: str | None
    seconds: float


def ask(url: str, key: str, question: Question, timeout: float, attempt: int) -> Answer:
    """One question, one fresh session.

    `session_id` is deliberately absent from the body: the bridge opens a new
    Hermes session when it is missing, and that new session is this question's
    only context. Do not add it — reusing one would make every later answer
    depend on every earlier one, which is the exact thing this tool exists to
    rule out.

    `ephemeral` tells the bridge to delete that session once the answer is out.
    Nothing here will ever send a second turn, and a 28-question run would
    otherwise leave 28 sessions behind in the agent's sidebar every time.
    """
    body = {"message": question.text, "ephemeral": True}
    if question.user:
        body["user"] = question.user
    if question.context:
        body["context"] = question.context

    request = urllib.request.Request(
        url.rstrip("/") + "/v1/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return Answer(
            id=question.id,
            attempt=attempt,
            question=question.text,
            note=question.note,
            reply=(payload.get("reply") or "").strip() or None,
            session_id=payload.get("session_id"),
            error=None if payload.get("reply") else "empty reply",
            seconds=time.monotonic() - started,
        )
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        return _failed(question, attempt, f"HTTP {e.code}: {detail}", started)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return _failed(question, attempt, f"{type(e).__name__}: {e}", started)
    except (ValueError, KeyError) as e:
        return _failed(question, attempt, f"unreadable response: {e}", started)


def _failed(question: Question, attempt: int, error: str, started: float) -> Answer:
    return Answer(
        id=question.id,
        attempt=attempt,
        question=question.text,
        note=question.note,
        reply=None,
        session_id=None,
        error=error,
        seconds=time.monotonic() - started,
    )


# ---------------------------------------------------------------- reporting


def write_results(out: Path, answers: list[Answer], meta: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)

    (out / "results.json").write_text(
        json.dumps(
            {"run": meta, "answers": [a.__dict__ for a in answers]},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Agent run — {meta['questions_file']}",
        "",
        f"- bridge: `{meta['url']}`",
        f"- questions: {meta['count']} · repeat: {meta['repeat']} · "
        f"concurrency: {meta['concurrency']}",
        f"- started: {meta['started']}",
        "",
        "Every answer below is a first turn in its own session — no question saw "
        "another question's answer.",
        "",
    ]
    for a in answers:
        lines += [f"## {a.id}" + (f" (run {a.attempt})" if meta["repeat"] > 1 else ""), ""]
        if a.note:
            lines += [f"> {a.note}", ""]
        lines += ["**Gevraagd**", "", "```", a.question, "```", "", "**Antwoord**", ""]
        lines += [a.reply or f"_(geen antwoord — {a.error})_", ""]
        lines += [f"`session {a.session_id or '—'}` · {a.seconds:.1f}s", ""]
    (out / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


def check_independence(answers: list[Answer]) -> list[str]:
    """Sessions must not be shared. A repeated id means two questions ran in the
    same conversation and could have contaminated each other — the results are
    not comparable and the run should be treated as void."""
    seen: dict[str, str] = {}
    problems = []
    for a in answers:
        if not a.session_id:
            continue
        if a.session_id in seen:
            problems.append(
                f"{a.id} and {seen[a.session_id]} share session {a.session_id}"
            )
        seen[a.session_id] = a.id
    return problems


# ---------------------------------------------------------------- plumbing


def die(msg: str, *hints: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"{RED}✗ {msg}{RESET}", file=sys.stderr)
    for hint in hints:
        print(f"  {DIM}→ {hint}{RESET}", file=sys.stderr)
    sys.exit(1)


def load_env_file(path: Path) -> None:
    """Fill in anything the real environment does not already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def next_run_dir(base: Path, name: str) -> Path:
    """`<name>-001`, `-002`, … so runs sit next to each other and diff cleanly.
    No timestamps in the path: a diff between two runs should show what the
    agent said differently, not that the clock moved."""
    base.mkdir(parents=True, exist_ok=True)
    existing = [p.name for p in base.glob(f"{name}-*") if p.is_dir()]
    return base / f"{name}-{len(existing) + 1:03d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ask the RGS+ agent a list of questions, independently.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("questions", type=Path, help="question file (.txt or .json)")
    parser.add_argument("--url", default=None,
                        help="bridge base URL (default $BRIDGE_URL or http://localhost:8081)")
    parser.add_argument("--key", default=None, help="bearer token (default $BRIDGE_API_KEY)")
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="questions in flight at once (default 1 — kindest to the agent)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="ask each question N times, to see how much the answer moves")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--shuffle", action="store_true",
                        help="randomise send order; answers are still reported in file order")
    parser.add_argument("--only", default=None,
                        help="only ask questions whose id matches this substring")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent and stop — no agent needed")
    parser.add_argument("--allow-shared-sessions", action="store_true",
                        help="do not fail when two answers share a session id (debugging only)")
    args = parser.parse_args()

    load_env_file(args.env_file)
    url = args.url or os.environ.get("BRIDGE_URL") or "http://localhost:8081"
    key = args.key or os.environ.get("BRIDGE_API_KEY") or ""

    if not args.questions.is_file():
        die(f"No question file at {args.questions}.")

    questions = load_questions(args.questions)
    if args.only:
        questions = [q for q in questions if args.only in q.id]
    if not questions:
        die(f"{args.questions} yielded no questions.",
            "Blocks are separated by a line of `---`; a block needs a body, not just headers.")

    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        die(f"Duplicate question ids: {', '.join(dupes)}.",
            "Ids name the sections in the transcript — they have to be unique.")

    if args.dry_run:
        print(f"{BOLD}{len(questions)} question(s) → {url}/v1/chat{RESET}\n")
        for q in questions:
            print(f"{BOLD}{q.id}{RESET} {DIM}(fresh session, no session_id sent){RESET}")
            if q.user or q.context:
                print(f"  {DIM}user={q.user or '{}'} context={q.context or '{}'}{RESET}")
            print("  " + q.text.replace("\n", "\n  ")[:400] + "\n")
        return 0

    if not key:
        die("No BRIDGE_API_KEY.",
            "Put it in .env, export it, or pass --key. The bridge rejects /v1 without it.")

    # Build the work list first, so send order and report order are separable.
    work = [(q, n + 1) for q in questions for n in range(max(1, args.repeat))]
    order = list(range(len(work)))
    if args.shuffle:
        random.Random(0).shuffle(order)  # fixed seed: shuffled, but reproducible

    print(f"{BOLD}{len(work)} request(s){RESET} → {url}  "
          f"{DIM}concurrency={args.concurrency}{RESET}\n")

    results: list[Answer | None] = [None] * len(work)
    done = 0

    def run(i: int) -> tuple[int, Answer]:
        q, attempt = work[i]
        return i, ask(url, key, q, args.timeout, attempt)

    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        for i, answer in pool.map(run, order):
            results[i] = answer
            done += 1
            mark = f"{RED}✗{RESET}" if answer.error else f"{GREEN}✓{RESET}"
            tail = answer.error or f"{len(answer.reply or '')} tekens"
            print(f" {mark} [{done}/{len(work)}] {answer.id:<28} "
                  f"{answer.seconds:5.1f}s  {DIM}{tail[:70]}{RESET}")

    answers = [a for a in results if a is not None]
    out = next_run_dir(args.out, args.questions.stem)
    write_results(out, answers, {
        "questions_file": str(args.questions),
        "url": url,
        "count": len(questions),
        "repeat": args.repeat,
        "concurrency": args.concurrency,
        "shuffled": args.shuffle,
        "started": started_at,
    })

    failures = [a for a in answers if a.error]
    shared = check_independence(answers)

    print(f"\n{BOLD}{len(answers) - len(failures)}/{len(answers)}{RESET} answered · "
          f"written to {out}")
    if failures:
        print(f"{YELLOW}  {len(failures)} failed — see results.json{RESET}")
    if shared:
        for problem in shared:
            print(f"{RED}  ✗ {problem}{RESET}")
        print(f"{RED}  Answers may have influenced each other — treat this run as "
              f"void.{RESET}")
        if not args.allow_shared_sessions:
            return 2

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
