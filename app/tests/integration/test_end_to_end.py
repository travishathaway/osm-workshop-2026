"""End-to-end tests for the entire workflow of the CLI tool."""

from __future__ import annotations

import logging

import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine, text

from parkalyzer.main import cli

from .conftest import REGION


@pytest.mark.integration
def test_full_workflow(migrated_db, osmprj_data, zensus_data, openrouteservice, caplog):
    """Happy-path end-to-end: find parks → list parks → calculate routes → check status."""
    runner = CliRunner()
    dsn = migrated_db["dsn"]
    ors_url = openrouteservice["url"]
    location = REGION.capitalize()  # "Bremen"

    # Step 1: find and import parks from OSM data
    result = runner.invoke(
        cli,
        ["--dsn", dsn, "parks", "find", "--osm-schema", REGION, location],
    )
    assert result.exit_code == 0, result.output

    engine = create_engine(dsn)
    with engine.connect() as conn:
        park_count = conn.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar()
    engine.dispose()
    assert park_count > 0, "parks find should have imported at least one park"

    # Step 2: list parks — the table title should report the correct total
    result = runner.invoke(cli, ["--dsn", dsn, "parks", "list"])
    assert result.exit_code == 0, result.output
    assert f"{park_count} total" in result.output

    # Step 3: calculate routes — limit to keep the test fast
    with caplog.at_level(logging.ERROR, logger="parkalyzer"):
        result = runner.invoke(
            cli,
            [
                "--dsn", dsn,
                "--ors-url", ors_url,
                "routes", "calculate",
                "--limit", "20",
                location,
            ],
            env={"PARKALYZER_OSM_SCHEMA": REGION},
        )
    assert result.exit_code == 0, result.output
    ors_400_errors = [r.message for r in caplog.records if "HTTP 400" in r.message]
    assert not ors_400_errors, "ORS returned unexpected 400 errors:\n" + "\n".join(ors_400_errors)

    # Step 4: status should reflect parks and zensus cells without error
    result = runner.invoke(cli, ["--dsn", dsn, "routes", "status"])
    assert result.exit_code == 0, result.output
    assert "Parks" in result.output
    assert "Zensus grid cells" in result.output
    assert "Computed pairs" in result.output

    # Step 5: generate a report — all sections must appear
    result = runner.invoke(
        cli,
        ["--dsn", dsn, "report", "--osm-schema", REGION, location],
    )
    assert result.exit_code == 0, result.output
    assert "Park Accessibility Report" in result.output
    assert location in result.output
    assert "Greenspace Overview" in result.output
    assert "Walk-Time Accessibility" in result.output
    assert "Greenspace Breakdown" in result.output
    assert "Top 10 Parks" in result.output
    assert "District Rankings" in result.output
