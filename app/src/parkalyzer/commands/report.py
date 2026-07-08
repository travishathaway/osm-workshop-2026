from __future__ import annotations

import datetime
import re

import click
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from sqlalchemy import text

from parkalyzer.config import Config
from parkalyzer.constants import SCHEMA_NAME, ZENSUS_SCHEMA, ZENSUS_TABLE
from parkalyzer.db.connection import make_session
from parkalyzer.errors import ConfigurationError

console = Console()


def _validate_schema_name(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise click.ClickException(
            f"Invalid schema name {name!r}. Only letters, digits, and underscores are allowed."
        )
    return name


def _bar(pct: float, width: int = 22) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _pct_markup(pct: float, text: str) -> str:
    if pct >= 75:
        color = "green"
    elif pct >= 50:
        color = "yellow"
    else:
        color = "red"
    return f"[{color}]{text}[/{color}]"


def _fmt_pop(n: int | None) -> str:
    if n is None:
        return "[dim]—[/dim]"
    return f"{int(n):,}"


# ── SQL ───────────────────────────────────────────────────────────────────────

def _summary_sql(osm_schema: str) -> str:
    return f"""
        SELECT
            COUNT(*)                                          AS total_parks,
            ROUND((SUM(p.area) / 1000000.0)::numeric, 2)     AS total_area_km2,
            ROUND((AVG(p.area) / 10000.0)::numeric,   2)     AS avg_area_ha,
            ROUND((MAX(p.area) / 10000.0)::numeric,   1)     AS max_area_ha
        FROM {SCHEMA_NAME}.parks p
        JOIN {osm_schema}.place_polygon b
            ON b.name = :location
           AND ST_Intersects(b.geom, p.geometry)
    """


def _walk_time_sql(osm_schema: str) -> str:
    return f"""
        WITH location_cells AS (
            SELECT z.gitter_id_100m,
                   COALESCE(z.insgesamt_bevoelkerung, 0) AS pop
            FROM {ZENSUS_SCHEMA}.{ZENSUS_TABLE} z
            JOIN {osm_schema}.place_polygon b
                ON b.name = :location AND ST_Contains(b.geom, z.geom)
        ),
        min_access AS (
            SELECT lc.gitter_id_100m,
                   lc.pop,
                   MIN(dp.duration_seconds) AS min_duration
            FROM location_cells lc
            LEFT JOIN {SCHEMA_NAME}.distance_pairs dp
                ON dp.gitter_id = lc.gitter_id_100m
               AND dp.distance_meters IS NOT NULL
            GROUP BY lc.gitter_id_100m, lc.pop
        )
        SELECT
            SUM(pop)                                              AS total_pop,
            SUM(pop) FILTER (WHERE min_duration <= 300)          AS within_5min,
            SUM(pop) FILTER (WHERE min_duration <= 900)          AS within_15min,
            SUM(pop) FILTER (WHERE min_duration <= 1800)         AS within_30min,
            SUM(pop) FILTER (WHERE min_duration IS NULL)         AS no_route
        FROM min_access
    """


def _park_types_sql(osm_schema: str) -> str:
    return f"""
        SELECT
            COALESCE(p.osm_type, 'unknown')           AS park_type,
            COUNT(*)                                          AS count,
            ROUND((SUM(p.area) / 10000.0)::numeric, 1)       AS total_area_ha,
            ROUND((AVG(p.area) / 10000.0)::numeric, 2)       AS avg_area_ha
        FROM {SCHEMA_NAME}.parks p
        JOIN {osm_schema}.place_polygon b
            ON b.name = :location
           AND ST_Intersects(b.geom, p.geometry)
        GROUP BY p.osm_type
        ORDER BY count DESC
    """


def _top_parks_sql(osm_schema: str) -> str:
    return f"""
        SELECT
            COALESCE(p.name, '[unnamed]')              AS name,
            COALESCE(p.osm_type, 'unknown')            AS park_type,
            ROUND((p.area / 10000.0)::numeric, 1)             AS area_ha
        FROM {SCHEMA_NAME}.parks p
        JOIN {osm_schema}.place_polygon b
            ON b.name = :location
           AND ST_Intersects(b.geom, p.geometry)
        GROUP BY p.osm_type, p.name, p.area
        ORDER BY p.area DESC NULLS LAST
        LIMIT 10
    """


def _districts_sql(osm_schema: str) -> str:
    return f"""
        WITH city AS (
            SELECT geom
            FROM {osm_schema}.place_polygon
            WHERE name = :location
            LIMIT 1
        ),
        districts AS (
            SELECT pp.name AS district_name, pp.geom
            FROM {osm_schema}.place_polygon pp, city
            WHERE pp.admin_level = 10
              AND ST_Intersects(pp.geom, city.geom)
        ),
        district_cells AS (
            SELECT d.district_name,
                   z.gitter_id_100m,
                   COALESCE(z.insgesamt_bevoelkerung, 0) AS pop
            FROM districts d
            JOIN {ZENSUS_SCHEMA}.{ZENSUS_TABLE} z
                ON ST_Contains(d.geom, z.geom)
        ),
        min_times AS (
            SELECT dc.district_name,
                   dc.gitter_id_100m,
                   dc.pop,
                   MIN(dp.duration_seconds) AS min_duration
            FROM district_cells dc
            LEFT JOIN {SCHEMA_NAME}.distance_pairs dp
                ON dp.gitter_id = dc.gitter_id_100m
               AND dp.distance_meters IS NOT NULL
            GROUP BY dc.district_name, dc.gitter_id_100m, dc.pop
        )
        SELECT
            district_name,
            SUM(pop)                                                      AS total_pop,
            SUM(pop) FILTER (WHERE min_duration <= 900)                   AS within_15min_pop,
            ROUND((100.0 * SUM(pop) FILTER (WHERE min_duration <= 900)
                  / NULLIF(SUM(pop), 0))::numeric, 1)                     AS pct_15min,
            ROUND((AVG(min_duration) FILTER (WHERE min_duration IS NOT NULL)
                  / 60.0)::numeric, 1)                                    AS avg_walk_min
        FROM min_times
        GROUP BY district_name
        ORDER BY pct_15min DESC NULLS LAST
    """


# ── Render helpers ────────────────────────────────────────────────────────────

def _render_header(location: str) -> None:
    console.print()
    console.print(Rule(f"[bold green] Park Accessibility Report — {location} [/bold green]"))
    console.print(
        f"  [dim]Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]"
    )
    console.print()


def _render_summary(summary) -> None:
    total = int(summary.total_parks or 0)
    area = float(summary.total_area_km2 or 0)
    avg_ha = float(summary.avg_area_ha or 0)
    max_ha = float(summary.max_area_ha or 0)

    content = Text()
    content.append(f"  {total:,}", style="bold cyan")
    content.append(" parks", style="")
    content.append("   ·   ", style="dim")
    content.append(f"{area:,.1f} km²", style="bold cyan")
    content.append(" total greenspace", style="")
    content.append("   ·   ", style="dim")
    content.append(f"{avg_ha:.1f} ha", style="bold cyan")
    content.append(" avg park size", style="")
    content.append("   ·   ", style="dim")
    content.append(f"{max_ha:.1f} ha", style="bold cyan")
    content.append(" largest", style="")

    console.print(Panel(content, title="[bold]Greenspace Overview[/bold]", padding=(0, 1)))
    console.print()


def _render_walk_times(walk) -> None:
    console.print(Rule("[bold]Walk-Time Accessibility[/bold]"))

    total = int(walk.total_pop or 0)
    if total == 0:
        console.print(
            "  [yellow]No routing data found. Run "
            "'parkalyzer routes calculate' first.[/yellow]\n"
        )
        return

    console.print(f"  [dim]{total:,} residents analysed[/dim]\n")

    rows = [
        ("Within  5 min", int(walk.within_5min or 0)),
        ("Within 15 min", int(walk.within_15min or 0)),
        ("Within 30 min", int(walk.within_30min or 0)),
        ("No route found", int(walk.no_route or 0)),
    ]

    for label, pop in rows:
        pct = 100.0 * pop / total if total else 0.0
        bar = _bar(pct)
        pct_str = f"{pct:5.1f}%"
        pop_str = f"({pop:,} residents)"

        if "No route" in label:
            bar_markup = f"[dim]{bar}[/dim]"
            pct_markup = f"[dim]{pct_str}[/dim]"
        else:
            bar_markup = _pct_markup(pct, bar)
            pct_markup = _pct_markup(pct, pct_str)

        console.print(
            f"  [bold]{label}[/bold]  {bar_markup}  {pct_markup}  [dim]{pop_str}[/dim]"
        )

    console.print()


def _render_park_types(types) -> None:
    console.print(Rule("[bold]Greenspace Breakdown[/bold]"))

    if not types:
        console.print("  [dim]No park data.[/dim]\n")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Type", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Total (ha)", justify="right")
    table.add_column("Avg (ha)", justify="right")

    for row in types:
        table.add_row(
            row.park_type,
            f"{int(row.count):,}",
            f"{float(row.total_area_ha):,.1f}" if row.total_area_ha else "[dim]—[/dim]",
            f"{float(row.avg_area_ha):,.2f}" if row.avg_area_ha else "[dim]—[/dim]",
        )

    console.print(table)
    console.print()


def _render_top_parks(parks) -> None:
    console.print(Rule("[bold]Top 10 Parks by Area[/bold]"))

    if not parks:
        console.print("  [dim]No park data.[/dim]\n")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", justify="right")
    table.add_column("Name")
    table.add_column("Type", style="cyan")
    table.add_column("Area (ha)", justify="right")

    for i, row in enumerate(parks, 1):
        table.add_row(
            str(i),
            row.name,
            row.park_type,
            f"{float(row.area_ha):,.1f}" if row.area_ha else "[dim]—[/dim]",
        )

    console.print(table)
    console.print()


def _render_districts(districts) -> None:
    console.print(Rule("[bold]District Rankings[/bold]"))
    console.print(
        "  [dim]Ranked by % of residents within 15 min walk of a park (admin level 10)[/dim]\n"
    )

    if not districts:
        console.print(
            "  [dim]No district data found. "
            "Ensure place_polygon has admin_level = 10 entries within the location.[/dim]\n"
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("District")
    table.add_column("Population", justify="right")
    table.add_column("Within 15 min")
    table.add_column("Avg Walk", justify="right")

    for row in districts:
        pct = float(row.pct_15min or 0)
        bar = _bar(pct, width=16)
        bar_markup = _pct_markup(pct, bar)
        pct_markup = _pct_markup(pct, f"{pct:5.1f}%")
        within_col = f"{bar_markup}  {pct_markup}"

        avg_walk = f"{float(row.avg_walk_min):.1f} min" if row.avg_walk_min else "[dim]—[/dim]"

        table.add_row(
            row.district_name,
            _fmt_pop(row.total_pop),
            within_col,
            avg_walk,
        )

    console.print(table)
    console.print()


# ── Command ───────────────────────────────────────────────────────────────────

@click.command("report")
@click.argument("location")
@click.option(
    "--osm-schema",
    default=None,
    envvar="PARKALYZER_OSM_SCHEMA",
    help="Schema where osmprj loaded OSM data.",
)
@click.pass_context
def report_cmd(ctx: click.Context, location: str, osm_schema: str | None) -> None:
    """Generate a park accessibility report for a location.

    Requires parks and routing data to be pre-computed:

      parkalyzer parks find LOCATION

      parkalyzer routes calculate LOCATION
    """
    try:
        config = Config.from_env(dsn=ctx.obj.get("dsn"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    schema = _validate_schema_name(osm_schema or config.osm_schema)
    params = {"location": location}

    with make_session(config.dsn) as session:
        summary = session.execute(text(_summary_sql(schema)), params).fetchone()

        if not summary or not summary.total_parks:
            raise click.ClickException(
                f"No parks found for '{location}'. "
                f"Run 'parkalyzer parks find {location}' first."
            )

        walk = session.execute(text(_walk_time_sql(schema)), params).fetchone()
        types = session.execute(text(_park_types_sql(schema)), params).fetchall()
        top_parks = session.execute(text(_top_parks_sql(schema)), params).fetchall()
        districts = session.execute(text(_districts_sql(schema)), params).fetchall()

    _render_header(location)
    _render_summary(summary)
    _render_walk_times(walk)
    _render_park_types(types)
    _render_top_parks(top_parks)
    _render_districts(districts)
