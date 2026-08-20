from __future__ import annotations

from typing import Any

from flask import current_app
from pydantic import ValidationError
from rasterio.errors import RasterioIOError

from app.extensions import celery as celery_app
from app.extensions import db
from app.gis.risk_models import RiskAnalysisError
from app.repositories.analysis_jobs import (
    claim_job,
    mark_job_failed,
    mark_job_running,
    mark_job_succeeded,
    release_job_for_retry,
)
from app.schemas.risk_analysis import RiskAnalysisJobRequest
from app.services.risk_analysis_jobs import RiskAnalysisJobService, write_failure_manifest


def _persist_failure_safely(
    *,
    task_id: str,
    runtime_dir,
    error_code: str,
    message: str,
) -> None:
    """Do not let a metadata write failure hide the original analysis exception."""

    # Database is the business source of truth and must not depend on artifact I/O.
    transitioned = False
    try:
        transitioned = mark_job_failed(task_id, error_code, message)
    except Exception:  # pragma: no cover - defensive logging around database failures
        db.session.rollback()
        current_app.logger.exception("Failed to persist risk-analysis failure state")

    if not transitioned:
        return
    try:
        write_failure_manifest(
            runtime_dir=runtime_dir,
            task_id=task_id,
            error_code=error_code,
            message=message,
        )
    except Exception:  # pragma: no cover - defensive logging around disk failures
        current_app.logger.exception("Failed to persist risk-analysis failure manifest")


@celery_app.task(bind=True, name="app.tasks.risk_analysis.run")
def run_risk_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Execute one risk-analysis job in the worker process.

    Only JSON-serializable data crosses Redis. Flask paths are resolved inside the
    worker's application context, and the deterministic pipeline remains unaware of
    Celery. Deterministic validation/analysis failures are not auto-retried because a
    retry with the same inputs would produce the same failure.
    """

    task_id = self.request.id
    if not task_id:
        raise RuntimeError("Celery task id is required for task-scoped artifacts")

    try:
        delivery_info = self.request.delivery_info or {}
        claimed = claim_job(
            task_id,
            allow_running_reclaim=bool(delivery_info.get("redelivered")),
        )
    except Exception:
        db.session.rollback()
        raise
    if not claimed:
        return {"task_id": task_id, "status": "IGNORED"}

    raster_dir = current_app.config["SOURCE_RASTER_DIR"]
    runtime_dir = current_app.config["RUNTIME_DATA_DIR"]
    service = RiskAnalysisJobService(raster_dir, runtime_dir)

    def report_progress(stage: str, progress: int) -> None:
        mark_job_running(task_id, stage, progress)
        self.update_state(
            state="PROGRESS",
            meta={"stage": stage, "progress": progress},
        )

    try:
        report_progress("VALIDATING", 5)
        request = RiskAnalysisJobRequest.model_validate(payload)
        result = service.execute(
            task_id=task_id,
            request=request,
            on_progress=report_progress,
        )
        mark_job_succeeded(
            task_id,
            result,
            runtime_dir,
            current_app.config["RESULT_TTL_HOURS"],
        )
        return result
    except ValidationError as exc:
        message = "风险分析任务参数校验失败"
        _persist_failure_safely(
            task_id=task_id,
            runtime_dir=runtime_dir,
            error_code="INVALID_REQUEST",
            message=message,
        )
        raise ValueError(message) from exc
    except RiskAnalysisError as exc:
        message = str(exc)
        _persist_failure_safely(
            task_id=task_id,
            runtime_dir=runtime_dir,
            error_code="ANALYSIS_ERROR",
            message=message,
        )
        raise ValueError(message) from exc
    except (OSError, RasterioIOError) as exc:
        if self.request.retries < 2:
            try:
                release_job_for_retry(task_id)
            except Exception:
                db.session.rollback()
                _persist_failure_safely(
                    task_id=task_id,
                    runtime_dir=runtime_dir,
                    error_code="INTERNAL_ERROR",
                    message="风险分析任务重试状态保存失败",
                )
                raise
            raise self.retry(exc=exc, countdown=5, max_retries=2) from exc
        message = "风险分析任务依赖暂时不可用，重试后仍失败"
        _persist_failure_safely(
            task_id=task_id,
            runtime_dir=runtime_dir,
            error_code="TRANSIENT_IO_ERROR",
            message=message,
        )
        raise
    except Exception:
        message = "风险分析任务执行失败"
        current_app.logger.exception("Unexpected risk-analysis task failure")
        _persist_failure_safely(
            task_id=task_id,
            runtime_dir=runtime_dir,
            error_code="INTERNAL_ERROR",
            message=message,
        )
        raise
