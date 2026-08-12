from __future__ import annotations

from typing import Any, BinaryIO

from shapely.geometry import mapping

from app.gis.analysis_area import create_metric_buffer, normalize_boundaries
from app.gis.geojson import parse_geojson_geometry
from app.gis.shapefile import import_shapefile_zip
from app.schemas.analysis_area import (
    AdministrativeBoundariesNormalizeRequest,
    AnalysisAreaBufferRequest,
)


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

    def import_shapefile(self, stream: BinaryIO) -> dict[str, Any]:
        result = import_shapefile_zip(stream)
        return {
            "crs": "EPSG:4326",
            "source_crs": result.source_crs,
            "feature_count": result.feature_count,
            "coordinate_count": result.coordinate_count,
            "geometry": mapping(result.geometry),
        }

    def normalize_boundaries(
        self, request: AdministrativeBoundariesNormalizeRequest
    ) -> dict[str, Any]:
        geometry = normalize_boundaries(request.boundaries)
        output_polygon_count = 1 if geometry.geom_type == "Polygon" else len(geometry.geoms)
        return {
            "crs": "EPSG:4326",
            "geometry": mapping(geometry),
            "input_boundary_count": len(request.boundaries),
            "output_polygon_count": output_polygon_count,
        }
