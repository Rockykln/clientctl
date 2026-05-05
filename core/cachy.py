"""Cachy-Update tray integration (arch-update).

Reads the tray icon state from ~/.local/state/arch-update/tray_icon and
shows it on a dedicated cell. Optional, only useful on Arch / CachyOS
with arch-update installed.
"""

import re
from pathlib import Path

from core import procs

STATE_FILE = Path.home() / ".local/state/arch-update/tray_icon"
ICON_DIR   = Path("/usr/share/icons/hicolor/scalable/apps")
FALLBACK   = "cachy-update-blue"

# Whitelist for icon names — alphanumeric, dash, underscore. Rejects any
# attempt to inject path components (../, /etc/passwd, …) via the state
# file. Even though the state file is owned by the user, a defensive
# filter keeps the icon resolver from ever building paths outside ICON_DIR.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def icon_name() -> str:
    try:
        name = STATE_FILE.read_text().strip()
    except Exception:
        return FALLBACK
    if not name or not _SAFE_NAME_RE.match(name):
        return FALLBACK
    return name


def icon_path() -> Path | None:
    name = icon_name()
    p = ICON_DIR / f"{name}.svg"
    if p.is_file():
        return p
    fallback = ICON_DIR / f"{FALLBACK}.svg"
    return fallback if fallback.is_file() else None


def state() -> dict:
    name = icon_name()
    return {"icon": name, "available": "updates-available" in name}


KONSOLE_CFG = {
    "name":          "Cachy-Update",
    "desktop_id":    "org.kde.konsole",
    "wm_class":      "konsole",
    "caption_match": "Cachy-Update",
}


def konsole_pids() -> list[int]:
    """PIDs of all konsole instances running arch-update."""
    return procs.find_konsole_with_arg("arch-update")
