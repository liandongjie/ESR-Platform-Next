from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.extensions import db
from app.models import AnalysisArtifact, AnalysisJob


def get_owned_job(task_id: str, owner_id: int) -> AnalysisJob | None:
    return db.session.scalar(
        db.select(AnalysisJob).where(
            AnalysisJob.id == task_id, AnalysisJob.owner_id == owner_id
        )
    )


def claim_job(task_id: str, *, allow_running_reclaim: bool = False) -> bool:
    """Atomically claim one queued delivery; canceled or duplicate deliveries are no-ops."""

    db.session.rollback()
    now = datetime.now(UTC)
    claimable_statuses = ("QUEUED", "RUNNING") if allow_running_reclaim else ("QUEUED",)
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(
            AnalysisJob.id == task_id,
            AnalysisJob.status.in_(claimable_statuses),
        )
        .values(
            status="RUNNING",
            stage="VALIDATING",
            progress=5,
            started_at=db.func.coalesce(AnalysisJob.started_at, now),
            dispatch_status="DISPATCHED",
            dispatched_at=db.func.coalesce(AnalysisJob.dispatched_at, now),
        )
    )
    db.session.commit()
    return result.rowcount == 1


def mark_job_running(task_id: str, stage: str, progress: int) -> bool:
    db.session.rollback()
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(AnalysisJob.id == task_id, AnalysisJob.status == "RUNNING")
        .values(stage=stage, progress=progress)
    )
    db.session.commit()
    return result.rowcount == 1


def release_job_for_retry(task_id: str) -> bool:
    db.session.rollback()
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(AnalysisJob.id == task_id, AnalysisJob.status == "RUNNING")
        .values(
            status="QUEUED",
            stage="RETRYING",
            dispatch_status="PENDING",
            dispatched_at=None,
        )
    )
    db.session.commit()
    return result.rowcount == 1


def mark_job_succeeded(
    task_id: str,
    result: dict[str, Any],
    runtime_dir: Path,
    result_ttl_hours: int,
) -> bool:
    db.session.rollback()
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=result_ttl_hours)
    updated = db.session.execute(
        db.update(AnalysisJob)
        .where(AnalysisJob.id == task_id, AnalysisJob.status == "RUNNING")
        .values(
            status="SUCCEEDED",
            stage="COMPLETED",
            progress=100,
            completed_at=now,
            expires_at=expires_at,
        )
    )
    if updated.rowcount != 1:
        db.session.rollback()
        return False

    for kind, relative_path in result.get("artifacts", {}).items():
        artifact = db.session.scalar(
            db.select(AnalysisArtifact).where(
                AnalysisArtifact.job_id == task_id,
                AnalysisArtifact.kind == kind,
            )
        )
        path = Path(runtime_dir) / relative_path
        if artifact is None:
            artifact = AnalysisArtifact(job_id=task_id, kind=kind)
            db.session.add(artifact)
        artifact.relative_path = relative_path
        artifact.size_bytes = path.stat().st_size if path.is_file() else 0
        artifact.expires_at = expires_at
        artifact.deleted_at = None
    db.session.commit()
    return True


def mark_job_failed(
    task_id: str,
    error_code: str,
    message: str,
    *,
    dispatch_failed: bool = False,
) -> bool:
    db.session.rollback()
    values: dict[str, Any] = {
        "status": "FAILED",
        "stage": "FAILED",
        "progress": 100,
        "error_code": error_code,
        "error_message": message,
        "completed_at": datetime.now(UTC),
    }
    if dispatch_failed:
        values["dispatch_status"] = "FAILED"
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(
            AnalysisJob.id == task_id,
            AnalysisJob.status.in_(("QUEUED", "RUNNING")),
        )
        .values(**values)
    )
    db.session.commit()
    return result.rowcount == 1


def cancel_queued_job(task_id: str, owner_id: int) -> bool:
    db.session.rollback()
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(
            AnalysisJob.id == task_id,
            AnalysisJob.owner_id == owner_id,
            AnalysisJob.status == "QUEUED",
        )
        .values(
            status="CANCELED",
            stage="CANCELED",
            completed_at=datetime.now(UTC),
        )
    )
    db.session.commit()
    return result.rowcount == 1


def mark_job_dispatched(task_id: str) -> bool:
    db.session.rollback()
    result = db.session.execute(
        db.update(AnalysisJob)
        .where(
            AnalysisJob.id == task_id,
            AnalysisJob.status == "QUEUED",
            AnalysisJob.dispatch_status == "PENDING",
        )
        .values(dispatch_status="DISPATCHED", dispatched_at=datetime.now(UTC))
    )
    db.session.commit()
    return result.rowcount == 1
