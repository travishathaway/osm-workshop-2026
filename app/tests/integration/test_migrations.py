from pathlib import Path

import pytest
from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect, text


def _alembic_cfg(dsn: str) -> AlembicConfig:
    ini_path = Path(__file__).parent.parent.parent / "alembic.ini"
    cfg = AlembicConfig(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", dsn)
    return cfg


@pytest.mark.integration
def test_upgrade_head_creates_parkalyzer_schema(postgresql):
    cfg = _alembic_cfg(postgresql["dsn"])
    alembic_cmd.upgrade(cfg, "head")

    engine = create_engine(postgresql["dsn"])
    with engine.connect() as conn:
        schema_exists = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'parkalyzer')")
        ).scalar()
    engine.dispose()

    assert schema_exists


@pytest.mark.integration
def test_upgrade_head_creates_all_tables(postgresql):
    cfg = _alembic_cfg(postgresql["dsn"])
    alembic_cmd.upgrade(cfg, "head")

    engine = create_engine(postgresql["dsn"])
    insp = inspect(engine)
    tables = insp.get_table_names(schema="parkalyzer")
    engine.dispose()

    assert "parks" in tables
    assert "census_points" in tables
    assert "distance_pairs" in tables


@pytest.mark.integration
def test_upgrade_head_is_idempotent(postgresql):
    cfg = _alembic_cfg(postgresql["dsn"])
    alembic_cmd.upgrade(cfg, "head")
    # Running upgrade head a second time should be a no-op (no error).
    alembic_cmd.upgrade(cfg, "head")


@pytest.mark.integration
def test_downgrade_to_base_removes_schema(postgresql):
    cfg = _alembic_cfg(postgresql["dsn"])
    alembic_cmd.upgrade(cfg, "head")
    alembic_cmd.downgrade(cfg, "base")

    engine = create_engine(postgresql["dsn"])
    with engine.connect() as conn:
        schema_exists = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name = 'parkalyzer')")
        ).scalar()
    engine.dispose()

    assert not schema_exists


@pytest.mark.integration
def test_upgrade_after_downgrade(postgresql):
    cfg = _alembic_cfg(postgresql["dsn"])
    alembic_cmd.upgrade(cfg, "head")
    alembic_cmd.downgrade(cfg, "base")
    alembic_cmd.upgrade(cfg, "head")  # must succeed after a full downgrade
