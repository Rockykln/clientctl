# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-05

Initial public release.

### Added

#### App grid + launcher
- 4×3 grid of app cells, configured via [`apps.yml`](apps.example.yml).
- Toggle behaviour: launch if not running, otherwise minimise/restore via KWin.
- Long-press action menu — close, **minimize/restore** (label and icon
  switch based on window state), pause (SIGSTOP/SIGCONT), kill (SIGKILL).
  PWAs skip pause/kill since both would freeze the parent Chromium.
- Live state per cell: active (green), background (grey), paused (yellow),
  off — pushed via `/api/apps/status` poll every 1.5 s.
- Special `cachy` cell for arch-update (Arch / CachyOS) with inline
  data-URL fallback icon for when the server dies between refreshes.
- App icons resolve via `~` and `$VAR` expansion, served at
  `/api/app/<id>/icon` with `Cache-Control: public, max-age=86400`.

#### Themes (8 + Auto)
- Dark (default), Light, Midnight, Dim, Nord, Catppuccin, Tokyo Night,
  Gruvbox, plus an **Auto** option that follows
  `prefers-color-scheme` and updates live when the OS preference changes.
- Picker in the settings dropdown renders each card as a live preview of
  its theme (matching bg / border / text / accent), not just a swatch
  icon. Pressed-state is highlighted with a soft accent glow.
- Palettes live in [`themes.yml`](themes.example.yml) (auto-copied from
  the example on first run). Hot-reload via `/api/themes/reload` —
  `core/themes.py` validates `REQUIRED_KEYS` and rejects incomplete
  palettes with a warning.
- Configurable cap: default 8, override with `CLIENTCTL_THEMES_LIMIT`,
  `0` disables. Themes beyond the cap are dropped in YAML order with a
  warning that names every dropped entry.
- Theme choice persists per-device in `localStorage`. The bootstrap
  script in [`/theme-bootstrap.js`](static/theme-bootstrap.js) applies
  the `data-theme` attribute before CSS paints — no FOUC.
- Test suite enforces parity of `REQUIRED_KEYS` across every theme.

#### Real-time live state
- **Server-Sent Events** at [`/api/events`](routes/system.py) replace
  several polling loops (sysinfo / battery / lock-state) with a single
  long-lived push connection. Cuts request volume by ~10× during normal
  use. Producer threads in [`core/realtime.py`](core/realtime.py) push
  state changes; clients subscribe via the standard `EventSource` API
  (built-in reconnect, no new dep).
- Polling stays as a fallback when the stream isn't connected, gated on
  `sse.connected` so we don't double up.
- Polling timers (`/api/ping`, `/api/battery`, `/api/sysinfo`,
  `/api/status` lock-poll …) stop on logout and when `applyAuthState`
  detects `!authed` — the server isn't hammered while the user sits on
  the login card.

#### Progressive Web App
- [`/manifest.webmanifest`](static/manifest.webmanifest) declares the
  panel as installable, with PWA icons in 192×192 + 512×512 (`purpose:
  "any maskable"`) and a 180×180 Apple touch icon for iOS.
- Service worker at [`/sw.js`](static/sw.js) precaches the static shell
  on install. `/api/*` is never cached (always live state); only the
  shell falls back to cache when the network is unreachable. Versioned
  cache name auto-clears old shells on update.
- Registered only in `isSecureContext` (HTTPS or localhost).

#### System controls
- Master volume slider + per-app stream sliders with mute (PipeWire via
  `wpctl`, PulseAudio via `pactl` — capability-detected).
- Brightness sliders per display: KDE PowerManagement (laptop) + DDC/CI
  (external monitors via `ddcutil`).
- Power profile cycling (power-saver / balanced / performance via
  `net.hadess.PowerProfiles`).
- Do-not-disturb (KDE `plasmanotifyrc` + freedesktop
  `Notifications.Inhibit` so non-KDE apps that respect the standard
  also stop notifying).
- Live notification history captured via `dbus-monitor` subprocess
  (last 30, in-memory deque).
- Lock / shutdown / server-kill / sign-out buttons. KDE-native shutdown
  dialog with `loginctl poweroff` fallback.
- Battery state (UPower) with charge animation, low/empty thresholds,
  charging bolt.

#### Stats row
- Live CPU, RAM, GPU, process count, network throughput.
- GPU support: AMD (sysfs `gpu_busy_percent`), Intel (`intel_gpu_top -J`
  streaming JSON parser, requires `cap_perfmon`), NVIDIA (`nvidia-smi`).
- Three-tier ping classification (good/ok/bad), median over the last 3
  samples, jitter shown in tooltip, hard 3 s timeout via AbortController.

#### Authentication
- 6-digit code login (10-minute TTL, regenerated on server start; renew
  on demand via `kill -USR1 <pid>`).
- WebAuthn passkeys (configurable max, default 2) with biometric unlock
  on supported hardware.
- Server-side challenge store keyed by token (cookie-independent
  begin/finish flow).
- Auto-unlock the PC after passkey verification (`loginctl unlock-session`).
- Session cookies survive server restart (persistent secret key, 0600).
- "Remember me on this device" extends session to 14 days (default 7).
- WebAuthn secure-context detection — passkey buttons are hidden with
  an inline hint when the page is loaded over plain HTTP from a
  non-loopback host. Avoids the cryptic
  "navigator.credentials is undefined" error on the LAN.
- Passkey list shows production-safe device identification — date + time
  + MAC (read from `/proc/net/arp` for LAN clients) or compact UA
  summary (`iPad · Safari` etc.) when registered through the tunnel.
  Independent server-side `use_count` + `last_used` fields track every
  successful auth (Apple/Hello pin WebAuthn `sign_count` to 0 by spec,
  so we count ourselves).
- Add-passkey button reflects server setup — `/api/passkey/list`
  reports `registration_enabled`. Frontend disables the button with an
  inline hint pointing at `.env` when `PASSKEY_REGISTRATION_PASSWORD`
  is not configured.

#### Multi-distro support
- Capability detection at startup ([`utils/caps.py`](utils/caps.py))
  for KDE Plasma, KDE brightness, ddcutil, audio backend, battery,
  power-profiles-daemon, logind, GPU vendor, dbus-monitor, cachy,
  session type, desktop environment.
- Frontend hides buttons whose backends are missing via the `data-cap`
  attribute.
- **Feature opt-out** — `CLIENTCTL_DISABLE_FEATURES=audio,gpu,brightness`
  hides any detected capability from the UI even when the backend is
  present. The special `brightness` alias hides both `kde_brightness`
  and `ddc` paths in one go. Documented in
  [`.env.example`](.env.example).
- Graceful fallbacks: KDE-Plasma shutdown dialog → systemd-logind
  poweroff.

#### Performance
- Single `/proc` walk (cached 0.8 s) replacing the old pgrep cascade —
  ~30× faster.
- KWin window-state cache 0.4 s; KWin scripts dispatched via
  `tempfile.mkstemp` (atomic, mode 0600).
- Threaded Flask: slow KWin/journalctl calls don't block other requests.
- Display + audio preload during `initApp()` so dropdowns feel instant
  the first time they're opened, even when ddcutil is slow.

#### Frontend
- Brand mark next to the `clientctl` heading in the header (inline SVG
  `</>` bracket logo, takes its color from the theme accent via
  `currentColor`).
- Bottom-right footer with the running version and an optional repo
  link (octocat icon). The repo URL is a single-source-of-truth
  constant alongside `VERSION` in [`config.py`](config.py); leave it
  empty to hide the link. The `#app` reserves a clear strip below the
  grid so the footer never overlaps a cell.
- **Custom confirm modal** replaces native `window.confirm()` for
  shutdown, server-kill, sign-out and passkey-delete. Theme-aware,
  scale-in animation, Esc / Enter keyboard shortcuts, click-outside
  cancels, danger variant for destructive actions. Cancel and confirm
  buttons are sized identically.
- **iPad-safe custom checkbox** for "Remember me on this device" — the
  native input is visually hidden and the visible 18×18 box is rendered
  via a `::before` pseudo-element on the `<span>`. Works around iOS
  Safari ignoring `width`/`height` on form controls even with
  `appearance: none`.
- Dynamic grid rendered from `/api/apps/list`.
- Drag-tracking on all sliders (no thumb-snap during drag); slider gap
  sized so the thumb at 0% / 100% never overlaps the percentage label.
- Toast notifications top-centre, no overlap with header; theme-aware
  via `--toast-bg` / `--toast-border`.
- Lock-screen overlay with passkey unlock fallback.

#### Ops + deployment
- [`start.sh`](start.sh) launcher boots Flask + (optional) Cloudflare
  tunnel with trap-based cleanup. Reads `CLIENTCTL_MODE` /
  `CLIENTCTL_TUNNEL` from `.env` via an awk parser (not bash `source`)
  — values are treated as literal strings, no command substitution.
- Three deployment modes via `CLIENTCTL_MODE`: `dev` (127.0.0.1 only,
  no tunnel), `lan` (0.0.0.0, no tunnel — default), `tunnel` (127.0.0.1
  + cloudflared).
- Auto-init on first run: copies `apps.example.yml` → `apps.yml`,
  `themes.example.yml` → `themes.yml`, `cloudflared.example.yml` →
  `cloudflared.yml`.
- Logging via Python `logging` (level via `CLIENTCTL_LOG_LEVEL`).
- Clean module split: `core/` (backend, no Flask), `routes/` (HTTP
  blueprints), `utils/` (helpers).
- Deployment templates in [`examples/`](examples/) —
  `clientctl.desktop` (KDE app launcher, locale-portable via
  `xdg-user-dir DESKTOP`), `clientctl.service` (systemd user service
  running the server headless), `clientctl-tunnel.service` (companion
  service for the Cloudflare tunnel) plus an
  [`examples/README.md`](examples/README.md) with one-liner install
  commands.

#### Tooling
- [`.editorconfig`](.editorconfig) and
  [`.gitattributes`](.gitattributes) for consistent line endings and
  indentation across editors and platforms.
- `*.local.*` gitignore pattern for personal scratch files.

#### Tests + CI
- 180-test hermetic pytest suite — runs on any Linux box, no KDE /
  Plasma session required, no real subprocess calls (the test fixtures
  block them).
- [`.github/workflows/test.yml`](.github/workflows/test.yml): matrix on
  Python 3.11 / 3.12 / 3.13, ruff lint.
- [`.github/workflows/codeql.yml`](.github/workflows/codeql.yml):
  GitHub CodeQL for Python + JS/TS, gated to public repos, weekly cron.
- [`.github/workflows/release.yml`](.github/workflows/release.yml):
  tag-driven GitHub release with `config.VERSION` ↔ `pyproject.toml`
  version-sync gate.
- [`.github/dependabot.yml`](.github/dependabot.yml): grouped weekly PRs
  for `pip` (flask-stack / webauthn-stack / runtime / dev-tools) and
  `github-actions`.

### Security

The server enforces these defaults — no opt-in required.

- **Rate-limiting** on `/api/login` (5 / 5 min),
  `/api/passkey/auth/finish` (10 / 5 min),
  `/api/passkey/register/begin` (5 / 5 min). Multi-hop
  `X-Forwarded-For` is rejected so an attacker can't spoof their way
  out of the per-IP bucket.
- **Constant-time comparison** (`hmac.compare_digest`) for the login
  code, the setup password and passkey IDs.
- **Generic passkey-auth errors** — every failure path returns the same
  message so attackers can't enumerate registered credentials by
  response content or timing.
- **Session cookie**: `HttpOnly` + `SameSite=Lax` always. `Secure`
  opt-in via `CLIENTCTL_COOKIE_SECURE` once you serve over HTTPS.
- **Security headers** on every response: `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
  `Permissions-Policy` (camera/mic/geo/payment/usb explicitly disabled),
  a strict `Content-Security-Policy` with no `'unsafe-inline'` for
  scripts (`worker-src 'self'` + `manifest-src 'self'` permit the SW +
  PWA manifest), and `Strict-Transport-Security` when
  `CLIENTCTL_COOKIE_SECURE` is on.
- **Server header neutralised** — Werkzeug's framework + version banner
  is replaced with `Server: clientctl` so the response doesn't disclose
  the underlying stack.
- **`/api/capabilities` is auth-gated** — its response fingerprints the
  host (KDE version, GPU vendor, session type, installed binaries). On a
  public-facing tunnel an unauthenticated probe could otherwise enumerate
  the stack.
- **FOUC theme bootstrap** lives in
  [`static/theme-bootstrap.js`](static/theme-bootstrap.js) (not inline
  in `<head>`) so the CSP can forbid inline scripts entirely.
- **`state/secret.key`** and **`state/passkeys.json`** are written with
  mode `0600`.
- **Input whitelist** on path-derived parameters (`ddc-<n>` brightness
  IDs, the Cachy tray-icon name) — even though `subprocess` runs without
  a shell, defensive whitelisting keeps third-party tools from
  misinterpreting hostile input.
- **KWin script tempfiles** go through `tempfile.mkstemp` (atomic, mode
  0600) — no symlink-race / world-readable hardcoded `/tmp` paths.
- **`start.sh`** parses `.env` with an awk reader instead of bash
  `source` — values are literal strings, no command substitution.
- [`.github/workflows/security.yml`](.github/workflows/security.yml)
  runs on every push: Bandit (Python SAST), pip-audit (OSV-backed
  dependency CVEs), TruffleHog (verified-secret scan over the full git
  history). All action references pinned to major-version tags.
- Bandit config in [`pyproject.toml`](pyproject.toml) — 0 medium/high
  findings on the production paths.
- 25+ regression tests under
  [`tests/test_security.py`](tests/test_security.py) pin every
  hardening step (rate-limit, headers, cookie flags, input validation,
  generic error messages, file permissions, HSTS gating, capabilities
  auth-gate, XFF spoofing).

[0.1.0]: https://github.com/_/clientctl/releases/tag/v0.1.0
