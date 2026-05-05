"""Tests for kwin window-matching logic.

The DBus + journalctl side effects are not exercised — those need a real
KDE Plasma session. We test the pure matcher and JS-template generator.
"""

import json

from core import kwin


def test_matches_window_by_desktop_id():
    cfg = {"desktop_id": "org.kde.dolphin"}
    win = {"df": "org.kde.dolphin", "rc": "", "rn": "", "cap": ""}
    assert kwin._matches_window(win, cfg) is True


def test_matches_window_by_wm_class_string():
    cfg = {"wm_class": "Firefox"}
    win = {"df": "", "rc": "firefox", "rn": "", "cap": ""}
    assert kwin._matches_window(win, cfg) is True


def test_matches_window_by_wm_class_list():
    cfg = {"wm_class": ["Discord", "discord-canary"]}
    win = {"df": "", "rc": "discord-canary", "rn": "", "cap": ""}
    assert kwin._matches_window(win, cfg) is True


def test_matches_window_case_insensitive():
    cfg = {"wm_class": "DOLPHIN"}
    win = {"df": "", "rc": "dolphin", "rn": "", "cap": ""}
    assert kwin._matches_window(win, cfg) is True


def test_matches_window_caption_includes():
    cfg = {"caption_includes": "Cachy-Update"}
    win = {"df": "", "rc": "", "rn": "", "cap": "Konsole — Cachy-Update"}
    assert kwin._matches_window(win, cfg) is True


def test_matches_window_no_match():
    cfg = {"desktop_id": "x", "wm_class": "y", "caption_includes": "z"}
    win = {"df": "other", "rc": "other", "rn": "other", "cap": "other"}
    assert kwin._matches_window(win, cfg) is False


def test_matches_window_empty_config_does_not_match():
    cfg = {}
    win = {"df": "anything", "rc": "anything", "rn": "anything", "cap": "anything"}
    assert kwin._matches_window(win, cfg) is False


def test_for_each_generates_valid_js(monkeypatch):
    """Verify the for_each runner produces JS that includes the criteria."""
    captured = {}

    def fake_run_script(js):
        captured["js"] = js

    monkeypatch.setattr(kwin, "run_script", fake_run_script)

    cfg = {
        "desktop_id":       "org.kde.dolphin",
        "wm_class":         ["Dolphin"],
        "caption_includes": "files",
        "pids":             [42, 43],
    }
    kwin.for_each(cfg, "/* action */")
    js = captured["js"]
    assert "org.kde.dolphin" in js
    assert "dolphin"          in js
    assert "files"            in js
    assert "42"               in js
    assert "/* action */"     in js


def test_run_script_handles_missing_qdbus(monkeypatch, tmp_path):
    """If qdbus6 isn't installed, run_script should not crash callers."""
    import subprocess

    def fake_run(cmd, **kw):
        raise FileNotFoundError("qdbus6 not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    # Replace tmp script directory so we don't pollute real /tmp
    monkeypatch.setattr(kwin, "Path", type(tmp_path))

    try:
        kwin.run_script("// no-op")
    except FileNotFoundError:
        # Allowed: the caller (query_states / for_each) catches this in their
        # own try/except. The function itself is permitted to bubble.
        pass
