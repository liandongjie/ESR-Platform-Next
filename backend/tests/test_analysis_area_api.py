from __future__ import annotations


def _point_payload(distance_m: float = 1000.0) -> dict:
    return {
        "geometry": {"type": "Point", "coordinates": [118.9, 32.1]},
        "distance_m": distance_m,
    }


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
