# Contributing to clientctl

Thanks for considering a contribution. clientctl is a single-machine
control panel — its scope is intentionally narrow, but additions that
fit that scope (more themes, more app definitions, multi-distro
hardening, accessibility fixes, performance) are very welcome.

## Quick dev setup

```bash
git clone https://github.com/<your-fork>/clientctl.git
cd clientctl

python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Set PASSKEY_REGISTRATION_PASSWORD if you want to register passkeys locally;
# leave empty for code-only login while developing.

./start.sh                     # full launcher (server + tunnel if configured)
.venv/bin/python server.py     # or just the server
```

## Running tests

The suite is hermetic — no KDE/Plasma session, no real subprocesses.
It passes on any Linux box and inside CI.

```bash
pytest                         # full hermetic suite, ~2 seconds
pytest --cov                   # with coverage report
pytest tests/test_themes.py    # single file
```

CI runs the same command on Python 3.11 / 3.12 / 3.13 — make sure your
PR is green there.

## Where things live

```
core/        backend (KWin, /proc, audio, displays, …) — no Flask here
routes/      Flask blueprints — pure HTTP layer, delegate to core/
utils/       generic helpers (encoding, auth decorator, capabilities)
static/      HTML / CSS / JS / favicon / mockup screenshots
tests/       hermetic pytest suite (every test must pass without a desktop session)
examples/    deployment templates (.desktop launcher, systemd services)
```

Backend files **never** import from Flask directly. Routes own the HTTP
layer; the backend modules in `core/` are reusable, testable units.

## Common contributions

### Adding a new theme

Themes live in [`themes.yml`](themes.example.yml) (auto-copied from
`themes.example.yml` on first launch — your local `themes.yml` is
gitignored, the example file is what ships in the repo).

1. Add a new entry under `themes:` in `themes.example.yml`. The schema
   is validated by [`core/themes.py`](core/themes.py) — every palette
   must define the full `REQUIRED_KEYS` set or the theme is rejected at
   load time.
2. Provide a `label` (shown in the picker) and an `accent` (used as the
   swatch color); the rest of the palette is rendered as a live preview
   card.
3. `pytest tests/test_themes.py` enforces variable parity across all
   themes.
4. Hot-reload without a server restart: `POST /api/themes/reload` (or
   restart). The CSS at `/themes.css` is regenerated from the YAML.

### Adding an app to the grid

`apps.example.yml` is the template that ships with the repo. For your
local setup edit `apps.yml` (gitignored) — see the comments at the top
of either file for field documentation.

### Adding a new endpoint

1. Backend logic goes into `core/<module>.py`. No Flask imports there.
2. The HTTP handler goes into `routes/<module>.py` as a Blueprint route.
3. Decorate authenticated endpoints with `@require_auth` from `utils.auth`.
4. Register the blueprint in `server.create_app()` if it's a new file.
5. Add a corresponding test under `tests/test_routes_<module>.py`.

### Bumping the version

`config.VERSION` and the `version` key in `pyproject.toml` are mirrored.
The smoke test (`tests/test_smoke.py::test_version_matches_pyproject`)
fails if they drift. Update both and tag:

```bash
git tag v0.2.0
git push origin v0.2.0
# The release workflow runs tests, verifies the tag matches config.VERSION,
# and creates the GitHub release with auto-generated notes.
```

A snapshot of the build numbers for each tag lives under
[`docs/releases/`](docs/releases/) — committed at release time so the
GitHub page has a browsable per-version history (test count, Bandit
findings, repo size, route count, …). The maintainer's check tooling
that produces those snapshots is internal and not in this repo.

## Code conventions

- **English everywhere** — comments, variable names, log messages,
  user-facing strings. The test suite scans for German-only words and
  accents in tracked files.
- **No private data** in tracked files — paths in `apps.yml` go through
  `config.expand_paths()`; secrets live in `.env` (gitignored).
- **Capability-aware features** — anything that depends on a specific
  tool/backend (KDE, ddcutil, intel_gpu_top, …) must be detected in
  `utils/caps.py` and gracefully hidden in the UI when missing.
- **Tests are hermetic** — no real subprocess / DBus / hardware calls
  in the test suite. Use the existing fixtures in `tests/conftest.py`.

Code style is enforced by `ruff` in CI as a warning. Run locally:

```bash
pip install ruff
ruff check .
```

## Submitting a PR

1. Fork → branch → push → open PR.
2. Fill in the PR template — especially the "Tested on" section. We
   accept PRs from contributors who only tested on one distro, but
   knowing where it was verified helps reviewers.
3. CI must be green.
4. Keep PRs focused. One logical change per PR — much easier to review
   than a 30-file refactor + bug fix bundle.

## Reporting issues

Use the issue templates: bug reports want the `/api/capabilities`
output, the version, and your distro/desktop. That's enough information
to reproduce 90% of the time.

Security issues: do **not** open a public issue — see [SECURITY.md](SECURITY.md).

## Licensing

By contributing you agree your work is licensed under the MIT License
of this repository. We don't ask for a CLA — GitHub's *inbound = outbound*
default applies.
