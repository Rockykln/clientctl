#!/usr/bin/env bash
# clientctl launcher — starts the Flask server + (optionally) the
# Cloudflare tunnel, prints the login code, and shuts everything down
# cleanly when the terminal is closed (via trap).

set -u
cd "$(dirname "$(readlink -f "$0")")"

PROJECT_DIR="$PWD"
LOGS_DIR="$PROJECT_DIR/state/logs"
mkdir -p "$LOGS_DIR"

SERVER_LOG="$LOGS_DIR/server.log"
TUNNEL_LOG="$LOGS_DIR/tunnel.log"

# Prevent Python from writing .pyc files at all — keeps the project tree clean
# and avoids stale-bytecode confusion across version bumps.
export PYTHONDONTWRITEBYTECODE=1

# Read CLIENTCTL_MODE / CLIENTCTL_TUNNEL out of .env without `source`-ing it.
# Sourcing would interpret the file as bash — anything resembling
# command-substitution (e.g. a password containing `$(...)` or backticks)
# would execute. This grep-based parser only reads the keys we need and
# treats their values as literal strings.
read_env() {
    local key="$1"
    [[ -f .env ]] || return
    awk -F= -v k="$key" '
        $0 ~ "^[[:space:]]*#" { next }
        $1 == k {
            sub(/^[^=]*=/, "")
            sub(/[[:space:]]*#.*$/, "")
            sub(/^[[:space:]]*"/, ""); sub(/"[[:space:]]*$/, "")
            sub(/^[[:space:]]*'\''/, ""); sub(/'\''[[:space:]]*$/, "")
            print; exit
        }
    ' .env
}
[[ -z "${CLIENTCTL_MODE:-}"   ]] && CLIENTCTL_MODE="$(read_env CLIENTCTL_MODE)"
[[ -z "${CLIENTCTL_TUNNEL:-}" ]] && CLIENTCTL_TUNNEL="$(read_env CLIENTCTL_TUNNEL)"
export CLIENTCTL_MODE CLIENTCTL_TUNNEL

# ── First-run setup ────────────────────────────────────────────────────
# apps.yml is also auto-created by the server; here we only handle the
# cloudflared.yml case before starting cloudflared.
if [[ ! -f apps.yml && -f apps.example.yml ]]; then
    cp apps.example.yml apps.yml
    echo "▶ apps.yml created from apps.example.yml — edit if needed."
fi

cleanup() {
    echo
    echo "▼ stopping clientctl ..."
    [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null
    [[ -n "${TUNNEL_PID:-}" ]] && kill "$TUNNEL_PID" 2>/dev/null
    sleep 0.5
    [[ -n "${SERVER_PID:-}" ]] && kill -9 "$SERVER_PID" 2>/dev/null
    [[ -n "${TUNNEL_PID:-}" ]] && kill -9 "$TUNNEL_PID" 2>/dev/null
    wait 2>/dev/null
    # Remove transient artifacts: __pycache__ + .pytest_cache + .coverage
    find "$PROJECT_DIR" \
        \( -type d \( -name "__pycache__" -o -name ".pytest_cache" \) \
           -not -path "*/.venv/*" -not -path "*/.git/*" -prune \
           -exec rm -rf {} + \) -o \
        \( -type f \( -name ".coverage" -o -name ".coverage.*" -o -name "coverage.xml" \) \
           -not -path "*/.venv/*" -delete \) \
        2>/dev/null || true
    echo "✓ stopped"
}
trap cleanup EXIT INT TERM

# ── Start Flask server ────────────────────────────────────────────────
: > "$SERVER_LOG"
.venv/bin/python -u server.py > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!

# Wait for the banner (until the server is ready)
for _ in $(seq 1 50); do
    grep -q 'Serving Flask app' "$SERVER_LOG" 2>/dev/null && break
    sleep 0.1
done

# Print banner (everything up to Flask's startup line)
awk '/Serving Flask app/{exit} {print}' "$SERVER_LOG"

# ── Cloudflared (only in tunnel mode) ─────────────────────────────────
# Mode comes from CLIENTCTL_MODE (default: lan). Only the `tunnel` mode
# starts cloudflared. dev/lan modes leave it stopped.
MODE="${CLIENTCTL_MODE:-lan}"
[[ "${CLIENTCTL_TUNNEL:-}" =~ ^(1|true|yes)$ ]] && MODE=tunnel
TUNNEL_STARTED=0

if [[ "$MODE" == "tunnel" ]]; then
    if ! command -v cloudflared >/dev/null 2>&1; then
        echo "✗ MODE=tunnel but cloudflared is not installed."
        echo "  Install it (e.g. 'pacman -S cloudflared') or set CLIENTCTL_MODE=lan."
    elif [[ ! -f cloudflared.yml ]]; then
        if [[ -f cloudflared.example.yml ]]; then
            cp cloudflared.example.yml cloudflared.yml
            echo "i cloudflared.yml created from example — fill in tunnel ID + credentials-file, then restart."
        else
            echo "✗ MODE=tunnel but cloudflared.yml is missing."
        fi
    elif grep -q '<YOUR-TUNNEL-ID>' cloudflared.yml 2>/dev/null; then
        echo "i cloudflared.yml is still the example — tunnel skipped."
        echo "  Edit it (tunnel ID + credentials-file), then restart."
    else
        echo "▶ starting Cloudflare tunnel ..."
        : > "$TUNNEL_LOG"
        cloudflared tunnel --config cloudflared.yml run > "$TUNNEL_LOG" 2>&1 &
        TUNNEL_PID=$!
        TUNNEL_STARTED=1
        for _ in $(seq 1 50); do
            grep -q 'Registered tunnel connection\|Connection registered' "$TUNNEL_LOG" 2>/dev/null && break
            sleep 0.2
        done
    fi
fi

echo
echo "============================================================"
echo "  ✓ clientctl is running   ($MODE mode)"
echo "============================================================"
echo
[[ "$TUNNEL_STARTED" == 1 ]] && echo "  Tunnel       running (see cloudflared.yml)"
echo "  Logs         $LOGS_DIR/"
echo "  Stop         close this window or Ctrl-C"
echo
echo "============================================================"
echo

# Hold until a process dies or the user breaks out
wait
