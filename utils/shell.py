"""subprocess wrapper with default timeout and stderr suppression.

All callers pass hardcoded list-form argv (no shell=True, no string
interpolation of user input). Even so, the wrapper enforces two
defence-in-depth checks before handing anything to ``subprocess``:

  1. ``cmd[0]`` must be in :data:`_ALLOWED_EXECS`. New helpers are added
     to this set explicitly; an unknown executable is a programmer error.
  2. Every element of ``cmd`` must match :data:`_SAFE_ARG_RE` — a tight
     ASCII character class with no shell metacharacters.

These two checks together also serve as the inline sanitizer that
CodeQL's ``py/command-line-injection`` query expects.
"""

import re
import subprocess

# Executables this wrapper is permitted to invoke. Add new entries here
# (alphabetical) when a caller needs a new tool; refuse anything else.
_ALLOWED_EXECS = frozenset({
    "busctl",
    "ddcutil",
    "ip",
    "loginctl",
    "qdbus6",
    "wpctl",
})

# Every argv element must match this — covers all flag/value shapes the
# callers use today (DBus paths, @DEFAULT_AUDIO_SINK@, decimals, percents)
# without admitting any shell metacharacters.
_SAFE_ARG_RE = re.compile(r"\A[A-Za-z0-9@/:._+\- ]+\Z")


def run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run *cmd* (list-form argv) and return stdout as text.

    Caller contract: ``cmd`` MUST be a list of strings, the first element
    a known executable in :data:`_ALLOWED_EXECS`, and each element a
    sequence of plain ASCII characters (see :data:`_SAFE_ARG_RE`). User
    input is never interpolated directly — callers validate first.

    Raises ``TypeError`` if the contract on the shape of ``cmd`` is
    violated, ``ValueError`` if any element fails the allow-/safe-list
    check, ``subprocess.CalledProcessError`` on non-zero exit, and
    ``subprocess.TimeoutExpired`` if *timeout* (seconds) elapses.

    stderr is silenced — callers that need it should use ``subprocess``
    directly.
    """
    if not isinstance(cmd, list) or not cmd:
        raise TypeError("cmd must be a non-empty list[str]")
    if cmd[0] not in _ALLOWED_EXECS:
        raise ValueError(f"executable not in allowlist: {cmd[0]!r}")

    # Build a fresh list from individually validated elements. This
    # breaks the taint path that CodeQL's py/command-line-injection
    # query tracks: ``safe_cmd`` only ever holds strings that already
    # matched ``_SAFE_ARG_RE``, so the value reaching ``subprocess``
    # is provably free of shell metacharacters. Per-element validation
    # with re.match is a sanitizer pattern CodeQL recognises.
    safe_cmd: list[str] = []
    for a in cmd:
        if not isinstance(a, str):
            raise TypeError("cmd elements must all be str")
        if not _SAFE_ARG_RE.match(a):
            raise ValueError(f"refusing argv element with unexpected chars: {a!r}")
        safe_cmd.append(a)

    return subprocess.check_output(
        safe_cmd, timeout=timeout, stderr=subprocess.DEVNULL
    ).decode()
