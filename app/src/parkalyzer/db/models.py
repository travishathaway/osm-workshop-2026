from __future__ import annotations

import datetime
from typing import Optional

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from parkalyzer.constants import SCHEMA_NAME


class Geometry(sa.types.UserDefinedType):
    """Minimal PostGIS geometry type for SQLAlchemy 2.0 (no geoalchemy2 required).

    Values round-trip as hex-encoded WKB. Use PostGIS functions in queries
    (ST_AsGeoJSON, ST_AsText, etc.) when human-readable output is needed.
    Autogenerate will not detect changes to this type — alter geometry
    columns via hand-written migration files.
    """

    cache_ok = True

    def __init__(self, geometry_type: str = "GEOMETRY", srid: int = 4326) -> None:
        self.geometry_type = geometry_type
        self.srid = srid

    def get_col_spec(self, **kw: object) -> str:
        return f"GEOMETRY({self.geometry_type}, {self.srid})"

    def bind_expression(self, bindvalue: sa.BindParameter) -> sa.Function:
        return sa.func.ST_GeomFromText(bindvalue, self.srid)

    def column_expression(self, col: sa.Column) -> sa.Column:
        return col


class Base(DeclarativeBase):
    pass


class Park(Base):
    """A park polygon sourced from OpenStreetMap."""

    __tablename__ = "parks"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    osm_id: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(sa.String(500), nullable=True)
    geometry: Mapped[str] = mapped_column(Geometry("POLYGON", 4326), nullable=False)
    area: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )

    distance_pairs: Mapped[list[DistancePair]] = relationship(
        back_populates="park", cascade="all, delete-orphan"
    )


class CensusPoint(Base):
    """A census grid point from Zensus 2022 data."""

    __tablename__ = "census_points"
    __table_args__ = {"schema": SCHEMA_NAME}

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(sa.String(100), nullable=False, unique=True, index=True)
    geometry: Mapped[str] = mapped_column(Geometry("POINT", 4326), nullable=False)
    population: Mapped[Optional[int]] = mapped_column(sa.Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )

    distance_pairs: Mapped[list[DistancePair]] = relationship(
        back_populates="census_point", cascade="all, delete-orphan"
    )


class DistancePair(Base):
    """A computed distance/duration between a park and a census grid point."""

    __tablename__ = "distance_pairs"
    __table_args__ = (
        sa.UniqueConstraint("park_id", "census_point_id", name="uq_park_census"),
        {"schema": SCHEMA_NAME},
    )

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    park_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey(f"{SCHEMA_NAME}.parks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    census_point_id: Mapped[int] = mapped_column(
        sa.Integer,
        sa.ForeignKey(f"{SCHEMA_NAME}.census_points.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    distance_meters: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(sa.Double, nullable=True)
    computed_at: Mapped[datetime.datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
    )

    park: Mapped[Park] = relationship(back_populates="distance_pairs")
    census_point: Mapped[CensusPoint] = relationship(back_populates="distance_pairs")
