#!/usr/bin/env bash
# Apply per-client branding to a hermes-webui install at image build time.
#
# Usage:
#   apply-branding.sh <hermes-webui-dir> <client-dir> <skin-key-output-file>
#
# The client dir must exist; brand.env is sourced if present (missing values
# fall back to safe defaults). theme.css, logo.svg, favicon.ico are all
# optional — anything that exists is applied; anything that doesn't is skipped.

set -euo pipefail

HERMES_WEBUI="${1:?usage: apply-branding.sh <hermes-webui> <client-dir> <skin-key-file>}"
CLIENT_DIR="${2:?usage: apply-branding.sh <hermes-webui> <client-dir> <skin-key-file>}"
SKIN_KEY_FILE="${3:?usage: apply-branding.sh <hermes-webui> <client-dir> <skin-key-file>}"

if [ ! -d "$HERMES_WEBUI" ]; then
    echo "apply-branding: hermes-webui dir not found: $HERMES_WEBUI" >&2
    exit 1
fi
if [ ! -d "$CLIENT_DIR" ]; then
    echo "apply-branding: client dir not found: $CLIENT_DIR" >&2
    exit 1
fi

# ---- Load brand.env if present (every value below has a fallback) ----
if [ -f "$CLIENT_DIR/brand.env" ]; then
    # shellcheck disable=SC1090
    . "$CLIENT_DIR/brand.env"
fi

CLIENT_NAME=$(basename "$CLIENT_DIR")

# Required strings — fall back so the build never breaks on a half-filled brand.env
BRAND_NAME="${BRAND_NAME:-$CLIENT_NAME}"
SKIN_KEY="${SKIN_KEY:-$CLIENT_NAME}"
SKIN_LABEL="${SKIN_LABEL:-$SKIN_KEY}"
SKIN_COLORS="${SKIN_COLORS:-#888,#aaa,#444}"

# All CSS-variable overrides are optional. Empty = inherit hermes-webui default.
: "${FONT_URL:=}"
: "${FONT_UI:=}"

: "${ACCENT_LIGHT:=}"            ; : "${ACCENT_DARK:=}"
: "${ACCENT_HOVER_LIGHT:=}"      ; : "${ACCENT_HOVER_DARK:=}"
: "${ACCENT_BG_LIGHT:=}"         ; : "${ACCENT_BG_DARK:=}"
: "${ACCENT_BG_STRONG_LIGHT:=}"  ; : "${ACCENT_BG_STRONG_DARK:=}"
: "${ACCENT_TEXT_LIGHT:=}"       ; : "${ACCENT_TEXT_DARK:=}"

: "${BG_LIGHT:=}"        ; : "${BG_DARK:=}"
: "${SIDEBAR_LIGHT:=}"   ; : "${SIDEBAR_DARK:=}"
: "${SURFACE_LIGHT:=}"   ; : "${SURFACE_DARK:=}"
: "${CODE_BG_LIGHT:=}"   ; : "${CODE_BG_DARK:=}"
: "${INPUT_BG_LIGHT:=}"  ; : "${INPUT_BG_DARK:=}"
: "${HOVER_BG_LIGHT:=}"  ; : "${HOVER_BG_DARK:=}"

: "${TEXT_LIGHT:=}"      ; : "${TEXT_DARK:=}"
: "${MUTED_LIGHT:=}"     ; : "${MUTED_DARK:=}"
: "${STRONG_LIGHT:=}"    ; : "${STRONG_DARK:=}"

: "${BORDER_LIGHT:=}"    ; : "${BORDER_DARK:=}"

: "${ERROR_LIGHT:=}"     ; : "${ERROR_DARK:=}"
: "${SUCCESS_LIGHT:=}"   ; : "${SUCCESS_DARK:=}"
: "${WARNING_LIGHT:=}"   ; : "${WARNING_DARK:=}"

# ---- 1. Product strings in index.html ----
HTML="$HERMES_WEBUI/static/index.html"
sed -i "s|<title>Hermes</title>|<title>${BRAND_NAME}</title>|g" "$HTML"
sed -i "s|content=\"Hermes\"|content=\"${BRAND_NAME}\"|g" "$HTML"
sed -i "s|id=\"appTitlebarTitle\">Hermes|id=\"appTitlebarTitle\">${BRAND_NAME}|g" "$HTML"
sed -i "s|placeholder=\"Message Hermes…\"|placeholder=\"Message ${BRAND_NAME}…\"|g" "$HTML"
sed -i "s|nous:1}|nous:1,${SKIN_KEY}:1}|g" "$HTML"

# ---- 2. Register skin in boot.js skin picker ----
SKIN_COLORS_JS=$(echo "$SKIN_COLORS" | sed "s/[^,][^,]*/'&'/g")
sed -i "s|{name:'Nous'\\([^}]*\\)}|{name:'Nous'\\1},{name:'${SKIN_LABEL}', colors:[${SKIN_COLORS_JS}]}|" \
    "$HERMES_WEBUI/static/boot.js"

# ---- 3. Generate CSS variable block + optional font import ----
emit() {
    # emit <var-name> <value> — only writes the line if value is non-empty
    [ -n "${2:-}" ] && printf '  --%s: %s;\n' "$1" "$2"
    return 0
}

STYLE="$HERMES_WEBUI/static/style.css"
{
    printf '\n/* === Per-client branding for skin "%s" === */\n' "$SKIN_KEY"
    if [ -n "$FONT_URL" ]; then
        printf "@import url('%s');\n" "$FONT_URL"
    fi
    # Light-mode block: scope to :not(.dark) so it only applies in
    # light/system mode AND so the specificity (0,2,0) matches the
    # `:root:not(.dark) .foo {…}` rules hermes-webui uses for its own
    # light-mode overrides. Without :not(.dark) here our --accent etc.
    # were silently beaten by webui's per-element light-mode CSS.
    printf ':root:not(.dark)[data-skin="%s"] {\n' "$SKIN_KEY"
    emit "font-ui"          "$FONT_UI"
    emit "accent"           "$ACCENT_LIGHT"
    emit "accent-hover"     "$ACCENT_HOVER_LIGHT"
    emit "accent-bg"        "$ACCENT_BG_LIGHT"
    emit "accent-bg-strong" "$ACCENT_BG_STRONG_LIGHT"
    emit "accent-text"      "$ACCENT_TEXT_LIGHT"
    emit "bg"               "$BG_LIGHT"
    emit "sidebar"          "$SIDEBAR_LIGHT"
    emit "surface"          "$SURFACE_LIGHT"
    emit "code-bg"          "$CODE_BG_LIGHT"
    emit "input-bg"         "$INPUT_BG_LIGHT"
    emit "hover-bg"         "$HOVER_BG_LIGHT"
    emit "text"             "$TEXT_LIGHT"
    emit "muted"            "$MUTED_LIGHT"
    emit "strong"           "$STRONG_LIGHT"
    emit "border"           "$BORDER_LIGHT"
    emit "error"            "$ERROR_LIGHT"
    emit "success"          "$SUCCESS_LIGHT"
    emit "warning"          "$WARNING_LIGHT"
    printf '}\n'
    printf ':root.dark[data-skin="%s"] {\n' "$SKIN_KEY"
    emit "accent"           "$ACCENT_DARK"
    emit "accent-hover"     "$ACCENT_HOVER_DARK"
    emit "accent-bg"        "$ACCENT_BG_DARK"
    emit "accent-bg-strong" "$ACCENT_BG_STRONG_DARK"
    emit "accent-text"      "$ACCENT_TEXT_DARK"
    emit "bg"               "$BG_DARK"
    emit "sidebar"          "$SIDEBAR_DARK"
    emit "surface"          "$SURFACE_DARK"
    emit "code-bg"          "$CODE_BG_DARK"
    emit "input-bg"         "$INPUT_BG_DARK"
    emit "hover-bg"         "$HOVER_BG_DARK"
    emit "text"             "$TEXT_DARK"
    emit "muted"            "$MUTED_DARK"
    emit "strong"           "$STRONG_DARK"
    emit "border"           "$BORDER_DARK"
    emit "error"            "$ERROR_DARK"
    emit "success"          "$SUCCESS_DARK"
    emit "warning"          "$WARNING_DARK"
    printf '}\n'
} >> "$STYLE"

# ---- 4. Append optional client theme.css (escape hatch for arbitrary CSS) ----
if [ -f "$CLIENT_DIR/theme.css" ]; then
    printf '\n/* === Client theme.css for skin "%s" === */\n' "$SKIN_KEY" >> "$STYLE"
    cat "$CLIENT_DIR/theme.css" >> "$STYLE"
fi

# ---- 5. Optional asset overrides ----
if [ -f "$CLIENT_DIR/logo.svg" ]; then
    cp "$CLIENT_DIR/logo.svg" "$HERMES_WEBUI/static/logo.svg"
fi
if [ -f "$CLIENT_DIR/favicon.ico" ]; then
    cp "$CLIENT_DIR/favicon.ico" "$HERMES_WEBUI/static/favicon.ico"
fi

# ---- 5b. Optional SOUL.md (per-client agent identity) ----
# Baked to a known location; start.sh seeds it into ~/.hermes/SOUL.md
# on first container start if the user hasn't already written one.
if [ -f "$CLIENT_DIR/SOUL.md" ]; then
    cp "$CLIENT_DIR/SOUL.md" /etc/uppr-soul.md
fi

# ---- 5c. Strip any previously injected UPPR launcher tags ----
# Older images injected a sidebar launcher (uppr-brain.js +
# uppr-launcher.js) here; the feature is gone, so just make sure a
# rebuilt webui doesn't keep stale tags around.
sed -i 's#<script src="/uppr-brain.js"></script><script src="/uppr-launcher.js[^"]*"></script>##g' "$HTML"

# ---- 6. Persist skin key for runtime ----
echo "$SKIN_KEY" > "$SKIN_KEY_FILE"

echo "apply-branding: name='${BRAND_NAME}' skin='${SKIN_KEY}' (client=${CLIENT_NAME})"
