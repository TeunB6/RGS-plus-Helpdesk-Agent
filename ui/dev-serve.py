"""Dev stand-in for the RGS+ backend route that fronts the bridge.

Serves ui/ and proxies POST /api/sam/chat to the bridge's POST /v1/chat,
attaching BRIDGE_API_KEY server-side. This is the piece RGS+ has to build in
their own application; this file is the smallest honest model of it, so the
customer surface can be driven against the REAL agent instead of dev-mock.py's
canned states.

    python3 ui/dev-serve.py            then open http://127.0.0.1:8000/customer/
    python3 ui/dev-serve.py --role beheerder --organisation "Gemeente X"

Stdlib only, like everything in scripts/.

── Why the proxy exists at all, and what it must keep doing ────────────────
The bearer token authenticates the RGS+ *application*, not the end user. So
`user.role` is only meaningful when a server attaches it: RGS+ is one database
partitioned by licence, and an answer that is right for an administrator is
WRONG for a normal user who cannot see the Stamgegevens menu at all.

Therefore this proxy DISCARDS any `user` the browser sends and substitutes its
own. That is not paranoia about a dev tool -- it is the behaviour RGS+'s route
has to copy. A proxy that forwards the browser's `user` through is a proxy that
lets a user promote themselves to beheerder, and it would let this UI ship
having never exercised the correct path.

The token is read from .env and never reaches the browser. Bind is 127.0.0.1
only.

Not part of any deployment. `EMBED_FRAME_ANCESTORS` in .env already lists
http://localhost:8000, which is where this serves.
"""
import argparse
import errno
import http.server
import json
import os
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request

# Line-buffered: the per-request `state=` line is the reason to watch this
# window, and block buffering hides it until the process exits.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:                             # Python < 3.7
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def load_env(path):
    """Minimal .env reader. Values may contain spaces and need no quoting --
    EMBED_FRAME_ANCESTORS is a space-separated list, so `source .env` breaks on
    it and this must not."""
    env = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]
                env[k.strip()] = v
    except FileNotFoundError:
        pass
    return env


ENV = load_env(os.path.join(REPO, ".env"))


def cfg(name, default=""):
    return os.environ.get(name) or ENV.get(name) or default


ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--port", type=int, default=8000)
ap.add_argument("--bridge", default="http://127.0.0.1:%s" % cfg("BRIDGE_PORT", "8081"))
ap.add_argument("--timeout", type=float, default=180.0,
                help="Longer than the bridge's HERMES_TIMEOUT (default 120), or "
                     "this reports OUR timeout for the agent's.")
# The identity the real backend would attach from the RGS+ session. `role`
# changes the answer, so it is a first-class flag rather than a buried constant.
ap.add_argument("--name", default="Dev Gebruiker")
ap.add_argument("--email", default="dev@example.invalid")
ap.add_argument("--organisation", default="Dev Organisatie")
ap.add_argument("--role", default="gebruiker",
                help="gebruiker | beheerder. Scopes the answer; see the docstring.")
ap.add_argument("--licence", default="DEV-1")
ap.add_argument("--host", default=None,
                help="Bind address. Default 127.0.0.1, except under WSL where it "
                     "is 0.0.0.0 — see WSL_NOTE.")
args = ap.parse_args()


def is_wsl():
    try:
        with open("/proc/version", encoding="utf-8", errors="replace") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


# ── WSL_NOTE ────────────────────────────────────────────────────────────────
# Under WSL2 the browser is normally Windows Chrome, which reaches this through
# WSL's localhost relay. That relay does NOT reliably forward a bind that is
# loopback-only inside the VM, so 127.0.0.1 gives Windows an
# ERR_CONNECTION_REFUSED while ports bound 0.0.0.0 work — which is exactly why
# the agent and bridge containers are reachable and this was not.
#
# So on WSL the default flips to 0.0.0.0. That is a wider bind and this process
# holds BRIDGE_API_KEY, so it is worth being precise about the exposure: in
# WSL2's default NAT mode the VM sits behind a virtual adapter, so 0.0.0.0
# reaches the Windows host and the WSL virtual network, NOT the physical LAN,
# unless someone has added a netsh portproxy. On mirrored networking, or on a
# non-WSL host, it would be the LAN — hence loopback stays the default
# everywhere else, and `--host 127.0.0.1` forces it back.
WSL = is_wsl()
BIND = args.host or ("0.0.0.0" if WSL else "127.0.0.1")

API_KEY = cfg("BRIDGE_API_KEY")
CHAT_URL = args.bridge.rstrip("/") + "/v1/chat"
SERVER_USER = {
    "name": args.name,
    "email": args.email,
    "organisation": args.organisation,
    "role": args.role,
    "licence": args.licence,
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=HERE, **k)

    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/sam/chat":
            return self.send_error(404)

        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"detail": "invalid JSON"})

        # Only these three come from the browser. `user` is dropped on purpose
        # -- see the docstring; the server is the authority on identity.
        out = {"message": payload.get("message") or ""}
        if payload.get("session_id"):
            out["session_id"] = payload["session_id"]
        if isinstance(payload.get("context"), dict):
            out["context"] = payload["context"]
        out["user"] = SERVER_USER

        req = urllib.request.Request(
            CHAT_URL,
            data=json.dumps(out).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + API_KEY,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=args.timeout) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            detail = (e.read() or b"").decode("utf-8", "replace")[:500]
            print("  bridge %s: %s" % (e.code, detail))
            # Pass the status through. app.js renders any non-2xx as "I cannot
            # reach the assistant" with a retry -- which is the truth here, and
            # must never be dressed up as the agent not knowing the answer.
            return self._json(e.code, {"detail": "bridge error"})
        except Exception as e:                     # noqa: BLE001 - dev aid
            print("  bridge unreachable: %r" % (e,))
            return self._json(502, {"detail": "bridge unreachable"})

        try:
            data = json.loads(body)
            print("  state=%s citations=%d draft=%s"
                  % (data.get("state"), len(data.get("citations") or []),
                     bool(data.get("draft"))))
            if data.get("state") is None:
                print("  ⚠️  no `state` in the bridge response — the bridge "
                      "container predates schemas.py. Rebuild: "
                      "docker compose up -d --build")
        except (ValueError, json.JSONDecodeError):
            pass

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *a):
        print("%s %s" % (self.command, self.path))


if not API_KEY:
    raise SystemExit(
        "BRIDGE_API_KEY is not set (looked in the environment and %s).\n"
        "The bridge rejects every call without it. Generate one with "
        "`openssl rand -hex 32` and put it in .env — the same value the bridge "
        "container is started with." % os.path.join(REPO, ".env")
    )

socketserver.TCPServer.allow_reuse_address = True

# Bind BEFORE announcing the URL. Printing first means a failed bind advertises
# an address that belongs to whatever else already holds the port.
try:
    srv = socketserver.TCPServer((BIND, args.port), Handler)
except OSError as e:
    if e.errno != errno.EADDRINUSE:
        raise
    raise SystemExit(
        "port %d is already in use — something else is serving there, quite "
        "possibly an earlier copy of this script.\n"
        "  see it:   ss -ltnp | grep :%d\n"
        "  stop it:  pkill -f dev-serve.py\n"
        "  or:       python3 ui/dev-serve.py --port %d"
        % (args.port, args.port, args.port + 1)
    )

print("ui        http://localhost:%d/customer/" % args.port)
print("proxy     POST /api/sam/chat  ->  %s" % CHAT_URL)
print("identity  role=%s licence=%s (server-side; the browser's is discarded)"
      % (SERVER_USER["role"], SERVER_USER["licence"]))
print("bind      %s:%d%s" % (BIND, args.port,
      "  (WSL detected: loopback-only is not reachable from a Windows browser)"
      if WSL and not args.host else ""))
with srv:
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
