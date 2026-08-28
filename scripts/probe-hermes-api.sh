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
# The webui is a Python app; its route decorators name every path it serves.
docker exec "${CONTAINER}" sh -c '
    grep -rhoE "@(app|router)\.(get|post|put|delete)\(\s*[\"'"'"'][^\"'"'"']+" \
        /hermes-webui --include="*.py" 2>/dev/null \
    | sed -E "s/.*[\"'"'"']//" | sort -u
' || echo "(source not found at /hermes-webui — image layout may differ)"

echo
echo "== paths the running server has actually been asked for =="
docker exec "${CONTAINER}" sh -c '
    cat /var/log/nginx/access.log 2>/dev/null \
    | grep -oE "\"(GET|POST) [^ ]+" | sed -E "s/\"//" | sort | uniq -c | sort -rn | head -30
' || echo "(no access log yet — open the UI and send one message, then re-run)"

echo
echo "== does the default session route answer? =="
docker exec "${CONTAINER}" sh -c '
    command -v curl >/dev/null 2>&1 || { echo "(curl not in the image; use the lists above)"; exit 0; }
    printf "POST /api/session/new -> "
    curl -s -o /dev/null -w "%{http_code}\n" -X POST \
        -H "Content-Type: application/json" -H "Origin: http://localhost" \
        -d "{}" http://127.0.0.1:8787/api/session/new
'

cat <<'EOF'

Next: pick the route from the first list that takes a chat message (it will
look like /api/session/<id>/message or /api/chat), and set it in .env with the
session id templated:

    HERMES_SEND_PATH=/api/session/{session_id}/message

Then: docker compose up -d rgsplus-bridge

Confirm with:
    curl -s localhost:8081/v1/chat -H "Authorization: Bearer $BRIDGE_API_KEY" \
         -H 'Content-Type: application/json' -d '{"message":"test"}'
A wrong path comes back as a 502 that says so explicitly.
EOF
