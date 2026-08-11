from __future__ import annotations

import pytest


def _point_payload(distance_m: float = 1000.0) -> dict:
    return {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "distance_m": distance_m,
    }


def _boundary(min_x: float, min_y: float, max_x: float, max_y: float) -> list[list[float]]:
    return [
        [min_x, min_y],
        [max_x, min_y],
        [max_x, max_y],
        [min_x, max_y],
        [min_x, min_y],
    ]


def test_normalize_boundaries_returns_polygon_and_metadata(client):
    response = client.post(
        "/api/v1/analysis-areas/normalize-boundaries",
        json={"boundaries": [_boundary(118.8, 32.0, 118.9, 32.1)]},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["crs"] == "EPSG:4326"
    assert payload["geometry"]["type"] == "Polygon"
    assert payload["input_boundary_count"] == 1
    assert payload["output_polygon_count"] == 1


def test_normalize_boundaries_returns_multipolygon_without_dropping_members(client):
    response = client.post(
        "/api/v1/analysis-areas/normalize-boundaries",
        json={
            "boundaries": [
                _boundary(118.8, 32.0, 118.82, 32.02),
                _boundary(118.9, 32.1, 118.92, 32.12),
            ]
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["geometry"]["type"] == "MultiPolygon"
    assert len(payload["geometry"]["coordinates"]) == 2
    assert payload["input_boundary_count"] == 2
    assert payload["output_polygon_count"] == 2


@pytest.mark.parametrize(
    "boundary",
    [
        [
            [118.8, 32.0],
            [118.9, 32.1],
            [118.9, 32.0],
            [118.8, 32.1],
            [118.8, 32.0],
        ],
        [[118.8, 32.0], [118.9, 32.0], [118.8, 32.0]],
        [[118.8, 32.0], [118.9, 32.0], [118.9, 32.1], [118.8, 32.1]],
        _boundary(181.0, 32.0, 182.0, 32.1),
    ],
)
def test_normalize_boundaries_rejects_invalid_unclosed_or_out_of_range_input(client, boundary):
    response = client.post(
        "/api/v1/analysis-areas/normalize-boundaries",
        json={"boundaries": [boundary]},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] in {"INVALID_REQUEST", "INVALID_ANALYSIS_AREA"}


def test_normalize_boundaries_is_all_or_nothing(client):
    response = client.post(
        "/api/v1/analysis-areas/normalize-boundaries",
        json={
            "boundaries": [
                _boundary(118.8, 32.0, 118.9, 32.1),
                [[118.9, 32.1], [119.0, 32.1], [119.0, 32.2], [118.9, 32.2]],
            ]
        },
    )

    assert response.status_code == 422
    payload = response.get_json()
    assert payload["code"] == "INVALID_ANALYSIS_AREA"
    assert "geometry" not in payload


def test_buffer_endpoint_returns_wgs84_polygon_and_metric_metadata(client):
    response = client.post("/api/v1/analysis-areas/buffer", json=_point_payload())

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"]["crs"] == "EPSG:4326"
    assert payload["source"]["geometry_type"] == "Point"
    assert payload["buffer"]["crs"] == "EPSG:4326"
    assert payload["buffer"]["working_crs"] == "EPSG:32650"
    assert payload["buffer"]["geometry"]["type"] == "Polygon"
    assert payload["buffer"]["area_m2"] > 3_000_000


@pytest.mark.parametrize(
    ("geometry", "geometry_type"),
    [
        (
            {
                "type": "LineString",
                "coordinates": [[118.89, 32.09], [118.91, 32.11]],
            },
            "LineString",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [118.89, 32.09],
                        [118.91, 32.09],
                        [118.91, 32.11],
                        [118.89, 32.09],
                    ]
                ],
            },
            "Polygon",
        ),
    ],
)
def test_buffer_endpoint_accepts_line_and_polygon(client, geometry, geometry_type):
    response = client.post(
        "/api/v1/analysis-areas/buffer",
        json={"geometry": geometry, "distance_m": 1000.0},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"]["geometry_type"] == geometry_type
    assert payload["source"]["crs"] == "EPSG:4326"
    assert payload["buffer"]["geometry"]["type"] == "Polygon"
    assert payload["buffer"]["crs"] == "EPSG:4326"


def test_buffer_endpoint_accepts_polygon_with_hole(client):
    geometry = {
        "type": "Polygon",
        "coordinates": [
            [
                [118.8, 32.0],
                [119.0, 32.0],
                [119.0, 32.2],
                [118.8, 32.2],
                [118.8, 32.0],
            ],
            [
                [118.86, 32.06],
                [118.94, 32.06],
                [118.94, 32.14],
                [118.86, 32.14],
                [118.86, 32.06],
            ],
        ],
    }

    response = client.post(
        "/api/v1/analysis-areas/buffer",
        json={"geometry": geometry, "distance_m": 100.0},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"]["geometry_type"] == "Polygon"
    assert payload["buffer"]["geometry"]["type"] == "Polygon"
    assert len(payload["buffer"]["geometry"]["coordinates"]) == 2


def test_buffer_endpoint_accepts_multipolygon(client):
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [
                [
                    [118.8, 32.0],
                    [118.82, 32.0],
                    [118.82, 32.02],
                    [118.8, 32.02],
                    [118.8, 32.0],
                ]
            ],
            [
                [
                    [118.9, 32.1],
                    [118.92, 32.1],
                    [118.92, 32.12],
                    [118.9, 32.12],
                    [118.9, 32.1],
                ]
            ],
        ],
    }

    response = client.post(
        "/api/v1/analysis-areas/buffer",
        json={"geometry": geometry, "distance_m": 100.0},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["source"]["geometry_type"] == "MultiPolygon"
    assert payload["buffer"]["geometry"]["type"] == "MultiPolygon"
    assert len(payload["buffer"]["geometry"]["coordinates"]) == 2


def test_buffer_endpoint_rejects_malformed_geojson(client):
    payload = _point_payload()
    payload["geometry"] = {"type": "Point", "coordinates": [118.9]}

    response = client.post("/api/v1/analysis-areas/buffer", json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_REQUEST"


def test_buffer_endpoint_rejects_unsupported_geometry_collection(client):
    payload = _point_payload()
    payload["geometry"] = {
        "type": "GeometryCollection",
        "geometries": [{"type": "Point", "coordinates": [118.9, 32.1]}],
    }

    response = client.post("/api/v1/analysis-areas/buffer", json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_ANALYSIS_AREA"


def test_buffer_endpoint_rejects_excessive_distance_before_gis_work(client):
    response = client.post("/api/v1/analysis-areas/buffer", json=_point_payload(20_000.0))

    assert response.status_code == 422
    body = response.get_json()
    assert body["code"] == "INVALID_REQUEST"
    assert any(item["field"] == "distance_m" for item in body["details"])


def test_buffer_endpoint_uses_configured_distance_limit(client, app):
    """修改服务配置后，Buffer API 必须立即使用同一个上限。"""
    app.config["MAX_BUFFER_METERS"] = 2500

    response = client.post("/api/v1/analysis-areas/buffer", json=_point_payload(3000.0))

    assert response.status_code == 422
    body = response.get_json()
    assert body["code"] == "INVALID_REQUEST"
    assert any(
        item["field"] == "distance_m" and "2500" in item["message"]
        for item in body["details"]
    )
