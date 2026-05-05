"""Configuration: .env, constants, apps.yml.

The app list is loaded at import time from `apps.yml`. If that file is
missing, it gets copied from `apps.example.yml`. apps.yml is gitignored.
"""

import getpass
import logging
import os
import secrets
import shutil
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

# ── Version + repo (single source of truth) ─────────────────────────
# Bumped per release. VERSION is mirrored in pyproject.toml — CI verifies
# they match. REPO_URL appears in the bottom-right corner of the UI as a
# tiny link; leave empty to hide it. Update both at release time.
VERSION  = "0.1.0"
REPO_URL = "https://github.com/Rockykln/clientctl"

ROOT   = Path(__file__).resolve().parent
STATIC = ROOT / "static"
STATE  = ROOT / "state"
STATE.mkdir(exist_ok=True)

# Load .env before any os.getenv call
load_dotenv(ROOT / ".env")

PORT                 = int(os.getenv("CLIENTCTL_PORT", "8090"))

# Deployment mode — controls bind address and whether the tunnel runs.
# Three values, default "lan":
#   dev     — bind 127.0.0.1 only, no tunnel. For development on the host.
#   lan     — bind 0.0.0.0  (LAN-reachable), no tunnel. Default.
#   tunnel  — bind 127.0.0.1, start cloudflared. Public over HTTPS.
# Aliases: CLIENTCTL_TUNNEL=1 forces tunnel mode for backward compatibility.
_mode_raw = os.getenv("CLIENTCTL_MODE", "lan").strip().lower()
if os.getenv("CLIENTCTL_TUNNEL", "").lower() in ("1", "true", "yes"):
    _mode_raw = "tunnel"
if _mode_raw not in ("dev", "lan", "tunnel"):
    _mode_raw = "lan"
MODE = _mode_raw

# nosec B104 — 0.0.0.0 is intentional in `lan` mode; the server is
# protected by auth + rate-limit + cookies, see SECURITY.md.
BIND_HOST = "127.0.0.1" if MODE in ("dev", "tunnel") else "0.0.0.0"  # nosec B104
CODE_TTL_SECONDS     = 600
# Default 7 days. Trade-off: shorter is safer, longer = less re-auth.
# "Remember me" extends to SESSION_TTL_REMEMBER_SECONDS (14 days).
SESSION_TTL_SECONDS         = int(os.getenv("CLIENTCTL_SESSION_TTL_DAYS", "7"))  * 24 * 3600
SESSION_TTL_REMEMBER_SECONDS = int(os.getenv("CLIENTCTL_SESSION_REMEMBER_DAYS", "14")) * 24 * 3600

# WebAuthn / Passkey
RP_ID         = os.getenv("RP_ID", "clientctl.localhost")
RP_NAME       = "clientctl"
ORIGIN        = f"https://{RP_ID}"
REG_PASSWORD  = os.getenv("PASSKEY_REGISTRATION_PASSWORD", "")
PASSKEYS_FILE = STATE / "passkeys.json"
MAX_PASSKEYS  = int(os.getenv("CLIENTCTL_MAX_PASSKEYS", "2"))
USER_ID_BYTES = b"clientctl-user"

# Feature opt-out: comma-separated list of capability keys the operator
# wants to hide regardless of detection. Useful when the system supports
# something (e.g. ddcutil, dbus_monitor) but the user doesn't want that
# control surfaced in the panel. Goes one layer beyond capability detection.
# Example:  CLIENTCTL_DISABLE_FEATURES=audio,gpu,brightness
DISABLED_FEATURES: set[str] = {
    f.strip().lower() for f in os.getenv("CLIENTCTL_DISABLE_FEATURES", "").split(",")
    if f.strip()
}

# Maximum themes loaded into the picker. Default 8 — keeps the picker
# scannable in one glance and prevents an over-stuffed themes.yml from
# bloating the generated /themes.css. Set to 0 to disable the cap.
# Themes are kept in YAML order, so the first N win when the file has more.
THEMES_LIMIT = max(0, int(os.getenv("CLIENTCTL_THEMES_LIMIT", "8")))

# Shown in the passkey UI ("Sign in as ___") — defaults to current login name
USER_NAME = os.getenv("CLIENTCTL_USER_NAME", getpass.getuser())

# Persistent secret key — sessions survive server restart
SECRET_FILE = STATE / "secret.key"
if not SECRET_FILE.exists():
    SECRET_FILE.write_bytes(secrets.token_bytes(32))
# Owner-only permissions: anyone reading this file can forge sessions.
try:
    SECRET_FILE.chmod(0o600)
except Exception:
    pass
SECRET_KEY = SECRET_FILE.read_bytes()

# Cookie hardening: set CLIENTCTL_COOKIE_SECURE=true ONLY when reached
# exclusively via HTTPS (Cloudflare tunnel, reverse proxy). On plain LAN
# HTTP the browser drops Secure cookies and auth breaks.
COOKIE_SECURE = os.getenv("CLIENTCTL_COOKIE_SECURE", "").lower() in ("1", "true", "yes")

# Login code: 6 digits, regenerated on server start AND on demand
# (SIGUSR1 to the server process, or via the CLI helper). Stored in
# mutable globals so the regen helper can update them at runtime.
LOGIN_CODE: str         = ""
LOGIN_CODE_EXPIRES: float = 0.0


def regenerate_login_code() -> str:
    """Generate a fresh 6-digit code, set its expiry to CODE_TTL_SECONDS
    from now, and return it. Caller is responsible for printing/logging."""
    global LOGIN_CODE, LOGIN_CODE_EXPIRES
    LOGIN_CODE         = f"{secrets.randbelow(1_000_000):06d}"
    LOGIN_CODE_EXPIRES = time.time() + CODE_TTL_SECONDS
    return LOGIN_CODE


# Initialize on import so the first server start has a code right away.
regenerate_login_code()


# ── Logging ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=os.getenv("CLIENTCTL_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("clientctl")


# ── Apps configuration ───────────────────────────────────────────────

APPS_FILE    = ROOT / "apps.yml"
APPS_EXAMPLE = ROOT / "apps.example.yml"


def expand_paths(value):
    """Recursively expand ~ and $VARS in string values.

    Public so tests can verify path expansion without going through the
    full apps.yml loader.
    """
    if isinstance(value, str):
        if "~" in value or "$" in value:
            return os.path.expandvars(os.path.expanduser(value))
        return value
    if isinstance(value, list):
        return [expand_paths(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_paths(v) for k, v in value.items()}
    return value


def load_apps_config(
    apps_file: Path | None = None,
    example_file: Path | None = None,
    auto_copy: bool = True,
) -> tuple[dict, list]:
    """Returns (apps_dict, grid_list).

    Creates apps.yml from the example file if missing — so the repo can be
    forked without exposing private paths. Parameterized so tests can
    point at a temp directory.
    """
    apps_file    = apps_file    or APPS_FILE
    example_file = example_file or APPS_EXAMPLE

    if not apps_file.exists():
        if auto_copy and example_file.exists():
            shutil.copy(example_file, apps_file)
            log.info("%s created from %s", apps_file.name, example_file.name)
        elif example_file.exists():
            apps_file = example_file
        else:
            log.warning("Neither %s nor %s found", apps_file.name, example_file.name)
            return {}, []

    try:
        data = yaml.safe_load(apps_file.read_text()) or {}
    except yaml.YAMLError as e:
        log.error("%s is not valid YAML: %s", apps_file.name, e)
        return {}, []

    apps = data.get("apps") or {}
    grid = data.get("grid") or []
    if not isinstance(apps, dict):
        log.warning("'apps:' must be a mapping, got %s", type(apps).__name__)
        apps = {}
    if not isinstance(grid, list):
        log.warning("'grid:' must be a list, got %s", type(grid).__name__)
        grid = []
    apps = {aid: expand_paths(cfg) for aid, cfg in apps.items() if isinstance(cfg, dict)}

    # Grid validation: only known IDs or the special "cachy" slot
    seen, valid_grid = set(), []
    for entry in grid:
        if not isinstance(entry, str):
            continue
        if entry == "cachy" or entry in apps:
            if entry not in seen:
                valid_grid.append(entry)
                seen.add(entry)
        else:
            log.warning("Grid entry '%s' missing from apps:", entry)

    return apps, valid_grid


LAUNCHABLE_APPS, GRID = load_apps_config()
