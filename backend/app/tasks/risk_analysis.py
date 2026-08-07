from __future__ import annotations

from typing import Any

from flask import current_app
from pydantic import ValidationError

from app.extensions import celery as celery_app
from app.gis.risk_models import RiskAnalysisError
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

    raster_dir = current_app.config["SOURCE_RASTER_DIR"]
    runtime_dir = current_app.config["RUNTIME_DATA_DIR"]
    service = RiskAnalysisJobService(raster_dir, runtime_dir)

    def report_progress(stage: str, progress: int) -> None:
        self.update_state(
            state="PROGRESS",
            meta={"stage": stage, "progress": progress},
        )

    try:
        report_progress("VALIDATING", 5)
        request = RiskAnalysisJobRequest.model_validate(payload)
        return service.execute(
            task_id=task_id,
            request=request,
            on_progress=report_progress,
        )
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
