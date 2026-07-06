from __future__ import annotations

import json

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


def _validate_schema_name(name: str) -> str:
    """Reject schema names that could enable SQL injection."""
    import re
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise click.ClickException(
            f"Invalid schema name {name!r}. Only letters, digits, and underscores are allowed."
        )
    return name


@parks_group.command("find")
@click.argument(
    "location",
)
@click.option(
    "--osm-schema",
    default=None,
    envvar="PARKALYZER_OSM_SCHEMA",
    help="Schema where osmprj loaded OSM data.",
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
    location: str,
    osm_schema: str | None,
    dry_run: bool,
) -> None:
    """Query OSM data for parks in the Berlin buffer boundary and upsert into parkalyzer.parks."""
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    schema = _validate_schema_name(osm_schema or config.osm_schema)

    find_sql = text(f"""
        SELECT osm_id, name, osm_type, tags,
               ST_AsText(ST_Transform(geom, {config.srid}))  AS geom_wkt,
               ST_Area(ST_Transform(geom, 3857))              AS area_m2
        FROM (
            SELECT l.geom, l.way_id AS osm_id, l.name, l.osm_type, t.tags
            FROM {schema}.leisure_polygon l
            JOIN {schema}.tags t ON abs(t.osm_id) = abs(l.way_id)
            JOIN {schema}.place_polygon b
                ON b.name = '{location}' AND st_intersects(b.geom, l.geom)
            WHERE (l.osm_type = 'park' OR l.osm_type = 'garden')
              AND COALESCE(t.tags->>'access', '') NOT IN ('private', 'no')

            UNION ALL

            SELECT u.geom, u.way_id AS osm_id, u.name, u.osm_type, t.tags
            FROM {schema}.landuse_polygon u
            JOIN {schema}.tags t ON abs(t.osm_id) = abs(u.way_id)
            JOIN {schema}.place_polygon b
                ON b.name = '{location}'  AND st_intersects(b.geom, u.geom)
            WHERE u.osm_type IN ('recreation_ground', 'forest', 'cemetery')
              AND COALESCE(t.tags->>'access', '') NOT IN ('private', 'no')

            UNION ALL

            SELECT l.geom, l.way_id AS osm_id, l.name, l.osm_type, t.tags
            FROM {schema}.poi_polygon l
            JOIN {schema}.tags t ON abs(t.osm_id) = abs(l.way_id)
            JOIN {schema}.place_polygon b
                ON b.name = '{location}' AND st_intersects(b.geom, l.geom)
            WHERE (l.osm_type = 'leisure'
                   AND (l.osm_subtype = 'garden' OR l.osm_subtype = 'park'))
              AND COALESCE(t.tags->>'access', '') NOT IN ('private', 'no')
        ) combined
        ORDER BY osm_id
    """)

    with make_session(config.dsn) as session:
        rows = session.execute(find_sql).fetchall()

    console.print(f"Found [bold]{len(rows)}[/bold] parks in the OSM data.")

    if dry_run:
        console.print("[yellow]Dry run — not writing to the database.[/yellow]")
        return

    upsert_sql = text(f"""
        INSERT INTO parkalyzer.parks (osm_id, name, osm_type, tags, geometry, area)
        VALUES (
            :osm_id,
            :name,
            :osm_type,
            CAST(:tags AS JSONB),
            ST_GeomFromText(:geom_wkt, {config.srid}),
            :area
        )
        ON CONFLICT (osm_id) DO UPDATE
            SET name     = EXCLUDED.name,
                osm_type = EXCLUDED.osm_type,
                tags     = EXCLUDED.tags,
                geometry = EXCLUDED.geometry,
                area     = EXCLUDED.area
    """)

    with make_session(config.dsn) as session:
        for row in rows:
            session.execute(
                upsert_sql,
                {
                    "osm_id": row.osm_id,
                    "name": row.name,
                    "osm_type": row.osm_type,
                    "tags": json.dumps(row.tags) if row.tags is not None else None,
                    "geom_wkt": row.geom_wkt,
                    "area": row.area_m2,
                },
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
