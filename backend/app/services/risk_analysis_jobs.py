from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from affine import Affine
from rasterio.crs import CRS

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.gis.indicators import (
    INDICATORS,
    IndicatorDefinition,
    risk_model_contract_payload,
)
from app.gis.risk_models import IndicatorWeight, RiskAnalysisValidationError
from app.gis.risk_pipeline import RiskAnalysisPipeline, write_risk_geotiff
from app.gis.risk_preview import (
    RISK_PREVIEW_PALETTE_VERSION,
    raster_bounds,
    validate_preview_png,
    write_risk_preview_png,
)
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore
from app.schemas.risk_analysis import (
    RiskAnalysisJobRequest,
    RiskAnalysisSpatialResult,
    RiskAnalysisSuccessResult,
)

_ALGORITHM_VERSION = "weighted-overlay-v1"

type ProgressCallback = Callable[[str, int], None]


class RiskAnalysisArtifactError(RuntimeError):
    """Persisted result artifacts are missing or contradict their manifest."""


def _notify(callback: ProgressCallback | None, stage: str, progress: int) -> None:
    if callback is not None:
        callback(stage, progress)


class RiskAnalysisJobService:
    """把一次已校验任务编排成持久化产物。

    Service 负责应用层编排和产物布局；``RiskAnalysisPipeline`` 只负责确定性的 GIS
    计算。文件路径和 JSON 原子写入交给 ``RiskAnalysisJobStore``，避免 API 与 Worker
    各自维护一套任务目录规则。
    """

    def __init__(
        self,
        raster_dir: Path,
        runtime_dir: Path,
        *,
        indicators: Sequence[IndicatorDefinition] = INDICATORS,
    ) -> None:
        self.raster_dir = Path(raster_dir)
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.store = RiskAnalysisJobStore(self.runtime_dir)
        self.pipeline = RiskAnalysisPipeline(self.raster_dir, indicators=indicators)

    def execute(
        self,
        *,
        task_id: str,
        request: RiskAnalysisJobRequest,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        _notify(on_progress, "PREPARING", 15)
        try:
            geometry = parse_geojson_geometry(request.geometry)
        except GeoJsonValidationError as exc:
            # Schema 正常校验后理论上不会到这里；保留转换用于直接 Service 调用的防御性边界。
            raise RiskAnalysisValidationError(str(exc)) from exc
        weights = tuple(
            IndicatorWeight(item.code, float(item.weight_percent))
            for item in request.weights
        )

        _notify(on_progress, "ANALYZING", 35)
        result = self.pipeline.run(geometry=geometry, weights=weights)

        _notify(on_progress, "PERSISTING", 85)
        task_dir = self.store.task_directory(task_id, create=True)
        raster_path = task_dir / "risk.tif"
        temporary_raster = task_dir / ".risk.tif.tmp"
        preview_path = task_dir / "preview.png"
        manifest_path = task_dir / "result.json"

        # 先完整写入临时 GeoTIFF，再原子替换最终文件，避免 Worker 中断后留下残缺结果。
        try:
            write_risk_geotiff(result, temporary_raster)
            temporary_raster.replace(raster_path)
        finally:
            temporary_raster.unlink(missing_ok=True)
        write_risk_preview_png(result.array, preview_path)

        height, width = result.array.shape

        payload: dict[str, Any] = {
            "schema_version": 1,
            "task_id": task_id,
            "status": "SUCCEEDED",
            "algorithm_version": _ALGORITHM_VERSION,
            "palette_version": RISK_PREVIEW_PALETTE_VERSION,
            "model_contract": risk_model_contract_payload(),
            "geometry": {
                "type": geometry.geom_type,
                "bounds": [float(value) for value in geometry.bounds],
            },
            "grid": {
                "crs": result.crs.to_string(),
                "shape": [int(result.array.shape[0]), int(result.array.shape[1])],
                "nodata": float(result.nodata),
                "bounds": list(
                    raster_bounds(result.transform, width=width, height=height)
                ),
            },
            "statistics": {
                "valid_pixel_count": result.stats.valid_pixel_count,
                "minimum": result.stats.minimum,
                "maximum": result.stats.maximum,
                "mean": result.stats.mean,
            },
            "indicators": [
                {
                    "code": item.code,
                    "name": item.name,
                    "weight_percent": item.weight_percent,
                    "statistics": {
                        "valid_pixel_count": item.stats.valid_pixel_count,
                        "minimum": item.stats.minimum,
                        "maximum": item.stats.maximum,
                        "mean": item.stats.mean,
                    },
                }
                for item in result.indicators
            ],
            # 对外只保存相对 runtime 根目录的 artifact key，不暴露 /data/runtime 等容器路径。
            "artifacts": {
                "raster": self.store.relative_path(raster_path),
                "manifest": self.store.relative_path(manifest_path),
                "preview": self.store.relative_path(preview_path),
            },
        }
        self.store.write_json(task_id=task_id, filename="result.json", payload=payload)
        _notify(on_progress, "COMPLETED", 100)
        return payload


def validate_risk_analysis_raster(
    *,
    runtime_dir: Path,
    task_id: str,
    manifest: RiskAnalysisSuccessResult,
) -> tuple[np.ma.MaskedArray, Affine]:
    """Read and validate the persisted raster against its success manifest."""

    store = RiskAnalysisJobStore(runtime_dir)
    raster_path = store.task_directory(task_id) / "risk.tif"
    try:
        expected_artifact = store.relative_path(raster_path)
    except ValueError as exc:
        raise RiskAnalysisArtifactError("风险栅格文件不在当前任务目录") from exc
    if manifest.task_id != task_id or manifest.artifacts.raster != expected_artifact:
        raise RiskAnalysisArtifactError("风险栅格声明与当前任务不一致")
    if not raster_path.is_file():
        raise RiskAnalysisArtifactError("风险栅格文件不存在")

    try:
        with rasterio.open(raster_path) as dataset:
            if dataset.count != 1:
                raise RiskAnalysisArtifactError("风险栅格必须是单波段")
            if dataset.crs != CRS.from_epsg(4326):
                raise RiskAnalysisArtifactError("风险栅格 CRS 必须是 EPSG:4326")
            if manifest.grid.crs != dataset.crs.to_string():
                raise RiskAnalysisArtifactError("风险栅格 CRS 与结果清单不一致")
            if dataset.dtypes[0] != "float32":
                raise RiskAnalysisArtifactError("风险栅格 dtype 必须是 float32")
            if dataset.shape != tuple(manifest.grid.shape):
                raise RiskAnalysisArtifactError("风险栅格 shape 与结果清单不一致")
            if dataset.nodata != float(manifest.grid.nodata):
                raise RiskAnalysisArtifactError("风险栅格 NoData 与结果清单不一致")

            band = dataset.read(1, masked=True)
            transform = dataset.transform
    except RiskAnalysisArtifactError:
        raise
    except Exception as exc:
        raise RiskAnalysisArtifactError("风险栅格文件无法读取") from exc

    mask = np.ma.getmaskarray(band)
    valid_values = band.data[~mask & np.isfinite(band.data)]
    if np.any((valid_values < 0.0) | (valid_values > 1.0)):
        raise RiskAnalysisArtifactError("风险栅格存在超出 [0,1] 的有效值")

    if valid_values.size != manifest.statistics.valid_pixel_count:
        raise RiskAnalysisArtifactError("风险栅格有效像元数与结果清单不一致")
    if valid_values.size:
        actual_statistics = (
            valid_values.min(),
            valid_values.max(),
            float(np.mean(valid_values, dtype=np.float64)),
        )
        expected_statistics = (
            float(manifest.statistics.minimum),
            float(manifest.statistics.maximum),
            float(manifest.statistics.mean),
        )
        if not np.allclose(
            actual_statistics,
            expected_statistics,
            rtol=0.0,
            atol=1e-6,
        ):
            raise RiskAnalysisArtifactError("风险栅格统计值与结果清单不一致")

    return band, transform


def resolve_risk_analysis_artifact(
    *,
    runtime_dir: Path,
    task_id: str,
    manifest: RiskAnalysisSuccessResult,
    artifact_kind: str,
) -> Path:
    """Resolve only fixed task artifacts after validating their declarations."""

    store = RiskAnalysisJobStore(runtime_dir)
    task_dir = store.task_directory(task_id)
    if artifact_kind == "raster":
        path = task_dir / "risk.tif"
        validate_risk_analysis_raster(
            runtime_dir=runtime_dir,
            task_id=task_id,
            manifest=manifest,
        )
        return path
    if artifact_kind == "preview":
        path = task_dir / "preview.png"
        try:
            expected_artifact = store.relative_path(path)
        except ValueError as exc:
            raise RiskAnalysisArtifactError("风险预览文件不在当前任务目录") from exc
        if (
            manifest.task_id != task_id
            or manifest.artifacts.preview != expected_artifact
            or manifest.grid.bounds is None
            or manifest.grid.crs != "EPSG:4326"
            or manifest.palette_version != RISK_PREVIEW_PALETTE_VERSION
        ):
            raise RiskAnalysisArtifactError("风险预览声明与当前任务不一致")
        if not path.is_file() or path.stat().st_size == 0:
            raise RiskAnalysisArtifactError("风险预览文件不存在")
        try:
            validate_preview_png(path.read_bytes(), shape=tuple(manifest.grid.shape))
        except (OSError, ValueError) as exc:
            raise RiskAnalysisArtifactError(str(exc)) from exc
        return path
    if artifact_kind != "manifest":
        raise ValueError("不支持的风险分析 artifact")

    path = task_dir / "result.json"
    try:
        expected_artifact = store.relative_path(path)
    except ValueError as exc:
        raise RiskAnalysisArtifactError("风险结果清单文件不在当前任务目录") from exc
    if manifest.task_id != task_id or manifest.artifacts.manifest != expected_artifact:
        raise RiskAnalysisArtifactError("风险结果清单声明与当前任务不一致")
    if not path.is_file():
        raise RiskAnalysisArtifactError("风险结果清单文件不存在")
    return path


def build_risk_analysis_spatial_result(
    *,
    runtime_dir: Path,
    task_id: str,
    manifest: RiskAnalysisSuccessResult,
) -> RiskAnalysisSpatialResult:
    """Convert valid GeoTIFF cells to WGS84 polygons without weakening Affine math."""

    band, transform = validate_risk_analysis_raster(
        runtime_dir=runtime_dir,
        task_id=task_id,
        manifest=manifest,
    )
    mask = np.ma.getmaskarray(band)
    features: list[dict[str, Any]] = []
    for row, col in np.ndindex(band.shape):
        value = float(band.data[row, col])
        if mask[row, col] or not np.isfinite(value):
            continue

        # 使用完整 Affine 对四个像元角运算，旋转/错切项也不会被静默丢弃。
        corners = [
            transform * (col, row),
            transform * (col + 1, row),
            transform * (col + 1, row + 1),
            transform * (col, row + 1),
        ]
        ring = [[float(x), float(y)] for x, y in [*corners, corners[0]]]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"value": value},
            }
        )

    return RiskAnalysisSpatialResult.model_validate(
        {
            "schema_version": 1,
            "task_id": task_id,
            "crs": "EPSG:4326",
            "value_range": {"minimum": 0.0, "maximum": 1.0},
            "feature_collection": {"type": "FeatureCollection", "features": features},
        }
    )

def write_failure_manifest(
    *,
    runtime_dir: Path,
    task_id: str,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    """持久化稳定失败原因，供轮询 API 和后续历史任务使用。"""

    store = RiskAnalysisJobStore(runtime_dir)
    task_dir = store.task_directory(task_id, create=True)
    manifest_path = task_dir / "result.json"
    payload = {
        "schema_version": 1,
        "task_id": task_id,
        "status": "FAILED",
        "error": {"code": error_code, "message": message},
        "artifacts": {
            "manifest": store.relative_path(manifest_path),
        },
    }
    store.write_json(task_id=task_id, filename="result.json", payload=payload)
    return payload
