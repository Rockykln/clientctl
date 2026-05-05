"""System backend: power profiles, DND, battery, sysinfo (CPU/RAM/GPU/NET).

Multi-distro:
  - Power profiles via net.hadess.PowerProfiles (power-profiles-daemon)
  - DND on two paths: plasmanotifyrc (KDE) + freedesktop.Notifications.Inhibit
  - Battery via UPower DisplayDevice
  - Sysinfo via psutil; GPU via AMD sysfs, Intel daemon, or nvidia-smi
"""

import logging
import re
import subprocess
import threading
import time
from pathlib import Path

import psutil

log = logging.getLogger("clientctl.core.system")


# ── Power profiles (power-profiles-daemon) ───────────────────────────

POWER_PROFILES = ["power-saver", "balanced", "performance"]


def power_profile() -> str:
    try:
        out = subprocess.check_output(
            ["busctl", "get-property",
             "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
             "net.hadess.PowerProfiles", "ActiveProfile"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        m = re.search(r'"([^"]+)"', out)
        return m.group(1) if m else "balanced"
    except Exception:
        return "balanced"


def power_set(profile: str) -> None:
    if profile not in POWER_PROFILES:
        raise ValueError(f"unknown profile: {profile}")
    subprocess.run(
        ["busctl", "set-property",
         "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
         "net.hadess.PowerProfiles", "ActiveProfile", "s", profile],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def power_cycle() -> str:
    cur = power_profile()
    idx = POWER_PROFILES.index(cur) if cur in POWER_PROFILES else 1
    nxt = POWER_PROFILES[(idx + 1) % len(POWER_PROFILES)]
    power_set(nxt)
    return nxt


# ── Do-Not-Disturb ───────────────────────────────────────────────────
# Two paths: plasmanotifyrc (KDE UI) + freedesktop.Notifications.Inhibit
# (for apps that respect it).

_DND_CONFIG     = Path.home() / ".config/plasmanotifyrc"
_DND_FAR_FUTURE = "2099-12-31T23:59:59"
_DND_COOKIE: int | None = None


def dnd_active() -> bool:
    if not _DND_CONFIG.exists():
        return False
    in_section = False
    try:
        for raw in _DND_CONFIG.read_text().splitlines():
            line = raw.strip()
            if line.startswith("[") and line.endswith("]"):
                in_section = (line == "[DoNotDisturb]")
                continue
            if in_section and line.startswith("Until="):
                return bool(line.split("=", 1)[1].strip())
    except Exception:
        pass
    return False


def dnd_set(enable: bool) -> None:
    global _DND_COOKIE
    # 1) plasmanotifyrc → KDE UI
    try:
        if enable:
            subprocess.run(
                ["kwriteconfig6", "--notify",
                 "--file", "plasmanotifyrc",
                 "--group", "DoNotDisturb", "--key", "Until", _DND_FAR_FUTURE],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.run(
                ["kwriteconfig6", "--notify",
                 "--file", "plasmanotifyrc",
                 "--group", "DoNotDisturb", "--key", "Until", "--delete"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception as e:
        log.debug("kwriteconfig6 failed: %s", e)

    # 2) freedesktop.Notifications.Inhibit — standardized inhibitor
    try:
        if enable and _DND_COOKIE is None:
            out = subprocess.check_output(
                ["busctl", "--user", "call",
                 "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                 "org.freedesktop.Notifications", "Inhibit",
                 "ssa{sv}", "clientctl", "Do not disturb", "0"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
            try:
                _DND_COOKIE = int(out.split()[-1])
            except Exception:
                _DND_COOKIE = None
        elif not enable and _DND_COOKIE is not None:
            subprocess.run(
                ["busctl", "--user", "call",
                 "org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                 "org.freedesktop.Notifications", "UnInhibit",
                 "u", str(_DND_COOKIE)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            _DND_COOKIE = None
    except Exception as e:
        log.debug("Notifications.Inhibit failed: %s", e)


# ── Battery (UPower) ─────────────────────────────────────────────────

_UPOWER_STATES = {
    1: "charging", 2: "discharging", 3: "empty",
    4: "full",     5: "charging",   6: "discharging",
}


def battery_info() -> dict:
    try:
        path = "/org/freedesktop/UPower/devices/DisplayDevice"
        pct_out = subprocess.check_output(
            ["busctl", "get-property",
             "org.freedesktop.UPower", path,
             "org.freedesktop.UPower.Device", "Percentage"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        st_out = subprocess.check_output(
            ["busctl", "get-property",
             "org.freedesktop.UPower", path,
             "org.freedesktop.UPower.Device", "State"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        present_out = subprocess.check_output(
            ["busctl", "get-property",
             "org.freedesktop.UPower", path,
             "org.freedesktop.UPower.Device", "IsPresent"],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        pct = float(pct_out.split()[-1])
        state_int = int(st_out.split()[-1])
        present = present_out.split()[-1] == "true"
        if not present and pct == 0:
            return {"present": False}
        return {
            "present":  True,
            "percent":  int(round(pct)),
            "state":    _UPOWER_STATES.get(state_int, "unknown"),
            "charging": state_int in (1, 5),
        }
    except Exception:
        return {"present": False}


# ── Sysinfo (CPU / RAM / GPU / NET) ──────────────────────────────────
# Warm psutil — first cpu_percent call would otherwise return 0.0
psutil.cpu_percent(interval=None)

_NET_LAST = {"rx": 0, "tx": 0, "ts": 0.0}
_NET_LOCK = threading.Lock()


def gpu_busy_percent() -> int | None:
    # AMD: gpu_busy_percent directly from sysfs
    try:
        for p in Path("/sys/class/drm").glob("card[0-9]*/device/gpu_busy_percent"):
            txt = p.read_text().strip()
            if txt.isdigit():
                return int(txt)
    except Exception:
        pass
    # Intel: live sample from intel_gpu_top daemon (see core.intel_gpu)
    try:
        from core import intel_gpu
        v = intel_gpu.busy_percent()
        if v is not None:
            return v
    except Exception:
        pass
    # NVIDIA via nvidia-smi
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, timeout=1,
        ).decode().strip().splitlines()
        if out:
            return int(out[0])
    except Exception:
        pass
    return None


def net_speed_bps() -> tuple[int, int]:
    counters = psutil.net_io_counters(pernic=False)
    now = time.time()
    rx, tx = counters.bytes_recv, counters.bytes_sent
    with _NET_LOCK:
        prev_rx, prev_tx, prev_ts = _NET_LAST["rx"], _NET_LAST["tx"], _NET_LAST["ts"]
        _NET_LAST["rx"], _NET_LAST["tx"], _NET_LAST["ts"] = rx, tx, now
    dt = now - prev_ts if prev_ts else 0.0
    if dt <= 0 or dt > 60:
        return 0, 0
    return int(max(0, rx - prev_rx) / dt), int(max(0, tx - prev_tx) / dt)


def sysinfo() -> dict:
    from core import procs as _procs
    return {
        "cpu":   round(psutil.cpu_percent(interval=None)),
        "mem":   round(psutil.virtual_memory().percent),
        "gpu":   gpu_busy_percent(),
        "net":   dict(zip(("rx", "tx"), net_speed_bps())),
        "procs": len(_procs.snapshot()),
    }


# ── Shutdown / logind ────────────────────────────────────────────────

def shutdown_prompt() -> None:
    """KDE Plasma shutdown dialog. Throws on non-KDE systems."""
    subprocess.run(
        ["qdbus6", "org.kde.LogoutPrompt", "/LogoutPrompt",
         "org.kde.LogoutPrompt.promptShutDown"],
        check=True, timeout=5,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def shutdown_logind() -> None:
    """Generic fallback: systemd-logind power-off."""
    subprocess.run(
        ["loginctl", "poweroff"],
        check=True, timeout=5,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
