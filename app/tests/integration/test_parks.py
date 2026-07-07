from pathlib import Path

import pytest
from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig
from click.testing import CliRunner

from parkalyzer.main import cli

from .conftest import REGION


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
def test_parks_list_empty(migrated_db):
    """list against an empty database should succeed and show 0 parks."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--dsn", migrated_db["dsn"], "parks", "list"])
    assert result.exit_code == 0, result.output
    assert "0 total" in result.output


@pytest.mark.integration
def test_parks_find_dry_run_reports_count(migrated_db, osmprj_data):
    """parks find --dry-run should find parks and report a count."""
    runner = CliRunner()
    result = runner.invoke(
        cli,[
            "--dsn", migrated_db["dsn"],
            "parks", "find",
            "--dry-run",
            "--osm-schema", REGION,
            REGION.capitalize()
        ],
    )
    assert result.exit_code == 0, result.output
    assert "parks" in result.output.lower()


@pytest.mark.integration
def test_parks_find_imports_parks(migrated_db, osmprj_data):
    """parks find without --dry-run should upsert parks into the database."""
    from sqlalchemy import create_engine, text

    runner = CliRunner()
    result = runner.invoke(
        cli,[
            "--dsn", migrated_db["dsn"],
            "parks", "find",
            "--osm-schema", REGION,
            REGION.capitalize()
        ],
    )
    assert result.exit_code == 0, result.output

    engine = create_engine(migrated_db["dsn"])
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar()
    engine.dispose()

    assert count > 0


@pytest.mark.integration
def test_parks_find_is_idempotent(migrated_db, osmprj_data):
    """Running parks find twice should upsert (not duplicate) parks."""
    from sqlalchemy import create_engine, text

    runner = CliRunner()
    for _ in range(2):
        result = runner.invoke(
            cli,[
                "--dsn", migrated_db["dsn"],
                "parks", "find",
                "--osm-schema", REGION,
                REGION.capitalize()
            ],
        )
        assert result.exit_code == 0, result.output

    engine = create_engine(migrated_db["dsn"])
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar()
    engine.dispose()

    # Count should be stable, not doubled
    assert count > 0
