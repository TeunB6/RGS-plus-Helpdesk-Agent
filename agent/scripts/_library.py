#!/usr/bin/env python3
"""Library staging + seeding for multi-tenant Hermes builds.

Two subcommands:

  stage  - build time: read clients/<name>/manifest.yaml and copy the
           selected library/<kind>/<item> entries into a staging dir
           that ends up baked into the image.

  seed   - first/subsequent container start: copy/merge the staging
           dir into ~/.hermes/ (which lives in the persistent volume).

Both are no-ops when there is nothing to do and never raise on missing
items. Library-OWNED content (skills, plugins, and a profile's
SOUL.md / description.txt / config.yaml skeleton) is refreshed in place
on every seed, so updates shipped in the git library always reach
deployed agents. Runtime STATE is never touched: the main and
per-profile `.env` (secrets), the kanban boards, durable / scheduled
(cron) tasks, and gateway_state.json all survive across restarts and
redeploys -- as do entire profiles a user created at runtime, since the
seed only ever refreshes the profiles the library actually ships.

Credential scoping: shared infra keys (LLM, search APIs, ...) replicate
from the main .env into every profile. Channel/identity credentials
(_CHANNEL_KEY_RE: TELEGRAM_*, DISCORD_*, ..., *_BOT_TOKEN,
*_WEBHOOK_URL) never replicate -- a bot token binds one external
identity to one gateway. Per-profile delivery uses BASE__SUFFIX keys
(_SCOPED_KEY_RE), where SUFFIX is the profile dir name uppercased with
non-alphanumerics as "_"; hydration strips the suffix and upserts the
base key into exactly that profile's .env, overwriting so rotation
works. Keep the channel pattern list in sync with the env scrub in
start.sh.
"""

from __future__ import annotations

import argparse
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write(
        "library helper: PyYAML is required. Install python3-yaml or "
        "invoke this script with the Hermes venv python "
        "(/usr/local/lib/hermes-agent/venv/bin/python3).\n"
    )
    sys.exit(2)


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _items(manifest: dict, key: str) -> list[str]:
    raw = manifest.get(key)
    if not raw:
        return []
    return [str(x) for x in raw if x]


def _resolve_dir(root: Path, name: str) -> Path | None:
    """Find a library item directory by name.

    Looks first at `<root>/<name>` (flat layout), then scans one level of
    subdirectories `<root>/<category>/<name>` (vertical-grouped layout).
    Returns the first match or None. Names are still globally unique --
    the subfolder is purely source-tree organisation; staging flattens
    so Hermes sees the same top-level names it always has.
    """
    flat = root / name
    if flat.is_dir():
        return flat
    if not root.is_dir():
        return None
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        candidate = sub / name
        if candidate.is_dir():
            return candidate
    return None


def _resolve_file(root: Path, name: str, suffix: str = ".yaml") -> Path | None:
    """Same as _resolve_dir but for single-file artifacts (e.g. MCP fragments)."""
    flat = root / f"{name}{suffix}"
    if flat.is_file():
        return flat
    if not root.is_dir():
        return None
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        candidate = sub / f"{name}{suffix}"
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# stage (build time)
# ---------------------------------------------------------------------------

def cmd_stage(args: argparse.Namespace) -> int:
    library = Path(args.library)
    manifest_path = Path(args.manifest)
    staging = Path(args.staging)

    for sub in ("skills", "mcp", "profiles", "tools"):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    if not manifest_path.is_file():
        print(f"stage-library: no manifest at {manifest_path}, nothing to stage")
        return 0

    manifest = _load_yaml(manifest_path)
    staged_any = False

    for name in _items(manifest, "skills"):
        src = _resolve_dir(library / "skills", name)
        if not src:
            print(f"  WARN: skill '{name}' not found under {library/'skills'}, skipping", file=sys.stderr)
            continue
        shutil.copytree(src, staging / "skills" / name, dirs_exist_ok=True)
        print(f"  staged skill: {name}")
        staged_any = True

    for name in _items(manifest, "mcp"):
        src = _resolve_file(library / "mcp", name, ".yaml")
        if not src:
            print(f"  WARN: mcp '{name}' not found under {library/'mcp'}, skipping", file=sys.stderr)
            continue
        shutil.copy2(src, staging / "mcp" / f"{name}.yaml")
        print(f"  staged mcp: {name}")
        staged_any = True

    for name in _items(manifest, "profiles"):
        src = _resolve_dir(library / "profiles", name)
        if not src:
            print(f"  WARN: profile '{name}' not found under {library/'profiles'}, skipping", file=sys.stderr)
            continue
        shutil.copytree(src, staging / "profiles" / name, dirs_exist_ok=True)
        print(f"  staged profile: {name}")
        staged_any = True

    for name in _items(manifest, "tools"):
        src = _resolve_dir(library / "tools", name)
        if not src:
            print(f"  WARN: tool '{name}' not found under {library/'tools'}, skipping", file=sys.stderr)
            continue
        shutil.copytree(src, staging / "tools" / name, dirs_exist_ok=True)
        print(f"  staged plugin: {name}")
        staged_any = True

    # Stash a minimal runtime metadata file for the seed step. The main
    # agent (~/.hermes itself) is always the default profile and acts as
    # orchestrator; bundle profiles are specialists it dispatches to via
    # delegate_task or kanban_create. We do NOT carry default_profile
    # through to seed -- writing a `.default_profile` sentinel would
    # demote the main agent.
    meta = {
        "specialists": _items(manifest, "profiles"),
        "secrets": _items(manifest, "secrets"),
        # bundle-only: the tenant gets ONLY the bundle's skills/tools/mcp;
        # hermes' built-in toolsets are disabled at seed time (see
        # _apply_bundle_only_toolsets). Also switchable at runtime via the
        # UPPR_BUNDLE_ONLY env var (that's the uppr_cloud delivery path).
        "bundle_only": bool(manifest.get("bundle_only")),
    }
    with (staging / "manifest.yaml").open("w") as f:
        yaml.safe_dump(meta, f, sort_keys=False)

    if not staged_any:
        print("stage-library: manifest had no resolvable items, staging dir left empty")
    return 0


# ---------------------------------------------------------------------------
# seed (runtime, first start)
# ---------------------------------------------------------------------------

_VAR_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_ENV_KV_RE = re.compile(r"^([A-Z_][A-Z0-9_]*)=(.*)$")

# Profile-scoped env keys: BASE_KEY__<PROFILE_SUFFIX> (double underscore).
# The suffix is the profile dir name normalised via _norm_profile()
# (non-alphanumerics -> "_", uppercased), e.g.
# TELEGRAM_BOT_TOKEN__SALES_RESEARCHER routes TELEGRAM_BOT_TOKEN into
# profiles/sales-researcher/.env. uppr_cloud delivers per-profile
# secrets in this form through the tenant env file; hydration strips
# the suffix and upserts the base key into exactly one profile's .env.
_SCOPED_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*?)__([A-Z0-9][A-Z0-9_]*)$")

# Identity/channel credentials -- a bot token binds ONE external
# identity (e.g. one Telegram bot) to ONE gateway. Replicating it to
# every profile makes all gateways poll the same bot (Telegram answers
# getUpdates with 409 and a random gateway wins), so unlike shared
# infra keys (LLM, search APIs) these are NEVER blanket-copied or
# merged from the main .env into profiles. Keep this pattern list in
# sync with the channel-env scrub in start.sh (gateway_runner).
_CHANNEL_KEY_RE = re.compile(
    r"^(TELEGRAM_|DISCORD_|WHATSAPP_|SIGNAL_|SLACK_)"
    r"|(_BOT_TOKEN|_WEBHOOK_URL)$"
)


def _norm_profile(name: str) -> str:
    """Normalise a profile dir name to its scoped-env-key suffix."""
    return re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def _is_scoped_key(key: str) -> bool:
    return bool(_SCOPED_KEY_RE.match(key))


def _is_channel_key(key: str) -> bool:
    return bool(_CHANNEL_KEY_RE.search(key))


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser for a dotenv file. Ignores comments
    and blank lines. Quotes are kept verbatim -- this is a sync helper
    between two dotenv files we control, not a general parser."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_KV_RE.match(line)
        if not m:
            continue
        out[m.group(1)] = m.group(2)
    return out


def _merge_env_keys(src: Path, dst: Path, exclude=None) -> int:
    """Append keys from src .env into dst .env when dst doesn't already
    have them. Returns the number of keys added. Idempotent: nothing
    is overwritten, only missing keys are appended. `exclude` is an
    optional predicate on the key name; matching keys are never merged
    (used to keep channel credentials and scoped BASE__SUFFIX keys out
    of profile .env files)."""
    src_pairs = _parse_env_file(src)
    if not src_pairs:
        return 0
    dst_pairs = _parse_env_file(dst)
    missing = {
        k: v for k, v in src_pairs.items()
        if k not in dst_pairs and not (exclude and exclude(k))
    }
    if not missing:
        return 0
    with dst.open("a") as f:
        if dst.stat().st_size > 0:
            f.write("\n")
        for k, v in missing.items():
            f.write(f"{k}={v}\n")
    return len(missing)


def _upsert_env_line(path: Path, key: str, value: str) -> bool:
    """Write KEY=value into a dotenv file, replacing an existing line
    for the same key (scoped delivery is authoritative so a rotated
    token actually takes effect). Returns True when the file changed.
    Same read-modify-write shape as _persist_bundle_secrets."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        try:
            path.chmod(0o600)
        except OSError:
            pass
    original = path.read_text().splitlines()
    lines = list(original)
    new_line = f"{key}={value}"
    replaced = False
    for i, line in enumerate(lines):
        m = _ENV_KV_RE.match(line.strip())
        if m and m.group(1) == key:
            lines[i] = new_line
            replaced = True
            break
    if not replaced:
        lines.append(new_line)
    if lines == original:
        return False
    path.write_text("\n".join(lines) + ("\n" if lines else ""))
    return True


def _remove_env_lines(path: Path, predicate) -> list[str]:
    """Drop KEY=VALUE lines for which predicate(key, value) is true.
    Comments and non-KV lines are kept. Returns the removed keys."""
    if not path.is_file():
        return []
    original = path.read_text().splitlines()
    kept: list[str] = []
    removed: list[str] = []
    for line in original:
        m = _ENV_KV_RE.match(line.strip())
        if m and predicate(m.group(1), m.group(2)):
            removed.append(m.group(1))
            continue
        kept.append(line)
    if removed:
        path.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed


def _expand_env(value):
    """Recursively substitute ${VAR} references from os.environ.

    Unset OR empty vars are left as-is. Treating an empty env var as
    "no value" prevents a missing secret from silently writing an
    empty string into a config (e.g. an Authorization header would
    become "Bearer " and produce confusing runtime errors). When the
    placeholder survives, downstream code or Hermes' runtime can
    surface a clearer error or fall back to the profile's .env.
    """
    if isinstance(value, str):
        def _sub(m):
            resolved = os.environ.get(m.group(1))
            return resolved if resolved else m.group(0)
        return _VAR_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _seed_dirs(src: Path, dst: Path, label: str, *, overwrite: bool = False) -> int:
    """Copy library item dirs into the volume.

    Items that don't exist yet are always seeded. For items that already
    exist the behaviour depends on `overwrite`:

      * overwrite=False (default): skip -- preserve whatever is in the
        volume (used where the item dir may carry runtime state).
      * overwrite=True: replace the dir wholesale from the library, so
        git-shipped updates to a fully library-owned item (e.g. a skill,
        which carries no runtime state) always reach deployed agents.

    Returns the number of items seeded OR refreshed.
    """
    if not src.is_dir():
        return 0
    items = [p for p in src.iterdir() if p.is_dir()]
    if not items:
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for item in items:
        target = dst / item.name
        if target.exists():
            if not overwrite:
                print(f"  {label} '{item.name}' already at {target}, skipping (re-seed by deleting target)")
                continue
            shutil.rmtree(target)
            shutil.copytree(item, target)
            print(f"  refreshed {label}: {item.name}")
            seeded += 1
            continue
        shutil.copytree(item, target)
        print(f"  seeded {label}: {item.name}")
        seeded += 1
    return seeded


# Files inside a profile dir that the library OWNS. They are refreshed
# from the library on every seed so updates to the git-shipped persona /
# description / config skeleton always reach deployed agents. Everything
# else in the profile home is runtime STATE that the seed must never
# touch: the per-profile `.env` (secrets), the kanban board, durable /
# scheduled (cron) tasks, and gateway_state.json. Because we refresh
# these files in place -- and never delete the profile dir -- a profile
# a user created at runtime and the cron jobs any specialist accumulated
# both survive container restarts and redeploys.
_PROFILE_LIBRARY_FILES = ("SOUL.md", "description.txt", "config.yaml")


def _seed_profiles(src: Path, dst: Path) -> int:
    """Seed/refresh specialist profile dirs.

    A brand-new profile is copied wholesale. An existing profile keeps
    all of its runtime state (.env, kanban board, durable/cron tasks,
    gateway_state.json) and only has its library-owned files
    (_PROFILE_LIBRARY_FILES) refreshed in place. config.yaml is reset to
    the library skeleton here; cmd_seed re-runs
    _hydrate_specialist_profile immediately after, which re-adds the
    model block, the self-scoped kanban block and inherited mcp_servers,
    so the effective config is regenerated from library + main config on
    every seed.

    Profiles the user created at runtime are not present in the library
    staging dir, so this never iterates over them -- they are left
    entirely untouched (and are no longer wiped by uppr_cloud either).

    Returns the number of profiles newly seeded (refreshes are not
    counted as "new").
    """
    if not src.is_dir():
        return 0
    items = [p for p in src.iterdir() if p.is_dir()]
    if not items:
        return 0
    dst.mkdir(parents=True, exist_ok=True)
    seeded = 0
    for item in items:
        target = dst / item.name
        if not target.exists():
            shutil.copytree(item, target)
            print(f"  seeded profile: {item.name}")
            seeded += 1
            continue
        refreshed = []
        for fname in _PROFILE_LIBRARY_FILES:
            src_file = item / fname
            if src_file.is_file():
                shutil.copy2(src_file, target / fname)
                refreshed.append(fname)
        if refreshed:
            print(f"  refreshed profile library files for '{item.name}': "
                  f"{', '.join(refreshed)} (.env + board/cron state preserved)")
    return seeded


# Platform-managed MCP servers injected by uppr_cloud (Pipedream
# Connect). Unlike user/bundle MCP servers, these are NOT
# user-editable, so we RECONCILE them in place on every seed instead of
# skipping when present. That's what lets a fragment fix (e.g. adding
# transport: sse), a rotated bearer token, or env that was missing on a
# previous boot (PIPEDREAM_MCP_* is only injected once the tenant's
# email backfill has run) reach an agent whose config.yaml already has
# the old entry — the normal skip-if-present behaviour froze the
# first-seeded version forever.
#
# Prefix-managed families. Pipedream ships one fragment per curated app
# (pipedream-gmail, pipedream-slack, ...); a static name set would go
# stale every time uppr_cloud's curated app list changes, so anything
# under the prefix is managed. Prefix-managed entries are additionally
# PRUNED when their fragment stops shipping (see _seed_mcp).
_MANAGED_MCP_PREFIXES = ("pipedream-",)


def _is_managed_mcp(name: str) -> bool:
    return str(name).startswith(_MANAGED_MCP_PREFIXES)


def _has_unresolved_vars(value) -> bool:
    """True when a fragment value (recursively) still contains ${VAR}
    placeholders _expand_env couldn't resolve — i.e. the backing env var
    was absent or empty on this boot."""
    if isinstance(value, str):
        return bool(_VAR_RE.search(value))
    if isinstance(value, dict):
        return any(_has_unresolved_vars(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_unresolved_vars(v) for v in value)
    return False


def _seed_mcp(src: Path, config_path: Path) -> int:
    if not src.is_dir():
        return 0
    fragments = sorted(src.glob("*.yaml"))
    if not fragments:
        return 0

    config = _load_yaml(config_path)
    mcp_servers = config.setdefault("mcp_servers", {})
    changed = 0
    for frag in fragments:
        name = frag.stem
        desired = _expand_env(_load_yaml(frag))
        if name in mcp_servers:
            if _is_managed_mcp(name) and mcp_servers[name] != desired:
                # Never clobber a resolved entry with one that still has
                # unresolved ${VAR} placeholders: the backing env being
                # absent on THIS boot (e.g. uppr_cloud skipped injection
                # for one poll) must not break a previously-good config.
                if _has_unresolved_vars(desired) and not _has_unresolved_vars(
                    mcp_servers[name]
                ):
                    print(f"  managed mcp '{name}' fragment has unresolved "
                          f"${{VAR}}, keeping existing resolved entry")
                    continue
                mcp_servers[name] = desired
                print(f"  reconciled managed mcp: {name}")
                changed += 1
            else:
                print(f"  mcp '{name}' already in config.yaml, skipping")
            continue
        mcp_servers[name] = desired
        print(f"  seeded mcp: {name}")
        changed += 1

    # Prune prefix-managed entries whose fragment no longer ships:
    # uppr_cloud dropping an app from the curated Pipedream set must
    # remove the connection, or the agent keeps dialing a proxy route
    # that now 404s. Guarded on at least one fragment of the family
    # being present, so a degraded tarball (uppr_cloud falls back to the
    # plain manifest when the injected build fails, shipping ZERO
    # pipedream fragments) doesn't wipe a working config.
    staged = {frag.stem for frag in fragments}
    for prefix in _MANAGED_MCP_PREFIXES:
        if not any(n.startswith(prefix) for n in staged):
            continue
        stale = [
            n for n in list(mcp_servers)
            if str(n).startswith(prefix) and n not in staged
        ]
        for name in stale:
            del mcp_servers[name]
            print(f"  pruned managed mcp: {name} (fragment no longer shipped)")
            changed += 1

    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
    return changed


def _persist_bundle_secrets(meta_path: Path, env_path: Path) -> int:
    """Upsert every secret declared in the staged bundle manifest into
    the main .env file -- if and only if the value is currently set in
    the container environment.

    Behaviour:
      * Only secret names listed in the bundle manifest are touched --
        we never dump the full container env into .env. The one
        exception: profile-scoped BASE__SUFFIX keys (see
        _SCOPED_KEY_RE) are always persisted regardless of the
        manifest, because that namespace is by construction
        uppr-managed. Suffixed names are inert for the main gateway
        (the binary only reads base names); persisting them here means
        a runtime hydrate -- long after boot, or after the container
        env file changed -- still sees the routed per-profile values.
      * An empty / unset env var is skipped (no `KEY=` lines written),
        so a missing secret stays visibly absent from .env instead of
        being silently zeroed out.
      * Existing values are overwritten on each run so rotating the
        secret via `docker run -e` actually takes effect. This is
        intentional and matches the OPENROUTER_API_KEY upsert pattern
        in start.sh.

    Returns the number of secrets persisted in this run.
    """
    meta = _load_yaml(meta_path)
    secrets = [str(n) for n in (meta.get("secrets") or [])]
    scoped = sorted(k for k in os.environ if _is_scoped_key(k))
    secrets += [k for k in scoped if k not in secrets]
    if not secrets:
        return 0

    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.touch()
        try:
            env_path.chmod(0o600)
        except OSError:
            pass

    original = env_path.read_text().splitlines()
    lines = list(original)

    written = 0
    for name in secrets:
        key = str(name)
        value = os.environ.get(key)
        if not value:
            continue
        new_line = f"{key}={value}"
        replaced = False
        for i, line in enumerate(lines):
            m = _ENV_KV_RE.match(line.strip())
            if m and m.group(1) == key:
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        written += 1

    if lines != original:
        env_path.write_text("\n".join(lines) + ("\n" if lines else ""))

    return written


def _seed_kanban_orchestrator(meta_path: Path, hermes_home: Path) -> None:
    """Wire the main agent as the kanban orchestrator on first seed.

    With specialist profiles installed, the main agent (the default
    Hermes home, with the client SOUL.md as identity) needs to know it
    owns decomposition + routing. We set `kanban.orchestrator_profile`
    to the empty string -- the kanban dispatcher interprets that as
    "fall back to the active default profile", which is exactly the
    main agent. Auto-decompose is left on so triage tasks fan out
    without manual prodding.

    Idempotent: keys already present in config.yaml are left alone so
    operator edits via the webui survive.
    """
    meta = _load_yaml(meta_path)
    specialists = meta.get("specialists") or []
    if not specialists:
        return

    config_path = hermes_home / "config.yaml"
    config = _load_yaml(config_path)
    kanban = config.setdefault("kanban", {})

    changed = False
    if "orchestrator_profile" not in kanban:
        kanban["orchestrator_profile"] = ""
        changed = True
    if "auto_decompose" not in kanban:
        kanban["auto_decompose"] = True
        changed = True

    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
        print(f"  wired kanban orchestrator: main agent routes to "
              f"{len(specialists)} specialist(s)")


# ── bundle-only mode ────────────────────────────────────────────────────
#
# "Bundle-only" tenants get ONLY the capabilities their bundle selected
# (library skills, plugin toolsets, mcp-<server> toolsets) — hermes'
# built-in toolsets are disabled via `agent.disabled_toolsets` in
# config.yaml, the upstream-documented global kill switch (it applies
# after per-platform tool config, so a listed toolset is always removed).
#
# The list below enumerates the built-ins to disable. Deliberately NOT
# disabled: skills (skill loading/browsing), cronjob (scheduled runs),
# clarify, todo, memory, session_search, and context_engine — the
# minimal core a bundle workflow needs to operate. Plugin and MCP
# toolsets are never in this list, so bundle capabilities are untouched.
BUNDLE_ONLY_DISABLED_TOOLSETS = [
    "browser",
    "code_execution",
    "coding",          # composite: file+terminal+web+...
    "computer_use",
    "debugging",       # composite: file+terminal+web
    "delegation",
    "discord",
    "discord_admin",
    "feishu_doc",
    "feishu_drive",
    "file",
    "homeassistant",
    "image_gen",
    "kanban",
    "project",
    "safe",            # composite: read-only research + media gen
    "search",
    "spotify",
    "terminal",
    "tts",
    "video",
    "video_gen",
    "vision",
    "web",
    "x_search",
    "yuanbao",
]

# With specialist profiles installed the orchestrator NEEDS delegation
# (delegate_task) and kanban (kanban_create) to route work — keep them.
BUNDLE_ONLY_KEEP_WITH_SPECIALISTS = {"delegation", "kanban"}

# Records which disabled_toolsets entries WE added, so toggling
# bundle-only off later removes exactly those and never an entry the
# operator disabled by hand via the webui.
_MANAGED_TOOLSETS_FILE = ".uppr-managed-toolsets.yaml"

# Hermes' own kill switch for its bundled skill catalog (claude-code,
# comfyui, computer-use, ...). Present => the gateway does NOT copy/re-copy
# its bundled skills into ~/.hermes/skills on start or `hermes update`.
# Our library seed (the bundle's skills) is independent and unaffected —
# so with this marker the agent's skills are EXACTLY the bundle's.
_NO_BUNDLED_SKILLS_MARKER = ".no-bundled-skills"

_TRUTHY = ("1", "true", "yes", "on")


def _bundle_only_requested(meta: dict) -> bool:
    env_flag = (os.environ.get("UPPR_BUNDLE_ONLY") or "").strip().lower()
    if env_flag in _TRUTHY:
        return True
    if env_flag in ("0", "false", "no", "off"):
        return False
    return bool(meta.get("bundle_only"))


def _apply_bundle_only_toolsets(meta_path: Path, hermes_home: Path) -> None:
    """Reconcile agent.disabled_toolsets in ~/.hermes/config.yaml with the
    bundle-only flag (staging meta `bundle_only: true`, or the
    UPPR_BUNDLE_ONLY env var — env wins, so uppr_cloud can toggle a
    tenant without a rebuild). Idempotent, and operator-added entries in
    disabled_toolsets are always preserved: we only ever add/remove the
    entries recorded in our own managed-state file.
    """
    meta = _load_yaml(meta_path)
    desired: list[str] = []
    if _bundle_only_requested(meta):
        desired = list(BUNDLE_ONLY_DISABLED_TOOLSETS)
        if meta.get("specialists"):
            desired = [t for t in desired
                       if t not in BUNDLE_ONLY_KEEP_WITH_SPECIALISTS]

    state_path = hermes_home / _MANAGED_TOOLSETS_FILE
    previously = set(_load_yaml(state_path).get("managed") or [])
    if not desired and not previously:
        return  # feature never used on this tenant — leave config alone

    config_path = hermes_home / "config.yaml"
    config = _load_yaml(config_path)
    agent = config.setdefault("agent", {})
    current: list[str] = list(agent.get("disabled_toolsets") or [])

    # Drop entries we managed before that are no longer desired; keep
    # everything else (operator edits). Then add what's desired now.
    kept = [t for t in current if t in desired or t not in previously]
    added = [t for t in desired if t not in kept]
    new = kept + added

    if new == current and previously == set(desired):
        return

    if new:
        agent["disabled_toolsets"] = new
    else:
        agent.pop("disabled_toolsets", None)
        if not agent:
            config.pop("agent", None)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    with state_path.open("w") as f:
        yaml.safe_dump({"managed": sorted(desired)}, f, sort_keys=False)
    if desired:
        print(f"  bundle-only: {len(desired)} built-in toolset(s) disabled "
              f"(agent.disabled_toolsets)")
    else:
        print("  bundle-only: off — managed toolset disables removed")


# Candidate locations of hermes' bundled-skill SOURCE dir (where the
# installer copies bundled skills FROM). Root/FHS install (our Docker
# image) is the first; the non-root default and an env override follow.
# Enumerating this dir at runtime gives the exact, version-matched set of
# skills hermes ships — no hardcoded list to drift when upstream changes.
def _hermes_bundled_skills_dir() -> Path | None:
    candidates = []
    env_dir = (os.environ.get("HERMES_INSTALL_DIR") or "").strip()
    if env_dir:
        candidates.append(Path(env_dir) / "skills")
    candidates.append(Path("/usr/local/lib/hermes-agent/skills"))
    candidates.append(Path.home() / ".hermes" / "hermes-agent" / "skills")
    for c in candidates:
        if c.is_dir():
            return c
    return None


def _prune_bundled_skills(hermes_home: Path, library_skill_names: set[str]) -> int:
    """Remove hermes' bundled skills already copied into ~/.hermes/skills.

    A skill is removed only when it is BOTH present in hermes' bundled-skill
    source dir (so it is definitely hermes-shipped, not user-created) AND
    not selected by this client's bundle (library_skill_names). Library and
    user-created skills are therefore never touched. Returns the count
    removed. Reversible: clearing the marker lets `hermes update` re-sync
    the bundled skills from source.
    """
    src = _hermes_bundled_skills_dir()
    installed = hermes_home / "skills"
    if src is None or not installed.is_dir():
        return 0
    bundled_names = {p.name for p in src.iterdir() if p.is_dir()}
    removed = 0
    for name in bundled_names:
        if name in library_skill_names:
            continue  # our bundle ships a skill of this name — keep it
        target = installed / name
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
            removed += 1
    if removed:
        print(f"  bundle-only: removed {removed} already-seeded hermes "
              f"bundled skill(s) from ~/.hermes/skills")
    return removed


def _apply_bundle_only_skills(meta_path: Path, hermes_home: Path,
                              staging: Path | None = None) -> None:
    """Reconcile hermes' bundled skills with the bundle-only flag.

    When bundle-only is on: write the `.no-bundled-skills` marker (stops
    hermes seeding its bundled catalog going forward) AND prune any bundled
    skills a previous run already copied into ~/.hermes/skills — identified
    positively against hermes' bundled-skill source dir, so the bundle's
    own library skills and user-created skills are never removed. The agent
    is then left with EXACTLY the bundle's skills, on a fresh home and on a
    long-running one alike.

    When off: remove the marker so bundled skills re-sync on the next
    `hermes update` / rebuild.
    """
    meta = _load_yaml(meta_path)
    marker = hermes_home / _NO_BUNDLED_SKILLS_MARKER
    if _bundle_only_requested(meta):
        if not marker.exists():
            hermes_home.mkdir(parents=True, exist_ok=True)
            marker.write_text(
                "Managed by uppr bundle-only mode: hermes bundled skills are "
                "suppressed so the agent has only its bundle's skills.\n"
            )
            print("  bundle-only: hermes bundled skills suppressed "
                  "(.no-bundled-skills)")
        # Library skills we ship (keep list) come from the staging dir.
        library_names: set[str] = set()
        skills_src = (staging / "skills") if staging else None
        if skills_src and skills_src.is_dir():
            library_names = {p.name for p in skills_src.iterdir() if p.is_dir()}
        _prune_bundled_skills(hermes_home, library_names)
    elif marker.exists():
        marker.unlink()
        print("  bundle-only: off — hermes bundled skills re-enabled "
              "(re-sync on next hermes update)")


def _is_importable(pip_spec: str) -> bool:
    """Best-effort check whether a pip_dependencies entry (e.g.
    'cloudinary>=1.36,<2.0') is already importable. Derives the import
    name by stripping the version spec and assumes it matches the
    package name -- true for every dependency currently declared in this
    repo (cloudinary, resend). A plugin whose import name differs from
    its package name would just get redundantly reinstalled on every
    seed -- harmless, not a correctness bug.
    """
    name = re.split(r"[<>=!\[; ]", pip_spec, 1)[0].strip()
    if not name:
        return True
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _ensure_pip_dependencies(manifest: dict, plugin_name: str) -> None:
    """Best-effort: pip-install any pip_dependencies declared in a
    plugin's manifest that aren't already importable.

    sys.executable is the right interpreter here: start.sh always
    invokes this script with the same hermes-agent venv python that
    later loads and runs the seeded plugins, so installing into
    sys.executable puts the package where the plugin will actually look
    for it. Never raises -- a failed/skipped install just means the
    plugin's own handler reports a configuration error when a tool call
    needs the package, exactly as if it were never declared.
    """
    deps = manifest.get("pip_dependencies") or []
    missing = [spec for spec in deps if not _is_importable(spec)]
    if not missing:
        return
    print(f"  plugin '{plugin_name}' needs: {', '.join(missing)} -- installing")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing],
            check=True, timeout=120,
        )
        print(f"  installed pip dependencies for '{plugin_name}'")
    except Exception as exc:
        print(f"  WARNING: could not install pip dependencies for '{plugin_name}' ({missing}): {exc}")


def _seed_plugins(src: Path, hermes_home: Path) -> int:
    """Copy plugin dirs into ~/.hermes/plugins/ AND add their names to
    config.yaml's plugins.enabled list (plugins are opt-in by default
    in Hermes; without this step the dir is on disk but inert).

    Flat plugins only -- a plugin dir is one that contains plugin.yaml.
    Sub-category plugins (image_gen/, platforms/, memory/, etc.) are
    not handled here yet; they need a different layout and the
    enable-key is path-derived rather than dir-name.
    """
    if not src.is_dir():
        return 0
    candidates = [p for p in src.iterdir() if p.is_dir()]
    if not candidates:
        return 0

    plugins_dir = hermes_home / "plugins"
    config_path = hermes_home / "config.yaml"
    config = _load_yaml(config_path)
    plugins_block = config.setdefault("plugins", {})
    enabled = plugins_block.setdefault("enabled", [])

    added = 0
    config_changed = False
    for src_plugin in candidates:
        manifest_path = src_plugin / "plugin.yaml"
        if not manifest_path.is_file():
            print(f"  plugin '{src_plugin.name}' has no plugin.yaml, skipping (sub-category plugins not yet supported)")
            continue

        target = plugins_dir / src_plugin.name
        already_existed = target.exists()

        manifest = _load_yaml(manifest_path)
        enable_key = manifest.get("name") or src_plugin.name
        _ensure_pip_dependencies(manifest, enable_key)

        plugins_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_plugin, target, dirs_exist_ok=True)
        if already_existed:
            print(f"  updated plugin: {src_plugin.name}")
        else:
            print(f"  seeded plugin: {src_plugin.name}")

        if enable_key not in enabled:
            enabled.append(enable_key)
            config_changed = True
            print(f"  enabled plugin: {enable_key}")
        added += 1

    if config_changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.safe_dump(config, f, sort_keys=False)
    return added


# Org-wide capabilities every agent on the deployment should have,
# main profile AND every specialist. When the deployment's library
# carries these (uppr_cloud injects the pipedream items whenever the
# platform Pipedream credentials are configured), profile hydration
# copies the skills into each specialist's skills/ dir and inherits the
# matching mcp_servers entries from the main config — overriding the
# usual "profiles do not inherit mcp_servers" scoping rule, because the
# user's own Pipedream app connections are deployment-global
# capabilities every agent persona should share. On deployments
# without them these names simply don't exist in the library/main
# config and all of this no-ops.
#
# The MCP side of "deployment-global" is _is_managed_mcp (pipedream-*)
# — the same predicate _seed_mcp reconciles by, so what's
# platform-managed at the root is exactly what every specialist
# inherits.
GLOBAL_DEFAULT_SKILLS = ("mcp-oauth-flow", "pipedream")


def _hydrate_specialist_profile(
    profile_dir: Path,
    main_env: Path,
    main_config: Path,
    global_skills: Path,
) -> None:
    """Make a freshly-seeded specialist profile actually usable.

    Hermes profiles are self-contained: each one needs its own `.env`
    (LLM + tool API keys), its own `model:` block in config.yaml, and
    its own `skills/` subdir. The library ships the SOUL + a partial
    config.yaml (skills list + plugin enablement); we fill in the rest
    on first seed by inheriting from the main profile.

    All operations are idempotent. The per-profile `.env` is preserved
    (only newly-added bundle secret keys are merged in -- existing values,
    including operator edits, are never overwritten). config.yaml and the
    per-profile library-owned skills, however, are regenerated/refreshed
    from the library + main config on every seed, so git-shipped updates
    always reach the specialist. The model block in particular is
    reconciled from the main config on EVERY hydrate, so switching
    LLM_PROVIDER (e.g. to a local vLLM/Ollama endpoint) propagates to all
    specialists on the next restart instead of leaving them pinned to a
    previous provider. Runtime state (kanban board, durable/cron tasks,
    gateway_state.json) is never touched.
    """
    env_target = profile_dir / ".env"
    profile_suffix = _norm_profile(profile_dir.name)
    _shared_infra_only = lambda k: _is_channel_key(k) or _is_scoped_key(k)  # noqa: E731
    if not env_target.exists() and main_env.is_file():
        # Seed the profile .env from main, WITHOUT channel credentials
        # (bot tokens bind one identity to one gateway -- see
        # _CHANNEL_KEY_RE) and without BASE__SUFFIX scoped keys (copying
        # KEY__A into profile B's env would itself be a leak). Shared
        # infra keys (LLM, search APIs, ...) replicate as before.
        pairs = _parse_env_file(main_env)
        kept = {k: v for k, v in pairs.items() if not _shared_infra_only(k)}
        env_target.write_text(
            "\n".join(f"{k}={v}" for k, v in kept.items()) + ("\n" if kept else "")
        )
        env_target.chmod(0o600)
        withheld = len(pairs) - len(kept)
        print(f"    + .env (seeded from {main_env}"
              + (f"; {withheld} channel/scoped key(s) withheld)" if withheld else ")"))
    elif env_target.exists() and main_env.is_file():
        # Profile already has a .env from a previous container run --
        # merge any keys present in the main .env but missing from the
        # profile .env, so newly-added bundle secrets reach existing
        # specialists without forcing the operator to delete the
        # profile directory. Existing values are NEVER overwritten:
        # operator edits via the webui survive. Channel and scoped keys
        # are excluded from the merge (see above).
        added = _merge_env_keys(main_env, env_target, exclude=_shared_infra_only)
        if added:
            print(f"    + .env merged {added} new key(s) from {main_env}")

    # One-time migration for .env files written by older images, which
    # blanket-copied the full main .env into every profile. A channel
    # key whose value is byte-identical to main's is the fingerprint of
    # that copy AND exactly the broken configuration (multiple gateways
    # polling one bot token -> Telegram getUpdates 409), so drop it. A
    # DIFFERING value means an operator deliberately configured a
    # profile-specific credential -- never touched. Scoped BASE__SUFFIX
    # lines are uppr-managed and meaningless inside a profile .env
    # (the binary only reads base names), so they are always dropped.
    # Idempotent: after removal nothing identical is left, and the
    # copy/merge above can no longer reintroduce these keys. Runs
    # BEFORE scoped routing so a routed value that happens to equal
    # main's survives (scrub, then route).
    if env_target.is_file():
        main_pairs = _parse_env_file(main_env)
        scrubbed = _remove_env_lines(
            env_target,
            lambda k, v: _is_scoped_key(k)
            or (_is_channel_key(k) and main_pairs.get(k) == v),
        )
        for key in scrubbed:
            print(f"    - scrubbed {key} (blanket-copied from main .env)")

    # Scoped routing: BASE__<SUFFIX> keys addressed to this profile are
    # written into its .env under the base name. Candidates come from
    # the main .env overlaid with the live container env (env wins --
    # same rotation semantics as _persist_bundle_secrets). Overwrites
    # an existing value on purpose: scoped delivery is authoritative,
    # which is what lets uppr_cloud rotate a bot token.
    scoped_candidates = _parse_env_file(main_env) if main_env.is_file() else {}
    scoped_candidates.update(
        {k: v for k, v in os.environ.items() if _is_scoped_key(k)}
    )
    for key in sorted(scoped_candidates):
        m = _SCOPED_KEY_RE.match(key)
        if not m or m.group(2) != profile_suffix:
            continue
        value = scoped_candidates[key]
        if not value:
            continue
        if _upsert_env_line(env_target, m.group(1), value):
            print(f"    + {m.group(1)} (scoped delivery: {key})")

    config_path = profile_dir / "config.yaml"
    profile_cfg = _load_yaml(config_path)
    main_cfg = _load_yaml(main_config)
    changed = False

    # Model block: RECONCILED from the main config on every hydrate, not
    # just seeded once. start.sh pins the main config's model block from
    # the LLM_PROVIDER / LOCAL_MODEL_* env on every boot, so the main
    # config is the single source of truth for which LLM this deployment
    # uses. Specialists must follow it: on a local-AI deployment
    # (LLM_PROVIDER=local) a specialist left on a stale cloud model
    # (e.g. an OpenRouter Claude pin from a previous provider) has no
    # API key and errors with "No LLM provider configured" — the
    # first-write-only behaviour this replaces froze exactly that state.
    # Per-profile model overrides therefore don't survive a restart; the
    # deployment-wide provider switch is deliberately authoritative.
    main_model = main_cfg.get("model")
    if main_model and profile_cfg.get("model") != main_model:
        verb = "+" if "model" not in profile_cfg else "~"
        profile_cfg["model"] = main_model
        changed = True
        print(f"    {verb} model block (reconciled from main config: "
              f"{main_model.get('default', '?')})")

    # Kanban scope: each specialist orchestrates its OWN task board. The
    # main agent is the org-wide orchestrator — it carries
    # orchestrator_profile="" (which resolves to "the active default
    # profile", i.e. the main agent) and auto_decompose=true so it fans
    # work out to specialists. A specialist must NOT inherit that block:
    # with an empty orchestrator_profile every cron / durable task it
    # creates is routed back to the *default* profile, so the job ends up
    # assigned to "default" and only ever shows up under the main agent —
    # never under the specialist that created it.
    #
    # Give each specialist a self-scoped block instead: it names itself as
    # orchestrator (so tasks it creates are owned by — and visible under —
    # itself) and turns auto_decompose off (a specialist must not try to
    # decompose work out to sibling profiles it can't see from its
    # isolated home). start.sh runs a dedicated gateway per profile, so
    # each one ticks its own schedule.
    #
    # Self-scoping is enforced whenever the block is missing, is a
    # verbatim copy of the main block, or names a DIFFERENT profile as
    # orchestrator (that includes the stale inherited "" from older
    # images, which routes every cron/durable task to main). Extra keys
    # an operator added to the block are preserved via merge. The only
    # opt-out is an explicit `operator_managed: true` inside the kanban
    # block -- set that when a profile must deliberately defer to
    # another orchestrator, and hydration will never touch the block.
    # An operator who customises auto_decompose but keeps
    # orchestrator_profile == the profile's own name is also left alone.
    profile_name = profile_dir.name
    self_kanban = {"orchestrator_profile": profile_name, "auto_decompose": False}
    existing_kanban = profile_cfg.get("kanban")
    existing_map = existing_kanban if isinstance(existing_kanban, dict) else {}
    operator_pinned = bool(existing_map.get("operator_managed"))
    needs_selfscope = (
        existing_kanban is None
        or existing_kanban == main_cfg.get("kanban")
        or (not operator_pinned
            and existing_map.get("orchestrator_profile") != profile_name)
    )
    merged_kanban = {**existing_map, **self_kanban}
    if needs_selfscope and existing_kanban != merged_kanban:
        profile_cfg["kanban"] = merged_kanban
        changed = True
        print(f"    + kanban block (self-scoped: orchestrator={profile_name}, "
              f"auto_decompose=off)")

    # Hermes profiles are isolated homes -- they do NOT inherit
    # mcp_servers from the default profile's config. Specialist
    # profile configs in the library re-declare any MCP server they
    # need, with ${VAR} placeholders for secrets. _seed_mcp env-expands
    # the root config; mirror that here so profile configs end up with
    # the real token baked in, otherwise the per-profile MCP client
    # sees literal ${VAR} strings and the server connection fails.
    if profile_cfg:
        expanded = _expand_env(profile_cfg)
        if expanded != profile_cfg:
            profile_cfg = expanded
            changed = True
            print(f"    + env-expanded ${{VAR}} placeholders in config.yaml")

    # MCP server inheritance. Hermes profiles are isolated homes that do
    # NOT inherit mcp_servers from the main config at runtime, so the
    # seed materialises inheritance by copying entries into each
    # profile's own config.yaml. Two modes, keyed on whether the profile
    # ships any mcp_servers of its own:
    #
    #   * UNSCOPED profile (declares no MCP server of its own): inherit
    #     EVERY root MCP server, so a plain specialist has the same tool
    #     reach as the main agent. This is the default — "all profiles
    #     see all MCP servers" (e.g. higgsfield on the UPPR deployment).
    #   * SCOPED profile (declares its own server — e.g. the cruiming
    #     specialists with their per-upstream cruiming_exact / _microsoft
    #     / _hix whitelists): inherit ONLY the deployment-global servers
    #     (pipedream-* — i.e. _is_managed_mcp) on
    #     top of what it declared. We must NOT pour the full root set
    #     into a scoped profile: that would re-introduce the
    #     cross-system tool leak the unique per-profile server names
    #     exist to prevent. Platform-managed servers don't count toward
    #     "declares its own": every profile carries them, so they say
    #     nothing about whether the profile wanted a whitelist.
    #
    # A server the profile already has is only overwritten when it is
    # platform-managed AND drifted from the main config — that mirrors
    # _seed_mcp's reconcile, so a rotated token or late-injected env
    # (PIPEDREAM_MCP_* arrives only after the tenant email backfill)
    # reaches existing specialists too. Non-managed entries are never
    # touched, so a profile that re-declares e.g. exa keeps its own.
    # Values copied from main_cfg were already env-expanded by _seed_mcp.
    #
    # Re-seed caveat (matches the rest of this file's first-write-only
    # behaviour): once inherited servers are written into a profile's
    # config.yaml they look "declared" on the next start, so an unscoped
    # profile is filled once. To pick up a non-managed root MCP server
    # added later, delete the profile dir so it re-seeds (managed ones
    # ride in via the reconcile above regardless).
    main_mcp = main_cfg.get("mcp_servers") or {}
    declared_mcp = profile_cfg.get("mcp_servers") or {}
    is_scoped = any(not _is_managed_mcp(name) for name in declared_mcp)
    if is_scoped:
        inherit_names = [n for n in main_mcp if _is_managed_mcp(n)]
    else:
        inherit_names = list(main_mcp.keys())
    for name in inherit_names:
        profile_mcp = profile_cfg.setdefault("mcp_servers", {})
        if name not in profile_mcp:
            profile_mcp[name] = main_mcp[name]
            changed = True
            print(f"    + mcp server: {name} (inherited from main config)")
        elif _is_managed_mcp(name) and profile_mcp[name] != main_mcp[name]:
            profile_mcp[name] = main_mcp[name]
            changed = True
            print(f"    ~ mcp server: {name} (reconciled from main config)")

    # Prefix-managed servers pruned from the main config (curated
    # Pipedream app removed) leave each profile too. The main config is
    # the source of truth here — _seed_mcp already guarded its prune
    # against degraded tarballs, so mirroring it is safe.
    profile_mcp = profile_cfg.get("mcp_servers") or {}
    for name in [
        n for n in list(profile_mcp)
        if str(n).startswith(_MANAGED_MCP_PREFIXES) and n not in main_mcp
    ]:
        del profile_mcp[name]
        changed = True
        print(f"    - mcp server: {name} (pruned; gone from main config)")

    if changed:
        with config_path.open("w") as f:
            yaml.safe_dump(profile_cfg, f, sort_keys=False)

    skill_names = list(profile_cfg.get("skills") or [])
    # Deployment-global skills ride along into every specialist, on
    # top of whatever the profile declares. Quietly optional: when the
    # library doesn't carry them they just don't exist under
    # global_skills and are skipped without a WARN.
    declared = set(skill_names)
    extra_names = [n for n in GLOBAL_DEFAULT_SKILLS if n not in declared]
    if (skill_names or extra_names) and global_skills.is_dir():
        per_profile_skills = profile_dir / "skills"
        per_profile_skills.mkdir(exist_ok=True)
        # Library-owned skills are refreshed in place on every seed so a
        # git-shipped skill update reaches the specialist. Skills the
        # operator dropped into the profile by hand (names not in the
        # config skills list) are not iterated here, so they survive.
        for name in skill_names:
            src = _resolve_dir(global_skills, name)
            if not src:
                print(f"    WARN: skill '{name}' missing under {global_skills}, "
                      f"specialist will boot without it", file=sys.stderr)
                continue
            dest = per_profile_skills / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            print(f"    + skill: {name}")
        for name in extra_names:
            src = _resolve_dir(global_skills, name)
            if not src:
                continue
            dest = per_profile_skills / name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest)
            print(f"    + skill: {name} (deployment default)")


def cmd_seed(args: argparse.Namespace) -> int:
    staging = Path(args.staging)
    hermes_home = Path(args.hermes_home)

    if not staging.is_dir():
        print(f"seed-library: no staging dir at {staging}, nothing to seed")
        return 0

    hermes_home.mkdir(parents=True, exist_ok=True)

    # Persist bundle-declared secrets from the live container env into
    # the main ~/.hermes/.env BEFORE anything that copies the .env to
    # downstream consumers (profile hydration in particular). This way
    # `${VAR}` placeholders in profile config.yaml resolve at Hermes'
    # runtime even if the operator forgets to re-export the var on a
    # later `docker run`, and existing profile .env files get the new
    # keys merged in via _merge_env_keys.
    persisted = _persist_bundle_secrets(staging / "manifest.yaml", hermes_home / ".env")
    if persisted:
        print(f"seed-library: persisted {persisted} bundle secret(s) into {hermes_home}/.env")

    # Skills are fully library-owned (no runtime state), so refresh them
    # in place on every seed -- this is what lets a git-shipped skill
    # update reach the main agent. Per-profile skill copies are refreshed
    # downstream in _hydrate_specialist_profile.
    seeded_skills = _seed_dirs(staging / "skills", hermes_home / "skills", "skill", overwrite=True)
    seeded_mcp = _seed_mcp(staging / "mcp", hermes_home / "config.yaml")
    seeded_profiles = _seed_profiles(staging / "profiles", hermes_home / "profiles")
    seeded_plugins = _seed_plugins(staging / "tools", hermes_home)
    _seed_kanban_orchestrator(staging / "manifest.yaml", hermes_home)
    _apply_bundle_only_toolsets(staging / "manifest.yaml", hermes_home)
    _apply_bundle_only_skills(staging / "manifest.yaml", hermes_home, staging)

    # Hydrate every specialist profile present in ~/.hermes/profiles/
    # (whether seeded just now or carried over from a previous run that
    # predates this hydration step). Idempotent — existing .env / model
    # block / per-profile skill dirs are never overwritten.
    profiles_root = hermes_home / "profiles"
    if profiles_root.is_dir():
        profile_dirs = sorted(p for p in profiles_root.iterdir() if p.is_dir())
        _warn_duplicate_suffixes(profile_dirs)
        for profile_dir in profile_dirs:
            print(f"  hydrating profile: {profile_dir.name}")
            try:
                _hydrate_specialist_profile(
                    profile_dir,
                    main_env=hermes_home / ".env",
                    main_config=hermes_home / "config.yaml",
                    global_skills=hermes_home / "skills",
                )
            except Exception as exc:  # noqa: BLE001 - isolate per profile
                print(f"  ERROR: hydrating '{profile_dir.name}' failed: {exc}",
                      file=sys.stderr)

    total = seeded_skills + seeded_mcp + seeded_profiles + seeded_plugins
    if total == 0:
        print("seed-library: nothing new to seed")
    else:
        print(f"seed-library: seeded {seeded_skills} skill(s), {seeded_mcp} mcp server(s), "
              f"{seeded_profiles} profile(s), {seeded_plugins} plugin(s)")
    return 0


def _warn_duplicate_suffixes(profile_dirs: list[Path]) -> None:
    """Two profile dir names that normalise to the same scoped-env
    suffix would both receive the same BASE__SUFFIX deliveries. Warn
    loudly; routing stays deterministic (each dir routes by its own
    suffix, so both simply get the value)."""
    by_suffix: dict[str, list[str]] = {}
    for d in profile_dirs:
        by_suffix.setdefault(_norm_profile(d.name), []).append(d.name)
    for suffix, names in sorted(by_suffix.items()):
        if len(names) > 1:
            print(f"  WARN: profiles {names} share scoped-env suffix "
                  f"'{suffix}'; scoped keys will reach all of them",
                  file=sys.stderr)


def cmd_hydrate(args: argparse.Namespace) -> int:
    """Hydrate specialist profiles in ~/.hermes/profiles/ without
    touching the library staging dir.

    cmd_seed already hydrates profiles, but it only runs at container
    start. This standalone entry point lets start.sh's gateway
    supervisor make a profile created via the webui/agent usable (own
    .env, model block, self-scoped kanban, per-profile skills) before
    it spins up a gateway for it -- otherwise a brand-new profile's
    gateway would crash-loop on a missing LLM key. Idempotent.

    With --profile NAME only that profile is hydrated (used by the
    supervisor so one broken profile can't block another's gateway
    start); the exit code is non-zero when it fails or doesn't exist.
    Without --profile every profile is processed, each isolated in its
    own try/except, and the exit code is non-zero iff any failed.
    """
    hermes_home = Path(args.hermes_home)
    profiles_root = hermes_home / "profiles"
    if not profiles_root.is_dir():
        if getattr(args, "profile", None):
            print(f"hydrate: no profiles dir at {profiles_root}", file=sys.stderr)
            return 1
        return 0

    only = getattr(args, "profile", None)
    if only:
        targets = [profiles_root / only]
        if not targets[0].is_dir():
            print(f"hydrate: profile '{only}' not found under {profiles_root}",
                  file=sys.stderr)
            return 1
    else:
        targets = sorted(p for p in profiles_root.iterdir() if p.is_dir())

    _warn_duplicate_suffixes(
        sorted(p for p in profiles_root.iterdir() if p.is_dir())
    )

    hydrated = 0
    failed = 0
    for profile_dir in targets:
        print(f"  hydrating profile: {profile_dir.name}")
        try:
            _hydrate_specialist_profile(
                profile_dir,
                main_env=hermes_home / ".env",
                main_config=hermes_home / "config.yaml",
                global_skills=hermes_home / "skills",
            )
            hydrated += 1
        except Exception as exc:  # noqa: BLE001 - isolate per profile
            failed += 1
            print(f"  ERROR: hydrating '{profile_dir.name}' failed: {exc}",
                  file=sys.stderr)
    print(f"hydrate: processed {hydrated} profile(s)"
          + (f", {failed} failed" if failed else ""))
    return 1 if failed else 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_stage = sub.add_parser("stage", help="copy selected library items into a staging dir (build time)")
    p_stage.add_argument("--library", required=True, help="path to library/ in the repo")
    p_stage.add_argument("--manifest", required=True, help="path to clients/<name>/manifest.yaml")
    p_stage.add_argument("--staging", required=True, help="path to write the staging dir to (inside the image)")
    p_stage.set_defaults(func=cmd_stage)

    p_seed = sub.add_parser("seed", help="seed a staging dir into ~/.hermes (runtime)")
    p_seed.add_argument("--staging", required=True, help="path to the staging dir baked into the image")
    p_seed.add_argument("--hermes-home", required=True, help="path to the Hermes home dir (~/.hermes)")
    p_seed.set_defaults(func=cmd_seed)

    p_hydrate = sub.add_parser("hydrate", help="hydrate existing profiles in ~/.hermes (runtime, no staging)")
    p_hydrate.add_argument("--hermes-home", required=True, help="path to the Hermes home dir (~/.hermes)")
    p_hydrate.add_argument("--profile", help="hydrate only this profile (dir name under profiles/)")
    p_hydrate.set_defaults(func=cmd_hydrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - belt-and-braces: never crash the container
        sys.stderr.write(f"library helper: unexpected error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
