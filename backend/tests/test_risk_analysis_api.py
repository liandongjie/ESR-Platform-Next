from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

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


def _write_success_spatial_artifacts(app, task_id: str) -> None:
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    manifest = _valid_success_manifest(task_id)
    manifest["statistics"] = {
        "valid_pixel_count": 9,
        "minimum": 0.0,
        "maximum": 0.8,
        "mean": 0.4,
    }
    store.write_json(task_id=task_id, filename="result.json", payload=manifest)
    values = np.full((4, 4), -9999.0, dtype="float32")
    values.flat[:9] = np.linspace(0.0, 0.8, 9, dtype="float32")
    with rasterio.open(
        store.task_directory(task_id) / "risk.tif",
        "w",
        driver="GTiff",
        width=4,
        height=4,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(118.0, 32.0, 0.01, 0.01),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(values, 1)


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
    assert submission["request"] == _valid_payload()


def test_submission_endpoint_returns_persisted_request(client, monkeypatch):
    task_id = _create_job(client, monkeypatch)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/submission")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["task_id"] == task_id
    assert payload["submitted_at"]
    assert payload["request"] == _valid_payload()
    assert "status" not in payload


def test_submission_endpoint_returns_404_for_unknown_task(client):
    response = client.get(
        "/api/v1/risk-analysis/jobs/not-created-by-api/submission"
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "JOB_NOT_FOUND"


def test_submission_endpoint_returns_404_when_known_task_has_no_submission(client, app):
    task_id = "result-only-task"
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/submission")

    assert response.status_code == 404
    assert response.get_json()["code"] == "SUBMISSION_NOT_FOUND"


def test_submission_endpoint_rejects_invalid_envelope(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    submission = store.read_submission(task_id)
    assert submission is not None
    submission["status"] = "RUNNING"
    store.write_json(task_id=task_id, filename="submission.json", payload=submission)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/submission")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_SUBMISSION_MANIFEST"


def test_submission_endpoint_rejects_task_id_mismatch(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    submission = store.read_submission(task_id)
    assert submission is not None
    submission["task_id"] = "different-task"
    store.write_json(task_id=task_id, filename="submission.json", payload=submission)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/submission")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_SUBMISSION_MANIFEST"


def test_submission_endpoint_rejects_invalid_request(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    submission = store.read_submission(task_id)
    assert submission is not None
    submission["request"]["weights"] = []
    store.write_json(task_id=task_id, filename="submission.json", payload=submission)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/submission")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_SUBMISSION_MANIFEST"


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


def test_spatial_result_endpoint_returns_custom_contract_with_geojson_cells(
    client,
    app,
    monkeypatch,
):
    task_id = _create_job(client, monkeypatch)
    _write_success_spatial_artifacts(app, task_id)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["schema_version"] == 1
    assert payload["task_id"] == task_id
    assert payload["crs"] == "EPSG:4326"
    assert payload["value_range"] == {"minimum": 0.0, "maximum": 1.0}
    assert payload["feature_collection"]["type"] == "FeatureCollection"
    assert len(payload["feature_collection"]["features"]) == 9
    assert payload["feature_collection"]["features"][0]["properties"]["value"] == 0.0


def test_spatial_result_endpoint_returns_202_while_job_is_running(client, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PROGRESS", {"stage": "ANALYZING", "progress": 35}),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 202
    assert response.get_json()["code"] == "RESULT_NOT_READY"
    assert response.get_json()["status"] == "RUNNING"
    assert response.headers["Retry-After"] == "2"


def test_spatial_result_endpoint_does_not_treat_canceled_as_not_ready(client, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("REVOKED"),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 409
    assert response.get_json()["status"] == "CANCELED"


def test_spatial_result_endpoint_returns_failed_manifest_as_409(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload={
            "task_id": task_id,
            "status": "FAILED",
            "error": {"code": "ANALYSIS_ERROR", "message": "分析失败"},
        },
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 409
    assert response.get_json()["status"] == "FAILED"


def test_spatial_result_endpoint_returns_409_for_missing_raster(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"
    assert "不存在" in response.get_json()["message"]


def test_spatial_result_endpoint_returns_409_for_artifact_declaration_mismatch(
    client,
    app,
    monkeypatch,
):
    task_id = _create_job(client, monkeypatch)
    _write_success_spatial_artifacts(app, task_id)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    manifest = store.read_result(task_id)
    assert manifest is not None
    manifest["artifacts"]["raster"] = "risk-analysis/other-task/risk.tif"
    store.write_json(task_id=task_id, filename="result.json", payload=manifest)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"
    assert "声明" in response.get_json()["message"]


def test_spatial_result_endpoint_returns_409_for_corrupt_manifest(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    (store.task_directory(task_id) / "result.json").write_text("not json", encoding="utf-8")

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_MANIFEST"


def test_spatial_result_endpoint_returns_404_for_unknown_task(client):
    response = client.get("/api/v1/risk-analysis/jobs/unknown-task/result/spatial")

    assert response.status_code == 404
    assert response.get_json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.parametrize(
    ("artifact_kind", "filename", "content_type", "download_suffix"),
    [
        ("manifest", "result.json", "application/json", "-result.json"),
        ("raster", "risk.tif", "image/tiff", "-risk.tif"),
    ],
)
def test_result_artifact_download_returns_exact_persisted_bytes(
    client,
    app,
    monkeypatch,
    artifact_kind,
    filename,
    content_type,
    download_suffix,
):
    task_id = _create_job(client, monkeypatch)
    _write_success_spatial_artifacts(app, task_id)
    artifact_path = (
        RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).task_directory(task_id)
        / filename
    )
    persisted_bytes = artifact_path.read_bytes()
    if artifact_kind == "manifest":
        assert b'"schema_version"' not in persisted_bytes

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 200
    assert response.data == persisted_bytes
    assert response.content_type == content_type
    assert response.headers["Cache-Control"] == "no-store"
    assert "attachment" in response.headers["Content-Disposition"]
    assert download_suffix in response.headers["Content-Disposition"]


def test_manifest_download_does_not_require_raster(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )
    persisted_bytes = (store.task_directory(task_id) / "result.json").read_bytes()

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/manifest"
    )

    assert response.status_code == 200
    assert response.data == persisted_bytes

    raster_response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/raster"
    )
    assert raster_response.status_code == 409
    assert raster_response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"


def test_raster_download_rejects_corrupt_geotiff(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )
    (store.task_directory(task_id) / "risk.tif").write_bytes(b"not a geotiff")

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/raster"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
@pytest.mark.parametrize("manifest_case", ["invalid-json", "missing-artifacts"])
def test_result_artifact_download_rejects_invalid_success_manifest(
    client,
    app,
    monkeypatch,
    artifact_kind,
    manifest_case,
):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    if manifest_case == "invalid-json":
        (store.task_directory(task_id) / "result.json").write_text(
            "not json",
            encoding="utf-8",
        )
    else:
        manifest = _valid_success_manifest(task_id)
        manifest.pop("artifacts")
        store.write_json(task_id=task_id, filename="result.json", payload=manifest)

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_MANIFEST"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_result_artifact_download_rejects_declaration_mismatch(
    client,
    app,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    _write_success_spatial_artifacts(app, task_id)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    manifest = store.read_result(task_id)
    assert manifest is not None
    manifest["artifacts"][artifact_kind] = (
        "risk-analysis/other-task/result.json"
        if artifact_kind == "manifest"
        else "risk-analysis/other-task/risk.tif"
    )
    store.write_json(task_id=task_id, filename="result.json", payload=manifest)

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_result_artifact_download_returns_202_while_running(
    client,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("PROGRESS", {"stage": "ANALYZING", "progress": 35}),
    )

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 202
    assert response.get_json()["code"] == "RESULT_NOT_READY"
    assert response.get_json()["status"] == "RUNNING"
    assert response.headers["Retry-After"] == "2"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_result_artifact_download_returns_canceled_as_409(
    client,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("REVOKED"),
    )

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["status"] == "CANCELED"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_result_artifact_download_returns_failed_manifest_as_409(
    client,
    app,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload={
            "task_id": task_id,
            "status": "FAILED",
            "error": {"code": "ANALYSIS_ERROR", "message": "分析失败"},
        },
    )

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["status"] == "FAILED"


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_result_artifact_download_returns_404_for_unknown_task(client, artifact_kind):
    response = client.get(
        f"/api/v1/risk-analysis/jobs/unknown-task/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 404
    assert response.get_json()["code"] == "JOB_NOT_FOUND"


def test_result_artifact_download_rejects_invalid_or_traversal_paths(
    client,
    app,
    monkeypatch,
):
    task_id = _create_job(client, monkeypatch)
    outside_bytes = b"must not be downloadable"
    outside_path = app.config["RUNTIME_DATA_DIR"] / "outside-secret.txt"
    outside_path.write_bytes(outside_bytes)
    urls = [
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/submission",
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/%2e%2e%2foutside-secret.txt",
        "/api/v1/risk-analysis/jobs/%2e%2e%2foutside/result/artifacts/manifest",
    ]

    for url in urls:
        response = client.get(url)
        assert response.status_code == 404
        assert outside_bytes not in response.data


@pytest.mark.parametrize("artifact_kind", ["manifest", "raster"])
def test_succeeded_job_without_manifest_returns_artifact_conflict(
    client,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.AsyncResult",
        lambda _: FakeAsyncResult("SUCCESS"),
    )

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"


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
