"""Shared pytest fixtures.

Most tests run hermetically — system calls (subprocess, /proc, busctl, …)
are patched so the suite passes on any Linux box (and inside CI, where
no KDE/Plasma is available).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project root importable
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402


@pytest.fixture
def tmp_state(tmp_path, monkeypatch):
    """Redirect config.STATE / PASSKEYS_FILE / SECRET_FILE to a tmp dir.

    Each test gets a clean isolated state directory.
    """
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(config, "STATE",         state)
    monkeypatch.setattr(config, "PASSKEYS_FILE", state / "passkeys.json")
    monkeypatch.setattr(config, "SECRET_FILE",   state / "secret.key")
    return state


@pytest.fixture
def known_login_code(monkeypatch):
    """Pin the login code to a known value for the duration of the test."""
    import time
    monkeypatch.setattr(config, "LOGIN_CODE",         "123456")
    monkeypatch.setattr(config, "LOGIN_CODE_EXPIRES", time.time() + 600)
    return "123456"


@pytest.fixture
def fake_caps(monkeypatch):
    """Force a known capability set so route logic stays deterministic."""
    from utils import caps as _caps
    fake = {
        "kde_plasma":     True,
        "kde_brightness": True,
        "ddc":            False,
        "audio":          "pipewire",
        "battery":        True,
        "power_profiles": True,
        "logind":         True,
        "gpu":            "intel",
        "dbus_monitor":   True,
        "cachy":          False,
        "session_type":   "wayland",
        "desktop":        "KDE",
    }
    monkeypatch.setattr(_caps, "_CAPS", fake)
    return fake


@pytest.fixture
def app(tmp_state, fake_caps, monkeypatch):
    """Flask test app — no real listeners started, no real subprocesses."""
    # Block accidental subprocess calls from route handlers
    import subprocess
    real_check_output = subprocess.check_output
    real_run          = subprocess.run

    def _block(*a, **kw):
        raise AssertionError("Unexpected subprocess call in test: " + repr(a[0] if a else kw))

    monkeypatch.setattr(subprocess, "check_output", _block)
    monkeypatch.setattr(subprocess, "run",          _block)

    # Re-import server module fresh so create_app doesn't hit cached state
    import importlib
    import server as _server
    importlib.reload(_server)
    app = _server.create_app()
    app.config.update(TESTING=True)
    yield app

    # restore so other fixtures can spawn processes if needed
    monkeypatch.setattr(subprocess, "check_output", real_check_output)
    monkeypatch.setattr(subprocess, "run",          real_run)


@pytest.fixture
def client(app):
    """Flask test client — unauthenticated."""
    return app.test_client()


@pytest.fixture
def authed_client(client, known_login_code):
    """Test client with an authenticated session cookie.

    Resets the login rate-limiter first — without this, a previous test
    that exhausted the bucket (e.g. brute-force probing) would block
    every subsequent test that needs an authed session, manifesting as a
    confusing 429 instead of the test's actual failure mode.
    """
    from utils import ratelimit
    ratelimit.LOGIN_LIMITER.reset("127.0.0.1")
    res = client.post("/api/login", json={"code": known_login_code})
    assert res.status_code == 200, res.get_json()
    return client


@pytest.fixture
def fake_proc(tmp_path, monkeypatch):
    """Build a fake /proc tree the procs module can scan.

    Returns a helper to register processes:

        fake_proc.add(pid=42, comm="firefox", cmdline=["/usr/bin/firefox"], ppid=1)
    """
    from core import procs as _procs

    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    monkeypatch.setattr(_procs, "_PROC", proc_root)
    monkeypatch.setattr(_procs, "_CACHE", {"data": [], "ts": 0.0})

    class FakeProc:
        def __init__(self, root): self.root = root

        def add(self, pid: int, comm: str, cmdline: list[str], ppid: int = 1, state: str = "S"):
            d = self.root / str(pid)
            d.mkdir()
            (d / "comm").write_text(comm + "\n")
            (d / "cmdline").write_bytes("\0".join(cmdline).encode() + b"\0")
            # /proc/<pid>/stat format: pid (comm) state ppid pgid ...
            (d / "stat").write_text(f"{pid} ({comm}) {state} {ppid} 0 0 0 -1\n")

    return FakeProc(proc_root)
