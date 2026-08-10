from __future__ import annotations

from typing import Any
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file, url_for
from pydantic import ValidationError

from app.api.validation import validation_details
from app.extensions import celery as celery_app
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore
from app.schemas.risk_analysis import (
    RiskAnalysisJobRequest,
    RiskAnalysisSubmissionRecord,
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


class TaskStatusBackendUnavailable(RuntimeError):
    """Celery result backend 暂时无法提供任务状态。"""


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


def _final_status_payload(
    *,
    task_id: str,
    submission: dict[str, Any] | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    status = str(result.get("status", "FAILED"))
    invalid_result_error: dict[str, str] | None = None

    if status == "SUCCEEDED":
        try:
            RiskAnalysisSuccessResult.model_validate(result)
        except ValidationError as exc:
            # 文件虽然声称成功，但缺少结果 Contract 必需字段时业务上已经不可消费。
            current_app.logger.warning(
                "Invalid risk-analysis result manifest for task %s: %s",
                task_id,
                exc,
            )
            status = "FAILED"
            invalid_result_error = {
                "code": "INVALID_RESULT_MANIFEST",
                "message": "风险分析结果文件格式不完整或已损坏",
            }

    payload: dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "stage": "COMPLETED" if status == "SUCCEEDED" else "FAILED",
        "progress": 100,
        "result_available": status == "SUCCEEDED",
        "submitted_at": submission.get("submitted_at") if submission else None,
    }
    if invalid_result_error is not None:
        payload["error"] = invalid_result_error
    elif status == "FAILED":
        payload["error"] = result.get("error")
    return payload


def _transient_status_payload(
    *,
    task_id: str,
    submission: dict[str, Any] | None,
) -> dict[str, Any]:
    """把 Celery 的内部状态映射成前端稳定的业务状态。"""

    try:
        async_result = celery_app.AsyncResult(task_id)
        celery_state = str(async_result.state)
        info = async_result.info if isinstance(async_result.info, dict) else {}
    except Exception as exc:
        raise TaskStatusBackendUnavailable("任务状态服务暂时不可用") from exc

    if celery_state in {"PENDING", "RECEIVED"}:
        status, stage, progress = "QUEUED", "QUEUED", 0
    elif celery_state == "PROGRESS":
        status = "RUNNING"
        stage = str(info.get("stage") or "RUNNING")
        raw_progress = info.get("progress")
        progress = raw_progress if isinstance(raw_progress, int) else None
    elif celery_state == "STARTED":
        status, stage, progress = "RUNNING", "STARTED", None
    elif celery_state == "RETRY":
        status, stage, progress = "RETRYING", "RETRYING", None
    elif celery_state == "REVOKED":
        status, stage, progress = "CANCELED", "CANCELED", None
    elif celery_state == "SUCCESS":
        # 正常情况下 result.json 会先于 Celery SUCCESS 产生；这里保留异常状态可观测性。
        status, stage, progress = "SUCCEEDED", "COMPLETED", 100
    elif celery_state == "FAILURE":
        status, stage, progress = "FAILED", "FAILED", 100
    else:
        status, stage, progress = "RUNNING", celery_state, None

    return {
        "task_id": task_id,
        "status": status,
        "stage": stage,
        "progress": progress,
        "result_available": False,
        "submitted_at": submission.get("submitted_at") if submission else None,
    }


def _job_status_payload(store: RiskAnalysisJobStore, task_id: str) -> dict[str, Any] | None:
    submission = store.read_submission(task_id)
    result = store.read_result(task_id)
    if submission is None and result is None:
        return None
    if result is not None:
        return _final_status_payload(task_id=task_id, submission=submission, result=result)
    return _transient_status_payload(task_id=task_id, submission=submission)


@risk_analysis_bp.post("/jobs")
def create_risk_analysis_job():
    """创建异步风险分析任务；HTTP 请求线程不执行任何栅格计算。"""

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

    task_id = str(uuid4())
    store = _job_store()
    submission = store.record_submission(
        task_id=task_id,
        request_payload=job_request.model_dump(mode="json"),
    )

    try:
        # 只按稳定任务名投递 JSON 数据，避免 API 层 import Worker 任务造成 Flask/Celery 循环初始化。
        celery_app.send_task(
            _RISK_ANALYSIS_TASK_NAME,
            kwargs={"payload": job_request.model_dump(mode="json")},
            task_id=task_id,
        )
    except Exception:
        current_app.logger.exception("Failed to enqueue risk-analysis task %s", task_id)
        message = "风险分析任务队列暂时不可用"
        write_failure_manifest(
            runtime_dir=current_app.config["RUNTIME_DATA_DIR"],
            task_id=task_id,
            error_code="QUEUE_UNAVAILABLE",
            message=message,
        )
        return (
            jsonify(
                {
                    "code": "TASK_QUEUE_UNAVAILABLE",
                    "message": message,
                    "task_id": task_id,
                }
            ),
            503,
        )

    status_url, result_url = _status_urls(task_id)
    response = jsonify(
        {
            "task_id": task_id,
            "status": "QUEUED",
            "submitted_at": submission["submitted_at"],
            "status_url": status_url,
            "result_url": result_url,
        }
    )
    response.status_code = 202
    response.headers["Location"] = status_url
    response.headers["Retry-After"] = "2"
    return response


@risk_analysis_bp.get("/jobs")
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

    store = _job_store()
    records: list[tuple[str, str, dict[str, Any] | None]] = []
    for task_id in store.list_task_ids():
        submission = store.read_submission(task_id)
        submitted_at = ""
        if submission is not None:
            raw_submitted_at = submission.get("submitted_at")
            if isinstance(raw_submitted_at, str):
                submitted_at = raw_submitted_at
        records.append((submitted_at, task_id, submission))

    # submitted_at 由服务端统一写成 UTC ISO 8601，可直接按字典序排序；缺失时间的旧任务排在末尾。
    records.sort(key=lambda item: (item[0], item[1]), reverse=True)

    items: list[dict[str, Any]] = []
    # offset/limit 只负责列表窗口切片，total 始终表示完整任务数，前端据此计算总页数。
    for _, task_id, submission in records[offset : offset + limit]:
        try:
            status = _job_status_payload(store, task_id)
        except TaskStatusBackendUnavailable as exc:
            current_app.logger.warning("Risk-analysis history status unavailable: %s", exc)
            return jsonify({"code": "STATUS_UNAVAILABLE", "message": str(exc)}), 503

        if status is None:  # pragma: no cover - 目录扫描与读取之间的极小竞态保护
            continue

        request_payload = submission.get("request") if submission else None
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
            "total": len(records),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>")
def get_risk_analysis_job(task_id: str):
    """查询稳定业务状态；未知 task_id 返回 404，而不是误报为 Celery PENDING。"""

    store = _job_store()
    if not store.task_exists(task_id):
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    try:
        payload = _job_status_payload(store, task_id)
    except TaskStatusBackendUnavailable as exc:
        current_app.logger.warning("Risk-analysis status backend unavailable: %s", exc)
        return jsonify({"code": "STATUS_UNAVAILABLE", "message": str(exc)}), 503

    if payload is None:  # pragma: no cover - task_exists 与读取之间的极小竞态保护
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/submission")
def get_risk_analysis_submission(task_id: str):
    """Return the immutable request persisted before enqueueing the task."""

    store = _job_store()
    if not store.task_exists(task_id):
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    try:
        raw_submission = store.read_submission(task_id)
        if raw_submission is None:
            return (
                jsonify(
                    {
                        "code": "SUBMISSION_NOT_FOUND",
                        "message": "该任务没有可恢复的提交上下文",
                    }
                ),
                404,
            )
        submission = RiskAnalysisSubmissionRecord.model_validate(raw_submission)
    except (OSError, ValueError, ValidationError) as exc:
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

    if submission.task_id != task_id:
        current_app.logger.warning(
            "Risk-analysis submission task id mismatch: route=%s persisted=%s",
            task_id,
            submission.task_id,
        )
        return (
            jsonify(
                {
                    "code": "INVALID_SUBMISSION_MANIFEST",
                    "message": "风险分析提交记录与任务不匹配",
                }
            ),
            409,
        )

    response = jsonify(
        {
            "task_id": submission.task_id,
            "submitted_at": submission.submitted_at,
            # 初始 QUEUED 只是持久化 envelope，不是当前状态；当前状态仍由 /jobs/{id} 提供。
            "request": submission.request.model_dump(mode="json"),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/result")
def get_risk_analysis_result(task_id: str):
    """只在最终结果已经落盘后返回结果；运行中的任务继续使用 202。"""

    store = _job_store()
    if not store.task_exists(task_id):
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    result = store.read_result(task_id)
    if result is not None:
        if result.get("status") == "SUCCEEDED":
            try:
                # API 边界必须验证磁盘上的持久化 Contract，不能把 status=SUCCEEDED 等同于结果完整。
                success_result = RiskAnalysisSuccessResult.model_validate(result)
            except ValidationError as exc:
                current_app.logger.warning(
                    "Invalid risk-analysis result manifest for task %s: %s",
                    task_id,
                    exc,
                )
                response = jsonify(
                    {
                        "code": "INVALID_RESULT_MANIFEST",
                        "message": "风险分析结果文件格式不完整或已损坏",
                        "task_id": task_id,
                        "status": "FAILED",
                    }
                )
                response.headers["Cache-Control"] = "no-store"
                return response, 409

            # 旧的完整结果即使没有 schema_version，也统一规范成当前 v1 响应。
            response = jsonify(success_result.model_dump(mode="json"))
            response.headers["Cache-Control"] = "no-store"
            return response, 200

        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    try:
        status_payload = _job_status_payload(store, task_id)
    except TaskStatusBackendUnavailable as exc:
        current_app.logger.warning("Risk-analysis status backend unavailable: %s", exc)
        return jsonify({"code": "STATUS_UNAVAILABLE", "message": str(exc)}), 503

    response = jsonify(
        {
            "task_id": task_id,
            "status": status_payload["status"] if status_payload else "QUEUED",
            "message": "风险分析任务尚未产生最终结果",
        }
    )
    response.status_code = 202
    response.headers["Retry-After"] = "2"
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/result/artifacts/<artifact_kind>")
def download_risk_analysis_artifact(task_id: str, artifact_kind: str):
    """Download a validated persisted result artifact without regenerating it."""

    artifact_responses = {
        "manifest": ("application/json", f"risk-analysis-{task_id}-result.json"),
        "raster": ("image/tiff", f"risk-analysis-{task_id}-risk.tif"),
    }
    if artifact_kind not in artifact_responses:
        return jsonify({"code": "ARTIFACT_NOT_FOUND", "message": "结果文件不存在"}), 404

    store = _job_store()
    if not store.task_exists(task_id):
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    try:
        result = store.read_result(task_id)
    except (OSError, ValueError) as exc:
        current_app.logger.warning(
            "Invalid risk-analysis result manifest for artifact task %s: %s",
            task_id,
            exc,
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_MANIFEST",
                "message": "风险分析结果文件格式不完整或已损坏",
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    if result is None:
        try:
            status = _job_status_payload(store, task_id)
        except TaskStatusBackendUnavailable as exc:
            current_app.logger.warning("Risk-analysis status backend unavailable: %s", exc)
            return jsonify({"code": "STATUS_UNAVAILABLE", "message": str(exc)}), 503

        if status and status["status"] in {"FAILED", "CANCELED"}:
            response = jsonify(status)
            response.headers["Cache-Control"] = "no-store"
            return response, 409
        if status and status["status"] == "SUCCEEDED":
            response = jsonify(
                {
                    "code": "INVALID_RESULT_ARTIFACT",
                    "message": "成功任务缺少结果文件",
                    "task_id": task_id,
                }
            )
            response.headers["Cache-Control"] = "no-store"
            return response, 409

        response = jsonify(
            {
                "code": "RESULT_NOT_READY",
                "message": "风险分析任务尚未产生最终结果",
                "task_id": task_id,
                "status": status["status"] if status else "QUEUED",
            }
        )
        response.headers["Retry-After"] = "2"
        response.headers["Cache-Control"] = "no-store"
        return response, 202

    if result.get("status") != "SUCCEEDED":
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    try:
        manifest = RiskAnalysisSuccessResult.model_validate(result)
    except ValidationError as exc:
        current_app.logger.warning(
            "Invalid risk-analysis result manifest for artifact task %s: %s",
            task_id,
            exc,
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_MANIFEST",
                "message": "风险分析结果文件格式不完整或已损坏",
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409

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
        as_attachment=True,
        download_name=download_name,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@risk_analysis_bp.get("/jobs/<task_id>/result/spatial")
def get_risk_analysis_spatial_result(task_id: str):
    """Return valid risk raster cells as WGS84 GeoJSON polygons."""

    store = _job_store()
    if not store.task_exists(task_id):
        return jsonify({"code": "JOB_NOT_FOUND", "message": "风险分析任务不存在"}), 404

    try:
        result = store.read_result(task_id)
    except (OSError, ValueError) as exc:
        current_app.logger.warning(
            "Invalid risk-analysis result manifest for spatial task %s: %s",
            task_id,
            exc,
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_MANIFEST",
                "message": "风险分析结果文件格式不完整或已损坏",
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409
    if result is None:
        try:
            status = _job_status_payload(store, task_id)
        except TaskStatusBackendUnavailable as exc:
            current_app.logger.warning("Risk-analysis status backend unavailable: %s", exc)
            return jsonify({"code": "STATUS_UNAVAILABLE", "message": str(exc)}), 503

        if status and status["status"] in {"FAILED", "CANCELED"}:
            response = jsonify(status)
            response.headers["Cache-Control"] = "no-store"
            return response, 409

        response = jsonify(
            {
                "code": "RESULT_NOT_READY",
                "message": "风险分析任务尚未产生最终结果",
                "task_id": task_id,
                "status": status["status"] if status else "QUEUED",
            }
        )
        response.headers["Retry-After"] = "2"
        response.headers["Cache-Control"] = "no-store"
        return response, 202

    if result.get("status") != "SUCCEEDED":
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response, 409

    try:
        manifest = RiskAnalysisSuccessResult.model_validate(result)
        spatial = build_risk_analysis_spatial_result(
            runtime_dir=current_app.config["RUNTIME_DATA_DIR"],
            task_id=task_id,
            manifest=manifest,
        )
    except ValidationError as exc:
        current_app.logger.warning(
            "Invalid risk-analysis result manifest for spatial task %s: %s",
            task_id,
            exc,
        )
        response = jsonify(
            {
                "code": "INVALID_RESULT_MANIFEST",
                "message": "风险分析结果文件格式不完整或已损坏",
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response, 409
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
