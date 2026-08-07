from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from shapely.errors import ShapelyError
from shapely.geometry import shape

from app.gis.indicators import INDICATORS, IndicatorDefinition
from app.gis.risk_models import IndicatorWeight, RiskAnalysisValidationError
from app.gis.risk_pipeline import RiskAnalysisPipeline, write_risk_geotiff
from app.schemas.risk_analysis import RiskAnalysisJobRequest

_ALGORITHM_VERSION = "weighted-overlay-v1"
_ARTIFACT_ROOT_NAME = "risk-analysis"
_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

type ProgressCallback = Callable[[str, int], None]


def _notify(callback: ProgressCallback | None, stage: str, progress: int) -> None:
    if callback is not None:
        callback(stage, progress)


def _task_directory(runtime_dir: Path, task_id: str) -> Path:
    """Return a task-scoped output directory without allowing path traversal."""

    if task_id in {".", ".."} or not _TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError("task_id 必须以字母或数字开头，且只能包含安全路径字符")

    root = Path(runtime_dir).expanduser().resolve()
    task_dir = root / _ARTIFACT_ROOT_NAME / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    return task_dir


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write metadata atomically so readers never observe a half-written manifest."""

    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def _relative_artifact_path(path: Path, runtime_dir: Path) -> str:
    return path.resolve().relative_to(runtime_dir.resolve()).as_posix()


class RiskAnalysisJobService:
    """Application service that turns one validated job into durable artifacts.

    The service owns orchestration and artifact layout, while ``RiskAnalysisPipeline``
    remains responsible only for deterministic GIS computation. Keeping these layers
    separate lets Flask, Celery and future CLI entry points reuse exactly one workflow.
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
        self.pipeline = RiskAnalysisPipeline(self.raster_dir, indicators=indicators)

    def execute(
        self,
        *,
        task_id: str,
        request: RiskAnalysisJobRequest,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        _notify(on_progress, "PREPARING", 15)
        geometry = self._parse_geometry(request.geometry)
        weights = tuple(
            IndicatorWeight(item.code, float(item.weight_percent))
            for item in request.weights
        )

        _notify(on_progress, "ANALYZING", 35)
        result = self.pipeline.run(geometry=geometry, weights=weights)

        _notify(on_progress, "PERSISTING", 85)
        task_dir = _task_directory(self.runtime_dir, task_id)
        raster_path = task_dir / "risk.tif"
        temporary_raster = task_dir / ".risk.tif.tmp"
        manifest_path = task_dir / "result.json"

        # Publish the GeoTIFF only after Rasterio has closed a complete temporary file.
        # A killed worker therefore cannot leave a partial file at the final path.
        try:
            write_risk_geotiff(result, temporary_raster)
            temporary_raster.replace(raster_path)
        finally:
            temporary_raster.unlink(missing_ok=True)

        payload: dict[str, Any] = {
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
            # Store paths relative to the runtime root. Future HTTP responses should
            # not expose container-internal absolute paths such as /data/runtime/....
            "artifacts": {
                "raster": _relative_artifact_path(raster_path, self.runtime_dir),
                "manifest": _relative_artifact_path(manifest_path, self.runtime_dir),
            },
        }
        _atomic_write_json(manifest_path, payload)
        _notify(on_progress, "COMPLETED", 100)
        return payload

    @staticmethod
    def _parse_geometry(geojson: dict[str, Any]):
        try:
            geometry = shape(geojson)
        except (KeyError, TypeError, ValueError, ShapelyError) as exc:
            raise RiskAnalysisValidationError("geometry 不是合法的 GeoJSON geometry") from exc
        return geometry


def write_failure_manifest(
    *,
    runtime_dir: Path,
    task_id: str,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    """Persist a stable failure reason for later polling/history APIs."""

    runtime_dir = Path(runtime_dir).expanduser().resolve()
    task_dir = _task_directory(runtime_dir, task_id)
    manifest_path = task_dir / "result.json"
    payload = {
        "task_id": task_id,
        "status": "FAILED",
        "error": {"code": error_code, "message": message},
        "artifacts": {
            "manifest": _relative_artifact_path(manifest_path, runtime_dir),
        },
    }
    _atomic_write_json(manifest_path, payload)
    return payload
