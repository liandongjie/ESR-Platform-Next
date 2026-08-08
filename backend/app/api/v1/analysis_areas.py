from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from app.api.validation import validation_details
from app.gis.analysis_area import AnalysisAreaValidationError
from app.schemas.analysis_area import AnalysisAreaBufferRequest
from app.services.analysis_areas import AnalysisAreaService

analysis_areas_bp = Blueprint("analysis_areas", __name__)


@analysis_areas_bp.post("/buffer")
def create_analysis_area_buffer():
    """按米生成研究对象缓冲区；该轻量向量运算同步完成，不占用 Celery Worker。"""

    raw_payload = request.get_json(silent=True)
    if not isinstance(raw_payload, dict):
        return jsonify({"code": "INVALID_JSON", "message": "请求体必须是 JSON object"}), 400

    try:
        # 与 /meta/capabilities 共用 MAX_BUFFER_METERS，避免前端展示和后端校验出现双重标准。
        buffer_request = AnalysisAreaBufferRequest.model_validate(
            raw_payload,
            context={"max_buffer_meters": current_app.config["MAX_BUFFER_METERS"]},
        )
    except ValidationError as exc:
        return (
            jsonify(
                {
                    "code": "INVALID_REQUEST",
                    "message": "研究区缓冲参数校验失败",
                    "details": validation_details(exc),
                }
            ),
            422,
        )

    try:
        payload = AnalysisAreaService().create_buffer(buffer_request)
    except AnalysisAreaValidationError as exc:
        # 这里是空间业务约束失败，不属于服务器异常，因此返回 422 而不是 500。
        return jsonify({"code": "INVALID_ANALYSIS_AREA", "message": str(exc)}), 422

    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, 200
