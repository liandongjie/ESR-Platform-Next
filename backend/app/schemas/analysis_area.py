from __future__ import annotations

from typing import Any

from pydantic import Field, FiniteFloat, ValidationInfo, field_validator

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.schemas.common import ApiModel


class AnalysisAreaBufferRequest(ApiModel):
    """研究对象生成米制缓冲区的 HTTP 请求。"""

    geometry: dict[str, Any]
    distance_m: FiniteFloat = Field(gt=0.0)

    @field_validator("distance_m")
    @classmethod
    def validate_distance_limit(cls, value: float, info: ValidationInfo) -> float:
        """缓冲距离上限由应用配置统一提供，避免 Schema 与 capabilities 维护两份规则。"""
        max_buffer_meters = (info.context or {}).get("max_buffer_meters")
        if max_buffer_meters is None:
            return value

        limit = float(max_buffer_meters)
        if value > limit:
            raise ValueError(f"缓冲距离不能超过当前服务上限 {limit:g} 米")
        return value

    @field_validator("geometry")
    @classmethod
    def validate_geojson_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """在进入 GIS 服务前拒绝无法解析的 GeoJSON transport 数据。"""

        try:
            parse_geojson_geometry(value)
        except GeoJsonValidationError as exc:
            raise ValueError(str(exc)) from exc
        return value
