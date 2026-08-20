from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.extensions import db
from app.gis.risk_preview import encode_risk_preview_png
from app.models import AnalysisJob
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore


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


def _post_job(client, payload, key="test-key"):
    return client.post(
        "/api/v1/risk-analysis/jobs",
        json=payload,
        headers={"Idempotency-Key": key},
    )


def _create_job(client, monkeypatch) -> str:
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    response = _post_job(client, _valid_payload())
    assert response.status_code == 202
    task_id = response.get_json()["task_id"]
    return task_id


def _set_job_status(
    app,
    task_id: str,
    status: str,
    stage: str,
    progress: int,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    with app.app_context():
        job = db.session.get(AnalysisJob, task_id)
        job.status = status
        job.stage = stage
        job.progress = progress
        job.error_code = error_code
        job.error_message = error_message
        db.session.commit()


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
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)


def _write_success_preview_artifacts(app, task_id: str) -> bytes:
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    manifest = _valid_success_manifest(task_id)
    manifest["palette_version"] = "risk-viridis-5-v1"
    manifest["grid"]["bounds"] = [118.0, 31.96, 118.04, 32.0]
    manifest["artifacts"]["preview"] = f"risk-analysis/{task_id}/preview.png"
    preview = encode_risk_preview_png(
        np.linspace(0.0, 1.0, 16, dtype=np.float32).reshape(4, 4)
    )
    task_dir = store.task_directory(task_id, create=True)
    (task_dir / "preview.png").write_bytes(preview)
    store.write_json(task_id=task_id, filename="result.json", payload=manifest)
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)
    return preview


def test_create_job_returns_202_and_persists_submission(client, app, monkeypatch):
    sent: dict[str, Any] = {}

    def fake_send_task(name, *, kwargs, task_id):
        sent.update({"name": name, "kwargs": kwargs, "task_id": task_id})
        return object()

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fake_send_task,
    )

    response = _post_job(client, _valid_payload())

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "QUEUED"
    assert response.headers["Location"].endswith(f"/jobs/{payload['task_id']}")
    assert sent["name"] == "app.tasks.risk_analysis.run"
    assert sent["task_id"] == payload["task_id"]
    assert sent["kwargs"]["payload"]["weights"][0]["code"] == "PM25"

    with app.app_context():
        job = db.session.get(AnalysisJob, payload["task_id"])
        assert job.status == "QUEUED"
        assert job.owner_id == 1
        assert job.request_payload == _valid_payload()
        assert job.dispatch_status == "DISPATCHED"
        assert job.dispatched_at is not None


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
    assert response.get_json()["code"] == "JOB_NOT_FOUND"


def test_submission_endpoint_rejects_invalid_request(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    with app.app_context():
        job = db.session.get(AnalysisJob, task_id)
        job.request_payload = {**job.request_payload, "weights": []}
        db.session.commit()

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
    response = _post_job(client, payload)

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
    response = _post_job(client, payload)

    assert response.status_code == 422
    body = response.get_json()
    assert body["code"] == "INVALID_REQUEST"
    assert any(item["field"] == "geometry" for item in body["details"])
    assert called is False


def test_create_job_rejects_area_over_configured_limit(client, monkeypatch):
    called = False

    def fake_send_task(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fake_send_task,
    )
    payload = _valid_payload()
    payload["geometry"] = {
        "type": "Polygon",
        "coordinates": [
            [
                [118.8, 32.0],
                [118.9, 32.0],
                [118.9, 32.1],
                [118.8, 32.1],
                [118.8, 32.0],
            ]
        ],
    }

    response = _post_job(client, payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "ANALYSIS_AREA_TOO_LARGE"
    assert called is False


def test_status_reads_persisted_business_state(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "RUNNING", "ANALYZING", 35)

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
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

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
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

    result_response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")
    status_response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}")

    assert result_response.status_code == 409
    assert result_response.get_json()["code"] == "INVALID_RESULT_MANIFEST"
    assert status_response.status_code == 409
    assert status_response.get_json()["status"] == "SUCCEEDED"
    assert status_response.get_json()["result_available"] is False
    assert status_response.get_json()["error"]["code"] == "INVALID_RESULT_MANIFEST"


def test_result_endpoint_rejects_manifest_for_another_task(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    manifest = _valid_success_manifest(task_id)
    manifest["task_id"] = "another-task"
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload=manifest,
    )
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result")

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_MANIFEST"


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
    _set_job_status(
        app,
        task_id,
        "FAILED",
        "FAILED",
        100,
        error_code="ANALYSIS_ERROR",
        error_message="权重错误",
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


def test_spatial_result_endpoint_returns_202_while_job_is_running(
    client, app, monkeypatch
):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "RUNNING", "ANALYZING", 35)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")

    assert response.status_code == 202
    assert response.get_json()["code"] == "RESULT_NOT_READY"
    assert response.get_json()["status"] == "RUNNING"
    assert response.headers["Retry-After"] == "2"


def test_spatial_result_endpoint_does_not_treat_canceled_as_not_ready(
    client, app, monkeypatch
):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "CANCELED", "CANCELED", 100)

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
    _set_job_status(
        app,
        task_id,
        "FAILED",
        "FAILED",
        100,
        error_code="ANALYSIS_ERROR",
        error_message="分析失败",
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
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

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
    (store.task_directory(task_id, create=True) / "result.json").write_text(
        "not json", encoding="utf-8"
    )
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

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
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)
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


def test_preview_download_returns_validated_inline_png(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    preview = _write_success_preview_artifacts(app, task_id)

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/preview"
    )

    assert response.status_code == 200
    assert response.data == preview
    assert response.content_type == "image/png"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Content-Disposition"].startswith("inline;")


def test_preview_download_rejects_corrupt_png(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    _write_success_preview_artifacts(app, task_id)
    task_dir = RiskAnalysisJobStore(
        app.config["RUNTIME_DATA_DIR"]
    ).task_directory(task_id)
    (task_dir / "preview.png").write_bytes(b"not a png")

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/preview"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_ARTIFACT"


def test_raster_download_rejects_corrupt_geotiff(client, app, monkeypatch):
    task_id = _create_job(client, monkeypatch)
    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    store.write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)
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
        (store.task_directory(task_id, create=True) / "result.json").write_text(
            "not json",
            encoding="utf-8",
        )
    else:
        manifest = _valid_success_manifest(task_id)
        manifest.pop("artifacts")
        store.write_json(task_id=task_id, filename="result.json", payload=manifest)
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

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
    app,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "RUNNING", "ANALYZING", 35)

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
    app,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "CANCELED", "CANCELED", 100)

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
    _set_job_status(
        app,
        task_id,
        "FAILED",
        "FAILED",
        100,
        error_code="ANALYSIS_ERROR",
        error_message="分析失败",
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
    app,
    monkeypatch,
    artifact_kind,
):
    task_id = _create_job(client, monkeypatch)
    _set_job_status(app, task_id, "SUCCEEDED", "COMPLETED", 100)

    response = client.get(
        f"/api/v1/risk-analysis/jobs/{task_id}/result/artifacts/{artifact_kind}"
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_RESULT_MANIFEST"


def test_queue_failure_returns_503_and_persists_failure(client, app, monkeypatch):
    def fail_send_task(*args, **kwargs):
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        fail_send_task,
    )

    response = _post_job(client, _valid_payload())

    assert response.status_code == 503
    payload = response.get_json()
    assert payload["code"] == "TASK_QUEUE_UNAVAILABLE"

    store = RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"])
    result = store.read_result(payload["task_id"])
    assert result is not None
    assert result["status"] == "FAILED"
    assert result["error"]["code"] == "QUEUE_UNAVAILABLE"

    with app.app_context():
        job = db.session.get(AnalysisJob, payload["task_id"])
        assert job.status == "FAILED"
        assert job.dispatch_status == "FAILED"


def test_queue_failure_persists_database_state_when_manifest_write_fails(
    client, app, monkeypatch
):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redis unavailable")),
    )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.write_failure_manifest",
        lambda **kwargs: (_ for _ in ()).throw(OSError("disk unavailable")),
    )

    response = _post_job(client, _valid_payload())

    assert response.status_code == 503
    with app.app_context():
        job = db.session.get(AnalysisJob, response.get_json()["task_id"])
        assert job.status == "FAILED"
        assert job.error_code == "QUEUE_UNAVAILABLE"
        assert job.dispatch_status == "FAILED"


def test_late_enqueue_failure_does_not_publish_failure_manifest(
    client, monkeypatch
):
    manifest_calls = []
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("late broker error")),
    )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.mark_job_failed",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.write_failure_manifest",
        lambda **kwargs: manifest_calls.append(kwargs),
    )

    response = _post_job(client, _valid_payload())

    assert response.status_code == 503
    assert manifest_calls == []


def test_sent_job_stays_pending_when_dispatch_marker_commit_fails(
    client, app, monkeypatch
):
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.celery_app.send_task",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "app.api.v1.risk_analysis.mark_job_dispatched",
        lambda task_id: (_ for _ in ()).throw(RuntimeError("database commit failed")),
    )

    response = _post_job(client, _valid_payload())

    assert response.status_code == 202
    with app.app_context():
        job = db.session.get(AnalysisJob, response.get_json()["task_id"])
        assert job.status == "QUEUED"
        assert job.dispatch_status == "PENDING"


@pytest.mark.parametrize(
    ("url_suffix", "expected_status"),
    [
        ("", 200),
        ("/result", 409),
        ("/result/artifacts/manifest", 409),
        ("/result/spatial", 409),
    ],
)
def test_failed_database_state_wins_over_stale_success_manifest(
    client, app, monkeypatch, url_suffix, expected_status
):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )
    _set_job_status(
        app,
        task_id,
        "FAILED",
        "FAILED",
        100,
        error_code="ANALYSIS_ERROR",
        error_message="分析失败",
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}{url_suffix}")

    assert response.status_code == expected_status
    assert response.get_json()["status"] == "FAILED"
    assert response.get_json()["error"]["code"] == "ANALYSIS_ERROR"


@pytest.mark.parametrize(
    "url_suffix",
    ["/result", "/result/artifacts/manifest", "/result/spatial"],
)
def test_queued_database_state_ignores_stale_success_manifest(
    client, app, monkeypatch, url_suffix
):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}{url_suffix}")

    assert response.status_code == 202
    assert response.get_json()["status"] == "QUEUED"


@pytest.mark.parametrize(
    ("url_suffix", "expected_status"),
    [
        ("", 200),
        ("/result", 409),
        ("/result/artifacts/manifest", 409),
        ("/result/spatial", 409),
    ],
)
def test_canceled_database_state_wins_over_stale_success_manifest(
    client, app, monkeypatch, url_suffix, expected_status
):
    task_id = _create_job(client, monkeypatch)
    RiskAnalysisJobStore(app.config["RUNTIME_DATA_DIR"]).write_json(
        task_id=task_id,
        filename="result.json",
        payload=_valid_success_manifest(task_id),
    )
    _set_job_status(app, task_id, "CANCELED", "CANCELED", 100)

    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}{url_suffix}")

    assert response.status_code == expected_status
    assert response.get_json()["status"] == "CANCELED"
