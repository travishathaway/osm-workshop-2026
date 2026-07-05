from __future__ import annotations

import sys

import click
from rich.console import Console

from parkalyzer.commands.db import db_group
from parkalyzer.commands.parks import parks_group
from parkalyzer.commands.routes import routes_group
from parkalyzer.errors import ConfigurationError

error_console = Console(stderr=True)


@click.group()
@click.option(
    "--dsn",
    envvar="PARKALYZER_DSN",
    default=None,
    help="PostgreSQL DSN (postgresql+psycopg://...). Also read from PARKALYZER_DSN.",
)
@click.option(
    "--ors-url",
    envvar="PARKALYZER_ORS_URL",
    default=None,
    help="ORS base URL. Also read from PARKALYZER_ORS_URL.",
)
@click.pass_context
def cli(ctx: click.Context, dsn: str | None, ors_url: str | None) -> None:
    """Parkalyzer — analyze park accessibility from census data using ORS routing."""
    ctx.ensure_object(dict)
    ctx.obj["dsn"] = dsn
    ctx.obj["ors_url"] = ors_url


cli.add_command(db_group)
cli.add_command(parks_group)
cli.add_command(routes_group)


def main() -> None:
    try:
        cli(standalone_mode=False)
    except ConfigurationError as exc:
        error_console.print(f"[bold red]Configuration error:[/bold red] {exc}")
        sys.exit(1)
    except click.exceptions.Abort:
        error_console.print("\n[yellow]Aborted.[/yellow]")
        sys.exit(130)
