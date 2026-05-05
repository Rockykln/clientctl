"""Drift detection: critical DOM IDs referenced by app.js must exist in
index.html. Catches "I removed this section but the JS still queries it"
regressions before they crash the frontend at runtime.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "index.html").read_text()
JS   = (ROOT / "static" / "app.js").read_text()


# ── Element IDs that JS depends on ──────────────────────────────────

CRITICAL_IDS = {
    # Top-level sections
    "login", "screen-lock", "app",

    # Login screen
    "code-input", "login-btn", "login-error",
    "login-passkey-btn", "login-insecure-hint",

    # Lock screen
    "screen-lock-sub", "unlock-passkey-btn", "unlock-code-btn",
    "unlock-error", "unlock-insecure-hint",

    # Header
    "ping", "battery", "battery-text",
    "notif-btn", "power-btn", "shutdown-btn", "server-kill-btn",
    "settings-btn", "logout-btn",
    "volume-btn", "brightness-btn", "lock-btn",

    # Stats row
    "stats",
    "stat-cpu", "stat-cpu-val", "stat-cpu-bar",
    "stat-mem", "stat-mem-val", "stat-mem-bar",
    "stat-gpu", "stat-gpu-val", "stat-gpu-bar",
    "stat-procs", "stat-procs-val",
    "stat-net",  "stat-net-val",

    # Grid container
    "grid",

    # Bottom-right footer
    "app-footer", "app-version", "app-repo",

    # Dropdowns
    "notif-dropdown", "notif-toggle-btn", "notif-toggle-hint",
    "notif-list", "notif-clear-btn",
    "volume-dropdown", "volume-row", "volume-mute",
    "volume-slider", "volume-value", "audio-streams",
    "brightness-dropdown", "brightness-bars",

    # Settings
    "settings-dropdown", "passkey-count", "passkey-list",
    "passkey-add-btn", "passkey-disabled-hint",
    "settings-version", "theme-picker",

    # Modals
    "passkey-modal", "passkey-name-input", "passkey-pw-input",
    "passkey-cancel-btn", "passkey-confirm-btn", "passkey-modal-error",

    # Toast + action menu
    "toast",
    "action-menu", "action-menu-backdrop",
    "action-menu-title",
    "action-pause-icon",  "action-pause-path",  "action-pause-label",
    "action-window-icon", "action-window-path", "action-window-label",

    # Templates
    "brightness-bar-tpl", "cell-app-tpl", "cell-cachy-tpl",
}


# ── Tests ────────────────────────────────────────────────────────────

def test_all_critical_ids_present():
    """Every ID JS queries must exist in the HTML, or the app breaks at boot."""
    missing = []
    for id_ in CRITICAL_IDS:
        if f'id="{id_}"' not in HTML:
            missing.append(id_)
    assert not missing, f"Missing IDs in index.html: {sorted(missing)}"


def test_no_duplicate_ids_in_html():
    """Browser only finds the first match for duplicate IDs — usually a bug."""
    ids_in_html = re.findall(r'\bid="([^"]+)"', HTML)
    seen = set()
    duplicates = []
    for i in ids_in_html:
        if i in seen:
            duplicates.append(i)
        seen.add(i)
    assert not duplicates, f"Duplicate IDs in index.html: {sorted(set(duplicates))}"


def test_brand_mark_is_present():
    """The bracket logo next to the 'clientctl' brand text. Inline SVG so
    it inherits the theme accent color via currentColor."""
    assert 'class="brand-mark"' in HTML, "brand-mark icon missing from header"
    # currentColor lets it adapt to the active theme
    assert 'stroke="currentColor"' in HTML, \
        "brand-mark must use currentColor so it follows the theme"


def test_theme_bootstrap_loads_before_stylesheet():
    """The FOUC-prevention script (theme-bootstrap.js) must be referenced
    in <head> BEFORE the main stylesheet, so the theme attribute is
    applied before any pixel paints. The script lives in a separate file
    so the CSP can forbid inline scripts."""
    head_match = re.search(r"<head[^>]*>(.*?)</head>", HTML, re.DOTALL | re.IGNORECASE)
    assert head_match, "index.html has no <head>"
    head = head_match.group(1)

    bootstrap_pos = head.find("/theme-bootstrap.js")
    css_link_pos  = head.find('href="/style.css"')
    assert bootstrap_pos != -1, "theme-bootstrap.js script tag missing from <head>"
    assert css_link_pos  != -1, "main stylesheet link missing from <head>"
    assert bootstrap_pos < css_link_pos, \
        "Theme bootstrap must be declared before the stylesheet link"

    # And the inline form must be gone — otherwise CSP 'unsafe-inline'
    # would still be needed.
    assert "localStorage.getItem(\"clientctl-theme\")" not in HTML, \
        "Inline theme bootstrap still present — move it to theme-bootstrap.js"


def test_no_native_confirm_in_app_js():
    """Drift guard: every confirmation goes through confirmModal() so the
    UI stays styled. Catches accidental window.confirm() additions."""
    bare_confirms = [
        m for m in re.finditer(r"(?<![a-zA-Z._])confirm\(", JS)
        if not _is_confirm_modal_call(JS, m.start())
    ]
    assert not bare_confirms, \
        "Native window.confirm() found in app.js — use confirmModal() instead"


def _is_confirm_modal_call(src: str, pos: int) -> bool:
    """True if the `confirm(` at `pos` is actually `confirmModal(`."""
    return src[pos - 5 : pos + 1].endswith("Modal(") or \
           src[pos - 5 : pos + 7] == "confirmModal"
