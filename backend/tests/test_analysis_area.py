from __future__ import annotations

import math

import pytest
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.gis.analysis_area import (
    AnalysisAreaValidationError,
    create_metric_buffer,
    local_utm_crs,
)


def test_point_buffer_uses_nanjing_utm_and_metric_area():
    result = create_metric_buffer(Point(118.9, 32.1), 1000.0)

    assert result.working_crs.to_epsg() == 32650
    assert result.buffer_geometry.geom_type == "Polygon"
    # Shapely 默认圆弧离散会略小于理论圆面积，因此只要求误差保持在合理范围。
    assert result.area_m2 == pytest.approx(math.pi * 1_000_000.0, rel=0.01)


@pytest.mark.parametrize(
    ("geometry", "geometry_type"),
    [
        (LineString([(118.89, 32.09), (118.91, 32.11)]), "LineString"),
        (
            Polygon(
                [
                    (118.89, 32.09),
                    (118.91, 32.09),
                    (118.91, 32.11),
                    (118.89, 32.09),
                ]
            ),
            "Polygon",
        ),
    ],
)
def test_line_and_polygon_use_the_existing_metric_buffer_contract(
    geometry, geometry_type
):
    result = create_metric_buffer(geometry, 1000.0)

    assert result.source_geometry.geom_type == geometry_type
    assert result.working_crs.to_epsg() == 32650
    assert result.buffer_geometry.geom_type == "Polygon"
    assert result.area_m2 > 0


def test_southern_hemisphere_uses_southern_utm_zone():
    assert local_utm_crs(Point(151.2, -33.8)).to_epsg() == 32756


def test_metric_buffer_rejects_non_positive_distance():
    with pytest.raises(AnalysisAreaValidationError, match="大于 0"):
        create_metric_buffer(Point(118.9, 32.1), 0.0)


def test_metric_buffer_rejects_geometry_collection():
    geometry = GeometryCollection([Point(118.9, 32.1)])

    with pytest.raises(AnalysisAreaValidationError, match="暂不支持 GeometryCollection"):
        create_metric_buffer(geometry, 1000.0)


def test_metric_buffer_rejects_invalid_polygon():
    bow_tie = Polygon(
        [
            (118.89, 32.09),
            (118.91, 32.11),
            (118.91, 32.09),
            (118.89, 32.11),
            (118.89, 32.09),
        ]
    )

    with pytest.raises(AnalysisAreaValidationError, match="geometry 无效"):
        create_metric_buffer(bow_tie, 1000.0)


def test_metric_buffer_rejects_coordinates_outside_wgs84_range():
    with pytest.raises(AnalysisAreaValidationError, match="超出 WGS84"):
        create_metric_buffer(Point(200.0, 32.1), 1000.0)
