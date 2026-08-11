from __future__ import annotations

import math

import pytest
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon

from app.gis.analysis_area import (
    AnalysisAreaValidationError,
    create_metric_buffer,
    local_utm_crs,
    normalize_boundaries,
)


def _boundary(min_x: float, min_y: float, max_x: float, max_y: float):
    return [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
        (min_x, min_y),
    ]


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


def test_polygon_with_hole_preserves_the_existing_metric_buffer_contract():
    geometry = Polygon(
        [
            (118.8, 32.0),
            (119.0, 32.0),
            (119.0, 32.2),
            (118.8, 32.2),
            (118.8, 32.0),
        ],
        [
            [
                (118.86, 32.06),
                (118.94, 32.06),
                (118.94, 32.14),
                (118.86, 32.14),
                (118.86, 32.06),
            ]
        ],
    )

    result = create_metric_buffer(geometry, 100.0)

    assert result.source_geometry.geom_type == "Polygon"
    assert result.buffer_geometry.geom_type == "Polygon"
    assert len(result.buffer_geometry.interiors) == 1


def test_multipolygon_preserves_all_disjoint_members_after_buffering():
    geometry = MultiPolygon(
        [
            Polygon(
                [
                    (118.8, 32.0),
                    (118.82, 32.0),
                    (118.82, 32.02),
                    (118.8, 32.02),
                    (118.8, 32.0),
                ]
            ),
            Polygon(
                [
                    (118.9, 32.1),
                    (118.92, 32.1),
                    (118.92, 32.12),
                    (118.9, 32.12),
                    (118.9, 32.1),
                ]
            ),
        ]
    )

    result = create_metric_buffer(geometry, 100.0)

    assert result.source_geometry.geom_type == "MultiPolygon"
    assert result.buffer_geometry.geom_type == "MultiPolygon"
    assert len(result.buffer_geometry.geoms) == 2


def test_normalize_single_boundary_returns_polygon():
    geometry = normalize_boundaries([_boundary(118.8, 32.0, 118.9, 32.1)])

    assert geometry.geom_type == "Polygon"
    assert geometry.is_valid


def test_normalize_disjoint_boundaries_returns_all_members():
    geometry = normalize_boundaries(
        [
            _boundary(118.8, 32.0, 118.82, 32.02),
            _boundary(118.9, 32.1, 118.92, 32.12),
        ]
    )

    assert geometry.geom_type == "MultiPolygon"
    assert len(geometry.geoms) == 2


@pytest.mark.parametrize(
    "boundaries",
    [
        [
            _boundary(118.8, 32.0, 119.0, 32.2),
            _boundary(118.86, 32.06, 118.94, 32.14),
        ],
        [
            _boundary(118.8, 32.0, 118.9, 32.1),
            _boundary(118.85, 32.05, 118.95, 32.15),
        ],
        [
            _boundary(118.75, 31.95, 119.05, 32.25),
            _boundary(118.82, 32.02, 118.92, 32.12),
            _boundary(119.0, 32.1, 119.12, 32.3),
        ],
    ],
)
def test_normalize_dissolves_contained_overlapping_and_nanjing_like_boundaries(boundaries):
    geometry = normalize_boundaries(boundaries)

    assert geometry.geom_type == "Polygon"
    assert geometry.is_valid


@pytest.mark.parametrize(
    ("boundary", "message"),
    [
        (
            [
                (118.8, 32.0),
                (118.9, 32.1),
                (118.9, 32.0),
                (118.8, 32.1),
                (118.8, 32.0),
            ],
            "有效",
        ),
        ([(118.8, 32.0), (118.9, 32.0), (118.8, 32.0)], "至少需要"),
        ([(118.8, 32.0), (118.9, 32.0), (118.9, 32.1), (118.8, 32.1)], "闭合"),
        (
            [(118.8, 32.0), (math.inf, 32.0), (118.9, 32.1), (118.8, 32.0)],
            "有限",
        ),
        (_boundary(181.0, 32.0, 182.0, 32.1), "WGS84"),
    ],
)
def test_normalize_rejects_invalid_boundary(boundary, message):
    with pytest.raises(AnalysisAreaValidationError, match=message):
        normalize_boundaries([boundary])


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
