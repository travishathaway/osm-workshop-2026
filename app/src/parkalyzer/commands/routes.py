from __future__ import annotations

import asyncio
import datetime
import json
import logging
from asyncio import CancelledError, Semaphore, create_task

import click
import httpx
import psycopg_pool
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table
from sqlalchemy import text

from parkalyzer.config import Config
from parkalyzer.constants import (
    BUFFER_METERS,
    ORS_CONCURRENCY,
    ORS_DEFAULT_PROFILE,
    ORS_DIRECTIONS_PATH,
    SCHEMA_NAME,
    ZENSUS_SCHEMA,
    ZENSUS_TABLE,
)
from parkalyzer.db.connection import make_session
from parkalyzer.errors import ConfigurationError
from parkalyzer.ors import ORSClient

logger = logging.getLogger(__name__)

console = Console()
error_console = Console(stderr=True)

_PAGE_SIZE = 10_000

# Composed once; reused across all pair inserts.
_INSERT_SQL = """
    INSERT INTO parkalyzer.distance_pairs
        (park_id, gitter_id, distance_meters, duration_seconds, route, computed_at)
    VALUES (%s, %s, %s, %s, ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326), %s)
    ON CONFLICT (park_id, gitter_id) DO NOTHING
"""

# Inserted when ORS cannot route a pair so it is never retried.
_SENTINEL_SQL = """
    INSERT INTO parkalyzer.distance_pairs
        (park_id, gitter_id, distance_meters, duration_seconds, route, computed_at)
    VALUES (%s, %s, NULL, NULL, NULL, %s)
    ON CONFLICT (park_id, gitter_id) DO NOTHING
"""


def _psycopg_dsn(dsn: str) -> str:
    """Convert a SQLAlchemy DSN to a psycopg-native connection string."""
    return dsn.replace("postgresql+psycopg://", "postgresql://")


def _build_pairs_sql(limit: int | None, osm_schema: str) -> str:
    limit_clause = f"LIMIT {limit}" if limit else ""
    return f"""
        SELECT
            p.gitter_id_100m                              AS gitter_id,
            ST_Y(ST_Transform(p.geom, 4326))              AS census_lat,
            ST_X(ST_Transform(p.geom, 4326))              AS census_lon,
            k.id                                          AS park_id,
            ST_Y(ST_Transform(ST_Centroid(k.geometry), 4326)) AS park_lat,
            ST_X(ST_Transform(ST_Centroid(k.geometry), 4326)) AS park_lon
        FROM (
            SELECT z.gitter_id_100m, z.geom
            FROM {ZENSUS_SCHEMA}.{ZENSUS_TABLE} z
            JOIN
                {osm_schema}.place_polygon b
            ON
                b.name = %s AND ST_Contains(b.geom, z.geom)
            {limit_clause}
        ) p
        CROSS JOIN LATERAL (
            SELECT id, geometry
            FROM {SCHEMA_NAME}.parks
            WHERE ST_DWithin(
                p.geom,
                ST_Transform(ST_Centroid(geometry), 3857),
                {BUFFER_METERS}
            )
            ORDER BY p.geom <-> ST_Transform(ST_Centroid(geometry), 3857)
        ) k
        WHERE NOT EXISTS (
            SELECT 1 FROM {SCHEMA_NAME}.distance_pairs dp
            WHERE dp.park_id = k.id AND dp.gitter_id = p.gitter_id_100m
        )
    """


def _build_count_sql(limit: int | None, osm_schema: str) -> str:
    limit_clause = f"LIMIT {limit}" if limit else ""
    return f"""
        SELECT COUNT(*)
        FROM (
            SELECT z.gitter_id_100m, z.geom
            FROM {ZENSUS_SCHEMA}.{ZENSUS_TABLE} z
            JOIN
                {osm_schema}.place_polygon b
            ON
                b.name = %s AND ST_Contains(b.geom, z.geom)
            {limit_clause}
        ) p
        CROSS JOIN LATERAL (
            SELECT id
            FROM {SCHEMA_NAME}.parks
            WHERE ST_DWithin(
                p.geom,
                ST_Transform(ST_Centroid(geometry), 3857),
                {BUFFER_METERS}
            )
        ) k
        WHERE NOT EXISTS (
            SELECT 1 FROM {SCHEMA_NAME}.distance_pairs dp
            WHERE dp.park_id = k.id AND dp.gitter_id = p.gitter_id_100m
        )
    """


async def _route_and_save(
    pool: psycopg_pool.AsyncConnectionPool,
    client: httpx.AsyncClient,
    semaphore: Semaphore,
    progress: Progress,
    task_id: int,
    gitter_id: str,
    census_lat: float,
    census_lon: float,
    park_id: int,
    park_lat: float,
    park_lon: float,
    ors_url: str,
    profile: str,
) -> None:
    """Call ORS directions for one census→park pair and persist the result."""
    async with semaphore:
        computed_at = datetime.datetime.now(tz=datetime.timezone.utc)
        try:
            response = await client.post(
                f"{ors_url}{ORS_DIRECTIONS_PATH.format(profile=profile)}",
                json={
                    "coordinates": [[census_lon, census_lat], [park_lon, park_lat]],
                    "geometry_format": "geojson",
                },
            )
            if response.status_code != 200:
                logger.error(
                    "ORS error for gitter_id=%s park_id=%s: HTTP %s — %s",
                    gitter_id, park_id, response.status_code, response.text,
                )
                async with pool.connection() as conn, conn.cursor() as cur:
                    await cur.execute(_SENTINEL_SQL, (park_id, gitter_id, computed_at))
                return

            data = response.json()
            route_data = data["routes"][0]
            summary = route_data["summary"]
            distance = summary["distance"]
            duration = summary["duration"]
            geometry = route_data["geometry"]

            async with pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    _INSERT_SQL,
                    (park_id, gitter_id, distance, duration, json.dumps(geometry), computed_at),
                )

        except CancelledError:
            raise
        except Exception:
            logger.exception(
                "Unexpected error for gitter_id=%s park_id=%s", gitter_id, park_id
            )
        finally:
            progress.advance(task_id)


async def _process_batch(
    pool: psycopg_pool.AsyncConnectionPool,
    client: httpx.AsyncClient,
    rows: list,
    semaphore: Semaphore,
    progress: Progress,
    task_id: int,
    ors_url: str,
    profile: str,
) -> None:
    """Fan out one async task per (census, park) pair in a page of rows."""
    tasks = [
        create_task(
            _route_and_save(
                pool, client, semaphore, progress, task_id,
                gitter_id, census_lat, census_lon,
                park_id, park_lat, park_lon,
                ors_url, profile,
            )
        )
        for gitter_id, census_lat, census_lon, park_id, park_lat, park_lon in rows
    ]
    try:
        await asyncio.gather(*tasks)
    except CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.error("Batch cancelled — all tasks stopped.")


async def _calculate_async(
    profile: str,
    limit: int | None,
    location: str,
    config: Config
) -> None:
    """Async entry point for the calculate command."""
    native_dsn = _psycopg_dsn(config.dsn)
    pool = psycopg_pool.AsyncConnectionPool(native_dsn, open=False)
    await pool.open()

    try:
        async with pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(_build_count_sql(limit, config.osm_schema), (location, ))
            (total,) = await cur.fetchone()

        if total == 0:
            console.print("[yellow]No unprocessed census–park pairs found. Nothing to do.[/yellow]")
            return

        console.print(f"Computing routes for [bold]{total}[/bold] census–park pairs.")

        semaphore = Semaphore(ORS_CONCURRENCY)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
        ) as progress:
            task_id = progress.add_task("[cyan]Routing pairs...", total=total)

            async with httpx.AsyncClient() as client:
                async with pool.connection() as conn:
                    async with conn.cursor(name="census_pairs_cursor") as cur:
                        await cur.execute(_build_pairs_sql(limit, config.osm_schema), (location, ))
                        while True:
                            rows = await cur.fetchmany(_PAGE_SIZE)
                            if not rows:
                                break
                            await _process_batch(
                                pool, client, rows, semaphore, progress, task_id, config.ors_url, profile
                            )

    finally:
        await pool.close()

    console.print("[green]Route calculation complete.[/green]")


@click.group("routes")
def routes_group() -> None:
    """Compute and manage ORS route distance pairs."""


@routes_group.command("calculate")
@click.argument("location")
@click.option("--profile", default=ORS_DEFAULT_PROFILE, show_default=True, help="ORS routing profile.")
@click.option("--limit", default=None, type=int, help="Process only this many census points (for testing).")
@click.pass_context
def calculate(
    ctx: click.Context,
    location: str,
    profile: str,
    limit: int | None,
) -> None:
    """Compute ORS walking routes from Zensus grid cells to nearby parks.

    For each census grid cell in zensus.alter_in_5_altersklassen_100m, finds all
    parks within a 3 km radius and calculates a route to each. Results are written
    to parkalyzer.distance_pairs; re-running is safe (existing pairs are skipped).
    """
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"), ors_url=ctx.obj.get("ors_url"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    with make_session(config.dsn) as session:
        park_count = session.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar()

    if not park_count:
        raise click.ClickException("No parks found. Run 'parkalyzer parks find' first.")

    with ORSClient(config.ors_url) as ors:
        if not ors.health_check():
            raise click.ClickException(
                f"ORS is not reachable at {config.ors_url}. "
                "Start ORS with 'ors-launcher start' or set PARKALYZER_ORS_URL."
            )

    asyncio.run(_calculate_async(profile, limit, location, config))


@routes_group.command("status")
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show the current state of distance pair computation."""
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    with make_session(config.dsn) as session:
        zensus_table_exists = session.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = :table
            )
        """), {"schema": ZENSUS_SCHEMA, "table": ZENSUS_TABLE}).scalar()

        zensus_count = (
            session.execute(text(f"SELECT COUNT(*) FROM {ZENSUS_SCHEMA}.{ZENSUS_TABLE}")).scalar()
            if zensus_table_exists else 0
        )

        row = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM parkalyzer.parks)                  AS park_count,
                (SELECT COUNT(*) FROM parkalyzer.distance_pairs)         AS pair_count,
                (SELECT COUNT(*) FROM parkalyzer.distance_pairs
                 WHERE distance_meters IS NULL)                           AS unreachable_count,
                (SELECT MAX(computed_at) FROM parkalyzer.distance_pairs) AS last_computed
        """)).fetchone()

    if row is None:
        raise click.ClickException("Could not query status — is the parkalyzer schema migrated?")

    table = Table(title="Parkalyzer Route Status")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    table.add_row("Parks", str(row.park_count or 0))
    table.add_row("Zensus grid cells", str(zensus_count))
    table.add_row("Computed pairs", str(row.pair_count or 0))
    table.add_row("Unreachable pairs", str(row.unreachable_count or 0))
    table.add_row("Last computed", str(row.last_computed) if row.last_computed else "[dim]never[/dim]")

    console.print(table)
