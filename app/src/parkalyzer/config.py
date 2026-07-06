from __future__ import annotations

import os
from dataclasses import dataclass

from parkalyzer.constants import DEFAULT_ORS_BASE_URL, GEOMETRY_SRID, OSM_SCHEMA, SCHEMA_NAME, ZENSUS_SCHEMA
from parkalyzer.errors import ConfigurationError


@dataclass
class Config:
    """Holds all runtime configuration for parkalyzer."""

    dsn: str
    ors_url: str = DEFAULT_ORS_BASE_URL
    schema_name: str = SCHEMA_NAME
    osm_schema: str = OSM_SCHEMA
    zensus_schema: str = ZENSUS_SCHEMA
    srid: int = GEOMETRY_SRID

    @classmethod
    def from_env(
        cls,
        dsn: str | None = None,
        ors_url: str | None = None,
    ) -> "Config":
        """Build a Config from environment variables, with optional overrides.

        Environment variables:
            PARKALYZER_DSN           — required unless ``dsn`` is passed
            PARKALYZER_ORS_URL       — optional
            PARKALYZER_SCHEMA        — optional
            PARKALYZER_OSM_SCHEMA    — optional
            PARKALYZER_ZENSUS_SCHEMA — optional
            PARKALYZER_SRID          — optional

        Raises:
            ConfigurationError: If no DSN is available.
        """
        resolved_dsn = dsn or os.environ.get("PARKALYZER_DSN")
        if not resolved_dsn:
            raise ConfigurationError(
                "No database DSN configured. Set PARKALYZER_DSN or pass --dsn."
            )

        return cls(
            dsn=resolved_dsn,
            ors_url=ors_url or os.environ.get("PARKALYZER_ORS_URL", DEFAULT_ORS_BASE_URL),
            schema_name=os.environ.get("PARKALYZER_SCHEMA", SCHEMA_NAME),
            osm_schema=os.environ.get("PARKALYZER_OSM_SCHEMA", OSM_SCHEMA),
            zensus_schema=os.environ.get("PARKALYZER_ZENSUS_SCHEMA", ZENSUS_SCHEMA),
            srid=int(os.environ.get("PARKALYZER_SRID", GEOMETRY_SRID)),
        )
