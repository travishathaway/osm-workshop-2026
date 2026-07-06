from pathlib import Path

import pytest
from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig
from click.testing import CliRunner

from parkalyzer.main import cli


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


@pytest.mark.integration
def test_routes_status_empty_database(migrated_db):
    """routes status on a migrated but empty database should succeed."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--dsn", migrated_db["dsn"], "routes", "status"])
    assert result.exit_code == 0, result.output
    assert "Parks" in result.output
    assert "Zensus grid cells" in result.output


@pytest.mark.integration
def test_routes_status_shows_zero_counts(migrated_db):
    """An empty database should report 0 parks, 0 census points, 0 pairs."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--dsn", migrated_db["dsn"], "routes", "status"])
    assert result.exit_code == 0, result.output
    # The status table should contain rows with 0 values
    assert "0" in result.output


@pytest.mark.integration
def test_routes_calculate_requires_parks(migrated_db, openrouteservice):
    """calculate should exit with an error when no parks exist."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--dsn", migrated_db["dsn"],
            "--ors-url", openrouteservice["url"],
            "routes", "calculate",
        ],
    )
    # Should fail with a helpful message about missing parks
    assert result.exit_code != 0 or "No parks" in result.output
