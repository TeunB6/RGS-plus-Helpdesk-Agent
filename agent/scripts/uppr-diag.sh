#!/usr/bin/env bash
# Periodically write a plaintext diagnostics dump to /var/uppr/diag.txt
# so an operator can fetch it via `GET /uppr-diag.txt` without SSH
# access. nginx serves the file, Caddy gates access on the cloud side.
#
# Deliberately no `set -e`/`set -u` — a diagnostic script that aborts
# mid-collection on the first failing command is worse than one that
# emits "(failed)" placeholders and keeps writing the rest.

OUT=/var/uppr/diag.txt
TMP="${OUT}.tmp"
mkdir -p /var/uppr 2>/dev/null

RUN_DIR=/var/run/uppr-gateways

# Per-gateway supervisor state + profile view. Shared by the bootstrap
# dump and the main loop. Keeps secret VALUES out of the dump: only
# .env key NAMES are listed.
diag_gateways() {
    echo "--- gateway supervisor state (${RUN_DIR}) ---"
    if [ -d "${RUN_DIR}" ]; then
        for f in "${RUN_DIR}"/*.pid; do
            [ -e "$f" ] || { echo "(no pidfiles)"; break; }
            case "$f" in *.child.pid) continue ;; esac
            name="$(basename "$f" .pid)"
            pid="$(cat "$f" 2>/dev/null)"
            child="$(cat "${RUN_DIR}/${name}.child.pid" 2>/dev/null)"
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then alive=yes; else alive=no; fi
            echo "gateway=${name} runner_pid=${pid:-?} alive=${alive} gateway_pid=${child:-none}"
        done
    else
        echo "(no run dir yet)"
    fi
    echo

    echo "--- profiles on disk (/root/.hermes/profiles) ---"
    ls -1 /root/.hermes/profiles 2>/dev/null || echo "(none)"
    echo

    echo "--- last 40 lines /var/log/hermes-gateway-watch.log ---"
    tail -n 40 /var/log/hermes-gateway-watch.log 2>&1
    echo

    echo "--- per-profile gateway stderr (last 20 lines each) ---"
    for log in /var/log/hermes-gateway-profile-*-stderr.log; do
        [ -e "$log" ] || { echo "(no per-profile gateway logs)"; break; }
        echo "  # $log"
        tail -n 20 "$log" 2>&1
    done
    echo

    echo "--- .env key names per home (values redacted) ---"
    for envf in /root/.hermes/.env /root/.hermes/profiles/*/.env; do
        [ -e "$envf" ] || continue
        echo "  # $envf"
        grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$envf" 2>/dev/null | sed 's/=$//' | sort || true
    done
    echo
}

# Write a bootstrap dump immediately so even if a downstream command
# hangs forever, an operator hitting /uppr-diag.txt still sees useful
# evidence. We deliberately keep this block to plain file reads — the
# loop below adds process probes (with timeouts) once we're past the
# synchronous boot.
{
    echo "=== uppr-diag bootstrap (synchronous, before main loop) ==="
    date -u +"%Y-%m-%dT%H:%M:%SZ"
    echo "pid=$$"
    echo

    echo "--- image build info ---"
    cat /etc/uppr-build-info.txt 2>/dev/null || echo "(no build info file)"
    echo

    echo "--- /root/.hermes/ top level ---"
    ls -la /root/.hermes/ 2>&1
    echo

    echo "--- gateway.pid (if exists) ---"
    cat /root/.hermes/gateway.pid 2>&1
    echo

    echo "--- gateway_state.json (if exists) ---"
    cat /root/.hermes/gateway_state.json 2>&1
    echo

    echo "--- hermes binaries on disk ---"
    ls -la /usr/local/bin/hermes /usr/local/lib/hermes-agent/venv/bin/hermes 2>&1
    echo

    echo "--- last 100 lines /var/log/hermes-gateway-stderr.log ---"
    tail -n 100 /var/log/hermes-gateway-stderr.log 2>&1
    echo

    echo "--- last 100 lines /var/log/hermes-gateway-stdout.log ---"
    tail -n 100 /var/log/hermes-gateway-stdout.log 2>&1
    echo

    diag_gateways

    echo "(main loop starting; refresh in ~5s for process status too)"
} > "$OUT" 2>/dev/null

while true; do
    {
        echo "=== uppr-agent diagnostics ==="
        date -u +"%Y-%m-%dT%H:%M:%SZ"
        echo

        echo "--- image build info ---"
        cat /etc/uppr-build-info.txt 2>/dev/null || echo "(no build info file)"
        echo

        # start.sh runs the webui + a foreground gateway supervisor
        # directly (no supervisord), so a process listing is the status
        # view; diag_gateways below adds the per-gateway breakdown.
        echo "--- container processes (ps -ef, 5s timeout) ---"
        timeout 5 ps -ef 2>&1 || echo "(ps timed out / failed)"
        echo

        echo "--- whoami / HOME / HERMES_HOME ---"
        echo "whoami=$(whoami 2>/dev/null)"
        echo "HOME=${HOME:-<unset>}"
        echo "HERMES_HOME=${HERMES_HOME:-<unset>}"
        echo

        echo "--- /root/.hermes/ top level ---"
        ls -la /root/.hermes/ 2>&1
        echo

        echo "--- gateway.pid (if exists) ---"
        cat /root/.hermes/gateway.pid 2>&1
        echo

        echo "--- gateway_state.json (if exists) ---"
        cat /root/.hermes/gateway_state.json 2>&1
        echo

        echo "--- hermes binaries on disk ---"
        ls -la /usr/local/bin/hermes /usr/local/lib/hermes-agent/venv/bin/hermes 2>&1
        echo

        echo "--- hermes --version (5s timeout) ---"
        timeout 5 /usr/local/bin/hermes --version 2>&1 || echo "(hermes --version timed out / failed)"
        echo

        echo "--- last 100 lines /var/log/hermes-gateway-stderr.log ---"
        tail -n 100 /var/log/hermes-gateway-stderr.log 2>&1
        echo

        echo "--- last 100 lines /var/log/hermes-gateway-stdout.log ---"
        tail -n 100 /var/log/hermes-gateway-stdout.log 2>&1
        echo

        echo "--- last 50 lines /var/log/hermes-webui-stderr.log ---"
        tail -n 50 /var/log/hermes-webui-stderr.log 2>&1
        echo

        diag_gateways
    } > "$TMP" 2>&1
    mv -f "$TMP" "$OUT" 2>/dev/null
    sleep 5
done
