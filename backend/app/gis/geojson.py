from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from shapely.errors import ShapelyError
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


class GeoJsonValidationError(ValueError):
    """GeoJSON transport data cannot be parsed into a Shapely geometry."""


def parse_geojson_geometry(geojson: Mapping[str, Any]) -> BaseGeometry:
    """把 JSON-safe GeoJSON geometry 转换为 Shapely geometry。

    HTTP API、Celery Worker 和研究区服务共用这一入口，避免不同边界各自
    维护一套 GeoJSON 解析规则。这里只判断 transport 数据能否正确解析，
    Polygon 类型、空间范围、缓冲区距离等 GIS 业务规则由各自领域服务校验。
    """

    try:
        return shape(dict(geojson))
    except (KeyError, TypeError, ValueError, ShapelyError) as exc:
        raise GeoJsonValidationError("geometry 不是合法的 GeoJSON geometry") from exc
