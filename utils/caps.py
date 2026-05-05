"""Capability detection for multi-distro support.

Probes available backends once at startup; result is exposed via
/api/capabilities. Frontend hides features that the running system does
not support.

Cached — `detect()` only runs on first call (or with force=True).
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("clientctl.caps")

_CAPS: dict | None = None


def _has(binary: str) -> bool:
    return shutil.which(binary) is not None


def _busctl_property(svc: str, path: str, iface: str, prop: str) -> str | None:
    try:
        return subprocess.check_output(
            ["busctl", "get-property", svc, path, iface, prop],
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
    except Exception:
        return None


def _detect_audio() -> str:
    if _has("wpctl"):
        return "pipewire"
    if _has("pactl"):
        return "pulse"
    return "none"


def _detect_gpu() -> str:
    """AMD via sysfs gpu_busy_percent, Intel via intel_gpu_top, NVIDIA via nvidia-smi."""
    try:
        for p in Path("/sys/class/drm").glob("card[0-9]*/device/gpu_busy_percent"):
            if p.is_file():
                return "amd"
    except Exception:
        pass
    # Intel: vendor 0x8086 in DRM AND intel_gpu_top installed
    if _has("intel_gpu_top"):
        try:
            for p in Path("/sys/class/drm").glob("card[0-9]*/device/vendor"):
                if p.read_text().strip() == "0x8086":
                    return "intel"
        except Exception:
            pass
    if _has("nvidia-smi"):
        return "nvidia"
    return "none"


def _detect_battery() -> bool:
    """UPower DisplayDevice IsPresent property."""
    if not _has("busctl"):
        return False
    out = _busctl_property(
        "org.freedesktop.UPower",
        "/org/freedesktop/UPower/devices/DisplayDevice",
        "org.freedesktop.UPower.Device", "IsPresent",
    )
    return bool(out and out.endswith("true"))


def _detect_kde_plasma() -> bool:
    """KDE Plasma 6: qdbus6 + kwriteconfig6 + KWin DBus reachable."""
    if not (_has("qdbus6") and _has("kwriteconfig6")):
        return False
    try:
        subprocess.check_output(
            ["qdbus6", "org.kde.KWin"],
            stderr=subprocess.DEVNULL, timeout=2,
        )
        return True
    except Exception:
        return False


def _detect_kde_brightness() -> bool:
    if not _detect_kde_plasma():
        return False
    try:
        subprocess.check_output(
            ["qdbus6", "org.kde.Solid.PowerManagement",
             "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
             "org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightness"],
            stderr=subprocess.DEVNULL, timeout=2,
        )
        return True
    except Exception:
        return False


def _detect_power_profiles() -> bool:
    """net.hadess.PowerProfiles (power-profiles-daemon)."""
    out = _busctl_property(
        "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
        "net.hadess.PowerProfiles", "ActiveProfile",
    )
    return out is not None


def _detect_logind() -> bool:
    return _has("loginctl")


def _detect_cachy() -> bool:
    return (Path.home() / ".local/state/arch-update").is_dir()


def detect(force: bool = False) -> dict:
    global _CAPS
    if _CAPS is not None and not force:
        return _CAPS

    caps = {
        "kde_plasma":      _detect_kde_plasma(),
        "kde_brightness":  _detect_kde_brightness(),
        "ddc":             _has("ddcutil"),
        "audio":           _detect_audio(),
        "battery":         _detect_battery(),
        "power_profiles":  _detect_power_profiles(),
        "logind":          _detect_logind(),
        "gpu":             _detect_gpu(),
        "dbus_monitor":    _has("dbus-monitor"),
        "cachy":           _detect_cachy(),
        "session_type":    os.getenv("XDG_SESSION_TYPE", ""),
        "desktop":         os.getenv("XDG_CURRENT_DESKTOP", ""),
    }
    # User opt-out: operator can disable any detected feature via
    # CLIENTCTL_DISABLE_FEATURES. Coerce to the same "feature off" sentinel
    # the frontend already understands ("none" for strings, False for bools).
    import config as _cfg  # late import — caps may be probed before .env loads
    disabled = getattr(_cfg, "DISABLED_FEATURES", set())
    # `brightness` is a UI-level alias resolved from kde_brightness OR ddc;
    # disabling it must hide both backends.
    if "brightness" in disabled:
        caps["kde_brightness"] = False
        caps["ddc"]            = False
    for key in disabled:
        if key in caps:
            current = caps[key]
            caps[key] = "none" if isinstance(current, str) else False
    _CAPS = caps
    log.info("Capabilities: %s", {k: v for k, v in caps.items() if v not in (False, "none", "")})
    if disabled:
        log.info("User-disabled features: %s", sorted(disabled))
    return caps


def get() -> dict:
    return detect()
