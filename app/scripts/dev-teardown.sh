#!/usr/bin/env bash
# scripts/dev-teardown.sh
#
# Stop all services started by scripts/dev-setup.sh.
#
# Usage (from project root, with pixi env active):
#   bash scripts/dev-teardown.sh
#
# Ports and paths can be overridden via the same environment variables as
# dev-setup.sh:
#   PARKALYZER_PG_PORT   (default: 65432)
#   PARKALYZER_ORS_PORT  (default: 8080)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# -- Configuration (mirrors dev-setup.sh) --------------------------------------
PG_PORT="${PARKALYZER_PG_PORT:-65432}"
PG_DATA_DIR="$PROJECT_ROOT/.pgdata"

# -- Helpers -------------------------------------------------------------------
_log()  { echo; echo "-- $*"; }
_ok()   { echo "   [ok] $*"; }
_info() { echo "    ->  $*"; }

# -- 1. OpenRouteService -------------------------------------------------------
_log "OpenRouteService"

# pgrep -of: oldest process whose full argument list matches the pattern.
# The negated PID sends SIGTERM to the entire process group (launcher + Java).
ORS_PID=$(pgrep -of 'ors-launcher start' 2>/dev/null || true)
if [[ -n "$ORS_PID" ]]; then
  _info "Sending SIGTERM to ORS process group (PID ${ORS_PID})..."
  kill -TERM -- "-${ORS_PID}" 2>/dev/null || true
  _ok "ORS stopped"
else
  _ok "ORS not running"
fi

# -- 2. PostgreSQL -------------------------------------------------------------
_log "PostgreSQL"

if pg-helper --port "$PG_PORT" --data-dir "$PG_DATA_DIR" status 2>/dev/null \
    | grep -q 'Status: Running'; then
  _info "Stopping PostgreSQL on port ${PG_PORT}..."
  pg-helper --port "$PG_PORT" --data-dir "$PG_DATA_DIR" stop
  _ok "PostgreSQL stopped"
else
  _ok "PostgreSQL not running"
fi

echo ""
echo "+-------------------------------------------------------------------+"
echo "|      All services stopped                                         |"
echo "+-------------------------------------------------------------------+"
echo ""
