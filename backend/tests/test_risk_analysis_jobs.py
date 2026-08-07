import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from app.gis.indicators import IndicatorDefinition
from app.schemas.risk_analysis import RiskAnalysisJobRequest
from app.services.risk_analysis_jobs import RiskAnalysisJobService, write_failure_manifest


def _write_raster(path: Path, values: np.ndarray, *, nodata: float = -9999.0) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(118.0, 32.0, 0.01, 0.01),
        nodata=nodata,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def _catalog() -> tuple[IndicatorDefinition, ...]:
    return (
        IndicatorDefinition(code="a", name="指标A", filename="a.tif"),
        IndicatorDefinition(code="b", name="指标B", filename="b.tif"),
    )


def _request() -> RiskAnalysisJobRequest:
    return RiskAnalysisJobRequest.model_validate(
        {
            "geometry": mapping(box(118.0, 31.98, 118.02, 32.0)),
            "weights": [
                {"code": "a", "weight_percent": 25},
                {"code": "b", "weight_percent": 75},
            ],
        }
    )


def test_job_service_persists_task_scoped_raster_and_manifest(tmp_path: Path):
    raster_dir = tmp_path / "source"
    runtime_dir = tmp_path / "runtime"
    raster_dir.mkdir()
    _write_raster(raster_dir / "a.tif", np.array([[0.2, 0.4], [0.6, 0.8]]))
    _write_raster(raster_dir / "b.tif", np.array([[0.8, 0.6], [0.4, 0.2]]))

    service = RiskAnalysisJobService(raster_dir, runtime_dir, indicators=_catalog())
    payload = service.execute(task_id="task-123", request=_request())

    task_dir = runtime_dir / "risk-analysis" / "task-123"
    raster_path = task_dir / "risk.tif"
    manifest_path = task_dir / "result.json"
    assert raster_path.is_file()
    assert manifest_path.is_file()
    assert payload["status"] == "SUCCEEDED"
    assert payload["algorithm_version"] == "weighted-overlay-v1"
    assert payload["artifacts"]["raster"] == "risk-analysis/task-123/risk.tif"
    assert payload["statistics"]["mean"] == pytest.approx(0.5)

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert persisted == payload
    with rasterio.open(raster_path) as dataset:
        values = dataset.read(1, masked=True)
        np.testing.assert_allclose(
            values.compressed(),
            np.array([0.65, 0.55, 0.45, 0.35], dtype="float32"),
            atol=1e-6,
        )


def test_job_service_reports_ordered_coarse_progress(tmp_path: Path):
    raster_dir = tmp_path / "source"
    raster_dir.mkdir()
    values = np.full((2, 2), 0.5, dtype="float32")
    _write_raster(raster_dir / "a.tif", values)
    _write_raster(raster_dir / "b.tif", values)
    events: list[tuple[str, int]] = []

    RiskAnalysisJobService(raster_dir, tmp_path / "runtime", indicators=_catalog()).execute(
        task_id="task-progress",
        request=_request(),
        on_progress=lambda stage, progress: events.append((stage, progress)),
    )

    assert events == [
        ("PREPARING", 15),
        ("ANALYZING", 35),
        ("PERSISTING", 85),
        ("COMPLETED", 100),
    ]


def test_task_id_cannot_escape_runtime_directory(tmp_path: Path):
    raster_dir = tmp_path / "source"
    raster_dir.mkdir()
    values = np.full((2, 2), 0.5, dtype="float32")
    _write_raster(raster_dir / "a.tif", values)
    _write_raster(raster_dir / "b.tif", values)

    service = RiskAnalysisJobService(raster_dir, tmp_path / "runtime", indicators=_catalog())
    for unsafe_task_id in ("../escape", "..", "."):
        with pytest.raises(ValueError, match="task_id"):
            service.execute(task_id=unsafe_task_id, request=_request())

    assert not (tmp_path / "escape").exists()


def test_failure_manifest_uses_same_task_scoped_contract(tmp_path: Path):
    runtime_dir = tmp_path / "runtime"
    payload = write_failure_manifest(
        runtime_dir=runtime_dir,
        task_id="task-failed",
        error_code="ANALYSIS_ERROR",
        message="研究区没有有效像元",
    )

    manifest = runtime_dir / "risk-analysis" / "task-failed" / "result.json"
    assert manifest.is_file()
    assert payload == json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "FAILED"
    assert payload["error"]["code"] == "ANALYSIS_ERROR"
    assert payload["artifacts"]["manifest"] == "risk-analysis/task-failed/result.json"
