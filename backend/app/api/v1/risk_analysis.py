from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file, url_for
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.validation import validation_details
from app.extensions import celery as celery_app
from app.extensions import db
from app.gis.analysis_area import AnalysisAreaValidationError, metric_area_m2
from app.gis.geojson import parse_geojson_geometry
from app.models import AnalysisJob, User
from app.repositories.analysis_jobs import (
    cancel_queued_job,
    get_owned_job,
    mark_job_dispatched,
    mark_job_failed,
)
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore
from app.schemas.risk_analysis import (
    RiskAnalysisJobRequest,
    RiskAnalysisSuccessResult,
)
from app.services.risk_analysis_jobs import (
    RiskAnalysisArtifactError,
    build_risk_analysis_spatial_result,
    resolve_risk_analysis_artifact,
    write_failure_manifest,
)

risk_analysis_bp = Blueprint("risk_analysis", __name__)
_RISK_ANALYSIS_TASK_NAME = "app.tasks.risk_analysis.run"
_ACTIVE_STATUSES = ("QUEUED", "RUNNING")
_FIXED_WINDOW_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return {current, redis.call('TTL', KEYS[1])}
"""


class RiskAnalysisManifestError(ValueError):
    """A succeeded database job has no consumable result manifest."""


def _idempotency_key():
    value = request.headers.get("Idempotency-Key", "")
    if not value or value != value.strip() or len(value) > 128:
        return None, (
            jsonify(
                {
                    "code": "INVALID_IDEMPOTENCY_KEY",
                    "message": "Idempotency-Key 必填且长度不能超过 128",
                }
            ),
            422,
        )
    return value, None


def _rate_limit_submission(owner_id: int):
    limit = current_app.config["SUBMISSION_RATE_LIMIT_PER_MINUTE"]
    window = int(time.time()) // 60
    key = f"rate:risk-analysis:{owner_id}:{window}"
    try:
        count, ttl = current_app.extensions["redis_auth"].eval(
            _FIXED_WINDOW_SCRIPT, 1, key, 60
        )
    except Exception:
        current_app.logger.exception("Risk-analysis submission rate limiter unavailable")
        return _no_store_json(
            {
                "code": "RATE_LIMIT_UNAVAILABLE",
                "message": "提交限流服务暂时不可用",
            },
            503,
        )
    if int(count) <= limit:
        return None
    response, status = _no_store_json(
        {
            "code": "SUBMISSION_RATE_LIMITED",
            "message": "提交过于频繁，请稍后重试",
        },
        429,
    )
    response.headers["Retry-After"] = str(max(1, int(ttl)))
    return response, status


def _job_store() -> RiskAnalysisJobStore:
    return RiskAnalysisJobStore(current_app.config["RUNTIME_DATA_DIR"])


def _status_urls(task_id: str) -> tuple[str, str]:
    status_url = url_for(
        "api_v1.risk_analysis.get_risk_analysis_job",
        task_id=task_id,
    )
    result_url = url_for(
        "api_v1.risk_analysis.get_risk_analysis_result",
        task_id=task_id,
    )
    return status_url, result_url


def _success_manifest(
    store: RiskAnalysisJobStore, job: AnalysisJob
) -> RiskAnalysisSuccessResult:
    try:
        result = store.read_result(job.id)
    except (OSError, ValueError) as exc:
        raise RiskAnalysisManifestError("风险分析结果文件格式不完整或已损坏") from exc
    if result is None:
        raise RiskAnalysisManifestError("成功任务缺少结果文件")
    try:
        manifest = RiskAnalysisSuccessResult.model_validate(result)
    except ValidationError as exc:
        raise RiskAnalysisManifestError("风险分析结果文件格式不完整或已损坏") from exc
    if manifest.task_id != job.id:
        raise RiskAnalysisManifestError("风险分析结果文件与任务不匹配")
    return manifest


def _elapsed_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return round(max(0.0, (end - start).total_seconds()), 3)


def _job_status_payload(
    job: AnalysisJob,
    manifest: RiskAnalysisSuccessResult | None = None,
    manifest_error: str | None = None,
    result_available: bool | None = None,
) -> dict[str, Any]:

    payload: dict[str, Any] = {
        "task_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "result_available": (
            result_available
            if result_available is not None
            else job.status == "SUCCEEDED" and manifest is not None
        ),
        "submitted_at": job.queued_at.isoformat(),
        "queued_at": job.queued_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
        "parent_job_id": job.parent_job_id,
        "timing": {
            "queue_seconds": _elapsed_seconds(job.queued_at, job.started_at),
            "execution_seconds": _elapsed_seconds(job.started_at, job.completed_at),
            "total_seconds": _elapsed_seconds(job.queued_at, job.completed_at),
        },
    }
    if manifest_error is not None:
        payload["error"] = {
            "code": "INVALID_RESULT_MANIFEST",
            "message": manifest_error,
        }
    elif job.status == "FAILED":
        payload["error"] = {
            "code": job.error_code or "INTERNAL_ERROR",
            "message": job.error_message or "风险分析任务执行失败",
        }
    return payload


def _no_store_json(payload: dict[str, Any], status_code: int):
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status_code


def _terminal_conflict(job: AnalysisJob):
    if job.status not in {"FAILED", "CANCELED"}:
        return None
    return _no_store_json(_job_status_payload(job), 409)


def _expired_result(job: AnalysisJob):
    if job.status != "EXPIRED":
        return None
    return _no_store_json(
        {
            "code": "RESULT_EXPIRED",
            "message": "风险分析成果已过期并清理",
            "task_id": job.id,
            "status": job.status,
        },
        410,
    )


def _result_not_ready(job: AnalysisJob):
    response = jsonify(
        {
            "code": "RESULT_NOT_READY",
            "message": "风险分析任务尚未产生最终结果",
            "task_id": job.id,
            "status": job.status,
        }
    )
    response.headers["Retry-After"] = "2"
    response.headers["Cache-Control"] = "no-store"
    return response, 202


def _invalid_manifest(job: AnalysisJob, error: RiskAnalysisManifestError):
    current_app.logger.warning("Invalid result manifest for task %s: %s", job.id, error)
    return _no_store_json(
        {
            "code": "INVALID_RESULT_MANIFEST",
            "message": str(error),
            "task_id": job.id,
            "status": job.status,
        },
        409,
    )


def _job_created_response(
    *,
    task_id: str,
    status: str,
    queued_at: datetime,
    replayed: bool,
    status_code: int,
):
    status_url, result_url = _status_urls(task_id)
    response = jsonify(
        {
            "task_id": task_id,
            "status": status,
            "submitted_at": queued_at.isoformat(),
            "status_url": status_url,
            "result_url": result_url,
            "replayed": replayed,
        }
    )
    response.status_code = status_code
    response.headers["Location"] = status_url
    response.headers["Retry-After"] = "2"
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


def _idempotent_replay(
    job: AnalysisJob,
    request_payload: dict[str, Any],
    parent_job_id: str | None,
):
    if (
        job.request_payload != request_payload
        or job.parent_job_id != parent_job_id
    ):
        return _no_store_json(
            {
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "Idempotency-Key 已用于不同的任务请求",
            },
            409,
        )
    return _job_created_response(
        task_id=job.id,
        status=job.status,
        queued_at=job.queued_at,
        replayed=True,
        status_code=200,
    )


def _create_and_dispatch_job(
    *,
    owner_id: int,
    request_payload: dict[str, Any],
    idempotency_key: str,
    parent_job_id: str | None = None,
):
    existing = db.session.scalar(
        db.select(AnalysisJob).where(
            AnalysisJob.owner_id == owner_id,
            AnalysisJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        response = _idempotent_replay(existing, request_payload, parent_job_id)
        db.session.rollback()
        return response
    db.session.rollback()

    # PostgreSQL serializes submissions per user here; the unique constraint is
    # still the final guard for concurrent requests and SQLite tests.
    db.session.scalar(
        db.select(User).where(User.id == owner_id).with_for_update()
    )
    existing = db.session.scalar(
        db.select(AnalysisJob).where(
            AnalysisJob.owner_id == owner_id,
            AnalysisJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        response = _idempotent_replay(existing, request_payload, parent_job_id)
        db.session.rollback()
        return response

    rate_limited = _rate_limit_submission(owner_id)
    if rate_limited is not None:
        db.session.rollback()
        return rate_limited

    active_count = db.session.scalar(
        db.select(db.func.count())
        .select_from(AnalysisJob)
        .where(
            AnalysisJob.owner_id == owner_id,
            AnalysisJob.status.in_(_ACTIVE_STATUSES),
        )
    )
    if (active_count or 0) >= current_app.config["MAX_ACTIVE_JOBS_PER_USER"]:
        db.session.rollback()
        response, status = _no_store_json(
            {
                "code": "ACTIVE_JOB_LIMIT_REACHED",
                "message": "当前活动任务数已达到上限",
            },
            429,
        )
        response.headers["Retry-After"] = "2"
        return response, status

    task_id = str(uuid4())
    job = AnalysisJob(
        id=task_id,
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        parent_job_id=parent_job_id,
        status="QUEUED",
        stage="QUEUED",
        progress=0,
        request_payload=request_payload,
        geometry=request_payload["geometry"],
    )
    db.session.add(job)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        existing = db.session.scalar(
            db.select(AnalysisJob).where(
                AnalysisJob.owner_id == owner_id,
                AnalysisJob.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        response = _idempotent_replay(existing, request_payload, parent_job_id)
        db.session.rollback()
        return response

    queued_at = db.session.scalar(
        db.select(AnalysisJob.queued_at).where(AnalysisJob.id == task_id)
    )
    if queued_at is None:  # pragma: no cover - committed row invariant
        raise RuntimeError("Committed analysis job could not be reloaded")

    try:
        celery_app.send_task(
            _RISK_ANALYSIS_TASK_NAME,
            kwargs={"payload": request_payload},
            task_id=task_id,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Failed to enqueue risk-analysis task %s", task_id)
        message = "风险分析任务队列暂时不可用"
        transitioned = mark_job_failed(
            task_id, "QUEUE_UNAVAILABLE", message, dispatch_failed=True
        )
        if transitioned:
            try:
                write_failure_manifest(
                    runtime_dir=current_app.config["RUNTIME_DATA_DIR"],
                    task_id=task_id,
                    error_code="QUEUE_UNAVAILABLE",
                    message=message,
                )
            except Exception:
                current_app.logger.exception(
                    "Failed to persist queue failure manifest for task %s", task_id
                )
        return _no_store_json(
            {
                "code": "TASK_QUEUE_UNAVAILABLE",
                "message": message,
                "task_id": task_id,
            },
            503,
        )

    try:
        mark_job_dispatched(task_id)
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "Task %s was sent but dispatch state could not be persisted", task_id
        )
    return _job_created_response(
        task_id=task_id,
        status="QUEUED",
        queued_at=queued_at,
        replayed=False,
        status_code=202,
    )


@risk_analysis_bp.post("/jobs")
@jwt_required()
def create_risk_analysis_job():
    """创建异步风险分析任务；HTTP 请求线程不执行任何栅格计算。"""

    idempotency_key, error = _idempotency_key()
    if error is not None:
        return error

    raw_payload = request.get_json(silent=True)
    if not isinstance(raw_payload, dict):
        return jsonify({"code": "INVALID_JSON", "message": "请求体必须是 JSON object"}), 400

    try:
        job_request = RiskAnalysisJobRequest.model_validate(raw_payload)
    except ValidationError as exc:
        return (
            jsonify(
                {
                    "code": "INVALID_REQUEST",
                    "message": "风险分析任务参数校验失败",
                    "details": validation_details(exc),
                }
            ),
            422,
        )

    try:
        area_km2 = metric_area_m2(parse_geojson_geometry(job_request.geometry)) / 1_000_000
    except AnalysisAreaValidationError as exc:
        return jsonify({"code": "INVALID_REQUEST", "message": str(exc)}), 422
    max_area_km2 = current_app.config["MAX_ANALYSIS_AREA_KM2"]
    if area_km2 > max_area_km2:
        return (
            jsonify(
                {
                    "code": "ANALYSIS_AREA_TOO_LARGE",
                    "message": f"研究区面积不能超过 {max_area_km2:g} km²",
                    "details": {"area_km2": area_km2, "max_area_km2": max_area_km2},
                }
            ),
            422,
        )

    request_payload = job_request.model_dump(mode="json")
    return _create_and_dispatch_job(
        owner_id=int(get_jwt_identity()),
        request_payload=request_payload,
        idempotency_key=idempotency_key,
    )


@risk_analysis_bp.post("/jobs/<task_id>/retry")
@jwt_required()
def retry_risk_analysis_job(task_id: str):
    idempotency_key, error = _idempotency_key()
    if error is not None:
        return error
    owner_id = int(get_jwt_identity())
    job = get_owned_job(task_id, owner_id)
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404
    if job.status != "FAILED":
        return _no_store_json(
            {
                "code": "JOB_NOT_RETRYABLE",
                "message": "只有失败任务可以重试",
                "task_id": task_id,
                "status": job.status,
            },
            409,
        )
    if idempotency_key == job.idempotency_key:
        return _no_store_json(
            {
                "code": "INVALID_IDEMPOTENCY_KEY",
                "message": "重试任务必须使用新的 Idempotency-Key",
            },
            422,
        )
    try:
        job_request = RiskAnalysisJobRequest.model_validate(job.request_payload)
    except ValidationError:
        return _no_store_json(
            {
                "code": "INVALID_SUBMISSION_RECORD",
                "message": "原任务提交参数已损坏，无法重试",
            },
            409,
        )
    return _create_and_dispatch_job(
        owner_id=owner_id,
        request_payload=job_request.model_dump(mode="json"),
        idempotency_key=idempotency_key,
        parent_job_id=job.id,
    )


@risk_analysis_bp.post("/jobs/<task_id>/cancel")
@jwt_required()
def cancel_risk_analysis_job(task_id: str):
    owner_id = int(get_jwt_identity())
    job = get_owned_job(task_id, owner_id)
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404
    if job.status == "RUNNING":
        return _no_store_json(
            {
                "code": "RUNNING_CANCEL_UNSUPPORTED",
                "message": "运行中任务暂不支持强制终止",
                "task_id": task_id,
                "status": job.status,
            },
            409,
        )
    if job.status != "QUEUED":
        return _no_store_json(
            {
                "code": "JOB_NOT_CANCELABLE",
                "message": "只有排队中的任务可以取消",
                "task_id": task_id,
                "status": job.status,
            },
            409,
        )

    if not cancel_queued_job(task_id, owner_id):
        job = get_owned_job(task_id, owner_id)
        code = "RUNNING_CANCEL_UNSUPPORTED" if job.status == "RUNNING" else "JOB_NOT_CANCELABLE"
        return _no_store_json(
            {
                "code": code,
                "message": "任务状态已变化，无法取消",
                "task_id": task_id,
                "status": job.status,
            },
            409,
        )
    job = get_owned_job(task_id, owner_id)
    return _no_store_json(_job_status_payload(job), 200)


@risk_analysis_bp.get("/jobs")
@jwt_required()
def list_risk_analysis_jobs():
    """按提交时间倒序返回最近风险分析任务，不在列表接口返回完整研究区 geometry。"""

    raw_limit = request.args.get("limit", "20")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = 0
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        offset = -1

    if not 1 <= limit <= 100:
        return (
            jsonify(
                {
                    "code": "INVALID_REQUEST",
                    "message": "limit 必须是 1 到 100 的整数",
                }
            ),
            422,
        )
    if offset < 0:
        return (
            jsonify(
                {
                    "code": "INVALID_REQUEST",
                    "message": "offset 必须是大于等于 0 的整数",
                }
            ),
            422,
        )

    owner_id = int(get_jwt_identity())
    total = db.session.scalar(
        db.select(db.func.count()).select_from(AnalysisJob).where(AnalysisJob.owner_id == owner_id)
    )
    jobs = db.session.scalars(
        db.select(AnalysisJob)
        .where(AnalysisJob.owner_id == owner_id)
        .options(selectinload(AnalysisJob.artifacts))
        .order_by(AnalysisJob.queued_at.desc(), AnalysisJob.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    items: list[dict[str, Any]] = []
    for job in jobs:
        result_available = job.status == "SUCCEEDED" and any(
            artifact.kind == "manifest" and artifact.deleted_at is None
            for artifact in job.artifacts
        )
        status = _job_status_payload(job, result_available=result_available)
        request_payload = job.request_payload
        geometry_type = None
        weights: list[dict[str, Any]] = []
        if isinstance(request_payload, dict):
            geometry = request_payload.get("geometry")
            if isinstance(geometry, dict) and isinstance(geometry.get("type"), str):
                geometry_type = geometry["type"]
            raw_weights = request_payload.get("weights")
            if isinstance(raw_weights, list):
                weights = [item for item in raw_weights if isinstance(item, dict)]

        # 历史列表只返回轻量摘要，避免复杂 Polygon 坐标在任务列表中反复传输。
        status["request_summary"] = {
            "geometry_type": geometry_type,
            "weights": weights,
        }
        items.append(status)

    response = jsonify(
        {
            "items": items,
            "limit": limit,
            "offset": offset,
            "total": total or 0,
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>")
@jwt_required()
def get_risk_analysis_job(task_id: str):
    """查询稳定业务状态；未知 task_id 返回 404，而不是误报为 Celery PENDING。"""

    store = _job_store()
    job = get_owned_job(task_id, int(get_jwt_identity()))
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    manifest = None
    if job.status == "SUCCEEDED":
        try:
            manifest = _success_manifest(store, job)
        except RiskAnalysisManifestError as exc:
            current_app.logger.warning(
                "Invalid result manifest for task %s: %s", job.id, exc
            )
            return _no_store_json(
                _job_status_payload(job, manifest_error=str(exc)), 409
            )
    payload = _job_status_payload(job, manifest)
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/submission")
@jwt_required()
def get_risk_analysis_submission(task_id: str):
    """Return the immutable request persisted before enqueueing the task."""

    job = get_owned_job(task_id, int(get_jwt_identity()))
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    try:
        job_request = RiskAnalysisJobRequest.model_validate(job.request_payload)
    except ValidationError as exc:
        current_app.logger.warning(
            "Invalid risk-analysis submission manifest for task %s: %s",
            task_id,
            exc,
        )
        return (
            jsonify(
                {
                    "code": "INVALID_SUBMISSION_MANIFEST",
                    "message": "风险分析提交记录格式不完整或已损坏",
                }
            ),
            409,
        )

    response = jsonify(
        {
            "task_id": job.id,
            "submitted_at": job.queued_at.isoformat(),
            "request": job_request.model_dump(mode="json"),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/result")
@jwt_required()
def get_risk_analysis_result(task_id: str):
    """只在最终结果已经落盘后返回结果；运行中的任务继续使用 202。"""

    store = _job_store()
    job = get_owned_job(task_id, int(get_jwt_identity()))
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    terminal_response = _terminal_conflict(job)
    if terminal_response is not None:
        return terminal_response
    expired_response = _expired_result(job)
    if expired_response is not None:
        return expired_response
    if job.status != "SUCCEEDED":
        return _result_not_ready(job)

    try:
        manifest = _success_manifest(store, job)
    except RiskAnalysisManifestError as exc:
        return _invalid_manifest(job, exc)

    response = jsonify(manifest.model_dump(mode="json"))
    response.headers["Cache-Control"] = "no-store"
    return response, 200


@risk_analysis_bp.get("/jobs/<task_id>/result/artifacts/<artifact_kind>")
@jwt_required()
def download_risk_analysis_artifact(task_id: str, artifact_kind: str):
    """Download a validated persisted result artifact without regenerating it."""

    artifact_responses = {
        "manifest": ("application/json", f"risk-analysis-{task_id}-result.json"),
        "raster": ("image/tiff", f"risk-analysis-{task_id}-risk.tif"),
        "preview": ("image/png", f"risk-analysis-{task_id}-preview.png"),
    }
    if artifact_kind not in artifact_responses:
        return jsonify({"code": "ARTIFACT_NOT_FOUND", "message": "结果文件不存在"}), 404

    store = _job_store()
    job = get_owned_job(task_id, int(get_jwt_identity()))
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    terminal_response = _terminal_conflict(job)
    if terminal_response is not None:
        return terminal_response
    expired_response = _expired_result(job)
    if expired_response is not None:
        return expired_response
    if job.status != "SUCCEEDED":
        return _result_not_ready(job)

    try:
        manifest = _success_manifest(store, job)
    except RiskAnalysisManifestError as exc:
        return _invalid_manifest(job, exc)

    try:
        artifact_path = resolve_risk_analysis_artifact(
            runtime_dir=current_app.config["RUNTIME_DATA_DIR"],
            task_id=task_id,
            manifest=manifest,
            artifact_kind=artifact_kind,
        )
    except RiskAnalysisArtifactError as exc:
        current_app.logger.warning(
            "Invalid risk-analysis result artifact for task %s: %s", task_id, exc
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_ARTIFACT",
                "message": str(exc),
                "task_id": task_id,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    mimetype, download_name = artifact_responses[artifact_kind]
    response = send_file(
        artifact_path,
        mimetype=mimetype,
        as_attachment=artifact_kind != "preview",
        download_name=download_name,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/result/spatial")
@jwt_required()
def get_risk_analysis_spatial_result(task_id: str):
    """Return valid risk raster cells as WGS84 GeoJSON polygons."""

    store = _job_store()
    job = get_owned_job(task_id, int(get_jwt_identity()))
    if job is None:
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    terminal_response = _terminal_conflict(job)
    if terminal_response is not None:
        return terminal_response
    expired_response = _expired_result(job)
    if expired_response is not None:
        return expired_response
    if job.status != "SUCCEEDED":
        return _result_not_ready(job)
    try:
        manifest = _success_manifest(store, job)
    except RiskAnalysisManifestError as exc:
        return _invalid_manifest(job, exc)

    try:
        spatial = build_risk_analysis_spatial_result(
            runtime_dir=current_app.config["RUNTIME_DATA_DIR"],
            task_id=task_id,
            manifest=manifest,
        )
    except RiskAnalysisArtifactError as exc:
        current_app.logger.warning(
            "Invalid risk-analysis spatial artifact for task %s: %s", task_id, exc
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_ARTIFACT",
                "message": str(exc),
                "task_id": task_id,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    response = jsonify(spatial.model_dump(mode="json"))
    response.headers["Cache-Control"] = "no-store"
    return response, 200
