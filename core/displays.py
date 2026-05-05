"""Display brightness: KDE PowerManagement (internal) + ddcutil (external).

Both are optional — missing tools are silently ignored, the display
simply does not appear in the list.
"""

import logging
import re

from utils import run

log = logging.getLogger("clientctl.core.displays")

_QDBUS       = "qdbus6"
_KDE_PM_SVC  = "org.kde.Solid.PowerManagement"
_KDE_PM_PATH = "/org/kde/Solid/PowerManagement/Actions/BrightnessControl"
_KDE_PM_IF   = "org.kde.Solid.PowerManagement.Actions.BrightnessControl"


def _kde_brightness() -> tuple[int, int]:
    cur = int(run([_QDBUS, _KDE_PM_SVC, _KDE_PM_PATH, f"{_KDE_PM_IF}.brightness"]).strip())
    mx  = int(run([_QDBUS, _KDE_PM_SVC, _KDE_PM_PATH, f"{_KDE_PM_IF}.brightnessMax"]).strip())
    return cur, mx


def _kde_set_brightness(percent: int) -> None:
    _, mx = _kde_brightness()
    target = int(round(percent * mx / 100))
    run([_QDBUS, _KDE_PM_SVC, _KDE_PM_PATH, f"{_KDE_PM_IF}.setBrightness", str(target)])


_DDC_DETECT_RE = re.compile(r"Display\s+(\d+)")
_DDC_VCP_RE    = re.compile(r"VCP\s+10\s+C\s+(\d+)\s+(\d+)")


def _ddc_displays() -> list[dict]:
    """External monitors via DDC/CI. Needs i2c permissions."""
    try:
        out = run(["ddcutil", "detect", "--brief"])
    except Exception:
        return []
    displays = []
    for block in re.split(r"\n(?=Display )", out.strip()):
        m = _DDC_DETECT_RE.match(block)
        if not m or "Invalid" in block:
            continue
        num = int(m.group(1))
        name_m = re.search(r"Monitor:\s*([^\n]+)", block)
        name = name_m.group(1).strip() if name_m else f"DDC-{num}"
        try:
            vcp = run(["ddcutil", "--display", str(num), "getvcp", "10", "--terse"])
            br = _DDC_VCP_RE.search(vcp)
            if br:
                cur, mx = int(br.group(1)), int(br.group(2))
                pct = int(round(cur * 100 / mx)) if mx else 0
                displays.append({"id": f"ddc-{num}", "name": name, "brightness": pct})
        except Exception:
            continue
    return displays


def detect() -> list[dict]:
    out = []
    try:
        cur, mx = _kde_brightness()
        pct = int(round(cur * 100 / mx)) if mx else 0
        out.append({"id": "primary", "name": "Display", "brightness": pct})
    except Exception:
        pass
    out.extend(_ddc_displays())
    return out


_DDC_NUM_RE = re.compile(r"^\d+$")


def set_brightness(display_id: str, percent: int) -> None:
    pct = max(0, min(100, int(percent)))
    if display_id == "primary":
        _kde_set_brightness(pct)
    elif display_id.startswith("ddc-"):
        num = display_id[4:]
        # Strict validation — even though subprocess.run with a list won't
        # invoke a shell, ddcutil could still misinterpret unexpected
        # characters. Whitelist digits only.
        if not _DDC_NUM_RE.match(num):
            raise ValueError(f"invalid ddc display id: {display_id}")
        run(["ddcutil", "--display", num, "setvcp", "10", str(pct)])
    else:
        raise ValueError(f"unknown display: {display_id}")
