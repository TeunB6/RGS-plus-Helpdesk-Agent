#!/usr/bin/env bash
# Stage library/ items selected by a client's manifest.yaml into a
# staging dir inside the image. start.sh later seeds the staging dir
# into ~/.hermes on container start.
#
# Usage:
#   apply-library.sh <library-dir> <client-dir> <staging-dir>
#
# Behaviour:
#   - Always creates the staging skeleton (skills/ mcp/ profiles/ tools/).
#   - If the client has no manifest.yaml or every list in it is empty,
#     the staging skeleton stays empty and the build proceeds normally.
#   - Missing library items referenced from the manifest produce a
#     warning, never a build failure.

set -euo pipefail

LIBRARY_DIR="${1:?usage: apply-library.sh <library> <client> <staging>}"
CLIENT_DIR="${2:?usage: apply-library.sh <library> <client> <staging>}"
STAGING_DIR="${3:?usage: apply-library.sh <library> <client> <staging>}"

mkdir -p "${STAGING_DIR}/skills" \
         "${STAGING_DIR}/mcp" \
         "${STAGING_DIR}/profiles" \
         "${STAGING_DIR}/tools"

MANIFEST="${CLIENT_DIR}/manifest.yaml"
if [ ! -f "${MANIFEST}" ]; then
    echo "apply-library: no manifest at ${MANIFEST}, staging dir left empty"
    exit 0
fi

# Prefer the Hermes venv python (it has PyYAML); fall back to system
# python3 so the script is runnable outside the container during dev.
HERMES_PY="${HERMES_PY:-/usr/local/lib/hermes-agent/venv/bin/python3}"
if [ ! -x "${HERMES_PY}" ]; then
    HERMES_PY="$(command -v python3 || true)"
fi
if [ -z "${HERMES_PY}" ]; then
    echo "apply-library: no python3 available, leaving staging empty" >&2
    exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Inside the image the helper lives at /opt/uppr/_library.py so start.sh
# can re-use it for runtime seeding; during local dev it sits next to
# this shell script. Prefer the install path, fall back to dev path.
if [ -f "/opt/uppr/_library.py" ]; then
    HELPER="/opt/uppr/_library.py"
else
    HELPER="${SCRIPT_DIR}/_library.py"
fi

"${HERMES_PY}" "${HELPER}" stage \
    --library "${LIBRARY_DIR}" \
    --manifest "${MANIFEST}" \
    --staging "${STAGING_DIR}"
