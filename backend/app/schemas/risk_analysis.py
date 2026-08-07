"""
Author: liandongjie
Date: 2026-08-07 16:59:18
LastEditors: liandongjie
LastEditTime: 2026-08-07 17:51:55
Description:
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, FiniteFloat, field_validator

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.schemas.common import ApiModel


class RiskIndicatorWeightInput(ApiModel):
    """JSON-safe weight item accepted at the asynchronous job boundary."""

    code: str = Field(min_length=1, max_length=64)
    weight_percent: FiniteFloat = Field(ge=0.0, le=100.0)


class RiskAnalysisJobRequest(ApiModel):
    """Serializable request passed from the API process to a Celery worker.

    Geometry stays as GeoJSON at the transport boundary. The worker converts it to
    Shapely only after deserialization, which keeps the Celery message JSON-only and
    avoids sending Python/GDAL objects through Redis.
    """

    geometry: dict[str, Any]
    weights: list[RiskIndicatorWeightInput] = Field(min_length=1, max_length=12)

    @field_validator("geometry")
    @classmethod
    def validate_geojson_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """在任务入队前拒绝无法解析的 GeoJSON，避免浪费 Worker 槽位。"""

        try:
            parse_geojson_geometry(value)
        except GeoJsonValidationError as exc:
            # 转成 ValueError 后由 Pydantic 统一包装成 API 可返回的 422 校验错误。
            raise ValueError(str(exc)) from exc
        return value
