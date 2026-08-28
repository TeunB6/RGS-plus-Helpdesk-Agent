#!/usr/bin/env python3
"""Serve the Sam UI and forward its calls to a running bridge.

    python3 ui/dev-proxy.py                 # auto: use the bridge if it is up
    python3 ui/dev-proxy.py --bridge-only   # fail loudly instead of falling back
    python3 ui/dev-proxy.py --mock-only     # never touch the bridge

    then open  http://127.0.0.1:8099/customer/

WHY A PROXY AND NOT A DIRECT CALL
---------------------------------
`ui/customer/app.js` posts to `/api/sam/chat` and deliberately holds no
BRIDGE_API_KEY. That is not an oversight: the bridge's bearer token
authenticates the *RGS+ application*, not the end user, so anything the browser
sends about who is asking — `user.role`, `user.licence` — is only trustworthy
when a server attaches it. Shipping the token to the browser would let a user
set their own role and hand it to the agent.

So in production RGS+ put a route on their own backend that adds identity and
forwards to the bridge. This script is that route, for development. Keeping the
same shape here means the UI never has to change when the real backend arrives.

WHAT IT DOES
------------
  GET  /...                 static files from ui/
  POST /api/sam/chat        -> POST {bridge}/v1/chat with the bearer token,
                               DEV_USER and DEV_CONTEXT merged in server-side

If the bridge is unreachable it falls back to canned answers that cycle every
`state` the contract defines, so the interface can still be looked at. The
fallback **says so in the reply text** — a mock silently impersonating the real
agent is how you end up demoing something that does not work.

Not part of any deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socketserver
import http.server
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent

CITE = [{"title": "Objecten beheren",
         "url": "https://rgsplus.atlassian.net/wiki/spaces/HELP/pages/1",
         "space": "HELP",
         "excerpt": "Dubbelklik op de statuskolom om de status te wisselen."}]

MOCK_SEQ = [
    {"state": "answer", "reply": "Je kunt de status wisselen door te dubbelklikken op de statuskolom.", "citations": CITE},
    {"state": "answer", "reply": "Dat kan waarschijnlijk via het actiemenu.", "citations": []},
    {"state": "clarify", "reply": "Gaat dit over de webversie of de inspectie-app? En om welk complex gaat het?"},
    {"state": "partial", "reply": "Het exporteren van een scenario naar Excel staat beschreven in de handleiding.",
     "citations": CITE,
     "draft": {"summary": "Import scenario met meerdere valuta's mislukt",
               "description": "Vraag van de klant:\n\"Ik krijg mijn import niet voor elkaar\"\n\nGezocht op: scenario import excel.\nNiet gedocumenteerd: gedrag bij afwijkende decimalen.",
               "draft_id": "2026-08-28-import.json"}},
    {"state": "unknown", "reply": "Hier staat niets over in de handleiding. Ik zet je vraag door naar een collega.",
     "draft": {"summary": "Garantieverklaring genereren vanuit RGS+",
               "description": "Klant vraagt of een garantieverklaring als formulier kan worden gegenereerd."}},
    {"state": "kb_unreachable", "reply": ""},
    {"state": "refuse", "reply": "Vragen over je licentie of facturatie kan ik niet beantwoorden. Je contactpersoon bij RGS+ helpt je hiermee verder."},
    {"state": "safety", "reply": ""},
]


def env(path: Path) -> dict:
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                out[k.strip()] = v
    return out


class Handler(http.server.SimpleHTTPRequestHandler):
    counter = 0
    cfg: dict = {}

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    # ---------- helpers ----------

    def _json(self, payload: dict, code: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mock(self, note: str | None):
        d = dict(MOCK_SEQ[Handler.counter % len(MOCK_SEQ)])
        Handler.counter += 1
        d.setdefault("citations", [])
        d.setdefault("draft", None)
        d["session_id"] = "dev-mock"
        if note:
            # Never let the mock pass for the real agent.
            d["reply"] = f"[{note}]\n\n{d.get('reply','')}".strip()
        self._json(d)

    # ---------- routes ----------

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/sam/chat":
            return self.send_error(404)

        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            return self._json({"detail": "invalid JSON"}, 400)

        if self.cfg["mode"] == "mock":
            return self._mock("MOCK — geen bridge, dit is geen echt antwoord")

        # Identity is attached HERE, server-side, exactly as RGS+'s backend will.
        payload["user"] = {**self.cfg["user"], **(payload.get("user") or {})}
        payload["context"] = {**self.cfg["context"], **(payload.get("context") or {})}

        req = urllib.request.Request(
            self.cfg["bridge"].rstrip("/") + "/v1/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.cfg["key"]},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                self._json(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            if e.code == 401:
                detail = "bridge rejected the bearer token — check BRIDGE_API_KEY in .env"
            print(f"  ! bridge HTTP {e.code}: {detail}")
            if self.cfg["strict"]:
                return self._json({"detail": detail}, 502)
            self._mock(f"MOCK — bridge gaf HTTP {e.code}")
        except (urllib.error.URLError, OSError) as e:
            print(f"  ! bridge unreachable: {e}")
            if self.cfg["strict"]:
                return self._json({"detail": f"bridge unreachable: {e}"}, 502)
            self._mock("MOCK — bridge niet bereikbaar, start Docker")

    def log_message(self, *a):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--bridge", default=None, help="default http://127.0.0.1:$BRIDGE_PORT")
    ap.add_argument("--bridge-only", action="store_true", help="never fall back to mock")
    ap.add_argument("--mock-only", action="store_true", help="never call the bridge")
    args = ap.parse_args()

    e = {**env(REPO / ".env"), **os.environ}
    bridge = args.bridge or f"http://127.0.0.1:{e.get('BRIDGE_PORT', '8081')}"
    key = (e.get("BRIDGE_API_KEY") or "").strip()

    mode = "mock" if args.mock_only else "bridge"
    if mode == "bridge" and not key:
        print("!! BRIDGE_API_KEY is not set in .env — the bridge would reject every call.")
        if args.bridge_only:
            return 1
        print("   Falling back to mock mode.")
        mode = "mock"

    Handler.cfg = {
        "bridge": bridge, "key": key, "mode": mode, "strict": args.bridge_only,
        # What RGS+'s backend will attach for real. Override with DEV_USER / DEV_CONTEXT.
        "user": json.loads(e.get("DEV_USER") or '{"name":"Demo gebruiker","organisation":"Demo BV","role":"gebruiker"}'),
        "context": json.loads(e.get("DEV_CONTEXT") or '{"screen":"Scenario","version":"3.3.1"}'),
    }

    print(f"\nSam UI          http://127.0.0.1:{args.port}/customer/")
    if mode == "bridge":
        print(f"forwarding to   {bridge}/v1/chat   (bearer set: {'yes' if key else 'no'})")
        reachable = True
        try:
            urllib.request.urlopen(bridge + "/healthz", timeout=3)
        except Exception:
            reachable = False
        print(f"bridge reachable: {'YES' if reachable else 'NO — start Docker; replies will be mocked and labelled'}")
    else:
        print("mode            MOCK — canned answers, every reply is labelled as such")
    print()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", args.port), Handler) as s:
        s.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
