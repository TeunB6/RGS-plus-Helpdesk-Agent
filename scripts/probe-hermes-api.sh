#!/usr/bin/env bash
# Find the HTTP routes the running agent container actually serves, so
# HERMES_SEND_PATH in .env can be set to a real one.
#
#   scripts/probe-hermes-api.sh [container-name]     # default: rgsplus-agent
#
# hermes-webui's routes are not a published API and shift between versions.
# The bridge keeps the path configurable precisely so this is a config change
# rather than a code change — this script tells you what to configure.

set -uo pipefail

CONTAINER="${1:-rgsplus-agent}"

if ! docker inspect "${CONTAINER}" >/dev/null 2>&1; then
    echo "No container named '${CONTAINER}'. Start it first: docker compose up -d" >&2
    exit 1
fi

echo "== routes declared in the webui source =="
# hermes-webui is not a framework app: server.py is a BaseHTTPRequestHandler and
# api/routes.py dispatches with `if parsed.path == "/api/…"`. There are no
# route decorators to grep, which is why an earlier version of this script
# printed nothing here and left the impression the API had no routes at all.
docker exec "${CONTAINER}" sh -c '
    grep -rhoE "parsed\.path (==|in) [^:]+" /hermes-webui --include="*.py" 2>/dev/null \
    | grep -oE "\"/api/[^\"]+\"" | tr -d "\"" | sort -u
' | sed 's/^/    /' || echo "(source not found at /hermes-webui — image layout may differ)"

echo
echo "== paths the running server has actually been asked for =="
docker exec "${CONTAINER}" sh -c '
    cat /var/log/nginx/access.log 2>/dev/null \
    | grep -oE "\"(GET|POST) [^ ]+" | sed -E "s/\"//" | sort | uniq -c | sort -rn | head -30
' || echo "(no access log yet — open the UI and send one message, then re-run)"

echo
echo "== do the routes the bridge uses answer? =="
# No Origin header, on purpose. hermes-webui runs a CSRF gate that rejects a
# request carrying an Origin that doesn't match the server's own host — an
# earlier version of this script sent `Origin: http://localhost` and got a 403
# it then reported as if the route were broken. The bridge is not a browser and
# sends no Origin, so probe it the way the bridge calls it. Port 80 is nginx in
# front of the webui on 8787; the bridge goes through nginx.
docker exec "${CONTAINER}" sh -c '
    command -v curl >/dev/null 2>&1 || { echo "(curl not in the image; use the lists above)"; exit 0; }

    printf "    POST /api/session/new    -> "
    body=$(curl -s -X POST -H "Content-Type: application/json" -d "{}" \
        http://127.0.0.1:80/api/session/new)
    sid=$(printf "%s" "$body" | python3 -c "
import json,sys
try: d = json.load(sys.stdin)
except Exception: sys.exit()
s = d.get(\"session\") if isinstance(d.get(\"session\"), dict) else d
print(s.get(\"session_id\") or s.get(\"id\") or \"\")
" 2>/dev/null)
    if [ -z "$sid" ]; then
        echo "no session id in: $(printf "%s" "$body" | head -c 120)"
        exit 1
    fi
    echo "session $sid"

    printf "    POST /api/chat           -> "
    curl -s -o /tmp/probe-chat -w "%{http_code}" --max-time 180 \
        -X POST -H "Content-Type: application/json" \
        -d "{\"session_id\":\"$sid\",\"message\":\"Antwoord met exact het woord: PONG\"}" \
        http://127.0.0.1:80/api/chat
    python3 -c "
import json
d = json.load(open(\"/tmp/probe-chat\"))
print(\"  answer=\" + repr(d.get(\"answer\"))[:60] + \"  keys=\" + \",\".join(d))
" 2>/dev/null || echo "  (unreadable body)"

    printf "    POST /api/session/delete -> "
    curl -s -o /dev/null -w "%{http_code}\n" -X POST -H "Content-Type: application/json" \
        -d "{\"session_id\":\"$sid\"}" http://127.0.0.1:80/api/session/delete
    rm -f /tmp/probe-chat
'

cat <<'EOF'

All three should answer, and /api/chat should carry the reply in `answer`.
Those are the defaults in .env:

    HERMES_SEND_PATH=/api/chat
    HERMES_SESSION_PATH=/api/session/new
    HERMES_DELETE_PATH=/api/session/delete

If a route moved, take the replacement from the first list above and set it
there. A path that takes the session in the URL instead of the body may use a
{session_id} placeholder: HERMES_SEND_PATH=/api/session/{session_id}/message

Then: docker compose up -d rgsplus-bridge

Confirm end to end (create, ask, delete):
    curl -s localhost:8081/v1/chat -H "Authorization: Bearer $BRIDGE_API_KEY" \
         -H 'Content-Type: application/json' \
         -d '{"message":"test","ephemeral":true}'
A wrong path comes back as a 502 that names the route it tried.
EOF
