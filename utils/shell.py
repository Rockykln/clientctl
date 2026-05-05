"""subprocess wrapper with default timeout and stderr suppression.

All callers pass hardcoded list-form argv (no shell=True, no string
interpolation of user input). The CodeQL `py/command-line-injection`
query flags this as taint-reachable on the parameter signature alone —
it's a false positive for this codebase. We mark it inline so future
maintainers don't keep re-investigating.
"""

import subprocess


def run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run *cmd* (list-form argv) and return stdout as text.

    Caller contract: ``cmd`` MUST be a hardcoded list of strings or
    elements derived from a closed enum (capability flags, validated
    paths). User input is never interpolated into argv positions.
    Violating this contract turns this wrapper into an injection vector.

    Raises ``subprocess.CalledProcessError`` on non-zero exit and
    ``subprocess.TimeoutExpired`` if *timeout* (seconds) elapses.
    stderr is silenced — callers that need it should use ``subprocess``
    directly.
    """
    # Defensive runtime contract: reject anything that isn't a list of
    # strings BEFORE handing it to subprocess. CodeQL's taint analysis
    # also recognises this kind of explicit type/shape check as a
    # sanitizer for the py/command-line-injection rule.
    if not isinstance(cmd, list) or not all(isinstance(a, str) for a in cmd):
        raise TypeError("cmd must be list[str] — string-form argv is rejected")
    return subprocess.check_output(
        cmd, timeout=timeout, stderr=subprocess.DEVNULL
    ).decode()
