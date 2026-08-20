from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import current_app

from app.extensions import celery, db
from app.models import AnalysisArtifact, AnalysisJob
from app.repositories.analysis_jobs import mark_job_dispatched
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore

_RISK_ANALYSIS_TASK_NAME = "app.tasks.risk_analysis.run"


def dispatch_pending_jobs(
    limit: int = 100,
    send_task: Callable[..., Any] | None = None,
) -> tuple[int, int]:
    sender = send_task or celery.send_task
    jobs = db.session.scalars(
        db.select(AnalysisJob)
        .where(
            AnalysisJob.status == "QUEUED",
            AnalysisJob.dispatch_status == "PENDING",
        )
        .order_by(AnalysisJob.queued_at)
        .limit(limit)
    ).all()
    successes = 0
    for job in jobs:
        task_id = job.id
        payload = job.request_payload
        try:
            sender(
                _RISK_ANALYSIS_TASK_NAME,
                kwargs={"payload": payload},
                task_id=task_id,
            )
            successes += int(mark_job_dispatched(task_id))
        except Exception:
            db.session.rollback()
            current_app.logger.exception("Failed to reconcile task dispatch %s", task_id)
    return successes, len(jobs)


def claim_expired_jobs(now: datetime) -> list[str]:
    """Commit the audit-visible EXPIRED state before touching artifact files."""

    try:
        job_ids = list(
            db.session.scalars(
                db.update(AnalysisJob)
                .where(
                    AnalysisJob.status == "SUCCEEDED",
                    AnalysisJob.expires_at.is_not(None),
                    AnalysisJob.expires_at <= now,
                )
                .values(status="EXPIRED", stage="EXPIRED")
                .returning(AnalysisJob.id)
            )
        )
        db.session.commit()
        return job_ids
    except Exception:
        db.session.rollback()
        raise


def cleanup_expired_results(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    runtime_dir = Path(current_app.config["RUNTIME_DATA_DIR"]).resolve()
    store = RiskAnalysisJobStore(runtime_dir)
    claimed_job_ids = claim_expired_jobs(now)
    artifacts = db.session.scalars(
        db.select(AnalysisArtifact)
        .join(AnalysisJob)
        .where(
            AnalysisJob.status == "EXPIRED",
            AnalysisArtifact.deleted_at.is_(None),
        )
    ).all()

    for artifact in artifacts:
        task_dir = store.task_directory(artifact.job_id).resolve()
        path = (runtime_dir / artifact.relative_path).resolve()
        try:
            path.relative_to(task_dir)
        except ValueError:
            current_app.logger.error(
                "Refusing to delete artifact outside task directory: %s",
                artifact.relative_path,
            )
            continue
        try:
            path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.exception(
                "Failed to delete expired artifact %s", artifact.relative_path
            )
            continue
        artifact.deleted_at = now
        try:
            db.session.commit()
        except Exception:
            # The file may already be gone; the next run treats missing_ok as success
            # and retries only the audit marker.
            db.session.rollback()
            current_app.logger.exception(
                "Failed to mark expired artifact deleted: %s", artifact.id
            )
    return len(claimed_job_ids)
