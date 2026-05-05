"""Theme YAML loader + generated CSS — drift detection.

Themes live in `themes.yml` (copied from `themes.example.yml` on first
run) and are rendered to `/themes.css` by core/themes.py at startup.
The frontend reads the picker data via `/api/themes` and never has a
hard-coded list of theme IDs.
"""

import re
from pathlib import Path

import pytest
import yaml

ROOT          = Path(__file__).resolve().parent.parent
EXAMPLE_FILE  = ROOT / "themes.example.yml"
JS_FILE       = ROOT / "static" / "app.js"
CSS_FILE      = ROOT / "static" / "style.css"
HTML_FILE     = ROOT / "static" / "index.html"


# ── Loader behaviour ────────────────────────────────────────────────

def test_themes_example_is_valid_yaml():
    data = yaml.safe_load(EXAMPLE_FILE.read_text())
    assert isinstance(data, dict)
    assert "themes" in data
    assert isinstance(data["themes"], dict)


def test_themes_example_contains_all_required_keys():
    """Every theme in the example must have a complete palette."""
    from core.themes import REQUIRED_KEYS
    data = yaml.safe_load(EXAMPLE_FILE.read_text())
    for tid, theme in data["themes"].items():
        palette = theme.get("palette") or {}
        missing = REQUIRED_KEYS - palette.keys()
        assert not missing, f"theme {tid!r} missing palette keys: {sorted(missing)}"


def test_themes_example_default_exists():
    data = yaml.safe_load(EXAMPLE_FILE.read_text())
    default = data.get("default")
    assert default in data["themes"], (
        f"themes.example.yml: 'default: {default}' "
        f"not in themes: {list(data['themes'].keys())}"
    )


# ── Generated CSS via core/themes.py ────────────────────────────────

def test_loader_generates_root_block(tmp_path, monkeypatch):
    from core import themes as themes_module
    # Use the example file as the source of truth
    monkeypatch.setattr(themes_module, "THEMES_FILE",    EXAMPLE_FILE)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", EXAMPLE_FILE)
    state = themes_module.load()
    css = state.get("css") or themes_module.get_css()
    assert ":root {" in css
    assert "--bg:" in css
    assert "color-scheme:" in css


def test_loader_emits_one_block_per_theme(monkeypatch):
    from core import themes as themes_module
    monkeypatch.setattr(themes_module, "THEMES_FILE",    EXAMPLE_FILE)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", EXAMPLE_FILE)
    themes_module.load()
    css = themes_module.get_css()
    for theme_id in ("dark", "light", "midnight", "dim", "nord"):
        assert f'[data-theme="{theme_id}"]' in css, f"missing block: {theme_id}"


def test_loader_rejects_themes_with_missing_keys(tmp_path, monkeypatch):
    """A theme with an incomplete palette must be skipped, not exported."""
    bad = tmp_path / "themes.yml"
    bad.write_text("""
themes:
  good:
    label: "Good"
    palette:
      bg: "#000"
      surface: "#111"
      surface-2: "#222"
      border: "#333"
      text: "#fff"
      muted: "#999"
      accent: "#5a8dee"
      error: "#f00"
      success: "#0f0"
      warn: "#fa0"
      thumb-track: "#3a3a45"
      thumb-bg: "#fff"
      inner-glow: "rgba(255,255,255,0.06)"
      shadow: "rgba(0,0,0,0.55)"
      toast-bg: "rgba(28,28,34,0.85)"
      toast-border: "rgba(255,255,255,0.06)"
  broken:
    label: "Broken"
    palette:
      bg: "#000"
      # Most keys missing on purpose
default: good
""")
    from core import themes as themes_module
    monkeypatch.setattr(themes_module, "THEMES_FILE",    bad)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", bad)
    state = themes_module.load()
    assert "good"   in state["themes"]
    assert "broken" not in state["themes"]


def test_default_theme_in_html_bootstrap():
    """The FOUC bootstrap script must default to a known theme id."""
    boot = (ROOT / "static" / "theme-bootstrap.js").read_text()
    assert '"dark"' in boot, "theme-bootstrap.js must default to 'dark'"


def test_storage_key_consistent():
    """Bootstrap script and app.js must use the same localStorage key."""
    boot = (ROOT / "static" / "theme-bootstrap.js").read_text()
    js = JS_FILE.read_text()
    assert "clientctl-theme" in boot, "bootstrap uses wrong storage key"
    assert "clientctl-theme" in js,   "JS uses wrong storage key"


def test_stylesheet_includes_themes_css_first():
    """index.html must <link> /themes.css BEFORE /style.css so the
    custom-property values are defined when the rules using them are
    parsed."""
    html = HTML_FILE.read_text()
    pos_themes = html.find('href="/themes.css"')
    pos_style  = html.find('href="/style.css"')
    assert pos_themes != -1, "themes.css <link> missing"
    assert pos_style  != -1, "style.css <link> missing"
    assert pos_themes < pos_style, "themes.css must precede style.css"


def test_no_inline_theme_blocks_in_style_css():
    """style.css must NOT contain hardcoded [data-theme] blocks anymore —
    those moved to themes.yml."""
    css = CSS_FILE.read_text()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)  # strip comments
    matches = re.findall(r'\[data-theme="[a-z-]+"\]\s*\{', css)
    assert not matches, (
        f"style.css still has inline [data-theme] blocks: {matches}. "
        f"Move them to themes.yml."
    )


# ── Theme limit cap ─────────────────────────────────────────────────

def _ten_theme_yaml(tmp_path):
    """Build a temp themes.yml with 10 valid theme entries (more than the
    default cap of 8) so we can verify the limit kicks in."""
    base_palette = {
        "bg":           "#0d0d10",
        "surface":      "#1a1a20",
        "surface-2":    "#25252e",
        "border":       "#34343f",
        "text":         "#f0f0f5",
        "muted":        "#8a8a96",
        "accent":       "#5a8dee",
        "error":        "#ee5a5a",
        "success":      "#5aee8d",
        "warn":         "#f0c43a",
        "thumb-track":  "#3a3a45",
        "thumb-bg":     "#f0f0f5",
        "inner-glow":   "rgba(255,255,255,0.06)",
        "shadow":       "rgba(0,0,0,0.55)",
        "toast-bg":     "rgba(28, 28, 34, 0.85)",
        "toast-border": "rgba(255,255,255,0.06)",
    }
    themes = {
        f"t{i}": {"label": f"T{i}", "accent": "#5a8dee", "palette": dict(base_palette)}
        for i in range(10)
    }
    f = tmp_path / "themes.yml"
    f.write_text(yaml.safe_dump({"themes": themes, "default": "t0"}))
    return f


def test_themes_limit_caps_at_default(tmp_path, monkeypatch):
    """With 10 themes defined and the default limit of 8, only the first
    8 are loaded and the rest are dropped with a warning."""
    from core import themes as themes_module
    import config
    yml = _ten_theme_yaml(tmp_path)
    monkeypatch.setattr(themes_module, "THEMES_FILE", yml)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", yml)  # avoid auto-copy
    monkeypatch.setattr(config, "THEMES_LIMIT", 8)
    state = themes_module.load()
    assert len(state["themes"]) == 8
    # First eight win — file order is preserved
    assert list(state["themes"].keys()) == [f"t{i}" for i in range(8)]


def test_themes_limit_zero_disables_cap(tmp_path, monkeypatch):
    """CLIENTCTL_THEMES_LIMIT=0 → load everything regardless of count."""
    from core import themes as themes_module
    import config
    yml = _ten_theme_yaml(tmp_path)
    monkeypatch.setattr(themes_module, "THEMES_FILE", yml)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", yml)
    monkeypatch.setattr(config, "THEMES_LIMIT", 0)
    state = themes_module.load()
    assert len(state["themes"]) == 10


def test_themes_limit_warning_lists_dropped(tmp_path, monkeypatch, caplog):
    """The warning must name which entries were dropped — operators need
    to be able to see what they lost."""
    import logging
    from core import themes as themes_module
    import config
    yml = _ten_theme_yaml(tmp_path)
    monkeypatch.setattr(themes_module, "THEMES_FILE", yml)
    monkeypatch.setattr(themes_module, "THEMES_EXAMPLE", yml)
    monkeypatch.setattr(config, "THEMES_LIMIT", 3)
    with caplog.at_level(logging.WARNING, logger="clientctl.core.themes"):
        themes_module.load()
    msg = "\n".join(r.getMessage() for r in caplog.records)
    assert "limit is 3" in msg
    assert "t9"  in msg          # dropped entries listed
    assert "CLIENTCTL_THEMES_LIMIT" in msg   # the override is mentioned
