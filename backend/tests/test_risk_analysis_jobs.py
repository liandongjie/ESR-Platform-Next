import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from app.gis.indicators import IndicatorDefinition
from app.schemas.risk_analysis import RiskAnalysisJobRequest, RiskAnalysisSuccessResult
from app.services.risk_analysis_jobs import (
    RiskAnalysisArtifactError,
    RiskAnalysisJobService,
    build_risk_analysis_spatial_result,
    write_failure_manifest,
)


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
        IndicatorDefinition(
            code="a",
            name="指标A",
            filename="a.tif",
            category="environment",
            risk_direction="increasing",
            risk_semantics="测试指标值越高，风险贡献越高。",
        ),
        IndicatorDefinition(
            code="b",
            name="指标B",
            filename="b.tif",
            category="environment",
            risk_direction="increasing",
            risk_semantics="测试指标值越高，风险贡献越高。",
        ),
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
    assert payload["schema_version"] == 1
    assert payload["status"] == "SUCCEEDED"
    assert payload["algorithm_version"] == "weighted-overlay-v1"
    assert payload["model_contract"] == {
        "code": "nimby_facility_siting_environmental_social_risk_sensitivity",
        "name": "邻避设施选址环境社会风险/敏感性",
        "source_value_semantics": "higher_means_higher_risk_contribution",
        "normalized_range": {"minimum": 0.0, "maximum": 1.0},
        "aggregation": "weighted_sum",
        "required_weight_total_percent": 100.0,
    }
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


def test_spatial_result_uses_full_affine_and_keeps_zero_distinct_from_nodata(
    tmp_path: Path,
):
    runtime_dir = tmp_path / "runtime"
    task_id = "task-spatial"
    task_dir = runtime_dir / "risk-analysis" / task_id
    task_dir.mkdir(parents=True)
    nodata = -9999.0
    transform = Affine(0.01, 0.002, 118.0, 0.001, -0.01, 32.0)
    values = np.array([[0.0, nodata], [np.nan, 0.75]], dtype="float32")
    with rasterio.open(
        task_dir / "risk.tif",
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)

    manifest = RiskAnalysisSuccessResult.model_validate(
        {
            "task_id": task_id,
            "status": "SUCCEEDED",
            "algorithm_version": "weighted-overlay-v1",
            "geometry": {"type": "Polygon", "bounds": [118.0, 31.9, 118.1, 32.0]},
            "grid": {"crs": "EPSG:4326", "shape": [2, 2], "nodata": nodata},
            "statistics": {
                "valid_pixel_count": 2,
                "minimum": 0.0,
                "maximum": 0.75,
                "mean": 0.375,
            },
            "indicators": [
                {
                    "code": "a",
                    "name": "指标A",
                    "weight_percent": 100.0,
                    "statistics": {
                        "valid_pixel_count": 2,
                        "minimum": 0.0,
                        "maximum": 0.75,
                        "mean": 0.375,
                    },
                }
            ],
            "artifacts": {
                "raster": f"risk-analysis/{task_id}/risk.tif",
                "manifest": f"risk-analysis/{task_id}/result.json",
            },
        }
    )

    spatial = build_risk_analysis_spatial_result(
        runtime_dir=runtime_dir,
        task_id=task_id,
        manifest=manifest,
    ).model_dump(mode="json")

    assert spatial["value_range"] == {"minimum": 0.0, "maximum": 1.0}
    assert "levels" not in spatial and "labels" not in spatial
    features = spatial["feature_collection"]["features"]
    assert [feature["properties"]["value"] for feature in features] == [0.0, 0.75]
    assert features[0]["geometry"]["coordinates"][0] == [
        list(transform * (0, 0)),
        list(transform * (1, 0)),
        list(transform * (1, 1)),
        list(transform * (0, 1)),
        list(transform * (0, 0)),
    ]


def test_spatial_result_rejects_manifest_artifact_mismatch(tmp_path: Path):
    manifest = RiskAnalysisSuccessResult.model_validate(
        {
            "task_id": "task-spatial",
            "status": "SUCCEEDED",
            "algorithm_version": "weighted-overlay-v1",
            "geometry": {"type": "Polygon", "bounds": [118.0, 31.9, 118.1, 32.0]},
            "grid": {"crs": "EPSG:4326", "shape": [1, 1], "nodata": -9999.0},
            "statistics": {
                "valid_pixel_count": 1,
                "minimum": 0.5,
                "maximum": 0.5,
                "mean": 0.5,
            },
            "indicators": [
                {
                    "code": "a",
                    "name": "指标A",
                    "weight_percent": 100.0,
                    "statistics": {
                        "valid_pixel_count": 1,
                        "minimum": 0.5,
                        "maximum": 0.5,
                        "mean": 0.5,
                    },
                }
            ],
            "artifacts": {
                "raster": "risk-analysis/other-task/risk.tif",
                "manifest": "risk-analysis/task-spatial/result.json",
            },
        }
    )

    with pytest.raises(RiskAnalysisArtifactError, match="声明"):
        build_risk_analysis_spatial_result(
            runtime_dir=tmp_path / "runtime",
            task_id="task-spatial",
            manifest=manifest,
        )


@pytest.mark.parametrize(
    ("case", "error_message"),
    [
        ("crs", "CRS 必须是 EPSG:4326"),
        ("dtype", "dtype 必须是 float32"),
        ("shape", "shape 与结果清单不一致"),
        ("nodata", "NoData 与结果清单不一致"),
        ("range", "超出 \\[0,1\\]"),
        ("unreadable", "文件无法读取"),
    ],
)
def test_spatial_result_rejects_invalid_raster_contract(
    tmp_path: Path,
    case: str,
    error_message: str,
):
    runtime_dir = tmp_path / "runtime"
    task_id = f"task-{case}"
    task_dir = runtime_dir / "risk-analysis" / task_id
    task_dir.mkdir(parents=True)
    raster_path = task_dir / "risk.tif"
    nodata = -9999.0

    if case == "unreadable":
        raster_path.write_bytes(b"not a GeoTIFF")
    else:
        values = np.array(
            [[1.1 if case == "range" else 0.5] * (2 if case == "shape" else 1)],
            dtype="int16" if case == "dtype" else "float32",
        )
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            width=values.shape[1],
            height=values.shape[0],
            count=1,
            dtype=values.dtype,
            crs="EPSG:3857" if case == "crs" else "EPSG:4326",
            transform=from_origin(118.0, 32.0, 0.01, 0.01),
            nodata=-9998.0 if case == "nodata" else nodata,
        ) as dataset:
            dataset.write(values, 1)

    manifest = RiskAnalysisSuccessResult.model_validate(
        {
            "task_id": task_id,
            "status": "SUCCEEDED",
            "algorithm_version": "weighted-overlay-v1",
            "geometry": {"type": "Polygon", "bounds": [118.0, 31.9, 118.1, 32.0]},
            "grid": {"crs": "EPSG:4326", "shape": [1, 1], "nodata": nodata},
            "statistics": {
                "valid_pixel_count": 1,
                "minimum": 0.5,
                "maximum": 0.5,
                "mean": 0.5,
            },
            "indicators": [
                {
                    "code": "a",
                    "name": "指标A",
                    "weight_percent": 100.0,
                    "statistics": {
                        "valid_pixel_count": 1,
                        "minimum": 0.5,
                        "maximum": 0.5,
                        "mean": 0.5,
                    },
                }
            ],
            "artifacts": {
                "raster": f"risk-analysis/{task_id}/risk.tif",
                "manifest": f"risk-analysis/{task_id}/result.json",
            },
        }
    )

    with pytest.raises(RiskAnalysisArtifactError, match=error_message):
        build_risk_analysis_spatial_result(
            runtime_dir=runtime_dir,
            task_id=task_id,
            manifest=manifest,
        )


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
    assert payload["schema_version"] == 1
    assert payload["status"] == "FAILED"
    assert payload["error"]["code"] == "ANALYSIS_ERROR"
    assert payload["artifacts"]["manifest"] == "risk-analysis/task-failed/result.json"
