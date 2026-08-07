from __future__ import annotations

from typing import Any

from shapely.geometry import mapping

from app.gis.analysis_area import create_metric_buffer
from app.gis.geojson import parse_geojson_geometry
from app.schemas.analysis_area import AnalysisAreaBufferRequest


class AnalysisAreaService:
    """编排研究区的轻量空间预处理，不承担栅格分析。"""

    def create_buffer(self, request: AnalysisAreaBufferRequest) -> dict[str, Any]:
        geometry = parse_geojson_geometry(request.geometry)
        result = create_metric_buffer(geometry, float(request.distance_m))

        # API 始终返回 WGS84 GeoJSON；working_crs 只用于解释米制缓冲的计算过程。
        return {
            "source": {
                "crs": "EPSG:4326",
                "geometry_type": result.source_geometry.geom_type,
                "bounds": [float(value) for value in result.source_geometry.bounds],
            },
            "buffer": {
                "crs": "EPSG:4326",
                "distance_m": result.distance_m,
                "working_crs": result.working_crs.to_string(),
                "area_m2": result.area_m2,
                "area_km2": result.area_m2 / 1_000_000.0,
                "bounds": [float(value) for value in result.buffer_geometry.bounds],
                "geometry": mapping(result.buffer_geometry),
            },
        }
