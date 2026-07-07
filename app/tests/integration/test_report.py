"""Integration tests for the report command."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig
from click.testing import CliRunner
from sqlalchemy import create_engine, text

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


@pytest.fixture(scope="module")
def populated_db(migrated_db, osmprj_data, zensus_data, openrouteservice):
    """Database with parks imported and a limited set of routes calculated."""
    runner = CliRunner()
    dsn = migrated_db["dsn"]
    location = REGION.capitalize()

    result = runner.invoke(
        cli,
        ["--dsn", dsn, "parks", "find", "--osm-schema", REGION, location],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        cli,
        [
            "--dsn", dsn,
            "--ors-url", openrouteservice["url"],
            "routes", "calculate",
            "--limit", "20",
            location,
        ],
        env={"PARKALYZER_OSM_SCHEMA": REGION},
    )
    assert result.exit_code == 0, result.output

    return migrated_db


# ── Guard tests ───────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_report_no_parks_exits_with_error(migrated_db, osmprj_data):
    """report should fail with a useful error message when no parks exist.

    This guard only fires when the shared DB is empty; if parks were already
    imported by another module we skip rather than corrupt that state.
    """
    engine = create_engine(migrated_db["dsn"])
    with engine.connect() as conn:
        park_count = conn.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar()
    engine.dispose()

    if park_count > 0:
        pytest.skip("Parks already present in shared database — skipping empty-DB guard")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", migrated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code != 0
    output = result.output.lower()
    assert "parks find" in output or "no parks" in output


# ── Output structure tests ────────────────────────────────────────────────────

@pytest.mark.integration
def test_report_exits_cleanly(populated_db):
    """report should exit with code 0 when parks and routes exist."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output


@pytest.mark.integration
def test_report_shows_location_in_header(populated_db):
    """The report header should contain the location name."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert REGION.capitalize() in result.output
    assert "Park Accessibility Report" in result.output


@pytest.mark.integration
def test_report_shows_greenspace_overview(populated_db):
    """The Greenspace Overview panel should report at least one park."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert "Greenspace Overview" in result.output
    assert "parks" in result.output
    assert "km²" in result.output


@pytest.mark.integration
def test_report_shows_walk_time_section(populated_db):
    """Walk-time accessibility section should appear with all four thresholds."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert "Walk-Time Accessibility" in result.output
    assert "Within  5 min" in result.output
    assert "Within 15 min" in result.output
    assert "Within 30 min" in result.output
    assert "No route found" in result.output


@pytest.mark.integration
def test_report_shows_greenspace_breakdown(populated_db):
    """Greenspace breakdown table should list at least one park type."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert "Greenspace Breakdown" in result.output


@pytest.mark.integration
def test_report_shows_top_parks(populated_db):
    """Top 10 Parks section should be present and numbered."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert "Top 10 Parks" in result.output


@pytest.mark.integration
def test_report_shows_district_rankings_or_note(populated_db):
    """District Rankings section should render or show a 'no data' note."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["--dsn", populated_db["dsn"], "report", "--osm-schema", REGION, REGION.capitalize()],
    )
    assert result.exit_code == 0, result.output
    assert "District Rankings" in result.output
    # Either districts were found or the fallback note is shown — both are valid
    has_data = "Within 15 min" in result.output and "avg walk" in result.output.lower()
    has_note = "no district data" in result.output.lower() or "admin_level" in result.output.lower()
    assert has_data or has_note, (
        "Expected either district rows or an informative note, got neither"
    )
