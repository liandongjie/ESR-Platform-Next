from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.gis.indicators import INDICATORS, IndicatorDefinition
from app.gis.risk_models import IndicatorWeight, RiskAnalysisValidationError
from app.gis.risk_pipeline import RiskAnalysisPipeline, write_risk_geotiff
from app.repositories.risk_analysis_job_store import RiskAnalysisJobStore
from app.schemas.risk_analysis import RiskAnalysisJobRequest

_ALGORITHM_VERSION = "weighted-overlay-v1"

type ProgressCallback = Callable[[str, int], None]


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
        manifest_path = task_dir / "result.json"

        # 先完整写入临时 GeoTIFF，再原子替换最终文件，避免 Worker 中断后留下残缺结果。
        try:
            write_risk_geotiff(result, temporary_raster)
            temporary_raster.replace(raster_path)
        finally:
            temporary_raster.unlink(missing_ok=True)

        payload: dict[str, Any] = {
            "schema_version": 1,
            "task_id": task_id,
            "status": "SUCCEEDED",
            "algorithm_version": _ALGORITHM_VERSION,
            "geometry": {
                "type": geometry.geom_type,
                "bounds": [float(value) for value in geometry.bounds],
            },
            "grid": {
                "crs": result.crs.to_string(),
                "shape": [int(result.array.shape[0]), int(result.array.shape[1])],
                "nodata": float(result.nodata),
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
            },
        }
        self.store.write_json(task_id=task_id, filename="result.json", payload=payload)
        _notify(on_progress, "COMPLETED", 100)
        return payload

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
