from __future__ import annotations

from typing import Any

from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore


class FakeAsyncResult:
    def __init__(self, state: str, info: dict[str, Any] | None = None) -> None:
        self.state = state
        self.info = info


def _valid_payload() -> dict[str, Any]:
    return {
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [118.885, 32.085],
                    [118.915, 32.085],
                    [118.915, 32.115],
                    [118.885, 32.115],
                    [118.885, 32.085],
                ]
            ],
        },
        "weights": [
            {"code": "PM25", "weight_percent": 30},
            {"code": "AQI", "weight_percent": 40},
            {"code": "NDVI", "weight_percent": 30},
        ],
    }


def _valid_success_manifest(task_id: str) -> dict[str, Any]:
    """模拟 schema_version 引入前已经生成、但字段完整的真实历史结果。"""

    return {
        "task_id": task_id,
        "status": "SUCCEEDED",
        "algorithm_version": "weighted-overlay-v1",
        "geometry": {
            "type": "Polygon",
            "bounds": [118.885, 32.085, 118.915, 32.115],
        },
        "grid": {
            "crs": "EPSG:4326",
            "shape": [4, 4],
            "nodata": -9999.0,
        },
        "statistics": {
            "valid_pixel_count": 9,
            "minimum": 0.36,
            "maximum": 0.41,
            "mean": 0.37,
        },
        "indicators": [
            {
                "code": "PM25",
                "name": "细颗粒物 (PM2.5)",
                "weight_percent": 100.0,
                "statistics": {
                    "valid_pixel_count": 9,
                    "minimum": 0.36,
                    "maximum": 0.41,
                    "mean": 0.37,
                },
            }
        ],
        "artifacts": {
            "raster": f"risk-analysis/{task_id}/risk.tif",
            "manifest": f"risk-analysis/{task_id}/result.json",
        },
    }


def _create_job(client, monkeypatch) -> str:
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    response = client.post("/api/v1/risk-analysis/jobs", json=_valid_payload())
    assert response.status_code == 202
    return response.get_json()["task_id"]


def test_create_job_returns_202_and_persists_submission(client, app, monkeypatch):
    sent: dict[str, Any] = {}

    def fake_send_task(name, *, kwargs, task_id):
        sent.update({"name": name, "kwargs": kwargs, "task_id": task_id})
        return object()

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fake_send_task,
    )

    response = client.post("/api/v1/risk-analysis/jobs", json=_valid_payload())

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "QUEUED"
    assert response.headers["Location"].endswith(f"/jobs/{payload['task_id']}")
    assert sent["name"] == "app.tasks.risk_analysis.run"
    assert sent["task_id"] == payload["task_id"]
    assert sent["kwargs"]["payload"]["weights"][0]["code"] == "PM25"

    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    submission = store.read_submission(payload["task_id"])
    assert submission is not None
    assert submission["status"] == "QUEUED"


def test_create_job_rejects_structurally_invalid_request_without_enqueue(client, monkeypatch):
    called = False

    def fake_send_task(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fake_send_task,
    )

    payload = _valid_payload()
    payload["weights"] = []
    response = client.post("/api/v1/risk-analysis/jobs", json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "INVALID_REQUEST"
    assert called is False


def test_create_job_rejects_malformed_geojson_without_enqueue(client, monkeypatch):
    called = False

    def fake_send_task(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fake_send_task,
    )

    payload = _valid_payload()
    # 模拟客户端把 Polygon 坐标层级压平后的请求；这种请求不能进入 Celery。
    payload["geometry"] = {
        "type": "Polygon",
        "coordinates": [118.885, 32.085, 118.915, 32.085],
    }
    response = client.post("/api/v1/risk-analysis/jobs", json=payload)

    assert response.status_code == 422
    body = response.get_json()
    assert body["code"] == "INVALID_REQUEST"
    assert any(item["field"] == "geometry" for item in body["details"])
    assert called is False


def test_status_maps_celery_progress_to_stable_business_state(client, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PROGRESS", {"stage": "ANALYZING", "progress": 35}),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}")

    assert response.status_code == 200
    assert response.get_json()["status"] == "RUNNING"
    assert response.get_json()["stage"] == "ANALYZING"
    assert response.get_json()["progress"] == 35
    assert response.get_json()["result_available"] is False


def test_unknown_task_id_returns_404_instead_of_celery_pending(client):
    response = client.get("/api/v1/risk-analysis/jobs/not-created-by-api")

    assert response.status_code == 404
    assert response.get_json()["code"] == "JOB_NOT_FOUND"


def test_result_endpoint_returns_202_before_final_manifest(client, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PENDING"),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")

    assert response.status_code == 202
    assert response.get_json()["status"] == "QUEUED"
    assert response.headers["Retry-After"] == "2"


def test_result_endpoint_returns_success_manifest(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    # 完整历史结果即使没有 schema_version，也应该按 v1 继续兼容。
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")

    assert response.status_code == 200
    assert response.get_json()["schema_version"] == 1
    assert response.get_json()["status"] == "SUCCEEDED"
    assert response.get_json()["statistics"]["valid_pixel_count"] == 9


def test_result_endpoint_rejects_incomplete_success_manifest(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    # 复现早期 pytest 污染真实 runtime 时留下的残缺 SUCCEEDED result.json。
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload={
            "task_id": task_id,
            "status": "SUCCEEDED",
            "statistics": {"valid_pixel_count": 9, "mean": 0.37},
        },
    )

    result_response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")
    status_response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}")

    assert result_response.status_code == 409
    assert result_response.get_json()["code"] == "INVALID_RESULT_MANIFEST"
    assert status_response.status_code == 200
    assert status_response.get_json()["status"] == "FAILED"
    assert status_response.get_json()["result_available"] is False
    assert status_response.get_json()["error"]["code"] == "INVALID_RESULT_MANIFEST"


def test_result_endpoint_returns_409_for_failed_job(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload={
            "task_id": task_id,
            "status": "FAILED",
            "error": {"code": "ANALYSIS_ERROR", "message": "权重错误"},
        },
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "ANALYSIS_ERROR"


def test_queue_failure_returns_503_and_persists_failure(client, app, monkeypatch):
    def fail_send_task(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fail_send_task,
    )

    response = client.post("/api/v1/risk-analysis/jobs", json=_valid_payload())

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["code"] == "TASK_QUEUE_UNAVAILABLE"

    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    result = store.read_result(payload["task_id"])
    assert result is not None
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "QUEUE_UNAVAILABLE"
