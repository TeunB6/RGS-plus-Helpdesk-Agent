# RGS+ agent image.
#
# VENDORED from uppr_hermes — see agent/README.md for the upstream commit and
# how to re-sync. Do not edit to change RGS+ behaviour; that lives in
# clients/rgsplus/ and library/. Edit here only when pulling upstream forward.
#
# Built from the REPOSITORY ROOT, not from agent/:
#
#     docker compose up -d --build        # context: . , dockerfile: agent/Dockerfile
#
# That is the whole point of the layout. The COPYs below need clients/ and
# library/ (this repo's, at the root) in the same context as the base files
# (under agent/). One context, no staging step — the upstream version of this
# file lived in a separate checkout and needed a copy-and-overlay script to
# bring the two halves together.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Default timezone for the container. The Hermes gateway evaluates
# cron/scheduled-task times against the system clock; the base image is
# UTC, so without this a "daily at 08:00" job fires at 08:00 UTC. start.sh
# materialises this into /etc/localtime at boot and honours an -e TZ=...
# override, so it can be changed per deployment without a rebuild.
ENV TZ=Europe/Amsterdam

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        git \
        python3 \
        python3-venv \
        nginx \
        supervisor \
        ca-certificates \
        tzdata \
        xz-utils \
        bzip2 \
        libatomic1 \
        libstdc++6 \
        ripgrep \
        ffmpeg \
        make \
        g++ \
    && rm -rf /var/lib/apt/lists/*

# libatomic1/libstdc++6: runtime deps of the official Node.js binaries the
# hermes-agent installer downloads (Node >= 26 links libatomic dynamically).
# Without libatomic1 the fresh node binary fails to exec (loader error,
# exit 127) and install.sh dies at its silenced `node --version` check.
# ripgrep/ffmpeg: install.sh tries `apt install` for these AFTER this layer
# wiped the apt lists ("Unable to locate package"); preinstalling gives the
# agent fast file search + TTS audio and silences that step.
# make/g++: node-gyp toolchain. hermes-agent's npm install builds node-pty
# from source when no prebuild exists for the bundled Node's ABI (Node 26
# has none); without a compiler that postinstall fails and install.sh dies.

# This is a headless server image: the hermes-agent desktop app (an npm
# workspace) is never run here, so skip Electron's postinstall binary
# download. It fetches from GitHub releases, which rate-limits the shared
# CI runner IPs — the main npm-install flake — and install.sh runs
# `npm install --silent`, which would swallow the error. ENV (not ARG) so
# a later `hermes update` inside a running container skips it too.
ENV ELECTRON_SKIP_BINARY_DOWNLOAD=1

# ── Upstream pins ──
# The two REAL upstreams — NousResearch/hermes-agent and nesquena/hermes-webui
# — are cloned from the internet at build time, so they are not vendored here
# and the image is only as reproducible as these refs. Pass a resolved commit
# SHA to pin a build:
#
#     docker compose build --build-arg HERMES_WEBUI_REF=<sha> rgsplus-agent
#
# uppr_hermes has CI that resolves these automatically; this repo does not, so
# a plain build tracks whatever those two projects' default branches say today.
#
# Why this matters: without a ref in the layer key, Docker keys the
# install/clone layers purely on the (never-changing) RUN command text,
# so a rebuild reuses the cached layers and the image stays frozen on
# whatever upstream was current when the layer was first built. Folding
# the resolved SHA into the layer means:
#   - upstream unchanged  → identical build-args → cache hit → same
#     image digest (no spurious "update available" downstream),
#   - upstream moved       → new SHA → cache bust → fresh hermes/webui.
# This is what makes the daily scheduled build actually pick up new
# upstream releases. Default "main" keeps a plain `docker build` working.
ARG HERMES_AGENT_REF=main
ARG HERMES_WEBUI_REF=main

# hermes-agent: upstream install.sh always pulls main HEAD. Referencing
# the resolved ref busts this layer when upstream moves.
# On failure: dump npm's debug logs into the build log — install.sh runs
# `npm install --silent`, which otherwise hides the real error entirely.
RUN echo "hermes-agent ref: ${HERMES_AGENT_REF}" \
    && { curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash; } \
    || { echo '=== hermes-agent install.sh failed — npm debug logs ==='; \
         for f in /root/.npm/_logs/*; do echo "--- $f"; tail -n 100 "$f"; done; \
         exit 1; }

# hermes-webui: clone, then pin to the exact ref so the image is
# reproducible and the layer busts precisely when the ref changes.
# CI passes a resolved commit SHA in HERMES_WEBUI_REF; a plain `docker build`
# (or `docker compose --build`) leaves it at the default "main". The upstream
# repo's default branch is not "main", so an unconditional `checkout main`
# fails ("pathspec 'main' did not match"). Only check out when an explicit ref
# was given; otherwise stay on the clone's default branch.
RUN git clone https://github.com/nesquena/hermes-webui.git /hermes-webui \
    && if [ -n "${HERMES_WEBUI_REF}" ] && [ "${HERMES_WEBUI_REF}" != "main" ]; then \
           git -C /hermes-webui checkout "${HERMES_WEBUI_REF}"; \
       else \
           echo "hermes-webui: using default branch ($(git -C /hermes-webui rev-parse --abbrev-ref HEAD))"; \
       fi

WORKDIR /hermes-webui

RUN python3 -m venv /hermes-webui/.venv --without-pip \
    && curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
    && /hermes-webui/.venv/bin/python3 /tmp/get-pip.py \
    && rm -f /tmp/get-pip.py

RUN HERMES_WEBUI_PYTHON=/usr/local/lib/hermes-agent/venv/bin/python3 \
        python3 bootstrap.py || true

# ── RGS+ addition: openpyxl, for the import_check plugin ──
#
# This is the one local addition to the base rather than a path fixup, and it
# is the concrete reason vendoring was worth doing. import_check opens
# customer .xlsx workbooks and needs openpyxl; without it every single
# validation returns
#
#     "ERROR: openpyxl is not installed in the agent image"
#
# which reaches a customer as the bot claiming it cannot read their file. While
# the base lived in another repo this could only be WARNED about at staging
# time (see the deleted scripts/stage-build-context.sh) and fixed there. Now
# that the Dockerfile is here, it is just installed.
#
# Into the hermes-agent venv specifically: both the gateway and the webui run
# from it (`hermes gateway run` and `/hermes-webui/server.py` are both
# /usr/local/lib/hermes-agent/venv/bin/python), and plugin handlers load
# in-process, so this is the interpreter that has to import it.
#
# Installed with uv, NOT pip. That venv is uv-managed and has no pip in it at
# all — `python3 -m pip install` there fails with "No module named pip", and so
# does the system python3 (the image installs python3-venv, not python3-pip).
# The only usable installer is the uv that hermes-agent's install.sh drops at
# /root/.hermes/bin/uv. It is baked into this layer; at RUNTIME the hermes-data
# volume mounts over /root/.hermes and shadows it, which is fine — this runs at
# build time.
#
# Note the venv is Python 3.11 while /hermes-webui/.venv is 3.12, so the
# webui's pip is not a substitute: it would install into the wrong site-packages.
#
# The import check on the second line is the point of the layer — a silent
# failure here is exactly the bug this replaces, so let the build fail loudly.
RUN /root/.hermes/bin/uv pip install \
        --python /usr/local/lib/hermes-agent/venv/bin/python3 \
        openpyxl \
    && /usr/local/lib/hermes-agent/venv/bin/python3 \
        -c "import openpyxl; print('openpyxl ' + openpyxl.__version__)"

# Which clients/<name>/ directory brands and seeds this image. Defaulted to
# rgsplus (upstream defaults to "uppr", which does not exist here) so a bare
# `docker build -f agent/Dockerfile .` works without the build-arg. Compose
# passes it explicitly anyway.
ARG UPPR_CLIENT=rgsplus
COPY clients/ /tmp/clients/
COPY library/ /tmp/library/
COPY agent/scripts/apply-branding.sh /tmp/apply-branding.sh
COPY agent/scripts/apply-library.sh  /tmp/apply-library.sh
COPY agent/scripts/_library.py       /opt/uppr/_library.py
RUN chmod +x /tmp/apply-branding.sh /tmp/apply-library.sh \
    && /tmp/apply-branding.sh /hermes-webui "/tmp/clients/${UPPR_CLIENT}" /etc/uppr-skin-key \
    && /tmp/apply-library.sh  /tmp/library  "/tmp/clients/${UPPR_CLIENT}" /etc/uppr-library \
    && rm -rf /tmp/clients /tmp/library /tmp/apply-branding.sh /tmp/apply-library.sh

# UPPR: embedded-download fix (see agent/scripts/uppr-download.js). A file
# download that NAVIGATES leaves the iframe's cookie partition and loses
# the Partitioned embed cookie, so it can't authenticate and the user is
# bounced out of the frame. This client script turns download clicks into
# same-origin fetch()->Blob saves, which keep the cookie and never
# navigate.
#
# The file is served by nginx at /uppr-download.js (see nginx.conf) rather
# than by hermes-webui, because hermes-webui does not serve arbitrary
# root-level static files. The <script> tag is injected into the webui's
# index.html here; the RUN asserts it landed so a bad build fails loudly.
COPY agent/scripts/uppr-download.js /var/uppr/uppr-download.js
RUN if grep -qiF '</body>' /hermes-webui/static/index.html; then \
        sed -i 's#</[bB][oO][dD][yY]>#<script src="/uppr-download.js"></script></body>#' /hermes-webui/static/index.html; \
    else \
        printf '\n<script src="/uppr-download.js"></script>\n' >> /hermes-webui/static/index.html; \
    fi \
    && grep -qF '/uppr-download.js' /hermes-webui/static/index.html

COPY agent/nginx.conf /etc/nginx/nginx.conf
# Empty default for the frame-ancestors snippet that nginx.conf includes.
# start.sh regenerates it at boot from EMBED_FRAME_ANCESTORS; this seed
# keeps the `include` target present so the config is valid pre-boot.
RUN touch /etc/nginx/uppr-frame.conf
COPY agent/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY agent/start.sh /start.sh
COPY agent/scripts/uppr-diag.sh /usr/local/bin/uppr-diag.sh
# /var/uppr holds runtime-written files nginx serves (diag.txt).
RUN mkdir -p /var/uppr
RUN chmod +x /start.sh /usr/local/bin/uppr-diag.sh

# Build-info stamp so /uppr-diag.txt can prove which image is running.
# CI passes --build-arg BUILD_INFO with the commit SHA + UTC timestamp.
ARG BUILD_INFO="dev"
RUN echo "${BUILD_INFO}" > /etc/uppr-build-info.txt

EXPOSE 80

CMD ["/start.sh"]
