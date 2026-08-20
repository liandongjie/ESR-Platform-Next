import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from affine import Affine
from rasterio.transform import from_origin
from shapely.geometry import box, mapping

from app.gis.indicators import IndicatorDefinition
from app.gis.risk_preview import RISK_PREVIEW_PALETTE_VERSION
from app.schemas.risk_analysis import RiskAnalysisJobRequest, RiskAnalysisSuccessResult
from app.services.risk_analysis_jobs import (
    RiskAnalysisArtifactError,
    RiskAnalysisJobService,
    build_risk_analysis_spatial_result,
    resolve_risk_analysis_artifact,
    validate_risk_analysis_raster,
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


def _success_manifest(
    *,
    task_id: str,
    shape: tuple[int, int],
    nodata: float,
    statistics: dict[str, int | float],
) -> RiskAnalysisSuccessResult:
    return RiskAnalysisSuccessResult.model_validate(
        {
            "task_id": task_id,
            "status": "SUCCEEDED",
            "algorithm_version": "weighted-overlay-v1",
            "geometry": {"type": "Polygon", "bounds": [118.0, 31.9, 118.1, 32.0]},
            "grid": {"crs": "EPSG:4326", "shape": shape, "nodata": nodata},
            "statistics": statistics,
            "indicators": [
                {
                    "code": "a",
                    "name": "指标A",
                    "weight_percent": 100.0,
                    "statistics": statistics,
                }
            ],
            "artifacts": {
                "raster": f"risk-analysis/{task_id}/risk.tif",
                "manifest": f"risk-analysis/{task_id}/result.json",
            },
        }
    )


def _write_result_raster(
    tmp_path: Path,
    *,
    task_id: str,
    values: np.ndarray,
    nodata: float = -9999.0,
) -> Path:
    runtime_dir = tmp_path / "runtime"
    task_dir = runtime_dir / "risk-analysis" / task_id
    task_dir.mkdir(parents=True)
    _write_raster(task_dir / "risk.tif", values, nodata=nodata)
    return runtime_dir


def test_validate_risk_raster_keeps_zero_and_skips_masked_or_non_finite_values(
    tmp_path: Path,
):
    task_id = "task-direct-valid"
    nodata = -9999.0
    values = np.array(
        [[0.0, 0.25, nodata], [np.nan, np.inf, 1.0]],
        dtype="float32",
    )
    runtime_dir = _write_result_raster(
        tmp_path,
        task_id=task_id,
        values=values,
        nodata=nodata,
    )
    manifest = _success_manifest(
        task_id=task_id,
        shape=values.shape,
        nodata=nodata,
        statistics={
            "valid_pixel_count": 3,
            "minimum": 0.0,
            "maximum": 1.0,
            "mean": 5.0 / 12.0,
        },
    )

    band, transform = validate_risk_analysis_raster(
        runtime_dir=runtime_dir,
        task_id=task_id,
        manifest=manifest,
    )

    assert band.dtype == np.dtype("float32")
    np.testing.assert_array_equal(np.ma.getmaskarray(band), values == nodata)
    assert transform == from_origin(118.0, 32.0, 0.01, 0.01)


def test_validate_risk_raster_accepts_empty_finite_valid_set(tmp_path: Path):
    task_id = "task-direct-empty"
    nodata = -9999.0
    values = np.array([[nodata, np.nan, np.inf]], dtype="float32")
    runtime_dir = _write_result_raster(
        tmp_path,
        task_id=task_id,
        values=values,
        nodata=nodata,
    )
    manifest = _success_manifest(
        task_id=task_id,
        shape=values.shape,
        nodata=nodata,
        statistics={
            "valid_pixel_count": 0,
            "minimum": 0.0,
            "maximum": 0.0,
            "mean": 0.0,
        },
    )

    band, _ = validate_risk_analysis_raster(
        runtime_dir=runtime_dir,
        task_id=task_id,
        manifest=manifest,
    )

    assert band.count() == 2
    assert np.isfinite(band.compressed()).sum() == 0


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_validate_risk_raster_rejects_out_of_range_before_count_mismatch(
    tmp_path: Path,
    value: float,
):
    task_id = f"task-direct-range-{value}"
    values = np.array([[value]], dtype="float32")
    runtime_dir = _write_result_raster(tmp_path, task_id=task_id, values=values)
    manifest = _success_manifest(
        task_id=task_id,
        shape=values.shape,
        nodata=-9999.0,
        statistics={
            "valid_pixel_count": 0,
            "minimum": 0.0,
            "maximum": 0.0,
            "mean": 0.0,
        },
    )

    with pytest.raises(RiskAnalysisArtifactError, match="超出 \\[0,1\\]"):
        validate_risk_analysis_raster(
            runtime_dir=runtime_dir,
            task_id=task_id,
            manifest=manifest,
        )


@pytest.mark.parametrize(
    ("statistics", "error_message"),
    [
        (
            {"valid_pixel_count": 1, "minimum": 0.25, "maximum": 0.75, "mean": 0.5},
            "有效像元数与结果清单不一致",
        ),
        (
            {"valid_pixel_count": 2, "minimum": 0.25, "maximum": 0.75, "mean": 0.6},
            "统计值与结果清单不一致",
        ),
    ],
)
def test_validate_risk_raster_rejects_manifest_value_mismatch(
    tmp_path: Path,
    statistics: dict[str, int | float],
    error_message: str,
):
    task_id = "task-direct-manifest-mismatch"
    values = np.array([[0.25, 0.75]], dtype="float32")
    runtime_dir = _write_result_raster(tmp_path, task_id=task_id, values=values)
    manifest = _success_manifest(
        task_id=task_id,
        shape=values.shape,
        nodata=-9999.0,
        statistics=statistics,
    )

    with pytest.raises(RiskAnalysisArtifactError, match=error_message):
        validate_risk_analysis_raster(
            runtime_dir=runtime_dir,
            task_id=task_id,
            manifest=manifest,
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
    preview_path = task_dir / "preview.png"
    manifest_path = task_dir / "result.json"
    assert raster_path.is_file()
    assert preview_path.is_file()
    assert manifest_path.is_file()
    assert payload["schema_version"] == 1
    assert payload["status"] == "SUCCEEDED"
    assert payload["algorithm_version"] == "weighted-overlay-v1"
    assert payload["palette_version"] == RISK_PREVIEW_PALETTE_VERSION
    assert payload["model_contract"] == {
        "code": "nimby_facility_siting_environmental_social_risk_sensitivity",
        "name": "邻避设施选址环境社会风险/敏感性",
        "source_value_semantics": "higher_means_higher_risk_contribution",
        "normalized_range": {"minimum": 0.0, "maximum": 1.0},
        "aggregation": "weighted_sum",
        "required_weight_total_percent": 100.0,
    }
    assert payload["artifacts"]["raster"] == "risk-analysis/task-123/risk.tif"
    assert payload["artifacts"]["preview"] == "risk-analysis/task-123/preview.png"
    assert payload["grid"]["bounds"] == pytest.approx([118.0, 31.98, 118.02, 32.0])
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


def test_job_service_new_manifest_requires_preview_contract(
    tmp_path: Path, monkeypatch
):
    service = RiskAnalysisJobService(
        tmp_path / "source", tmp_path / "runtime", indicators=_catalog()
    )
    statistics = SimpleNamespace(
        valid_pixel_count=4,
        minimum=0.0,
        maximum=1.0,
        mean=0.5,
    )
    result = SimpleNamespace(
        array=np.array([[0.0, 0.25], [0.75, 1.0]], dtype=np.float32),
        transform=Affine(0.01, 0.002, 118.0, 0.001, -0.01, 32.0),
        crs=SimpleNamespace(to_string=lambda: "EPSG:4326"),
        nodata=-9999.0,
        stats=statistics,
        indicators=(
            SimpleNamespace(
                code="a",
                name="指标A",
                weight_percent=100.0,
                stats=statistics,
            ),
        ),
    )
    monkeypatch.setattr(service.pipeline, "run", lambda **kwargs: result)
    monkeypatch.setattr(
        "app.services.risk_analysis_jobs.write_risk_geotiff",
        lambda _result, path: path.write_bytes(b"fake-tiff"),
    )

    payload = service.execute(task_id="preview-contract", request=_request())
    validated = RiskAnalysisSuccessResult.model_validate(payload)

    assert validated.palette_version == "risk-viridis-5-v1"
    assert validated.artifacts.preview == (
        "risk-analysis/preview-contract/preview.png"
    )
    assert validated.grid.bounds == pytest.approx(
        (118.0, 31.98, 118.024, 32.002)
    )


def test_success_schema_keeps_old_manifest_without_preview_compatible():
    manifest = _success_manifest(
        task_id="old-task",
        shape=(1, 1),
        nodata=-9999.0,
        statistics={
            "valid_pixel_count": 1,
            "minimum": 0.5,
            "maximum": 0.5,
            "mean": 0.5,
        },
    )

    assert manifest.artifacts.preview is None
    assert manifest.grid.bounds is None
    assert manifest.palette_version is None


def test_preview_contract_rejects_non_wgs84_in_schema_and_resolver(tmp_path: Path):
    payload = _success_manifest(
        task_id="preview-crs",
        shape=(1, 1),
        nodata=-9999.0,
        statistics={
            "valid_pixel_count": 1,
            "minimum": 0.5,
            "maximum": 0.5,
            "mean": 0.5,
        },
    ).model_dump(mode="json")
    payload["grid"]["bounds"] = [118.0, 31.0, 119.0, 32.0]
    payload["artifacts"]["preview"] = "risk-analysis/preview-crs/preview.png"
    payload["palette_version"] = "risk-viridis-5-v1"
    payload["grid"]["crs"] = "EPSG:3857"

    with pytest.raises(ValueError, match="EPSG:4326"):
        RiskAnalysisSuccessResult.model_validate(payload)

    payload["grid"]["crs"] = "EPSG:4326"
    manifest = RiskAnalysisSuccessResult.model_validate(payload)
    manifest.grid.crs = "EPSG:3857"
    with pytest.raises(RiskAnalysisArtifactError, match="声明"):
        resolve_risk_analysis_artifact(
            runtime_dir=tmp_path,
            task_id="preview-crs",
            manifest=manifest,
            artifact_kind="preview",
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
