from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from parkalyzer.config import Config
from parkalyzer.db.connection import make_session
from parkalyzer.errors import ConfigurationError

console = Console()
error_console = Console(stderr=True)


@click.group("parks")
def parks_group() -> None:
    """Find and manage parks from OSM data."""


@parks_group.command("find")
@click.option(
    "--bbox",
    required=True,
    metavar="MINLON,MINLAT,MAXLON,MAXLAT",
    help="Bounding box in WGS84, e.g. 13.35,52.49,13.45,52.54 for central Berlin.",
)
@click.option(
    "--osm-schema",
    default=None,
    envvar="PARKALYZER_OSM_SCHEMA",
    help="Schema where osmprj loaded OSM data (default: public).",
)
@click.option(
    "--min-area",
    default=1000.0,
    show_default=True,
    type=float,
    help="Minimum park area in square meters to import.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print how many parks would be imported without writing to the DB.",
)
@click.pass_context
def find_parks(
    ctx: click.Context,
    bbox: str,
    osm_schema: str | None,
    min_area: float,
    dry_run: bool,
) -> None:
    """Query OSM data for parks within BBOX and upsert them into parkalyzer.parks."""
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    schema = osm_schema or config.osm_schema

    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        minlon, minlat, maxlon, maxlat = parts
    except ValueError:
        raise click.ClickException(
            "Invalid --bbox. Expected: MINLON,MINLAT,MAXLON,MAXLAT (four floats)."
        )

    # OSM data is in SRID 3857; transform the bbox envelope before intersecting.
    find_sql = text(f"""
        SELECT
            osm_id,
            name,
            ST_AsText(ST_Transform(way, 4326))  AS geom_wkt,
            ST_Area(ST_Transform(way, 3857))     AS area_m2
        FROM {schema}.planet_osm_polygon
        WHERE leisure = 'park'
          AND ST_IsValid(way)
          AND ST_Intersects(
                way,
                ST_Transform(
                    ST_MakeEnvelope(:minlon, :minlat, :maxlon, :maxlat, 4326),
                    3857
                )
              )
          AND ST_Area(ST_Transform(way, 3857)) >= :min_area
        ORDER BY osm_id
    """)

    with make_session(config.dsn) as session:
        rows = session.execute(
            find_sql,
            {"minlon": minlon, "minlat": minlat, "maxlon": maxlon, "maxlat": maxlat, "min_area": min_area},
        ).fetchall()

    console.print(f"Found [bold]{len(rows)}[/bold] parks in the OSM data.")

    if dry_run:
        console.print("[yellow]Dry run — not writing to the database.[/yellow]")
        return

    upsert_sql = text("""
        INSERT INTO parkalyzer.parks (osm_id, name, geometry, area)
        VALUES (
            :osm_id,
            :name,
            ST_GeomFromText(:geom_wkt, 4326),
            :area
        )
        ON CONFLICT (osm_id) DO UPDATE
            SET name     = EXCLUDED.name,
                geometry = EXCLUDED.geometry,
                area     = EXCLUDED.area
    """)

    with make_session(config.dsn) as session:
        for row in rows:
            session.execute(
                upsert_sql,
                {"osm_id": row.osm_id, "name": row.name, "geom_wkt": row.geom_wkt, "area": row.area_m2},
            )

    console.print(f"[green]Upserted {len(rows)} parks into parkalyzer.parks.[/green]")


@parks_group.command("list")
@click.option("--limit", default=50, show_default=True, type=int, help="Maximum rows to display.")
@click.pass_context
def list_parks(ctx: click.Context, limit: int) -> None:
    """List parks stored in the parkalyzer.parks table."""
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    with make_session(config.dsn) as session:
        total = session.execute(text("SELECT COUNT(*) FROM parkalyzer.parks")).scalar_one()
        rows = session.execute(
            text("""
                SELECT id, osm_id, name, round(area::numeric, 0) AS area_m2
                FROM parkalyzer.parks
                ORDER BY area DESC NULLS LAST
                LIMIT :limit
            """),
            {"limit": limit},
        ).fetchall()

    table = Table(title=f"Parks ({total} total, showing {len(rows)})")
    table.add_column("ID", style="dim")
    table.add_column("OSM ID", style="cyan")
    table.add_column("Name")
    table.add_column("Area (m²)", justify="right")

    for row in rows:
        table.add_row(
            str(row.id),
            str(row.osm_id),
            row.name or "[dim]—[/dim]",
            f"{row.area_m2:,.0f}" if row.area_m2 else "[dim]—[/dim]",
        )

    console.print(table)
