from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import httpx
import pytest
import platformdirs
from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig

from parkalyzer.constants import APP_NAME

REGION = "bremen"
OSM_PBF_URL = f"https://download.geofabrik.de/europe/germany/{REGION}-latest.osm.pbf"
ZENSUS_DATASET = "alter_in_5_altersklassen"
SRID = "3857"

def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _alembic_cfg(dsn: str) -> AlembicConfig:
    ini_path = Path(__file__).parent.parent.parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", dsn)
    return cfg


@pytest.fixture(scope="module")
def migrated_db(postgresql):
    """Run alembic migrations once for this test module."""
    alembic_cmd.upgrade(_alembic_cfg(postgresql["dsn"]), "head")
    return postgresql


@pytest.fixture(scope="session")
def postgresql(tmp_path_factory):
    """Start a temporary PostgreSQL cluster with PostGIS enabled.

    Yields a dict with connection details:
        port, host, database, user, dsn (SQLAlchemy), native_dsn (libpq)
    """
    from pg_helper.postgres import PostgresCluster

    port = _find_free_port()
    data_dir = tmp_path_factory.mktemp("pgdata") / "cluster"

    cluster = PostgresCluster(data_dir=data_dir, port=port)
    cluster.setup(databases=["parkalyzer"], enable_postgis=True)

    yield {
        "port": port,
        "host": "localhost",
        "database": "parkalyzer",
        "user": "postgres",
        "dsn": f"postgresql+psycopg://postgres@localhost:{port}/parkalyzer",
        "native_dsn": f"postgresql://postgres@localhost:{port}/parkalyzer",
    }

    cluster.teardown(remove_data=True)

@pytest.fixture(scope="session")
def cache_dir():
    """Ensure cache directory exists."""
    location = Path(platformdirs.user_cache_dir(f"{APP_NAME}-tests"))
    location.mkdir(parents=True, exist_ok=True)

    return location

@pytest.fixture(scope="session")
def osm_pbf(cache_dir):
    """Provide the Bremen OSM PBF file path, downloading it if not cached.
    """
    pbf = cache_dir / f"{REGION}-latest.osm.pbf"
    if not pbf.exists():
        urllib.request.urlretrieve(OSM_PBF_URL, pbf)
    return pbf


@pytest.fixture(scope="session")
def osmprj_data(postgresql, osm_pbf, tmp_path_factory):
    """Load Bremen OSM data into the test PostgreSQL database via osmprj.

    Uses the 'pgosm' theme to populate planet_osm_polygon and related tables
    in the public schema (SRID 3857), which is what the parks find command reads.
    """
    workdir = tmp_path_factory.mktemp("osmprj")

    subprocess.run(
        [
            "osmprj", "init",
            "--db", postgresql["native_dsn"],
        ],
        check=True,
        cwd=workdir,
    )

    subprocess.run(
        [
            "osmprj", "add",
            "--srid", SRID,
            "--path", str(osm_pbf),
            "--theme", "pgosm",
            "--name", REGION
        ],
        check=True,
        cwd=workdir,
    )

    subprocess.run(
        [
            "osmprj", "sync",
        ],
        check=True,
        cwd=workdir,
    )
    yield workdir


@pytest.fixture(scope="session")
def zensus_data(postgresql):
    """Import the alter_in_5_altersklassen Zensus dataset into the test database.

    Creates the 'zensus' schema first (required by zensus2pgsql), then runs
    zensus2pgsql to download and import the census grid data.
    Downloads from destatis.de — requires internet access on first run.
    """
    from sqlalchemy import create_engine, text

    # zensus2pgsql checks that the target schema exists and exits 1 if not.
    engine = create_engine(postgresql["dsn"])
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS zensus"))
        conn.commit()
    engine.dispose()

    subprocess.run(
        [
            "zensus2pgsql", "create", ZENSUS_DATASET,
            "--host", postgresql["host"],
            "--port", str(postgresql["port"]),
            "--database", postgresql["database"],
            "--user", postgresql["user"],
            "--schema", "zensus",
            "--srid", SRID,
            "--password", "",  # trust auth — any value avoids the interactive password prompt
        ],
        check=True,
    )
    yield postgresql


@pytest.fixture(scope="session")
def openrouteservice(tmp_path_factory, osm_pbf):
    """Start an OpenRouteService instance for the test session.

    Uses the Bremen OSM PBF for routing graphs. First run builds the graph,
    which can take several minutes. Subsequent runs reuse cached graphs in the
    installation directory (inside tmp_path_factory, so NOT cached across test runs).

    Yields a dict with:
        port: int — the port ORS is listening on
        url:  str — base URL, e.g. http://localhost:PORT
    """
    port = _find_free_port()
    install_dir = tmp_path_factory.mktemp("ors")

    # Write the ORS config for this port and OSM file.
    subprocess.run(
        [
            "ors-launcher", "init",
            "--osm-file", str(osm_pbf),
            "--install-dir", str(install_dir),
            "--port", str(port),
        ],
        check=True,
    )

    # ors-launcher start is a blocking foreground process that streams ORS output.
    # Run it as a background Popen with start_new_session=True so that both
    # ors-launcher and its child `ors` (Java) process share the same process group.
    # os.killpg at teardown kills the entire group cleanly.
    proc = subprocess.Popen(
        ["ors-launcher", "start", "--install-dir", str(install_dir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    health_url = f"http://localhost:{port}/ors/v2/health"
    deadline = time.monotonic() + 300  # 5-minute startup timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(health_url, timeout=2.0).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    else:
        os.killpg(proc.pid, signal.SIGTERM)
        raise RuntimeError(
            f"ORS did not become healthy within 5 minutes at {health_url}"
        )

    yield {"port": port, "url": f"http://localhost:{port}"}

    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
