from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.gis.risk_models import RiskAnalysisValidationError


def parse_geojson_geometry(geojson: Mapping[str, Any]) -> BaseGeometry:
    """把 JSON-safe GeoJSON geometry 转换为 Shapely geometry。

    HTTP API 和 Celery Worker 共用这一入口，避免两层分别维护一套 GeoJSON
    解析规则。这里仅判断 GeoJSON 是否能被正确解析；Polygon 类型、空几何等
    GIS 业务约束仍由 ``RiskAnalysisPipeline`` 统一校验。
    """

    try:
        return shape(dict(geojson))
    except (KeyError, TypeError, ValueError, ShapelyError) as exc:
        raise RiskAnalysisValidationError("geometry 不是合法的 GeoJSON geometry") from exc
