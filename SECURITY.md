# Security policy

clientctl exposes a Flask server that controls your desktop session.
Take any vulnerability that affects authentication, session handling,
WebAuthn, or remote command execution seriously.

## Supported versions

Only the latest minor release line receives security fixes.

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a vulnerability

**Do not open a public GitHub issue for security problems.**

Use GitHub's *Private vulnerability reporting* (Security tab → "Report a
vulnerability"). If that's unavailable, contact the maintainer through
the email listed on their GitHub profile.

When reporting, include:

- Affected version (`clientctl --version` is not a thing yet — check
  `config.VERSION` or the bottom-right of the UI)
- A short description of the vulnerability
- Reproduction steps or a proof-of-concept (logs, request/response, etc.)
- Your assessment of impact (auth bypass, RCE, info disclosure, …)

## Response expectations

- **Acknowledgement**: within 7 days
- **Initial triage**: within 14 days
- **Fix or mitigation**: depending on severity, typically within 30 days
  for high/critical issues

We will coordinate disclosure with you. Public credit (CVE filing,
acknowledgement in the release notes) is offered unless you prefer to
stay anonymous.

## Out of scope

- Issues that require physical access to the machine running clientctl
- Self-DOS via the `/api/server/kill` endpoint (this is intentional)
- Lack of HTTPS when bound to `0.0.0.0` without a tunnel — clientctl
  expects to run behind Cloudflare or another HTTPS terminator. Plain
  HTTP on the LAN is supported but not recommended; WebAuthn refuses to
  work on insecure origins by design.
- Third-party tools clientctl talks to (`kwriteconfig6`, `wpctl`,
  `intel_gpu_top`, `cloudflared`, …)

## Built-in hardening

The server enforces these defaults — no opt-in required:

- **Rate-limiting** on `/api/login` (5/5min), `/api/passkey/auth/finish`
  (10/5min), and `/api/passkey/register/begin` (5/5min), keyed per remote
  IP. Multi-hop `X-Forwarded-For` chains are ignored to prevent spoofing.
- **Constant-time comparison** (`hmac.compare_digest`) for the login
  code, the setup password, and passkey IDs.
- **Generic error messages** on every passkey auth failure path —
  attackers can't distinguish "credential exists" from "credential not
  registered" via response content or timing.
- **Session cookie**: `HttpOnly` + `SameSite=Lax` always. `Secure` is
  opt-in via `CLIENTCTL_COOKIE_SECURE=true` once you serve over HTTPS.
- **Security headers** on every response: `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
  and a restrictive `Content-Security-Policy` that forbids cross-origin
  fetches and frame embedding.
- **`state/secret.key`** is created with mode `0600` so a shell-level
  attacker on the same machine can't forge sessions.
- **Input validation** on path-derived parameters (`ddc-<n>` brightness
  IDs, the Cachy tray-icon name) — even though `subprocess` runs without
  a shell, defensive whitelisting keeps third-party tools from
  misinterpreting hostile input.
- **`/tmp` script files** for KWin go through `tempfile.mkstemp` (atomic,
  mode 0600) instead of a hardcoded path.

## Continuous scanning in CI

| Workflow | What it does |
|----------|--------------|
| [`codeql.yml`](.github/workflows/codeql.yml) | GitHub CodeQL for Python + JS/TS, on every push and weekly cron |
| [`security.yml`](.github/workflows/security.yml) | Bandit (Python SAST), pip-audit (OSV-backed CVE scan), TruffleHog (verified secret detection across full git history) |
| [`dependabot.yml`](.github/dependabot.yml) | Weekly batched dependency-update PRs |

## Hardening checklist for operators

- Set a strong `PASSKEY_REGISTRATION_PASSWORD` in `.env` (30+ random
  chars; generate with `python -c "import secrets; print(secrets.token_urlsafe(27))"`)
- Register passkeys for every device that should have access — the
  6-digit code is only meant to bootstrap the very first device
- Run behind HTTPS (Cloudflare tunnel, Caddy, nginx, …) and set
  `CLIENTCTL_COOKIE_SECURE=true`
- Keep dependencies current (`pip install -U -r requirements.txt`);
  Dependabot opens PRs weekly, the security workflow re-checks every push
- Restrict file permissions on `state/` (server enforces `0600` on
  `secret.key` and `passkeys.json`)
