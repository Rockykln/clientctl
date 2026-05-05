# Roadmap

Ideas for future versions. None of this is promised — what ships and
what doesn't depends on whether it stays useful and in-scope. Open an
issue if you'd vote for one of these or have something else to add.

| Symbol | Meaning |
|--------|---------|
| ☐  | planned |
| 🚧 | in progress |
| ✅ | done |
| ❌ | rejected |

| Effort | Rough scale |
|--------|-------------|
| **S** | a few hours, mostly UI / config |
| **M** | a few days, new endpoint or backend module |
| **L** | weeks, new architecture / cross-platform work |


## User interface

- ☐ **[S] More themes** — community palettes welcome via PR. Add an
  entry to `themes.example.yml` covering all `REQUIRED_KEYS`; the
  validator + test suite catch incomplete blocks.
- ✅ **[S] Auto-theme via `prefers-color-scheme`** — follow the OS / browser
  appearance setting unless the user explicitly picked one. Lands as the
  10th picker entry; bootstrap resolves it before CSS paints (no FOUC).
- ☐ **[S] Compact mode** — denser layout for phone-sized portrait viewports.
- ☐ **[S] Custom keyboard shortcuts** — `1`–`9` toggle the matching cell
  when the panel has focus on a desktop browser. Configurable.
- ☐ **[M] Drag-to-reorder grid cells** — order is in `apps.yml`; a UI
  reorder writes back through a new `/api/apps/order` endpoint.
- ☐ **[S] Stats sparklines** — last 60 seconds of CPU / RAM as a tiny
  inline chart on each stat pill.


## App grid + launcher

- ☐ **[S] Icon resolution by theme name** — instead of full paths in
  `apps.yml`, accept icon names that resolve against `XDG_DATA_DIRS`.
  Less brittle when distros move icon paths around.
- ☐ **[M] Per-app CPU / RAM** in the long-press menu so you can spot
  the Electron app eating your battery without Plasma System Monitor.
- ☐ **[M] Quick-actions row** — user-defined shortcut buttons at the
  top of the grid (`bash -c "..."`, paste-text, sleep, …).
- ☐ **[S] Cell search / filter** — Cmd+K palette over the grid, useful
  once the app list grows past 12.


## System integration

- ☐ **[S] Workspace switcher** — KWin virtual desktops as a tiny strip
  in the header.
- ☐ **[S] One-click screenshot** of the current desktop, served as a
  transient image to the panel.
- ☐ **[M] System-tray dropdown** — show all StatusNotifierItems in a
  panel, not just the Cachy cell.
- ☐ **[M] Clipboard history** — read klipper's history into a dropdown,
  click to re-copy on the PC.


## Automation

- ☐ **[L] Scenes / automations** — "Movie mode" sets brightness 30%, DND
  on, audio profile to TV. Triggered manually or by time / event.
- ☐ **[L] Push notifications** to your device when something happens on
  the PC (battery low, build finished, system update available).


## Authentication & access

- ☐ **[M] Two-factor passkey** for destructive actions (shutdown,
  server-kill, passkey-delete) — re-auth required, not just a session.
- ☐ **[L] Multi-host control** — one panel UI, switchable between
  several PCs via a dropdown. Each PC runs its own clientctl + tunnel.


## Performance & architecture

- ✅ **[L] Live updates via Server-Sent Events** — battery, sysinfo, lock
  state pushed via `/api/events` instead of polled. Polling stays as a
  fallback when the stream isn't connected. Cuts request volume ~10×.
  (Used SSE rather than WebSockets — simpler, no new dep, EventSource
  has built-in reconnect, and we only need server→client push.)
- ☐ **[L] Plugin API** — defined interface for third-party cells /
  dropdowns loaded from a `plugins/` directory.


## Platform support

- ☐ **[L] GNOME / Mutter support** — port KWin window-state queries to
  `gdbus call org.gnome.Shell.Eval`. Deal-breaker for half the Linux desktop.
- ☐ **[L] Hyprland / Sway / i3** support via their respective IPC sockets.
- ☐ **[M] Voice control** — Web Speech API in the browser for "Hey
  clientctl, open Firefox". Privacy-friendly because it stays in the browser.
- ☐ **[S] Native iOS Shortcuts** — Siri integration via the Shortcuts
  app. Mostly docs + a curated list of API calls.


## Developer experience & operations

- ✅ **[M] Service worker / installable PWA** — manifest + SW cache the
  static shell, "Add to Home Screen" on iOS/Chrome installs the panel
  as a standalone app. `/api/*` is never cached; only the shell.
- ☐ **[M] i18n** — externalize strings, ship German + English baseline.
- ☐ **[M] Backup / restore** for `state/` — encrypt → zip → download.
- ☐ **[M] Playwright browser tests** for the parts the hermetic pytest
  suite can't reach (drag, slider behavior, modal dialogs).


## Definitively out of scope

- ❌ **Cloud-hosted SaaS version** — clientctl is intentionally local.
  No managed offering, no telemetry endpoint, no central account system.
- ❌ **Closed-source extensions / paid tier** — MIT means MIT.
- ❌ **Mobile push without a tunnel** — the architecture assumes the
  panel reaches your PC, not the other way around. Push would require
  the PC to talk to a third-party service we don't control.
