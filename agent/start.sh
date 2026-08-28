#!/usr/bin/env bash
set -e

HERMES_DIR="${HOME}/.hermes"
mkdir -p "${HERMES_DIR}"

# Timezone. Hermes' gateway evaluates cron / scheduled-task times against
# the system clock, and the base image is UTC -- so a "daily at 08:00"
# job would fire at 08:00 UTC (10:00 CEST), which reads as "it didn't
# fire (when I expected)". Default to Europe/Amsterdam (overridable with
# -e TZ=...) and materialise it into /etc/localtime so date(1), libc and
# the gateway all agree on local time. Export it so the backgrounded
# gateway processes inherit it.
TZ="${TZ:-Europe/Amsterdam}"
if [ -f "/usr/share/zoneinfo/${TZ}" ]; then
    ln -sf "/usr/share/zoneinfo/${TZ}" /etc/localtime
    echo "${TZ}" > /etc/timezone
    export TZ
    echo "start.sh: timezone set to ${TZ}"
else
    echo "start.sh: WARNING unknown TZ='${TZ}', leaving container clock as UTC" >&2
fi

# Stale gateway.pid from an unclean previous shutdown can fool
# hermes-webui into reporting the gateway as already running before
# the supervisor has had a chance to (re)start it. The supervisor
# rewrites the pid as soon as the main gateway comes up (and clears
# per-profile pids in start_runner too).
rm -f "${HERMES_DIR}/gateway.pid"

# Default skin/theme prefs — skin is baked into the image at build time
# from clients/<UPPR_CLIENT>/brand.env.
SKIN_KEY="$(cat /etc/uppr-skin-key 2>/dev/null || echo uppr)"
PREFS_FILE="${HERMES_DIR}/webui-prefs.json"
if [ ! -f "${PREFS_FILE}" ]; then
    printf '{"theme":"dark","skin":"%s"}\n' "${SKIN_KEY}" > "${PREFS_FILE}"
fi

# Credentials -> ~/.hermes/.env
ENV_FILE="${HERMES_DIR}/.env"
touch "${ENV_FILE}"

upsert_env() {
    local key="$1" value="$2"
    if grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${value}|" "${ENV_FILE}"
    else
        echo "${key}=${value}" >> "${ENV_FILE}"
    fi
}

LLM_PROVIDER="${LLM_PROVIDER:-openrouter}"
CONFIG_FILE="${HERMES_DIR}/config.yaml"

# Validate the provider choice up front. A wrong or unknown value must
# mean "agent runs degraded on the fallback", never "container exits 1
# and Docker crash-loops it" — that takes the whole domain down with a
# 502 even though the webui itself is fine.
case "${LLM_PROVIDER}" in
    openrouter|openai|anthropic|groq)
        ;;
    local)
        if [ -z "${LOCAL_MODEL_NAME}" ]; then
            echo "WARNING: LLM_PROVIDER=local requires LOCAL_MODEL_NAME (e.g. qwen2.5-coder:7b);" >&2
            echo "         falling back to openrouter so the container keeps serving." >&2
            LLM_PROVIDER="openrouter"
        fi
        ;;
    *)
        echo "WARNING: unknown LLM_PROVIDER='${LLM_PROVIDER}' (expected openrouter, openai, anthropic, groq or local);" >&2
        echo "         falling back to openrouter so the container keeps serving." >&2
        LLM_PROVIDER="openrouter"
        ;;
esac

# Map LLM_PROVIDER to the hermes-agent provider id, endpoint, key env
# var and default model. hermes-agent has native profiles for
# openrouter, openai-api and anthropic; groq has no profile, but its
# OpenAI-compatible endpoint rides the generic "custom" provider and
# hermes-agent's runtime resolver derives GROQ_API_KEY from the
# api.groq.com host automatically.
MODEL_CONTEXT=""
MODEL_API_MODE=""
case "${LLM_PROVIDER}" in
    openrouter)
        MODEL_PROVIDER="openrouter"
        MODEL_BASE_URL="https://openrouter.ai/api/v1"
        MODEL_DEFAULT="${OPENROUTER_MODEL:-anthropic/claude-sonnet-4-5}"
        KEY_ENV="OPENROUTER_API_KEY"
        KEY_VALUE="${OPENROUTER_API_KEY:-}"
        ;;
    openai)
        # hermes-agent's provider id for the OpenAI platform is
        # "openai-api" — plain "openai" is rejected by its resolver.
        MODEL_PROVIDER="openai-api"
        MODEL_BASE_URL="https://api.openai.com/v1"
        MODEL_DEFAULT="${OPENAI_MODEL:-gpt-5.4}"
        KEY_ENV="OPENAI_API_KEY"
        KEY_VALUE="${OPENAI_API_KEY:-}"
        # hermes-agent auto-detects api.openai.com as the Responses API
        # and requests reasoning.encrypted_content — required for GPT-5.x
        # tool calls, but non-reasoning legacy models reject it with
        # HTTP 400 "Encrypted content is not supported with this model".
        # Pin those to plain chat completions; leave reasoning families
        # (gpt-5.x, o-series, and whatever comes next) on auto-detect.
        case "${MODEL_DEFAULT}" in
            gpt-4*|gpt-3.5*|chatgpt*)
                MODEL_API_MODE="chat_completions"
                ;;
        esac
        ;;
    anthropic)
        MODEL_PROVIDER="anthropic"
        MODEL_BASE_URL="https://api.anthropic.com"
        MODEL_DEFAULT="${ANTHROPIC_MODEL:-claude-sonnet-4-5}"
        KEY_ENV="ANTHROPIC_API_KEY"
        KEY_VALUE="${ANTHROPIC_API_KEY:-}"
        ;;
    groq)
        MODEL_PROVIDER="custom"
        MODEL_BASE_URL="https://api.groq.com/openai/v1"
        MODEL_DEFAULT="${GROQ_MODEL:-llama-3.3-70b-versatile}"
        KEY_ENV="GROQ_API_KEY"
        KEY_VALUE="${GROQ_API_KEY:-}"
        ;;
    local)
        MODEL_PROVIDER="custom"
        MODEL_BASE_URL="${LOCAL_MODEL_BASE_URL:-http://host.docker.internal:11434/v1}"
        MODEL_DEFAULT="${LOCAL_MODEL_NAME}"
        KEY_ENV="OPENAI_API_KEY"
        KEY_VALUE="${LOCAL_API_KEY:-ollama}"
        MODEL_CONTEXT="${LOCAL_MODEL_CONTEXT:-}"
        ;;
esac

if [ -n "${KEY_VALUE}" ]; then
    upsert_env "${KEY_ENV}" "${KEY_VALUE}"
fi

# Always pin model.default + provider + base_url so changing the
# provider or model env vars actually takes effect on restart — the
# cloud dashboard relies on this when a tenant switches providers.
# (The old code setdefault'ed provider/base_url, which silently kept a
# previous provider's values forever.) The Hermes installer writes a
# default config.yaml during the image build, so the 'first run' branch
# never fires in practice. Use the Hermes venv python (PyYAML is
# bundled there) to do a minimal merge that preserves any operator
# edits to other keys (mcp_servers, plugins, ...).
HERMES_PY="/usr/local/lib/hermes-agent/venv/bin/python3"
if [ -x "${HERMES_PY}" ]; then
    "${HERMES_PY}" - "${CONFIG_FILE}" "${MODEL_PROVIDER}" "${MODEL_BASE_URL}" "${MODEL_DEFAULT}" "${MODEL_CONTEXT}" "${MODEL_API_MODE}" <<'PY'
import sys, os
import yaml
config_path, provider, base_url, model, context, api_mode = sys.argv[1:7]
cfg = {}
if os.path.isfile(config_path):
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
model_block = cfg.setdefault("model", {})
model_block["default"] = model
model_block["provider"] = provider
model_block["base_url"] = base_url
if context:
    model_block["context_length"] = int(context)
else:
    # context_length only means something for local servers; drop a
    # value left over from a previous LLM_PROVIDER=local config.
    model_block.pop("context_length", None)
if api_mode:
    model_block["api_mode"] = api_mode
else:
    # No explicit mode for this provider/model combo: drop a stale pin
    # so hermes-agent auto-detects from the endpoint again.
    model_block.pop("api_mode", None)
os.makedirs(os.path.dirname(config_path), exist_ok=True)
with open(config_path, "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
print(f"start.sh: pinned model.default={model} provider={provider}")
PY
elif [ ! -f "${CONFIG_FILE}" ]; then
    {
        echo "model:"
        echo "  default: \"${MODEL_DEFAULT}\""
        echo "  provider: \"${MODEL_PROVIDER}\""
        echo "  base_url: \"${MODEL_BASE_URL}\""
        if [ -n "${MODEL_CONTEXT}" ]; then
            echo "  context_length: ${MODEL_CONTEXT}"
        fi
        if [ -n "${MODEL_API_MODE}" ]; then
            echo "  api_mode: \"${MODEL_API_MODE}\""
        fi
    } > "${CONFIG_FILE}"
fi

# Per-client SOUL.md baked at /etc/uppr-soul.md (by apply-branding.sh).
# Seeded into the volume only if the user/Hermes hasn't already written
# one -- never overwrite a SOUL the customer edited via the webui.
if [ -f /etc/uppr-soul.md ] && [ ! -f "${HERMES_DIR}/SOUL.md" ]; then
    cp /etc/uppr-soul.md "${HERMES_DIR}/SOUL.md"
fi

# Seed library items (skills, MCP servers, profiles) baked into the
# image at /etc/uppr-library into ~/.hermes. Idempotent: items already
# present in the volume are left alone. Failures are logged and
# explicitly do not abort startup -- a missing or broken library item
# must never take the whole container down.
STAGING_DIR="/etc/uppr-library"
LIBRARY_HELPER="/opt/uppr/_library.py"
if [ -d "${STAGING_DIR}" ] && [ -f "${LIBRARY_HELPER}" ]; then
    SEED_PY="/usr/local/lib/hermes-agent/venv/bin/python3"
    if [ ! -x "${SEED_PY}" ]; then
        SEED_PY="$(command -v python3 || true)"
    fi
    if [ -n "${SEED_PY}" ]; then
        "${SEED_PY}" "${LIBRARY_HELPER}" seed \
            --staging "${STAGING_DIR}" \
            --hermes-home "${HERMES_DIR}" \
            || echo "seed-library: warning - seeding failed, continuing without library items"
    else
        echo "seed-library: no python3 available, skipping"
    fi
fi

# Start webui
export HERMES_WEBUI_PYTHON=/usr/local/lib/hermes-agent/venv/bin/python3
cd /hermes-webui
./ctl.sh start || true

# Generate the embed snippet included by nginx.conf's `location /`.
# When EMBED_FRAME_ANCESTORS is set (space-separated list of origins
# allowed to iframe this agent, e.g. passed by uppr_cloud for
# aiCruiter-embedded recruiting agents), we:
#   - strip the webui's own X-Frame-Options + Content-Security-Policy
#     (it ships frame-ancestors 'none', which would otherwise block
#     framing even when we add our own CSP — multiple CSP headers are
#     combined with the most-restrictive winning), and
#   - emit a frame-ancestors CSP scoped to the allowed origin(s).
# When unset, the file is empty so a standalone agent keeps its own
# headers untouched. The file must exist before nginx starts — nginx
# fails to load if an `include` target is missing.
FRAME_CONF=/etc/nginx/uppr-frame.conf
if [ -n "${EMBED_FRAME_ANCESTORS:-}" ]; then
    cat > "${FRAME_CONF}" <<EOF
proxy_hide_header X-Frame-Options;
proxy_hide_header Content-Security-Policy;
proxy_hide_header Content-Security-Policy-Report-Only;
add_header Content-Security-Policy "frame-ancestors ${EMBED_FRAME_ANCESTORS}" always;
EOF
else
    : > "${FRAME_CONF}"
fi

# Start nginx
nginx

# ---------------------------------------------------------------------------
# Gateway supervision
# ---------------------------------------------------------------------------
# The hermes gateway daemon writes ~/.hermes/gateway.pid and
# gateway_state.json on startup; hermes-webui's api/agent_health.py
# checks those files to flip the "Gateway not configured" banner off
# and to drive scheduled job ticks. Logs go to fixed per-gateway paths
# so the cloud diagnostics panel can fetch them with `docker exec`.
#
# One gateway runs per agent home: "main" (~/.hermes) plus one per
# specialist profile under ~/.hermes/profiles/<name>/. Each profile is
# an isolated home with its own config.yaml, .env, skills and kanban
# board; without a dedicated gateway its cron / durable tasks never
# tick (see _hydrate_specialist_profile in _library.py).
#
# Supervision model: a reconciling loop runs in the FOREGROUND and
# keeps the container alive — if it ever dies, PID 1 exits and the
# Docker restart policy brings the whole container back, so no second
# watchdog is needed. Every tick it derives the desired set from disk
# and compares it against reality tracked in pidfiles:
#   * a profile dir pruned at runtime (uppr_cloud's reconcile_lib) gets
#     its runner AND its live gateway killed — a removed profile must
#     not keep polling e.g. its Telegram bot;
#   * a profile dir that (re)appears — created via the webui/agent, or
#     pruned-and-reseeded — is hydrated and gets a gateway again. The
#     previous implementation tracked started profiles by NAME in a
#     string, so a pruned-then-recreated profile never got its gateway
#     back until a full container restart;
#   * when hydrate fails, the start is SKIPPED this tick and retried on
#     the next one, instead of crash-looping a gateway that has no LLM
#     key every 5s.
mkdir -p /var/log

RUN_DIR=/var/run/uppr-gateways
mkdir -p "${RUN_DIR}"
rm -f "${RUN_DIR}"/*.pid 2>/dev/null || true

PROFILES_DIR="${HERMES_DIR}/profiles"
PROFILE_HOME_ROOT=/var/lib/uppr/profile-homes
WATCH_LOG="/var/log/hermes-gateway-watch.log"
SEED_PY="/usr/local/lib/hermes-agent/venv/bin/python3"
[ -x "${SEED_PY}" ] || SEED_PY="$(command -v python3 || true)"
LIBRARY_HELPER="/opt/uppr/_library.py"

log_watch() {
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "${WATCH_LOG}"
}

# Channel/identity env vars are scrubbed from PROFILE gateway process
# environments: the container env is tenant-wide (one flat --env-file
# from uppr_cloud), and a bot token that reaches every profile gateway
# makes them all poll the same bot (Telegram answers getUpdates with
# 409 and a random gateway wins). Profiles receive their own
# credentials through their per-profile .env instead (BASE__SUFFIX
# routing in _library.py). The MAIN gateway keeps the full env — it is
# the legitimate holder of unscoped channel tokens. Keep this pattern
# list in sync with _CHANNEL_KEY_RE in agent/scripts/_library.py.
channel_env_unset_args() {
    local v
    while IFS= read -r v; do
        case "$v" in
            TELEGRAM_*|DISCORD_*|WHATSAPP_*|SIGNAL_*|SLACK_*|*_BOT_TOKEN|*_WEBHOOK_URL)
                printf -- '-u\n%s\n' "$v" ;;
        esac
    done < <(compgen -e)
}

gateway_runner() {
    # Autorestart loop for ONE gateway. Runs as a background job; the
    # 5s backoff lives here because the supervisor tick is too coarse
    # for crash restarts. The live binary's PID is tracked in
    # <name>.child.pid so the supervisor can kill precisely this
    # gateway without pkill pattern-matching.
    set +e
    local home_dir="$1" name="$2"
    local log_tag out_log err_log child_pid rc
    if [ "${name}" = main ]; then log_tag="main"; else log_tag="profile-${name}"; fi
    out_log="/var/log/hermes-gateway-${log_tag}-stdout.log"
    err_log="/var/log/hermes-gateway-${log_tag}-stderr.log"
    while true; do
        # A profile dir can be removed at runtime (the operator
        # deselects a library profile, which uppr_cloud prunes on the
        # next apply). Stop cleanly instead of crash-looping against a
        # missing home; the supervisor reaps this runner and starts a
        # fresh one if the dir ever comes back.
        if [ ! -d "${home_dir}" ]; then
            echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) gateway(${log_tag}) home ${home_dir} gone; stopping runner" \
                >> "${err_log}"
            break
        fi
        if [ "${name}" = main ]; then
            HOME=/root HERMES_HOME="${home_dir}" HERMES_ALLOW_ROOT_GATEWAY=1 \
                /usr/local/bin/hermes gateway run \
                >> "${out_log}" 2>> "${err_log}" &
        else
            # Isolated HOME per profile: if the binary ever resolves ~
            # instead of HERMES_HOME, it must not land in the MAIN
            # agent's files. The synthetic home preserves the invariant
            # ~/.hermes == HERMES_HOME via a symlink. main keeps
            # HOME=/root (there ~/.hermes IS the home dir already).
            mkdir -p "${PROFILE_HOME_ROOT}/${name}"
            ln -sfn "${home_dir}" "${PROFILE_HOME_ROOT}/${name}/.hermes"
            local unset_args=()
            mapfile -t unset_args < <(channel_env_unset_args)
            env "${unset_args[@]}" \
                HOME="${PROFILE_HOME_ROOT}/${name}" \
                HERMES_HOME="${home_dir}" HERMES_ALLOW_ROOT_GATEWAY=1 \
                /usr/local/bin/hermes gateway run \
                >> "${out_log}" 2>> "${err_log}" &
        fi
        child_pid=$!
        echo "${child_pid}" > "${RUN_DIR}/${name}.child.pid"
        rc=0
        wait "${child_pid}" || rc=$?
        rm -f "${RUN_DIR}/${name}.child.pid"
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) gateway(${log_tag}) exited rc=${rc}; restart in 5s" \
            >> "${err_log}"
        sleep 5
    done
    rm -f "${RUN_DIR}/${name}.pid" "${RUN_DIR}/${name}.child.pid"
}

start_runner() {
    local home_dir="$1" name="$2" pid
    # Stale gateway.pid from an unclean previous shutdown can fool
    # hermes-webui into reporting the gateway as already running.
    rm -f "${home_dir}/gateway.pid"
    gateway_runner "${home_dir}" "${name}" &
    pid=$!
    echo "${pid}" > "${RUN_DIR}/${name}.pid"
    log_watch "supervisor: started gateway(${name}) runner pid ${pid}"
}

runner_alive() {
    local pid
    [ -f "${RUN_DIR}/$1.pid" ] || return 1
    pid="$(cat "${RUN_DIR}/$1.pid" 2>/dev/null || true)"
    [ -n "${pid}" ] && kill -0 "${pid}" 2>/dev/null
}

kill_runner() {
    local name="$1" pid child
    pid="$(cat "${RUN_DIR}/${name}.pid" 2>/dev/null || true)"
    child="$(cat "${RUN_DIR}/${name}.child.pid" 2>/dev/null || true)"
    [ -n "${pid}" ] && kill "${pid}" 2>/dev/null
    [ -n "${child}" ] && kill "${child}" 2>/dev/null
    rm -f "${RUN_DIR}/${name}.pid" "${RUN_DIR}/${name}.child.pid"
}

supervise_gateways() {
    # Foreground reconciling loop; also what keeps the container alive.
    # Everything in here is failure-hardened: the loop dying means the
    # container restarts, which must never happen because of one bad
    # profile or a transient hydrate error.
    set +e
    local name dir pid_file
    while true; do
        # Reap: kill runners whose home vanished (runner + live child,
        # so a pruned profile stops polling its channels immediately)
        # and clean up runners that died on their own so the start
        # branch below re-creates them. The dead-runner branch also goes
        # through kill_runner: a hard-killed runner subshell can leave
        # its `hermes gateway run` child orphaned and still polling, and
        # starting a fresh runner next to that orphan would give two
        # gateways on one bot token (Telegram 409). kill_runner reaps
        # the recorded child (if any) and removes both pidfiles; the
        # kill of the already-dead runner pid fails harmlessly.
        for pid_file in "${RUN_DIR}"/*.pid; do
            [ -e "${pid_file}" ] || continue
            case "${pid_file}" in *.child.pid) continue ;; esac
            name="$(basename "${pid_file}" .pid)"
            if [ "${name}" = main ]; then dir="${HERMES_DIR}"; else dir="${PROFILES_DIR}/${name}"; fi
            if [ ! -d "${dir}" ]; then
                log_watch "supervisor: home for gateway(${name}) gone; killing runner + child"
                kill_runner "${name}"
            elif ! runner_alive "${name}"; then
                log_watch "supervisor: runner for gateway(${name}) died; reaping child + pidfiles"
                kill_runner "${name}"
            fi
        done

        # Start: main first, then one runner per profile dir on disk.
        if ! runner_alive main; then
            start_runner "${HERMES_DIR}" main
        fi
        if [ -d "${PROFILES_DIR}" ]; then
            for dir in "${PROFILES_DIR}"/*/; do
                [ -d "${dir}" ] || continue
                name="$(basename "${dir%/}")"
                runner_alive "${name}" && continue
                # Hydrate before (re)starting so the gateway has its
                # own .env, model block, self-scoped kanban and skills.
                # On failure: skip THIS tick, retry on the next — which
                # also covers "the LLM key arrives a minute later via
                # the next uppr_cloud apply". The helper being ABSENT is
                # treated the same way, not as "start anyway": an
                # unhydrated gateway is exactly the bug class this
                # supervisor exists to prevent (stale inherited kanban →
                # cron under main, missing LLM key → crash-loop). The
                # image ships /opt/uppr/_library.py, so this branch only
                # fires on a broken image — loud in the watch log.
                if [ -z "${SEED_PY}" ] || [ ! -f "${LIBRARY_HELPER}" ]; then
                    log_watch "supervisor: hydrate helper unavailable (SEED_PY='${SEED_PY}', helper=${LIBRARY_HELPER}); NOT starting gateway(${name})"
                    continue
                fi
                if ! "${SEED_PY}" "${LIBRARY_HELPER}" hydrate \
                        --hermes-home "${HERMES_DIR}" --profile "${name}" \
                        >> "${WATCH_LOG}" 2>&1; then
                    log_watch "supervisor: hydrate failed for '${name}'; skipping start this tick"
                    continue
                fi
                start_runner "${dir%/}" "${name}"
            done
        fi
        sleep 15
    done
}

# Legacy log paths (hermes-gateway-stdout.log / -stderr.log) keep
# pointing at the main gateway's logs so existing diag tooling and
# dashboard log fetchers keep working.
ln -sf /var/log/hermes-gateway-main-stdout.log /var/log/hermes-gateway-stdout.log
ln -sf /var/log/hermes-gateway-main-stderr.log /var/log/hermes-gateway-stderr.log

# Diagnostics writer. It used to be launched by supervisord's
# [program:uppr-diag], but supervisord is never started in this image
# (see the note above), so /uppr-diag.txt was only ever populated when
# uppr_cloud exec'd the script. Start it here so nginx's
# /uppr-diag.txt is always live. It's an infinite loop of its own with
# no `set -e`, so a bare background start is enough.
if [ -x /usr/local/bin/uppr-diag.sh ]; then
    /usr/local/bin/uppr-diag.sh &
fi

# Stream the webui log to container stdout in the background; the
# supervisor below is the foreground process that keeps the container
# alive (this used to be an `exec tail -F`, with the gateways on
# unsupervised background loops).
WEBUI_LOG="/hermes-webui/logs/webui.log"
mkdir -p /hermes-webui/logs
touch "${WEBUI_LOG}"
tail -F "${WEBUI_LOG}" &

supervise_gateways
