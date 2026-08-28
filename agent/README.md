# `agent/` — the vendored base image

Everything in this directory is **vendored from `uppr_hermes`**. It is the
generic Hermes-agent-in-a-container base: install Hermes, clone the web UI,
apply per-client branding, seed the client's skills and plugins, run nginx +
supervisor. Nothing in here is RGS+-specific.

What makes this deployment RGS+ lives outside this directory, and that split is
the point:

| | |
|---|---|
| `agent/` | the base. Vendored. Changes only when pulling upstream forward. |
| `clients/rgsplus/` | identity: `SOUL.md`, `brand.env`, `manifest.yaml`. |
| `library/` | the capabilities the manifest selects: skills + tool plugins. |

## Why it's vendored rather than referenced

It used to be a second checkout. `docker-compose.yml` built from
`.build/agent-context`, and `scripts/stage-build-context.sh` produced that
directory by copying a sibling `uppr_hermes` clone and overlaying this repo's
`library/` and `clients/` on top — because the Dockerfile `COPY`s those two
directories from its own context, and Docker cannot read them from a second
repo.

The cost was that a fresh `git clone` of this repo could not build anything.
The staging script exited 1, and no file in the repo said which repository or
commit to get, so the deployment was not reproducible from its own source.

Vendoring the ten files the Dockerfile actually needs removes both problems.
The build context is now the repository root, the Dockerfile is
`agent/Dockerfile`, and `docker compose up -d --build` is the entire build.

## Upstream

```
repo:   https://github.com/Kian1208/uppr_hermes
commit: 243cff148adab146031b4487fb6493530f69e9af
vendored: 2026-08-28
```

Files taken, with the paths they had upstream:

| Here | Upstream |
|---|---|
| `agent/Dockerfile` | `Dockerfile` |
| `agent/start.sh` | `start.sh` |
| `agent/nginx.conf` | `nginx.conf` |
| `agent/supervisord.conf` | `supervisord.conf` |
| `agent/scripts/apply-branding.sh` | `scripts/apply-branding.sh` |
| `agent/scripts/apply-library.sh` | `scripts/apply-library.sh` |
| `agent/scripts/_library.py` | `scripts/_library.py` |
| `agent/scripts/uppr-download.js` | `scripts/uppr-download.js` |
| `agent/scripts/uppr-diag.sh` | `scripts/uppr-diag.sh` |

That is the complete set: those are every path `COPY`ed by the Dockerfile
other than `clients/` and `library/`, which this repo supplies itself.

Deliberately **not** vendored, because the image build never reads them:
`control-panel/`, `benchmark-dashboard/`, `multiuser/`, `tool-server/`,
`recipes/`, `Dockerfile.openwebui`, `Dockerfile.spawner`, upstream's
`bundles/`, and upstream's `library/` and `clients/`.

### Local edits

Only three, all confined to `agent/Dockerfile` (plus two stale path comments
in `nginx.conf` and `start.sh`):

1. `COPY` paths for the base files are prefixed `agent/`, since the context is
   now the repository root rather than the upstream checkout.
2. `ARG UPPR_CLIENT` defaults to `rgsplus` instead of `uppr`. There is no
   `clients/uppr/` here, and `apply-branding.sh` hard-fails on a missing client
   directory — so the upstream default would break a bare `docker build`.
3. The header comment, and the note on `HERMES_AGENT_REF` / `HERMES_WEBUI_REF`
   explaining that this repo has no CI to resolve them.

### Not vendored, and not vendorable: the two real upstreams

`agent/Dockerfile` clones these from the internet at build time:

- `NousResearch/hermes-agent` — via its `install.sh`
- `nesquena/hermes-webui`

So a build still needs network access, and an unpinned build tracks whatever
those projects' default branches say that day. To pin one:

```bash
docker compose build --build-arg HERMES_WEBUI_REF=<sha> rgsplus-agent
```

Vendoring those two is a much larger job than this and buys reproducibility
this deployment has not needed yet.

## Re-syncing with upstream

```bash
UP=../uppr_hermes            # your uppr_hermes checkout
git -C "$UP" pull

# Diff each vendored file against upstream. The Dockerfile will always show
# the three local edits listed above; the other eight should be identical.
for f in start.sh nginx.conf supervisord.conf \
         scripts/apply-branding.sh scripts/apply-library.sh \
         scripts/_library.py scripts/uppr-download.js scripts/uppr-diag.sh; do
    diff -u "agent/$f" "$UP/$f" && echo "same: $f"
done
diff -u agent/Dockerfile "$UP/Dockerfile"
```

Copy over what changed, re-apply the three Dockerfile edits by hand, update the
commit above, and rebuild. If upstream adds a new `COPY` of a file under
`scripts/`, that file has to be vendored too — the build fails loudly if you
miss it.
