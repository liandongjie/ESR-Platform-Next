from __future__ import annotations

from typing import Any

from pydantic import Field, FiniteFloat, field_validator

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.schemas.common import ApiModel

# 10 km 是第一版 API 的防误用保护阈值，不代表最终业务模型的固定上限。
# 后续会结合真实栅格性能与产品交互，把该阈值调整为配置项。
_MAX_BUFFER_DISTANCE_M = 10_000.0


class AnalysisAreaBufferRequest(ApiModel):
    """研究对象生成米制缓冲区的 HTTP 请求。"""

    geometry: dict[str, Any]
    distance_m: FiniteFloat = Field(gt=0.0, le=_MAX_BUFFER_DISTANCE_M)

    @field_validator("geometry")
    @classmethod
    def validate_geojson_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """在进入 GIS 服务前拒绝无法解析的 GeoJSON transport 数据。"""

        try:
            parse_geojson_geometry(value)
        except GeoJsonValidationError as exc:
            raise ValueError(str(exc)) from exc
        return value
