#!/usr/bin/env bash
# Assemble the Docker build context for rgsplus-agent.
#
#   scripts/stage-build-context.sh          # -> .build/agent-context
#   docker compose up -d --build
#
# Why this exists
# ---------------
# The agent image's Dockerfile lives in the uppr_hermes checkout and does
#
#     COPY clients/ /tmp/clients/
#     COPY library/ /tmp/library/
#
# from its *own* build context. There is no build-arg or bind mount that can
# make Docker read those two directories from a second repo, and the seeding
# that turns a manifest into ~/.hermes content happens at build time (see
# uppr_hermes/scripts/apply-library.sh). So this repo's library/ and
# clients/ are invisible to a plain `docker build -f ../uppr_hermes/...`.
#
# The fix is a staged context: copy the Hermes checkout, then overlay this
# repo's library/ and clients/ on top. docker-compose builds from the result.
# Everything else about the image — Hermes, webui, nginx, start.sh — still
# comes from uppr_hermes, which stays the single owner of the base.
#
# Cheap to re-run: it's a file copy of a small repo, and Docker's layer cache
# keys on content, so an unchanged staging dir is a full cache hit.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

# Keep in sync with HERMES_CONTEXT in .env / docker-compose.yml.
HERMES_CONTEXT="${HERMES_CONTEXT:-../uppr_hermes}"

# Honour .env so `scripts/stage-build-context.sh` and `docker compose` agree
# on which checkout is the base, without having to export anything.
if [ -f .env ] && [ -z "${HERMES_CONTEXT_EXPLICIT:-}" ]; then
    from_env="$(sed -n 's/^[[:space:]]*HERMES_CONTEXT[[:space:]]*=[[:space:]]*//p' .env | tail -n1 | tr -d '"'"'"'')"
    [ -n "${from_env}" ] && HERMES_CONTEXT="${from_env}"
fi

if [ ! -f "${HERMES_CONTEXT}/Dockerfile" ]; then
    echo "error: no Dockerfile at ${HERMES_CONTEXT}" >&2
    echo "       Point HERMES_CONTEXT at your uppr_hermes checkout, in .env" >&2
    echo "       or in the environment." >&2
    exit 1
fi

OUT=".build/agent-context"

rm -rf "${OUT}"
mkdir -p "${OUT}"

# 1. The base: everything the Dockerfile needs from uppr_hermes.
#    .git and .env are excluded — the first is large and useless in a build
#    context, the second would bake another deployment's secrets into a layer.
tar -C "${HERMES_CONTEXT}" \
    --exclude=.git \
    --exclude=.env \
    --exclude=__pycache__ \
    --exclude=node_modules \
    --exclude=.build \
    -cf - . | tar -C "${OUT}" -xf -

# 2. The overlay: what makes this deployment RGS+. Same paths, so these win.
tar -C "${REPO_DIR}" \
    --exclude=__pycache__ \
    -cf - library clients | tar -C "${OUT}" -xf -

echo "staged ${HERMES_CONTEXT} + this repo's library/ clients/ -> ${OUT}"
echo "  client dir : $(ls -d "${OUT}/clients/rgsplus" 2>/dev/null || echo 'MISSING — build will fall back to the default client')"
echo "  atlassian  : $(ls "${OUT}/library/tools/support/atlassian/plugin.yaml" 2>/dev/null || echo 'MISSING')"
