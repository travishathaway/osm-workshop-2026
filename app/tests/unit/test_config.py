import pytest

from parkalyzer.config import Config
from parkalyzer.constants import DEFAULT_ORS_BASE_URL, GEOMETRY_SRID, OSM_SCHEMA, SCHEMA_NAME, ZENSUS_SCHEMA
from parkalyzer.errors import ConfigurationError


def test_from_env_raises_when_no_dsn(monkeypatch):
    monkeypatch.delenv("PARKALYZER_DSN", raising=False)
    with pytest.raises(ConfigurationError, match="No database DSN"):
        Config.from_env()


def test_from_env_accepts_dsn_kwarg():
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.dsn == "postgresql+psycopg://localhost/test"


def test_from_env_reads_parkalyzer_dsn_env(monkeypatch):
    monkeypatch.setenv("PARKALYZER_DSN", "postgresql+psycopg://localhost/from_env")
    config = Config.from_env()
    assert config.dsn == "postgresql+psycopg://localhost/from_env"


def test_from_env_kwarg_overrides_env_var(monkeypatch):
    monkeypatch.setenv("PARKALYZER_DSN", "postgresql+psycopg://localhost/from_env")
    config = Config.from_env(dsn="postgresql+psycopg://localhost/from_kwarg")
    assert config.dsn == "postgresql+psycopg://localhost/from_kwarg"


def test_from_env_ors_url_default(monkeypatch):
    monkeypatch.delenv("PARKALYZER_ORS_URL", raising=False)
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.ors_url == DEFAULT_ORS_BASE_URL


def test_from_env_respects_ors_url_env(monkeypatch):
    monkeypatch.setenv("PARKALYZER_ORS_URL", "http://ors.example.com:9090")
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.ors_url == "http://ors.example.com:9090"


def test_from_env_ors_url_kwarg_overrides_env(monkeypatch):
    monkeypatch.setenv("PARKALYZER_ORS_URL", "http://ors.example.com:9090")
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test", ors_url="http://override:1234")
    assert config.ors_url == "http://override:1234"


def test_from_env_schema_defaults(monkeypatch):
    monkeypatch.delenv("PARKALYZER_SCHEMA", raising=False)
    monkeypatch.delenv("PARKALYZER_OSM_SCHEMA", raising=False)
    monkeypatch.delenv("PARKALYZER_ZENSUS_SCHEMA", raising=False)
    monkeypatch.delenv("PARKALYZER_SRID", raising=False)
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.schema_name == SCHEMA_NAME
    assert config.osm_schema == OSM_SCHEMA
    assert config.zensus_schema == ZENSUS_SCHEMA
    assert config.srid == GEOMETRY_SRID


def test_from_env_schema_env_overrides(monkeypatch):
    monkeypatch.setenv("PARKALYZER_SCHEMA", "custom_schema")
    monkeypatch.setenv("PARKALYZER_OSM_SCHEMA", "osm_custom")
    monkeypatch.setenv("PARKALYZER_ZENSUS_SCHEMA", "zensus_custom")
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.schema_name == "custom_schema"
    assert config.osm_schema == "osm_custom"
    assert config.zensus_schema == "zensus_custom"


def test_from_env_srid_default(monkeypatch):
    monkeypatch.delenv("PARKALYZER_SRID", raising=False)
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.srid == GEOMETRY_SRID


def test_from_env_srid_env_override(monkeypatch):
    monkeypatch.setenv("PARKALYZER_SRID", "4326")
    config = Config.from_env(dsn="postgresql+psycopg://localhost/test")
    assert config.srid == 4326
