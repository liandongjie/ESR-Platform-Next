from pathlib import Path

import pytest

import app.api.v1.health as health
from app.gis.indicators import INDICATORS


class HealthyRedis:
    def ping(self):
        return True

    def close(self):
        pass


def prepare_healthy_dependencies(app, monkeypatch):
    source_dir = app.config["SOURCE_RASTER_DIR"]
    source_dir.mkdir()
    for indicator in INDICATORS:
        (source_dir / indicator.filename).touch()

    monkeypatch.setattr(health.db.session, "execute", lambda statement: None)
    monkeypatch.setattr(health, "create_redis_client", lambda url: HealthyRedis())


def test_live_health(client):
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_live_does_not_check_dependencies(client, monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("dependency check must not run")

    monkeypatch.setattr(health.db.session, "execute", fail)
    monkeypatch.setattr(health, "create_redis_client", fail)
    monkeypatch.setattr(health.os, "scandir", fail)
    monkeypatch.setattr(health.tempfile, "TemporaryFile", fail)

    assert client.get("/api/v1/health/live").status_code == 200


def test_ready_returns_200_when_all_dependencies_are_healthy(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)
    runtime_contents = set(app.config["RUNTIME_DATA_DIR"].iterdir())

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.get_json()["status"] == "ready"
    assert set(app.config["RUNTIME_DATA_DIR"].iterdir()) == runtime_contents


def test_ready_checks_each_distinct_redis_endpoint_once(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)
    redis_url = "redis://localhost:6379/0"
    result_backend_url = "redis://localhost:6379/1"
    app.config["REDIS_URL"] = redis_url
    app.config["CELERY"] = {
        **app.config["CELERY"],
        "broker_url": redis_url,
        "result_backend": result_backend_url,
    }
    calls = []
    monkeypatch.setattr(
        health,
        "create_redis_client",
        lambda url: calls.append(url) or HealthyRedis(),
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert calls == [redis_url, result_backend_url]
    endpoints = response.get_json()["checks"]["redis"]["endpoints"]
    assert endpoints[0]["roles"] == ["redis", "celery_broker"]
    assert endpoints[1]["roles"] == ["celery_result_backend"]


def test_ready_returns_503_when_database_is_unavailable(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)

    def fail(statement):
        raise RuntimeError("raw database exception with secret")

    monkeypatch.setattr(health.db.session, "execute", fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.get_json()["checks"]["database"] == {
        "status": "unavailable",
        "reason": "connection_failed",
    }
    assert "raw database exception" not in response.get_data(as_text=True)


@pytest.mark.parametrize("failed_suffix", ["/0", "/1"])
def test_ready_returns_503_when_redis_endpoint_is_unavailable(
    app, client, monkeypatch, failed_suffix
):
    prepare_healthy_dependencies(app, monkeypatch)
    app.config["REDIS_URL"] = "redis://user:secret@redis.internal:6379/0"
    app.config["CELERY"] = {
        **app.config["CELERY"],
        "broker_url": app.config["REDIS_URL"],
        "result_backend": "redis://user:secret@redis.internal:6379/1",
    }

    def create_client(url):
        if url.endswith(failed_suffix):
            raise RuntimeError("raw redis exception")
        return HealthyRedis()

    monkeypatch.setattr(health, "create_redis_client", create_client)

    response = client.get("/api/v1/health/ready")
    response_text = response.get_data(as_text=True)

    assert response.status_code == 503
    assert response.get_json()["checks"]["redis"]["status"] == "unavailable"
    assert "secret" not in response_text
    assert "redis.internal" not in response_text
    assert "raw redis exception" not in response_text


def test_ready_returns_503_when_source_directory_is_missing(app, client, monkeypatch):
    monkeypatch.setattr(health.db.session, "execute", lambda statement: None)
    monkeypatch.setattr(health, "create_redis_client", lambda url: HealthyRedis())

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.get_json()["checks"]["source_rasters"]["reason"] == (
        "source_directory_missing"
    )


def test_ready_returns_503_when_source_directory_is_unreadable(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)
    original_scandir = health.os.scandir

    def fail_for_source(path):
        if Path(path) == app.config["SOURCE_RASTER_DIR"]:
            raise PermissionError("sensitive absolute path")
        return original_scandir(path)

    monkeypatch.setattr(health.os, "scandir", fail_for_source)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.get_json()["checks"]["source_rasters"]["reason"] == (
        "source_directory_unreadable"
    )
    assert str(app.config["SOURCE_RASTER_DIR"]) not in response.get_data(as_text=True)


def test_ready_returns_503_when_required_raster_is_missing(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)
    missing_filename = INDICATORS[0].filename
    (app.config["SOURCE_RASTER_DIR"] / missing_filename).unlink()

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    check = response.get_json()["checks"]["source_rasters"]
    assert check["reason"] == "required_rasters_missing"
    assert check["files"] == [missing_filename]


def test_ready_returns_503_when_required_raster_is_unreadable(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)
    unreadable_path = app.config["SOURCE_RASTER_DIR"] / INDICATORS[0].filename
    original_open = Path.open

    def fail_for_raster(path, *args, **kwargs):
        if path == unreadable_path:
            raise PermissionError("raw open exception")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_for_raster)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    check = response.get_json()["checks"]["source_rasters"]
    assert check["reason"] == "required_rasters_unreadable"
    assert check["files"] == [unreadable_path.name]
    assert "raw open exception" not in response.get_data(as_text=True)


def test_ready_returns_503_when_runtime_directory_is_unwritable(app, client, monkeypatch):
    prepare_healthy_dependencies(app, monkeypatch)

    def fail(*args, **kwargs):
        raise PermissionError("raw runtime exception")

    monkeypatch.setattr(health.tempfile, "TemporaryFile", fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.get_json()["checks"]["runtime_data"]["reason"] == (
        "runtime_directory_unwritable"
    )
    assert "raw runtime exception" not in response.get_data(as_text=True)


def test_capabilities_exposes_framework_stage(client):
    response = client.get("/api/v1/meta/capabilities")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["project"] == "ESR-Platform-Next"
    assert payload["stage"] == "framework"
    assert payload["coordinate_system"] == "EPSG:4326"


def test_risk_indicator_metadata_exposes_complete_model_contract(client):
    response = client.get("/api/v1/meta/risk-indicators")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema_version"] == 1
    assert payload["model_contract"] == {
        "code": "nimby_facility_siting_environmental_social_risk_sensitivity",
        "name": "邻避设施选址环境社会风险/敏感性",
        "source_value_semantics": "higher_means_higher_risk_contribution",
        "normalized_range": {"minimum": 0.0, "maximum": 1.0},
        "aggregation": "weighted_sum",
        "required_weight_total_percent": 100.0,
    }
    assert payload["categories"] == [
        {"code": "environment", "name": "环境因素", "order": 0},
        {"code": "population", "name": "人口因素", "order": 1},
        {"code": "social", "name": "社会因素", "order": 2},
    ]
    assert len(payload["indicators"]) == 12
    assert {item["risk_direction"] for item in payload["indicators"]} == {
        "increasing"
    }
    assert all(item["risk_semantics"] for item in payload["indicators"])
    assert {
        item["code"]: item["legacy_mvp_default_weight_percent"]
        for item in payload["indicators"]
        if item["legacy_mvp_default_selected"]
    } == {"PM25": 30.0, "AQI": 40.0, "NDVI": 30.0}
