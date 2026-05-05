"""Helpers shared across blueprints and core modules.

Submodules:
    shell      — subprocess wrapper (run)
    encoding   — base64url helpers
    auth       — session check + @require_auth decorator
    caps       — capability probe (which backends/binaries are present)
    ratelimit  — sliding-window per-IP brute-force gate

Flat-symbol re-exports below let call sites write
``from utils import require_auth`` instead of digging into submodules.
Namespace-style modules (`caps`, `ratelimit`) are not re-exported — they
are imported directly via ``from utils import caps`` / ``from utils import
ratelimit`` since callers use them as namespaces, not flat symbols.
"""

from utils.auth     import is_authed, require_auth        # noqa: F401
from utils.encoding import b64url_decode, b64url_encode   # noqa: F401
from utils.shell    import run                            # noqa: F401
