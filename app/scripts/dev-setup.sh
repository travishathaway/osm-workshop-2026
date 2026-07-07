#!/usr/bin/env bash
# scripts/dev-setup.sh
#
# Start all services required for parkalyzer local development and integration testing.
# Mirrors the session fixtures in tests/integration/conftest.py.
#
# Usage (from project root, with pixi env active):
#   bash scripts/dev-setup.sh
#
# Ports and paths can be overridden via environment variables:
#   PARKALYZER_PG_PORT   (default: 65432)
#   PARKALYZER_ORS_PORT  (default: 8080)
#
# After the script exits, source the printed export block:
#   export PARKALYZER_DSN='...'
#   export PARKALYZER_ORS_URL='...'

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# -- Configuration -------------------------------------------------------------
PG_PORT="${PARKALYZER_PG_PORT:-65432}"
ORS_PORT="${PARKALYZER_ORS_PORT:-8080}"
DB_NAME="parkalyzer"
PG_USER="postgres"
REGION="brandenburg"
NATIVE_DSN="postgresql://${PG_USER}@localhost:${PG_PORT}/${DB_NAME}"
SQLALCHEMY_DSN="postgresql+psycopg://${PG_USER}@localhost:${PG_PORT}/${DB_NAME}"

# Cache directory - matches platformdirs.user_cache_dir("parkalyzer-tests")
case "$(uname -s)" in
  Darwin) CACHE_DIR="$HOME/Library/Caches/parkalyzer-tests" ;;
  *)      CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/parkalyzer-tests" ;;
esac

OSMPRJ_WORKDIR="$PROJECT_ROOT/.osmprj"
ORS_INSTALL_DIR="$PROJECT_ROOT/.ors"
PG_DATA_DIR="$PROJECT_ROOT/.pgdata"
OSM_PBF="$CACHE_DIR/$REGION-latest.osm.pbf"
OSM_PBF_URL="https://download.geofabrik.de/europe/germany/$REGION-latest.osm.pbf"

# -- Helpers -------------------------------------------------------------------
_log()  { echo; echo "-- $*"; }
_ok()   { echo "   [ok] $*"; }
_info() { echo "    ->  $*"; }
_err()  { echo "ERROR: $*" >&2; exit 1; }

_psql_bool() {
  # Run a SELECT that returns 't' or 'f'; strip whitespace.
  psql "$NATIVE_DSN" -tc "$1" 2>/dev/null | tr -d '[:space:]'
}

# -- 1. PostgreSQL -------------------------------------------------------------
_log "PostgreSQL"

if pg-helper --port "$PG_PORT" --data-dir "$PG_DATA_DIR" status 2>/dev/null \
    | grep -q 'Status: Running'; then
  _ok "PostgreSQL already running"
else
  pg-helper --port "$PG_PORT" --data-dir "$PG_DATA_DIR" start
fi

# Create the application database if it doesn't already exist.
psql "postgresql://${PG_USER}@localhost:${PG_PORT}/postgres" \
  -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" \
  | grep -q 1 \
  || psql "postgresql://${PG_USER}@localhost:${PG_PORT}/postgres" \
       -c "CREATE DATABASE ${DB_NAME}" -q

psql "$NATIVE_DSN" -c "CREATE EXTENSION IF NOT EXISTS postgis" -q

_ok "PostgreSQL ready -- port ${PG_PORT}, database ${DB_NAME}"

# -- 2. OSM PBF ----------------------------------------------------------------
_log "OSM PBF"
mkdir -p "$CACHE_DIR"

if [[ -f "$OSM_PBF" ]]; then
  _ok "Already cached -- ${OSM_PBF}"
else
  _info "Downloading from Geofabrik..."
  curl -L --progress-bar -o "${OSM_PBF}.tmp" "$OSM_PBF_URL"
  mv "${OSM_PBF}.tmp" "$OSM_PBF"
  _ok "Downloaded -- ${OSM_PBF}"
fi

# -- 3. OSM data via osmprj ----------------------------------------------------
_log "OSM data (osmprj)"

mkdir -p "$OSMPRJ_WORKDIR"

echo "$OSMPRJ_WORKDIR/osmprj.toml"

if [[ ! -e "$OSMPRJ_WORKDIR/osmprj.toml" ]]; then
    cd "$OSMPRJ_WORKDIR"
    osmprj init --db "$NATIVE_DSN"
    osmprj add --srid 3857 --path "$OSM_PBF" --name $REGION --theme pgosm
fi

OSM_LOADED=$(_psql_bool \
  "SELECT EXISTS(
     SELECT 1 FROM information_schema.tables
     WHERE table_schema = '$REGION' AND table_name = 'amenity_polygon'
   )")

if [[ "$OSM_LOADED" == "t" ]]; then
  _ok "Already loaded -- amenity_polygon present"
else
  _info "Running osmprj init / add / sync in ${OSMPRJ_WORKDIR} (may take several minutes)..."
  # osmprj stores its project config in the working directory, so all three
  # commands must run from the same directory.
  (
    cd "$OSMPRJ_WORKDIR"
    osmprj sync
  )
  _ok "OSM data loaded"
fi

# -- 4. Zensus census data -----------------------------------------------------
_log "Zensus census data (zensus2pgsql)"

ZENSUS_LOADED=$(_psql_bool \
  "SELECT EXISTS(
     SELECT 1 FROM information_schema.tables
     WHERE table_schema = 'zensus'
       AND table_name LIKE '%alter%altersklassen%'
   )")

if [[ "$ZENSUS_LOADED" == "t" ]]; then
  _ok "Already loaded -- zensus.alter_in_5_altersklassen present"
else
  _info "Creating zensus schema..."
  psql "$NATIVE_DSN" -c "CREATE SCHEMA IF NOT EXISTS zensus" -q

  _info "Importing census data from destatis.de (downloads ~50 MB)..."
  zensus2pgsql create alter_in_5_altersklassen \
    --host     localhost \
    --port     "$PG_PORT" \
    --database "$DB_NAME" \
    --user     "$PG_USER" \
    --schema   zensus \
    --srid     3857 \
    --password ""
  _ok "Zensus data loaded"
fi

# -- 5. OpenRouteService -------------------------------------------------------
_log "OpenRouteService"

HEALTH_URL="http://localhost:${ORS_PORT}/ors/v2/health"

if curl -sf "$HEALTH_URL" > /dev/null 2>&1; then
  _ok "Already running on port ${ORS_PORT}"
else
  mkdir -p "$ORS_INSTALL_DIR"

  _info "Writing ORS config for port ${ORS_PORT} and OSM file..."
  ors-launcher init \
    --osm-file    "$OSM_PBF" \
    --install-dir "$ORS_INSTALL_DIR" \
    --port        "$ORS_PORT"

  _info "Starting ORS in background (logs -> ${ORS_INSTALL_DIR}/ors-stdout.log)..."
  # python3 start_new_session=True is the cross-platform equivalent of setsid:
  # puts ors-launcher and its Java child in a new session (PGID == PID) so
  # "kill -TERM -- -$ORS_PID" terminates the whole group on macOS and Linux.
  ORS_PID=$(python3 -c "
import subprocess, sys
p = subprocess.Popen(
    ['ors-launcher', 'start', '--install-dir', sys.argv[1]],
    stdout=open(sys.argv[2], 'w'),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(p.pid)
" "$ORS_INSTALL_DIR" "${ORS_INSTALL_DIR}/ors-stdout.log")

  _info "Waiting for ORS health check -- first run builds routing graph (3-5 min)..."
  DEADLINE=$((SECONDS + 300))
  until curl -sf "$HEALTH_URL" > /dev/null 2>&1; do
    if (( SECONDS > DEADLINE )); then
      echo ""
      _err "ORS did not become healthy within 5 minutes. Check ${ORS_INSTALL_DIR}/ors-stdout.log"
    fi
    sleep 5
    printf '.'
  done
  echo ""

  _ok "ORS ready -- port ${ORS_PORT} (launcher PID ${ORS_PID})"
  echo "    ->  To stop ORS: kill -TERM -- -${ORS_PID}"
fi

# -- 6. Alembic migrations -----------------------------------------------------
_log "Alembic migrations"

cd "$PROJECT_ROOT"

PARKALYZER_DSN="$SQLALCHEMY_DSN" parkalyzer db migrate

_ok "Schema is up to date"

# -- env.sh --------------------------------------------------------------------
ENV_FILE="$PROJECT_ROOT/env.sh"

cat > "$ENV_FILE" <<EOF
# Generated by scripts/dev-setup.sh — re-run to refresh.
export PARKALYZER_DSN='${SQLALCHEMY_DSN}'
export PARKALYZER_ORS_URL='http://localhost:${ORS_PORT}'
export PARKALYZER_OSM_SCHEMA='brandenburg'
export PARKALYZER_ZENSUS_SCHEMA='zensus'
export PARKALYZER_SRID='3857'
EOF

# -- Summary -------------------------------------------------------------------
echo ""
echo "+-------------------------------------------------------------------+"
echo "|      All services ready for parkalyzer development               |"
echo "+-------------------------------------------------------------------+"
echo ""
echo "  Credentials written to env.sh. To activate:"
echo ""
printf "    source %s\n" "$ENV_FILE"
echo ""
echo "  To stop services:"
printf "    bash %s/scripts/dev-teardown.sh\n" "$PROJECT_ROOT"
echo ""
