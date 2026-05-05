"""config — apps.yml loader + path expansion + .env.example sync."""

import re
from pathlib import Path

import config


# ── expand_paths ─────────────────────────────────────────────────────

def test_expand_paths_tilde(monkeypatch):
    monkeypatch.setenv("HOME", "/home/test")
    assert config.expand_paths("~/foo") == "/home/test/foo"


def test_expand_paths_var(monkeypatch):
    monkeypatch.setenv("MYVAR", "/x/y")
    assert config.expand_paths("$MYVAR/bin") == "/x/y/bin"


def test_expand_paths_nested():
    inp = {
        "a": "no-expand",
        "b": ["plain", "$HOME/x"],
        "c": {"d": "~/f"},
        "e": 42,
    }
    out = config.expand_paths(inp)
    assert out["a"] == "no-expand"
    assert out["e"] == 42
    assert out["b"][0] == "plain"
    assert out["b"][1].endswith("/x")
    assert out["c"]["d"].endswith("/f")


def test_expand_paths_no_op_for_plain_string():
    assert config.expand_paths("foo") == "foo"


# ── load_apps_config ────────────────────────────────────────────────

def _write_yaml(path: Path, content: str) -> None:
    path.write_text(content)


def test_load_apps_config_basic(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, """
apps:
  files:
    name: "Files"
    binary: "dolphin"
grid:
  - files
""")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert "files" in apps
    assert apps["files"]["name"] == "Files"
    assert grid == ["files"]


def test_load_apps_config_filters_unknown_grid_entries(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, """
apps:
  files:
    name: "Files"
    binary: "dolphin"
grid:
  - files
  - non_existent
  - cachy
""")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert grid == ["files", "cachy"]   # cachy is the special-case slot


def test_load_apps_config_dedupes_grid_entries(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, """
apps:
  a:
    name: "A"
grid:
  - a
  - a
  - cachy
  - cachy
""")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert grid == ["a", "cachy"]


def test_load_apps_config_handles_missing_file(tmp_path):
    apps, grid = config.load_apps_config(
        apps_file=tmp_path / "missing.yml",
        example_file=tmp_path / "also-missing.yml",
    )
    assert apps == {}
    assert grid == []


def test_load_apps_config_copies_example_when_apps_missing(tmp_path):
    example = tmp_path / "apps.example.yml"
    _write_yaml(example, """
apps:
  a:
    name: "A"
grid:
  - a
""")
    target = tmp_path / "apps.yml"
    apps, grid = config.load_apps_config(apps_file=target, example_file=example, auto_copy=True)
    assert target.exists()
    assert "a" in apps
    assert grid == ["a"]


def test_load_apps_config_falls_back_to_example_without_copy(tmp_path):
    example = tmp_path / "apps.example.yml"
    _write_yaml(example, "apps: {a: {name: A}}\ngrid: [a]\n")
    target = tmp_path / "apps.yml"  # does not exist
    apps, grid = config.load_apps_config(apps_file=target, example_file=example, auto_copy=False)
    assert "a" in apps
    assert not target.exists()


def test_load_apps_config_invalid_yaml(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    apps_yml.write_text(":::: not valid yaml ::::")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert apps == {}
    assert grid == []


def test_load_apps_config_rejects_non_dict_apps_section(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, "apps: [not, a, mapping]\ngrid: []\n")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert apps == {}


def test_load_apps_config_skips_non_string_grid_entries(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, """
apps:
  a:
    name: A
grid:
  - a
  - 42
  - null
""")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert grid == ["a"]


def test_load_apps_config_expands_paths_in_app_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/example")
    apps_yml = tmp_path / "apps.yml"
    _write_yaml(apps_yml, """
apps:
  a:
    name: "A"
    icon: "~/.local/share/icons/a.png"
    cmd: ["~/bin/a", "--flag"]
grid:
  - a
""")
    apps, _ = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert apps["a"]["icon"] == "/home/example/.local/share/icons/a.png"
    assert apps["a"]["cmd"] == ["/home/example/bin/a", "--flag"]


def test_load_apps_config_empty_yaml(tmp_path):
    apps_yml = tmp_path / "apps.yml"
    apps_yml.write_text("")
    apps, grid = config.load_apps_config(apps_file=apps_yml, example_file=tmp_path / "missing")
    assert apps == {}
    assert grid == []


# ── .env.example must document every var that config.py actually reads ──

ROOT = Path(__file__).resolve().parent.parent


def _vars_used_in_config() -> set[str]:
    """Every os.getenv("X", ...) call in config.py."""
    src = (ROOT / "config.py").read_text()
    return set(re.findall(r'os\.getenv\(["\']([A-Z][A-Z0-9_]*)', src))


def _vars_documented_in_env_example() -> set[str]:
    """Every X=... line (commented or not) in .env.example."""
    src = (ROOT / ".env.example").read_text()
    return set(re.findall(r'^#?\s*([A-Z][A-Z0-9_]+)=', src, re.MULTILINE))


def test_env_example_documents_all_used_vars():
    """Drift guard: every env var read by config.py must be in .env.example."""
    used       = _vars_used_in_config()
    documented = _vars_documented_in_env_example()
    missing    = used - documented
    assert not missing, (
        f"These env vars are read by config.py but not documented in "
        f".env.example: {sorted(missing)}"
    )


def test_env_example_has_no_orphan_vars():
    """Drift guard: every var in .env.example should still be read by config.py."""
    used       = _vars_used_in_config()
    documented = _vars_documented_in_env_example()
    orphans    = documented - used
    assert not orphans, (
        f"These env vars are documented in .env.example but no longer "
        f"read by config.py: {sorted(orphans)}"
    )


def test_env_example_required_vars_have_no_default():
    """The required block must leave PASSKEY_REGISTRATION_PASSWORD empty
       so a fresh fork doesn't ship a placeholder password."""
    src = (ROOT / ".env.example").read_text()
    m = re.search(r'^PASSKEY_REGISTRATION_PASSWORD=(.*)$', src, re.MULTILINE)
    assert m, "PASSKEY_REGISTRATION_PASSWORD line missing"
    assert m.group(1).strip() == "", (
        f"PASSKEY_REGISTRATION_PASSWORD should be empty in .env.example "
        f"(got {m.group(1)!r})"
    )
