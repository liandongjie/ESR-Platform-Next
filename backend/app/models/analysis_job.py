from __future__ import annotations

from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.shape import from_shape
from shapely.geometry import shape
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.extensions import db


class GeoJsonGeometry(TypeDecorator):
    """GeoJSON in SQLite tests, PostGIS Geometry in production."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Geometry("GEOMETRY", srid=4326))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is not None and dialect.name == "postgresql":
            return from_shape(shape(value), srid=4326)
        return value


class AnalysisJob(db.Model):
    __tablename__ = "analysis_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    parent_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("analysis_jobs.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    dispatch_status: Mapped[str] = mapped_column(
        String(24), default="PENDING", server_default="PENDING", index=True
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    geometry: Mapped[dict[str, Any]] = mapped_column(GeoJsonGeometry())
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner = relationship("User", back_populates="jobs")
    artifacts = relationship(
        "AnalysisArtifact", back_populates="job", cascade="all, delete-orphan"
    )

    __table_args__ = (
        db.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_analysis_jobs_owner_id_idempotency_key",
        ),
    )


class AnalysisArtifact(db.Model):
    __tablename__ = "analysis_artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_jobs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    relative_path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job = relationship("AnalysisJob", back_populates="artifacts")

    __table_args__ = (db.UniqueConstraint("job_id", "kind"),)
