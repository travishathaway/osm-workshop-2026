from __future__ import annotations

from pathlib import Path

import click
from rich.console import Console

console = Console()

_ALEMBIC_INI_CANDIDATES = [
    Path.cwd() / "alembic.ini",
    Path(__file__).parent.parent.parent.parent.parent / "alembic.ini",  # project root from src/parkalyzer/commands/
]


def _find_alembic_ini() -> Path:
    for candidate in _ALEMBIC_INI_CANDIDATES:
        if candidate.exists():
            return candidate
    raise click.ClickException(
        f"Could not find alembic.ini. Run parkalyzer from the project root. "
        f"Searched: {[str(c) for c in _ALEMBIC_INI_CANDIDATES]}"
    )


def _make_alembic_config(dsn: str | None):
    from alembic.config import Config

    ini_path = _find_alembic_ini()
    cfg = Config(str(ini_path))
    if dsn:
        cfg.set_main_option("sqlalchemy.url", dsn)
    return cfg


@click.group("db")
def db_group() -> None:
    """Database migration commands."""


@db_group.command("migrate")
@click.pass_context
def migrate(ctx: click.Context) -> None:
    """Run all pending Alembic migrations (upgrade head)."""
    from alembic import command as alembic_cmd

    dsn = ctx.obj.get("dsn")
    cfg = _make_alembic_config(dsn)
    console.print("[cyan]Running migrations...[/cyan]")
    alembic_cmd.upgrade(cfg, "head")
    console.print("[green]Migrations complete.[/green]")


@db_group.command("downgrade")
@click.argument("revision", default="-1")
@click.pass_context
def downgrade(ctx: click.Context, revision: str) -> None:
    """Downgrade the database by REVISION steps (default: -1 = one step back)."""
    from alembic import command as alembic_cmd

    dsn = ctx.obj.get("dsn")
    cfg = _make_alembic_config(dsn)
    console.print(f"[yellow]Downgrading to {revision!r}...[/yellow]")
    alembic_cmd.downgrade(cfg, revision)
    console.print("[green]Downgrade complete.[/green]")


@db_group.command("revision")
@click.option("-m", "--message", required=True, help="Short description for this revision.")
@click.option(
    "--autogenerate",
    is_flag=True,
    default=False,
    help=(
        "Autogenerate migration from model diff. "
        "Note: geometry columns will NOT be detected correctly without geoalchemy2."
    ),
)
@click.pass_context
def revision(ctx: click.Context, message: str, autogenerate: bool) -> None:
    """Create a new Alembic migration revision file."""
    from alembic import command as alembic_cmd

    dsn = ctx.obj.get("dsn")
    cfg = _make_alembic_config(dsn)
    alembic_cmd.revision(cfg, message=message, autogenerate=autogenerate)
    console.print(f"[green]Revision created:[/green] {message!r}")
