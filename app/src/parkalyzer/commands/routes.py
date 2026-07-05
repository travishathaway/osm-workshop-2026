from __future__ import annotations

import datetime
from typing import Iterator

import click
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from sqlalchemy import text

from parkalyzer.config import Config
from parkalyzer.constants import ORS_DEFAULT_PROFILE, ORS_MAX_LOCATIONS
from parkalyzer.db.connection import make_session
from parkalyzer.errors import ConfigurationError, ORSError
from parkalyzer.ors import ORSClient

console = Console()
error_console = Console(stderr=True)


def _chunked(items: list, size: int) -> Iterator[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


@click.group("routes")
def routes_group() -> None:
    """Compute and manage ORS route distance pairs."""


@routes_group.command("calculate")
@click.option("--profile", default=ORS_DEFAULT_PROFILE, show_default=True, help="ORS routing profile.")
@click.option(
    "--batch-size",
    default=ORS_MAX_LOCATIONS,
    show_default=True,
    type=click.IntRange(1, ORS_MAX_LOCATIONS),
    help="Max parks per ORS matrix call (ORS limit: 50).",
)
@click.option("--limit-parks", default=None, type=int, help="Process only this many parks (for testing).")
@click.option("--limit-census", default=None, type=int, help="Use only this many census points (for testing).")
@click.pass_context
def calculate(
    ctx: click.Context,
    profile: str,
    batch_size: int,
    limit_parks: int | None,
    limit_census: int | None,
) -> None:
    """Compute ORS travel distances between all parks and census points.

    Parks must exist in parkalyzer.parks (run 'parks find' first).
    Census points must exist in parkalyzer.census_points.
    Results are written to parkalyzer.distance_pairs; re-running is safe
    (existing pairs are skipped via ON CONFLICT DO NOTHING).
    """
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"), ors_url=ctx.obj.get("ors_url"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    parks_sql = "SELECT id, ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat FROM parkalyzer.parks ORDER BY id"
    census_sql = "SELECT id, ST_X(geometry) AS lon, ST_Y(geometry) AS lat FROM parkalyzer.census_points ORDER BY id"
    if limit_parks:
        parks_sql += f" LIMIT {limit_parks}"
    if limit_census:
        census_sql += f" LIMIT {limit_census}"

    with make_session(config.dsn) as session:
        parks = session.execute(text(parks_sql)).fetchall()
        census_points = session.execute(text(census_sql)).fetchall()

    if not parks:
        raise click.ClickException("No parks found. Run 'parkalyzer parks find' first.")
    if not census_points:
        raise click.ClickException("No census points found. Import census data first.")

    console.print(
        f"Computing distances: [bold]{len(parks)}[/bold] parks × "
        f"[bold]{len(census_points)}[/bold] census points "
        f"using profile [cyan]{profile}[/cyan]."
    )

    with ORSClient(config.ors_url) as ors:
        if not ors.health_check():
            raise click.ClickException(
                f"ORS is not reachable at {config.ors_url}. "
                "Start ORS with 'ors-launcher start' or set PARKALYZER_ORS_URL."
            )

    upsert_sql = text("""
        INSERT INTO parkalyzer.distance_pairs
            (park_id, census_point_id, distance_meters, duration_seconds, computed_at)
        VALUES
            (:park_id, :census_point_id, :distance_meters, :duration_seconds, :computed_at)
        ON CONFLICT (park_id, census_point_id) DO NOTHING
    """)

    total_batches = (len(parks) + batch_size - 1) // batch_size

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(), MofNCompleteColumn()) as progress:
        task = progress.add_task("[cyan]ORS matrix batches...", total=total_batches)

        for park_chunk in _chunked(list(parks), batch_size):
            park_locs = [(p.lon, p.lat) for p in park_chunk]
            census_locs = [(c.lon, c.lat) for c in census_points]
            all_locs = park_locs + census_locs
            src_indices = list(range(len(park_locs)))
            dst_indices = list(range(len(park_locs), len(all_locs)))

            try:
                with ORSClient(config.ors_url) as ors:
                    result = ors.matrix(
                        locations=all_locs,
                        profile=profile,
                        sources=src_indices,
                        destinations=dst_indices,
                    )
            except ORSError as exc:
                error_console.print(f"[red]ORS error for batch:[/red] {exc}")
                progress.advance(task)
                continue

            computed_at = datetime.datetime.now(tz=datetime.timezone.utc)
            rows_to_insert = []
            for park_i, park in enumerate(park_chunk):
                for census_j, census_pt in enumerate(census_points):
                    dur = result.durations[park_i][census_j] if result.durations else None
                    dist = result.distances[park_i][census_j] if result.distances else None
                    rows_to_insert.append({
                        "park_id": park.id,
                        "census_point_id": census_pt.id,
                        "distance_meters": dist,
                        "duration_seconds": dur,
                        "computed_at": computed_at,
                    })

            with make_session(config.dsn) as session:
                session.execute(upsert_sql, rows_to_insert)

            progress.advance(task)

    console.print("[green]Distance calculation complete.[/green]")


@routes_group.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show the current state of distance pair computation."""
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    status_sql = text("""
        SELECT
            (SELECT COUNT(*) FROM parkalyzer.parks)                  AS park_count,
            (SELECT COUNT(*) FROM parkalyzer.census_points)          AS census_count,
            (SELECT COUNT(*) FROM parkalyzer.distance_pairs)         AS pair_count,
            (SELECT COUNT(*) FROM parkalyzer.distance_pairs
             WHERE distance_meters IS NULL)                           AS unreachable_count,
            (SELECT MAX(computed_at) FROM parkalyzer.distance_pairs) AS last_computed
    """)

    with make_session(config.dsn) as session:
        row = session.execute(status_sql).fetchone()

    if row is None:
        raise click.ClickException("Could not query status — is the parkalyzer schema migrated?")

    expected_pairs = (row.park_count or 0) * (row.census_count or 0)
    coverage_pct = f"{100 * row.pair_count / expected_pairs:.1f}%" if expected_pairs > 0 else "N/A"

    table = Table(title="Parkalyzer Route Status")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Parks", str(row.park_count or 0))
    table.add_row("Census points", str(row.census_count or 0))
    table.add_row("Expected pairs (total)", str(expected_pairs))
    table.add_row("Computed pairs", str(row.pair_count or 0))
    table.add_row("Coverage", coverage_pct)
    table.add_row("Unreachable pairs", str(row.unreachable_count or 0))
    table.add_row("Last computed", str(row.last_computed) if row.last_computed else "[dim]never[/dim]")

    console.print(table)
