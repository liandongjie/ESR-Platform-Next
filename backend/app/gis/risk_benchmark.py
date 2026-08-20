from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import json
import math
import os
import platform
import pstats
import re
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import ExitStack
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from flask_jwt_extended import create_access_token
from rasterio.windows import Window
from rasterio.windows import bounds as window_bounds
from shapely.geometry import box, mapping

from app import create_app
from app.extensions import db
from app.gis.geojson import parse_geojson_geometry
from app.gis.indicators import INDICATOR_BY_CODE, INDICATORS
from app.gis.risk_models import IndicatorWeight
from app.gis.risk_pipeline import RiskAnalysisPipeline
from app.models import AnalysisJob, User
from app.schemas.risk_analysis import RiskAnalysisJobRequest, RiskAnalysisSuccessResult
from app.services.risk_analysis_jobs import (
    RiskAnalysisJobService,
    validate_risk_analysis_raster,
)

BASELINE_SHA = "5810240e14d1d5a86562d73d6b85f2cdd2083cc4"
PRODUCTION_CANDIDATE_SHA = "8f85c420dcc07edbcbf03674478b973c108e6746"
CENTER = (118.9, 32.1)
COMPUTE_SIZES = {"small": 128, "medium": 384, "large": 1024}
SPATIAL_SIZES = {"small": 32, "medium": 64, "large": 128}
INDICATOR_GROUPS = {
    3: ("PM25", "AQI", "NDVI"),
    6: ("PM25", "AQI", "NDVI", "rkmd", "gyfb", "fmyl"),
    12: tuple(indicator.code for indicator in INDICATORS),
}
VALIDATION_TIMING = "standalone_post_execute_warm_cache"
VALIDATION_INCLUDED_IN_TOTAL_SERVICE = False
DEFAULT_WARMUPS = 1
DEFAULT_RUNS = 5
PIPELINE_PROFILE_SIZE = COMPUTE_SIZES["large"]
PIPELINE_PROFILE_TOP_N = 30
RASTER_READ_ATTRIBUTION_SIZE = COMPUTE_SIZES["large"]
RASTER_READ_MODES = (
    "open_only",
    "masked_read_new_handle",
    "masked_reread_same_handle",
    "data_read",
    "mask_read",
    "data_plus_mask",
)
RASTER_READ_CACHE_SEMANTICS = "warm_process_and_os_cache_not_explicitly_flushed"
HANDLE_REUSE_APPLICABILITY_SIZE = COMPUTE_SIZES["large"]
HANDLE_REUSE_WINDOW_SHIFTS = {
    "same_window": 0,
    "half_overlap": 512,
    "zero_block_overlap": 1152,
}
HANDLE_REUSE_MODES = (
    "reopen_between_requests",
    "reuse_same_process_handles",
)
HANDLE_REUSE_MIN_SPEEDUP = 1.5
SOURCE_TREE_VERIFICATION_METHOD = "host_git_diff_and_untracked_allowlist_v1"
ALLOWED_BENCHMARK_PATHS = (
    "backend/app/gis/risk_benchmark.py",
    "backend/tests/test_risk_benchmark.py",
    "scripts/benchmark-risk-analysis.ps1",
    "docs/performance/",
)
ALLOWED_PIPELINE_DIAGNOSTIC_PATHS = ALLOWED_BENCHMARK_PATHS


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000


def _verified_provenance(
    subject_baseline_sha: str,
    repository_head_sha: str,
    verification_method: str,
    source_tree_verified: bool,
    baseline_is_ancestor: bool,
    allowed_benchmark_paths: Sequence[str],
    tracked_differences: Sequence[str],
    untracked_paths: Sequence[str],
) -> dict[str, Any]:
    subject = subject_baseline_sha.lower()
    head = repository_head_sha.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", subject):
        raise ValueError("subject baseline SHA 必须是完整 40 位十六进制 Git SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("repository HEAD SHA 必须是完整 40 位十六进制 Git SHA")
    if verification_method != SOURCE_TREE_VERIFICATION_METHOD:
        raise ValueError(f"不支持的 source-tree 验证方式: {verification_method}")
    if source_tree_verified is not True:
        raise ValueError("source_tree_verified 必须由 host runner 明确验证为 true")
    if baseline_is_ancestor is not True:
        raise ValueError("subject baseline 不是 repository HEAD 的 ancestor")
    if tuple(allowed_benchmark_paths) != ALLOWED_BENCHMARK_PATHS:
        raise ValueError("host runner 的 benchmark-only allowlist 与正式 Contract 不一致")

    tracked: list[dict[str, str]] = []
    detected_paths: list[str] = []
    for entry in tracked_differences:
        status, separator, raw_path = entry.partition(":")
        if separator != ":" or status not in {"A", "B", "D", "M", "T", "U", "X"}:
            raise ValueError(f"非法 tracked difference: {entry}")
        path = _validated_allowed_path(raw_path)
        tracked.append({"status": status, "path": path})
        detected_paths.append(path)
    validated_untracked = [_validated_allowed_path(path) for path in untracked_paths]
    detected_paths.extend(validated_untracked)

    return {
        "subject_baseline_sha": subject,
        "repository_head_sha": head,
        "source_tree_verification_method": verification_method,
        "source_tree_verified": True,
        "baseline_is_head_ancestor": True,
        "allowed_benchmark_paths": list(ALLOWED_BENCHMARK_PATHS),
        "detected_allowed_diff_paths": sorted(set(detected_paths)),
        "tracked_differences": tracked,
        "untracked_paths": validated_untracked,
    }


def _validated_allowed_path(raw_path: str) -> str:
    path = raw_path.replace("\\", "/").removeprefix("./")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"非法 repository-relative path: {raw_path}")
    if path in ALLOWED_BENCHMARK_PATHS[:3] or path.startswith("docs/performance/"):
        return path
    raise ValueError(f"source tree 包含非 benchmark 路径: {path}")


def _verified_instrumentation_lineage(
    production_candidate_sha: str,
    instrumented_subject_sha: str,
    production_candidate_is_ancestor: bool,
    diagnostic_source_tree_verified: bool,
    allowed_diagnostic_paths: Sequence[str],
    diagnostic_differences: Sequence[str],
) -> dict[str, Any]:
    candidate = production_candidate_sha.lower()
    subject = instrumented_subject_sha.lower()
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("production candidate SHA 必须是完整 40 位十六进制 Git SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", subject):
        raise ValueError("instrumented subject SHA 必须是完整 40 位十六进制 Git SHA")
    if production_candidate_is_ancestor is not True:
        raise ValueError("production candidate 不是 instrumented subject 的 ancestor")
    if diagnostic_source_tree_verified is not True:
        raise ValueError("diagnostic source tree 必须由 host runner 明确验证为 true")
    if tuple(allowed_diagnostic_paths) != ALLOWED_PIPELINE_DIAGNOSTIC_PATHS:
        raise ValueError("host runner 的 pipeline diagnostic allowlist 与 Contract 不一致")

    differences: list[dict[str, str]] = []
    for entry in diagnostic_differences:
        status, separator, raw_path = entry.partition(":")
        if separator != ":" or status not in {"A", "B", "D", "M", "T", "U", "X"}:
            raise ValueError(f"非法 diagnostic difference: {entry}")
        path = raw_path.replace("\\", "/").removeprefix("./")
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError(f"非法 repository-relative path: {raw_path}")
        if path not in ALLOWED_PIPELINE_DIAGNOSTIC_PATHS[:-1] and not path.startswith(
            "docs/performance/"
        ):
            raise ValueError(f"instrumented subject 包含非 diagnostic 路径: {path}")
        differences.append({"status": status, "path": path})

    return {
        "production_candidate_sha": candidate,
        "instrumented_subject_sha": subject,
        "production_candidate_is_instrumented_subject_ancestor": True,
        "diagnostic_source_tree_verified": True,
        "allowed_pipeline_diagnostic_paths": list(ALLOWED_PIPELINE_DIAGNOSTIC_PATHS),
        "diagnostic_differences": differences,
    }


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _cpu_model() -> str:
    model = platform.processor() or os.getenv("PROCESSOR_IDENTIFIER", "")
    if model:
        return model
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raster_metadata(raster_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for indicator in INDICATORS:
        path = raster_dir / indicator.filename
        with rasterio.open(path) as dataset:
            records.append(
                {
                    "code": indicator.code,
                    "filename": indicator.filename,
                    "sha256": _sha256(path),
                    "size_bytes": path.stat().st_size,
                    "mtime_ns": path.stat().st_mtime_ns,
                    "crs": dataset.crs.to_string() if dataset.crs else None,
                    "shape": list(dataset.shape),
                    "resolution": [float(value) for value in dataset.res],
                    "transform": [float(value) for value in dataset.transform[:6]],
                    "bounds": [float(value) for value in dataset.bounds],
                    "nodata": dataset.nodata,
                    "dtype": dataset.dtypes[0],
                    "block_shapes": [list(shape) for shape in dataset.block_shapes],
                    "compression": str(dataset.compression),
                }
            )
    return records


def _environment_metadata() -> dict[str, Any]:
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "os": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": _cpu_model(),
        "logical_cpu_count": os.cpu_count(),
        "versions": {
            name: _package_version(name)
            for name in ("flask", "numpy", "pydantic", "rasterio", "shapely")
        },
    }


def _equal_weights(codes: Sequence[str]) -> list[dict[str, float | str]]:
    share = 100.0 / len(codes)
    weights = [share] * (len(codes) - 1)
    weights.append(100.0 - sum(weights))
    return [
        {"code": code, "weight_percent": weight}
        for code, weight in zip(codes, weights, strict=True)
    ]


def _scenario_geometry(
    reference_path: Path,
    size: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with rasterio.open(reference_path) as reference:
        window, center = _scenario_window(reference, size)
        left, bottom, right, top = window_bounds(window, reference.transform)
    # 各向内移动一个浮点单位，避免 geometry_window 因 Affine 舍入多取一行/列；
    # 这个 ULP 级调整不会改变 AOI 覆盖的任何像元中心。
    geometry_bounds = (
        math.nextafter(left, right),
        math.nextafter(bottom, top),
        math.nextafter(right, left),
        math.nextafter(top, bottom),
    )
    return mapping(box(*geometry_bounds)), {
        "requested_center": list(CENTER),
        "grid_aligned_center": [float(center[0]), float(center[1])],
        "bounds": [float(value) for value in geometry_bounds],
        "target_rows": size,
        "target_cols": size,
        "target_window_cells": size * size,
    }


def _scenario_window(reference: Any, size: int) -> tuple[Window, tuple[float, float]]:
    col_edge = round((CENTER[0] - reference.transform.c) / reference.transform.a)
    row_edge = round((CENTER[1] - reference.transform.f) / reference.transform.e)
    window = Window(
        col_off=col_edge - size // 2,
        row_off=row_edge - size // 2,
        width=size,
        height=size,
    )
    if (
        window.col_off < 0
        or window.row_off < 0
        or window.col_off + window.width > reference.width
        or window.row_off + window.height > reference.height
    ):
        raise ValueError(f"AOI {size}x{size} 超出参考栅格范围")
    center = reference.transform * (col_edge, row_edge)
    return window, (float(center[0]), float(center[1]))


def _window_block_metrics(
    window: Window,
    block_shape: tuple[int, int],
    dtype: str,
) -> dict[str, int | float]:
    block_rows, block_cols = block_shape
    first_block_row = math.floor(window.row_off / block_rows)
    last_block_row = math.ceil((window.row_off + window.height) / block_rows)
    first_block_col = math.floor(window.col_off / block_cols)
    last_block_col = math.ceil((window.col_off + window.width) / block_cols)
    block_count = (last_block_row - first_block_row) * (
        last_block_col - first_block_col
    )
    decoded_cells = block_count * block_rows * block_cols
    window_cells = int(window.width * window.height)
    return {
        "touched_block_count": block_count,
        "estimated_decoded_cells": decoded_cells,
        "estimated_uncompressed_bytes": decoded_cells * np.dtype(dtype).itemsize,
        "read_amplification_ratio": decoded_cells / window_cells,
    }


def _window_overlap_metrics(
    base: Window,
    target: Window,
    block_shape: tuple[int, int],
) -> dict[str, int | float]:
    overlap_width = max(
        0,
        min(base.col_off + base.width, target.col_off + target.width)
        - max(base.col_off, target.col_off),
    )
    overlap_height = max(
        0,
        min(base.row_off + base.height, target.row_off + target.height)
        - max(base.row_off, target.row_off),
    )
    pixel_overlap_cells = int(overlap_width * overlap_height)

    block_rows, block_cols = block_shape

    def touched_blocks(window: Window) -> set[tuple[int, int]]:
        return {
            (row, col)
            for row in range(
                math.floor(window.row_off / block_rows),
                math.ceil((window.row_off + window.height) / block_rows),
            )
            for col in range(
                math.floor(window.col_off / block_cols),
                math.ceil((window.col_off + window.width) / block_cols),
            )
        }

    base_blocks = touched_blocks(base)
    target_blocks = touched_blocks(target)
    shared_blocks = base_blocks & target_blocks
    target_cells = int(target.width * target.height)
    return {
        "pixel_overlap_cells": pixel_overlap_cells,
        "pixel_overlap_ratio": pixel_overlap_cells / target_cells,
        "base_touched_block_count": len(base_blocks),
        "target_touched_block_count": len(target_blocks),
        "shared_block_count": len(shared_blocks),
        "target_block_cache_coverage_ratio": len(shared_blocks) / len(target_blocks),
    }


def _request(
    reference_path: Path,
    size: int,
    codes: Sequence[str],
) -> tuple[RiskAnalysisJobRequest, dict[str, Any]]:
    geometry, aoi = _scenario_geometry(reference_path, size)
    request = RiskAnalysisJobRequest.model_validate(
        {"geometry": geometry, "weights": _equal_weights(codes)}
    )
    return request, aoi


def _execute_timed(
    *,
    raster_dir: Path,
    runtime_dir: Path,
    task_id: str,
    request: RiskAnalysisJobRequest,
) -> tuple[dict[str, Any], float, float]:
    service = RiskAnalysisJobService(raster_dir, runtime_dir)
    original_run = service.pipeline.run
    pipeline_elapsed_ms: float | None = None

    def timed_run(**kwargs: Any):
        nonlocal pipeline_elapsed_ms
        started = time.perf_counter_ns()
        try:
            return original_run(**kwargs)
        finally:
            pipeline_elapsed_ms = _elapsed_ms(started)

    service.pipeline.run = timed_run  # type: ignore[method-assign]
    started = time.perf_counter_ns()
    payload = service.execute(task_id=task_id, request=request)
    total_service_elapsed_ms = _elapsed_ms(started)
    if pipeline_elapsed_ms is None:
        raise RuntimeError("RiskAnalysisJobService.execute() 未调用 pipeline.run()")
    return payload, pipeline_elapsed_ms, total_service_elapsed_ms


def _validate_timed(
    *,
    runtime_dir: Path,
    task_id: str,
    payload: dict[str, Any],
) -> float:
    manifest = RiskAnalysisSuccessResult.model_validate(payload)
    started = time.perf_counter_ns()
    validate_risk_analysis_raster(
        runtime_dir=runtime_dir,
        task_id=task_id,
        manifest=manifest,
    )
    return _elapsed_ms(started)


def _compute_sample(
    *,
    raster_dir: Path,
    runtime_dir: Path,
    task_id: str,
    request: RiskAnalysisJobRequest,
    aoi_name: str,
    codes: Sequence[str],
    sample_index: int,
) -> dict[str, Any]:
    payload, pipeline_ms, total_ms = _execute_timed(
        raster_dir=raster_dir,
        runtime_dir=runtime_dir,
        task_id=task_id,
        request=request,
    )
    validation_ms = _validate_timed(
        runtime_dir=runtime_dir,
        task_id=task_id,
        payload=payload,
    )
    rows, cols = payload["grid"]["shape"]
    return {
        "family": "compute",
        "aoi": aoi_name,
        "indicator_count": len(codes),
        "indicator_codes": list(codes),
        "sample_index": sample_index,
        "rows": rows,
        "cols": cols,
        "window_cells": rows * cols,
        "valid_cells": payload["statistics"]["valid_pixel_count"],
        "pipeline_elapsed_ms": pipeline_ms,
        "validation_elapsed_ms": validation_ms,
        "validation_timing": VALIDATION_TIMING,
        "validation_included_in_total_service": VALIDATION_INCLUDED_IN_TOTAL_SERVICE,
        "total_service_elapsed_ms": total_ms,
    }


def _run_compute(
    *,
    raster_dir: Path,
    runtime_dir: Path,
    warmups: int,
    runs: int,
    sizes: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    samples: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    for indicator_count, codes in INDICATOR_GROUPS.items():
        for aoi_name, size in sizes.items():
            request, aoi = _request(reference_path, size, codes)
            scenarios.append(
                {
                    "aoi": aoi_name,
                    "indicator_count": indicator_count,
                    "indicator_codes": list(codes),
                    "weights": request.model_dump(mode="json")["weights"],
                    **aoi,
                }
            )
            for warmup_index in range(warmups):
                _compute_sample(
                    raster_dir=raster_dir,
                    runtime_dir=runtime_dir,
                    task_id=f"compute-{indicator_count}-{aoi_name}-warmup-{warmup_index}",
                    request=request,
                    aoi_name=aoi_name,
                    codes=codes,
                    sample_index=warmup_index,
                )
            for sample_index in range(runs):
                samples.append(
                    _compute_sample(
                        raster_dir=raster_dir,
                        runtime_dir=runtime_dir,
                        task_id=f"compute-{indicator_count}-{aoi_name}-{sample_index}",
                        request=request,
                        aoi_name=aoi_name,
                        codes=codes,
                        sample_index=sample_index,
                    )
                )
    return scenarios, samples


def _spatial_response(client: Any, task_id: str) -> tuple[float, Any]:
    started = time.perf_counter_ns()
    response = client.get(f"/api/v1/risk-analysis/jobs/{task_id}/result/spatial")
    elapsed_ms = _elapsed_ms(started)
    if response.status_code != 200:
        raise RuntimeError(
            f"/spatial 返回 HTTP {response.status_code}: {response.get_data(as_text=True)}"
        )
    return elapsed_ms, response


def _run_spatial(
    *,
    raster_dir: Path,
    runtime_dir: Path,
    warmups: int,
    runs: int,
    sizes: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    app = create_app(
        "testing",
        {
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "RUNTIME_DATA_DIR": runtime_dir,
            "TESTING": True,
        },
    )
    client = app.test_client()
    codes = INDICATOR_GROUPS[12]
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    scenarios: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    with app.app_context():
        db.create_all()
        user = User(username="benchmark-user")
        user.set_password("benchmark-only-password")
        db.session.add(user)
        db.session.flush()
        client.environ_base["HTTP_AUTHORIZATION"] = (
            f"Bearer {create_access_token(identity=str(user.id))}"
        )

        for aoi_name, size in sizes.items():
            request, aoi = _request(reference_path, size, codes)
            task_id = f"spatial-12-{aoi_name}"
            payload = RiskAnalysisJobService(raster_dir, runtime_dir).execute(
                task_id=task_id,
                request=request,
            )
            db.session.add(
                AnalysisJob(
                    id=task_id,
                    owner_id=user.id,
                    idempotency_key=f"benchmark:{task_id}",
                    status="SUCCEEDED",
                    stage="COMPLETED",
                    progress=100,
                    request_payload=request.model_dump(mode="json"),
                    geometry=request.geometry,
                )
            )
            db.session.commit()
            rows, cols = payload["grid"]["shape"]
            scenarios.append(
                {
                    "aoi": aoi_name,
                    "indicator_count": 12,
                    "indicator_codes": list(codes),
                    "weights": request.model_dump(mode="json")["weights"],
                    "output_rows": rows,
                    "output_cols": cols,
                    "output_window_cells": rows * cols,
                    "output_valid_cells": payload["statistics"]["valid_pixel_count"],
                    **aoi,
                }
            )
            for _ in range(warmups):
                _spatial_response(client, task_id)
            for sample_index in range(runs):
                elapsed_ms, response = _spatial_response(client, task_id)
                body = response.get_json()
                feature_count = len(body["feature_collection"]["features"])
                samples.append(
                    {
                        "family": "spatial",
                        "aoi": aoi_name,
                        "indicator_count": 12,
                        "indicator_codes": list(codes),
                        "sample_index": sample_index,
                        "rows": rows,
                        "cols": cols,
                        "window_cells": rows * cols,
                        "valid_cells": payload["statistics"]["valid_pixel_count"],
                        "spatial_elapsed_ms": elapsed_ms,
                        "feature_count": feature_count,
                        "response_bytes": len(response.get_data()),
                        "transport": "flask_test_client_no_network",
                    }
                )
    return scenarios, samples


def _metric_summary(samples: Sequence[dict[str, Any]], key: str) -> dict[str, float]:
    values = [float(sample[key]) for sample in samples]
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def _summaries(
    samples: Sequence[dict[str, Any]],
    metrics: Sequence[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for sample in samples:
        grouped.setdefault((sample["indicator_count"], sample["aoi"]), []).append(sample)
    summaries: list[dict[str, Any]] = []
    for (indicator_count, aoi), group in grouped.items():
        first = group[0]
        summaries.append(
            {
                "indicator_count": indicator_count,
                "aoi": aoi,
                "rows": first["rows"],
                "cols": first["cols"],
                "window_cells": first["window_cells"],
                "valid_cells": _metric_summary(group, "valid_cells"),
                "sample_count": len(group),
                "metrics": {metric: _metric_summary(group, metric) for metric in metrics},
            }
        )
    return summaries


def _profile_entries(
    profiler: cProfile.Profile,
    *,
    sort_by: str,
    limit: int,
) -> list[dict[str, Any]]:
    if sort_by not in {"self_seconds", "cumulative_seconds"}:
        raise ValueError(f"不支持的 profile 排序字段: {sort_by}")
    entries: list[dict[str, Any]] = []
    for (filename, line, function), values in pstats.Stats(profiler).stats.items():
        primitive_calls, total_calls, self_seconds, cumulative_seconds, _ = values
        normalized = filename.replace("\\", "/")
        if normalized.startswith("/app/"):
            normalized = normalized.removeprefix("/app/")
        entries.append(
            {
                "file": normalized,
                "line": line,
                "function": function,
                "primitive_calls": primitive_calls,
                "total_calls": total_calls,
                "self_seconds": self_seconds,
                "cumulative_seconds": cumulative_seconds,
            }
        )
    return sorted(entries, key=lambda item: item[sort_by], reverse=True)[:limit]


def _profile_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Risk Analysis Pipeline cProfile",
        "",
        f"- Subject production candidate: `{result['source_provenance']['subject_baseline_sha']}`",
        f"- Repository HEAD: `{result['source_provenance']['repository_head_sha']}`",
        (
            "- Source-tree verification: "
            f"`{result['source_provenance']['source_tree_verification_method']}`"
        ),
        "- Source tree verified: `true`",
        f"- Profile elapsed: `{result['profile_elapsed_seconds']:.3f}s`",
        (
            "- Repetition: warm-up "
            f"{result['configuration']['warmups_per_scenario']} + profiled "
            f"{result['configuration']['measured_runs_per_scenario']} per scenario"
        ),
        "",
        "## Profiling semantics",
        "",
        "- `cProfile` wraps only `RiskAnalysisPipeline.run()`.",
        (
            "- Profiled wall time includes cProfile overhead and must not be compared "
            "with baseline latency."
        ),
        "- Function rankings use aggregate self/cumulative time across all measured runs.",
        "",
        "## Scenarios",
        "",
        "Profiled wall time is min/median/max milliseconds and is diagnostic only.",
        "",
        "| Indicators | Rows×Cols | Cells | Valid cells | Profiled wall time | Profile file |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for summary in result["pipeline_profile"]["summaries"]:
        scenario = next(
            item
            for item in result["pipeline_profile"]["scenarios"]
            if item["indicator_count"] == summary["indicator_count"]
        )
        lines.append(
            f"| {summary['indicator_count']} | {summary['rows']}×{summary['cols']} | "
            f"{summary['window_cells']} | {_range_text(summary['valid_cells'], 0)} | "
            f"{_range_text(summary['metrics']['profiled_pipeline_elapsed_ms'])} | "
            f"`{scenario['profile_file']}` |"
        )
    for scenario in result["pipeline_profile"]["scenarios"]:
        lines.extend(
            [
                "",
                f"## {scenario['indicator_count']}-indicator hotspots",
                "",
                "### Top cumulative time",
                "",
                "| Function | Calls | Self s | Cumulative s |",
                "|---|---:|---:|---:|",
            ]
        )
        for entry in scenario["top_cumulative"][:10]:
            label = (
                f"{entry['file']}:{entry['line']}:{entry['function']}".replace("|", "\\|")
            )
            lines.append(
                f"| `{label}` | {entry['total_calls']} | {entry['self_seconds']:.6f} | "
                f"{entry['cumulative_seconds']:.6f} |"
            )
        lines.extend(
            [
                "",
                "### Top self time",
                "",
                "| Function | Calls | Self s | Cumulative s |",
                "|---|---:|---:|---:|",
            ]
        )
        for entry in scenario["top_self"][:10]:
            label = (
                f"{entry['file']}:{entry['line']}:{entry['function']}".replace("|", "\\|")
            )
            lines.append(
                f"| `{label}` | {entry['total_calls']} | {entry['self_seconds']:.6f} | "
                f"{entry['cumulative_seconds']:.6f} |"
            )
    lines.extend(
        [
            "",
            (
                "Full call graphs are retained in the `.prof` files; raw samples and "
                "metadata are in JSON."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def run_pipeline_profile(
    *,
    raster_dir: Path,
    output_dir: Path,
    repository_head_sha: str,
    source_tree_verified: bool,
    baseline_is_ancestor: bool,
    subject_baseline_sha: str = BASELINE_SHA,
    verification_method: str = SOURCE_TREE_VERIFICATION_METHOD,
    allowed_benchmark_paths: Sequence[str] = ALLOWED_BENCHMARK_PATHS,
    tracked_differences: Sequence[str] = (),
    untracked_paths: Sequence[str] = (),
    warmups: int = DEFAULT_WARMUPS,
    runs: int = DEFAULT_RUNS,
    size: int = PIPELINE_PROFILE_SIZE,
    top_n: int = PIPELINE_PROFILE_TOP_N,
) -> tuple[dict[str, Any], dict[str, Path]]:
    raster_dir = raster_dir.expanduser().resolve()
    provenance = _verified_provenance(
        subject_baseline_sha,
        repository_head_sha,
        verification_method,
        source_tree_verified,
        baseline_is_ancestor,
        allowed_benchmark_paths,
        tracked_differences,
        untracked_paths,
    )
    if warmups < 0 or runs < 1 or size < 1 or top_n < 1:
        raise ValueError("warmups 必须 >= 0，runs/size/top_n 必须 >= 1")

    started = time.perf_counter_ns()
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    scenarios: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    paths: dict[str, Path] = {}
    for indicator_count, codes in INDICATOR_GROUPS.items():
        request, aoi = _request(reference_path, size, codes)
        geometry = parse_geojson_geometry(request.geometry)
        weights = tuple(
            IndicatorWeight(item.code, float(item.weight_percent)) for item in request.weights
        )
        pipeline = RiskAnalysisPipeline(raster_dir)
        for _ in range(warmups):
            pipeline.run(geometry=geometry, weights=weights)

        profiler = cProfile.Profile()
        last_result = None
        for sample_index in range(runs):
            sample_started = time.perf_counter_ns()
            last_result = profiler.runcall(pipeline.run, geometry=geometry, weights=weights)
            samples.append(
                {
                    "family": "pipeline_profile",
                    "aoi": "large",
                    "indicator_count": indicator_count,
                    "indicator_codes": list(codes),
                    "sample_index": sample_index,
                    "rows": int(last_result.array.shape[0]),
                    "cols": int(last_result.array.shape[1]),
                    "window_cells": int(last_result.array.size),
                    "valid_cells": last_result.stats.valid_pixel_count,
                    "profiled_pipeline_elapsed_ms": _elapsed_ms(sample_started),
                }
            )
        if last_result is None:  # guarded by runs >= 1; keeps type narrowing explicit
            raise RuntimeError("Pipeline profile 未产生结果")

        profile_path = output_dir / f"risk-pipeline-{indicator_count}.prof"
        profiler.dump_stats(profile_path)
        paths[f"profile_{indicator_count}"] = profile_path
        scenarios.append(
            {
                "aoi": "large",
                "indicator_count": indicator_count,
                "indicator_codes": list(codes),
                "weights": request.model_dump(mode="json")["weights"],
                "rows": int(last_result.array.shape[0]),
                "cols": int(last_result.array.shape[1]),
                "window_cells": int(last_result.array.size),
                "valid_cells": last_result.stats.valid_pixel_count,
                "profile_file": profile_path.name,
                "top_cumulative": _profile_entries(
                    profiler,
                    sort_by="cumulative_seconds",
                    limit=top_n,
                ),
                "top_self": _profile_entries(
                    profiler,
                    sort_by="self_seconds",
                    limit=top_n,
                ),
                **aoi,
            }
        )

    result = {
        "schema_version": 1,
        "benchmark": "risk-analysis-pipeline-cprofile",
        "subject_baseline_sha": provenance["subject_baseline_sha"],
        "source_provenance": provenance,
        "profile_elapsed_seconds": _elapsed_ms(started) / 1000.0,
        "configuration": {
            "warmups_per_scenario": warmups,
            "measured_runs_per_scenario": runs,
            "profile_size": size,
            "indicator_groups": {
                str(count): list(codes) for count, codes in INDICATOR_GROUPS.items()
            },
            "top_entries_per_sort": top_n,
        },
        "profiling_semantics": {
            "target": "RiskAnalysisPipeline.run() only",
            "profiler": "Python standard library cProfile/pstats",
            "aggregation": "one profiler aggregates all measured runs per indicator group",
            "wall_time_includes_profiler_overhead": True,
            "wall_time_comparable_to_unprofiled_benchmark": False,
        },
        "environment": _environment_metadata(),
        "raster_dataset": {
            "directory": str(raster_dir),
            "files": _raster_metadata(raster_dir),
        },
        "pipeline_profile": {
            "scenarios": scenarios,
            "raw_samples": samples,
            "summaries": _summaries(samples, ("profiled_pipeline_elapsed_ms",)),
        },
    }
    paths["json"] = output_dir / "risk-pipeline-profile.json"
    paths["markdown"] = output_dir / "risk-pipeline-profile.md"
    paths["json"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    paths["markdown"].write_text(_profile_markdown(result), encoding="utf-8")
    return result, paths


def _numeric_summary(values: Sequence[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def _time_raster_read_mode(
    path: Path,
    window: Window,
    mode: str,
    *,
    same_handle: Any | None = None,
) -> int:
    if mode == "open_only":
        started = time.perf_counter_ns()
        dataset = rasterio.open(path)
        elapsed_ns = time.perf_counter_ns() - started
        dataset.close()
        return elapsed_ns

    owns_handle = same_handle is None
    dataset = rasterio.open(path) if owns_handle else same_handle
    try:
        started = time.perf_counter_ns()
        if mode in {"masked_read_new_handle", "masked_reread_same_handle"}:
            dataset.read(1, window=window, masked=True)
        elif mode == "data_read":
            dataset.read(1, window=window, masked=False)
        elif mode == "mask_read":
            dataset.read_masks(1, window=window)
        elif mode == "data_plus_mask":
            dataset.read(1, window=window, masked=False)
            dataset.read_masks(1, window=window)
        else:
            raise ValueError(f"不支持的 raster read attribution mode: {mode}")
        return time.perf_counter_ns() - started
    finally:
        if owns_handle:
            dataset.close()


def _verify_raster_read_equivalence(path: Path, window: Window) -> dict[str, Any]:
    with rasterio.open(path) as dataset:
        masked = dataset.read(1, window=window, masked=True)
    with rasterio.open(path) as dataset:
        data = dataset.read(1, window=window, masked=False)
        valid_mask = dataset.read_masks(1, window=window)

    expected_mask = valid_mask == 0
    if masked.shape != data.shape or masked.dtype != data.dtype:
        raise RuntimeError(f"{path.name} masked/data shape 或 dtype 不一致")
    if not np.array_equal(masked.data, data, equal_nan=True):
        raise RuntimeError(f"{path.name} masked/data 像元值不一致")
    if not np.array_equal(np.ma.getmaskarray(masked), expected_mask):
        raise RuntimeError(f"{path.name} masked/read_masks 有效像元不一致")
    return {
        "rows": int(data.shape[0]),
        "cols": int(data.shape[1]),
        "dtype": str(data.dtype),
        "valid_cells": int(np.count_nonzero(valid_mask)),
        "equivalent": True,
    }


def _raster_read_summaries(
    samples: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for indicator in INDICATORS:
        modes: dict[str, dict[str, float]] = {}
        for mode in RASTER_READ_MODES:
            values = [
                sample["elapsed_ns"] / 1_000_000
                for sample in samples
                if sample["indicator_code"] == indicator.code and sample["mode"] == mode
            ]
            modes[mode] = _numeric_summary(values)
        masked = modes["masked_read_new_handle"]["median"]
        data = modes["data_read"]["median"]
        combined = modes["data_plus_mask"]["median"]
        same_handle = modes["masked_reread_same_handle"]["median"]
        summaries.append(
            {
                "indicator_code": indicator.code,
                "modes": modes,
                "median_ratios": {
                    "masked_read_over_data_read": masked / data,
                    "masked_read_over_data_plus_mask": masked / combined,
                    "same_handle_reread_over_new_handle_read": same_handle / masked,
                },
                "estimated_open_plus_masked_read_ms": (
                    modes["open_only"]["median"] + masked
                ),
            }
        )
    return summaries


def _raster_read_markdown(result: dict[str, Any]) -> str:
    source = result["source_provenance"]
    lineage = result["instrumentation_lineage"]
    scenarios = {
        item["indicator_code"]: item
        for item in result["raster_read_attribution"]["scenarios"]
    }
    lines = [
        "# Risk Raster Read Attribution",
        "",
        f"- Production candidate: `{lineage['production_candidate_sha']}`",
        f"- Diagnostic subject: `{lineage['instrumented_subject_sha']}`",
        f"- Repository HEAD: `{source['repository_head_sha']}`",
        "- Source tree and diagnostic lineage verified: `true`",
        f"- Benchmark elapsed: `{result['benchmark_elapsed_seconds']:.3f}s`",
        (
            "- Repetition: warm-up "
            f"{result['configuration']['warmups_per_mode']} + measured "
            f"{result['configuration']['measured_runs_per_mode']} per TIF/mode"
        ),
        "",
        "## Cache and timing semantics",
        "",
        f"- Cache state: `{result['timing_semantics']['cache_state']}`.",
        "- Windows OS cache is not flushed; these are not physical cold-disk timings.",
        "- Open/close are outside read timings except for `open_only`, which times open only.",
        "- Result equivalence checks run outside timed regions.",
        "",
        "## Raster layout",
        "",
        "| TIF | Compression | Tiled | Block | Blocks touched | Amplification | File bytes |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for indicator in INDICATORS:
        scenario = scenarios[indicator.code]
        lines.append(
            f"| {indicator.code} | {scenario['compression']} | "
            f"{str(scenario['tiled']).lower()} | "
            f"{scenario['block_rows']}×{scenario['block_cols']} | "
            f"{scenario['touched_block_count']} | "
            f"{scenario['read_amplification_ratio']:.3f} | "
            f"{scenario['file_size_bytes']} |"
        )
    lines.extend(
        [
            "",
            "## Median timing by TIF",
            "",
            "All values are milliseconds after one warm-up per mode.",
            "",
            (
                "| TIF | Open | Masked/new | Masked/same | Data | Mask | "
                "Data+mask |"
            ),
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in result["raster_read_attribution"]["summaries"]:
        modes = summary["modes"]
        lines.append(
            f"| {summary['indicator_code']} | {modes['open_only']['median']:.3f} | "
            f"{modes['masked_read_new_handle']['median']:.3f} | "
            f"{modes['masked_reread_same_handle']['median']:.3f} | "
            f"{modes['data_read']['median']:.3f} | "
            f"{modes['mask_read']['median']:.3f} | "
            f"{modes['data_plus_mask']['median']:.3f} |"
        )
    lines.extend(
        [
            "",
            "## Median ratios",
            "",
            "| TIF | Masked/data | Masked/(data+mask) | Same/new handle |",
            "|---|---:|---:|---:|",
        ]
    )
    for summary in result["raster_read_attribution"]["summaries"]:
        ratios = summary["median_ratios"]
        lines.append(
            f"| {summary['indicator_code']} | "
            f"{ratios['masked_read_over_data_read']:.3f} | "
            f"{ratios['masked_read_over_data_plus_mask']:.3f} | "
            f"{ratios['same_handle_reread_over_new_handle_read']:.3f} |"
        )
    lines.extend(
        [
            "",
            "Raw nanosecond samples, min/median/max summaries, GDAL configuration, "
            "environment metadata and TIF SHA-256 values are retained in JSON/CSV.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_raster_read_csv(path: Path, samples: Sequence[dict[str, Any]]) -> None:
    fields = [
        "indicator_code",
        "filename",
        "mode",
        "sample_index",
        "rows",
        "cols",
        "window_cells",
        "elapsed_ns",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(samples)


def run_raster_read_attribution(
    *,
    raster_dir: Path,
    output_dir: Path,
    repository_head_sha: str,
    source_tree_verified: bool,
    baseline_is_ancestor: bool,
    production_candidate_is_ancestor: bool,
    diagnostic_source_tree_verified: bool,
    subject_baseline_sha: str,
    production_candidate_sha: str = PRODUCTION_CANDIDATE_SHA,
    verification_method: str = SOURCE_TREE_VERIFICATION_METHOD,
    allowed_benchmark_paths: Sequence[str] = ALLOWED_BENCHMARK_PATHS,
    tracked_differences: Sequence[str] = (),
    untracked_paths: Sequence[str] = (),
    allowed_diagnostic_paths: Sequence[str] = ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
    diagnostic_differences: Sequence[str] = (),
    warmups: int = DEFAULT_WARMUPS,
    runs: int = DEFAULT_RUNS,
    size: int = RASTER_READ_ATTRIBUTION_SIZE,
) -> tuple[dict[str, Any], dict[str, Path]]:
    raster_dir = raster_dir.expanduser().resolve()
    provenance = _verified_provenance(
        subject_baseline_sha,
        repository_head_sha,
        verification_method,
        source_tree_verified,
        baseline_is_ancestor,
        allowed_benchmark_paths,
        tracked_differences,
        untracked_paths,
    )
    lineage = _verified_instrumentation_lineage(
        production_candidate_sha,
        subject_baseline_sha,
        production_candidate_is_ancestor,
        diagnostic_source_tree_verified,
        allowed_diagnostic_paths,
        diagnostic_differences,
    )
    if warmups < 0 or runs < 1 or size < 1:
        raise ValueError("warmups 必须 >= 0，runs/size 必须 >= 1")

    started = time.perf_counter_ns()
    output_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    scenarios: list[dict[str, Any]] = []
    for indicator in INDICATORS:
        path = raster_dir / indicator.filename
        with rasterio.open(path) as dataset:
            window, grid_center = _scenario_window(dataset, size)
            block_shape = dataset.block_shapes[0]
            scenario = {
                "indicator_code": indicator.code,
                "filename": indicator.filename,
                "file_size_bytes": path.stat().st_size,
                "compression": str(dataset.compression),
                "tiled": bool(dataset.profile.get("tiled", False)),
                "block_rows": block_shape[0],
                "block_cols": block_shape[1],
                "window": {
                    "row_off": int(window.row_off),
                    "col_off": int(window.col_off),
                    "height": int(window.height),
                    "width": int(window.width),
                },
                "grid_aligned_center": list(grid_center),
                **_window_block_metrics(window, block_shape, dataset.dtypes[0]),
            }
        scenario["read_equivalence"] = _verify_raster_read_equivalence(path, window)
        scenarios.append(scenario)

        same_handle = rasterio.open(path)
        try:
            for mode in RASTER_READ_MODES:
                for _ in range(warmups):
                    _time_raster_read_mode(
                        path,
                        window,
                        mode,
                        same_handle=(
                            same_handle if mode == "masked_reread_same_handle" else None
                        ),
                    )

            modes = list(RASTER_READ_MODES)
            for sample_index in range(runs):
                offset = sample_index % len(modes)
                for mode in modes[offset:] + modes[:offset]:
                    elapsed_ns = _time_raster_read_mode(
                        path,
                        window,
                        mode,
                        same_handle=(
                            same_handle if mode == "masked_reread_same_handle" else None
                        ),
                    )
                    samples.append(
                        {
                            "indicator_code": indicator.code,
                            "filename": indicator.filename,
                            "mode": mode,
                            "sample_index": sample_index,
                            "rows": int(window.height),
                            "cols": int(window.width),
                            "window_cells": int(window.width * window.height),
                            "elapsed_ns": elapsed_ns,
                        }
                    )
        finally:
            same_handle.close()

    result = {
        "schema_version": 1,
        "benchmark": "risk-raster-read-attribution",
        "production_candidate_sha": lineage["production_candidate_sha"],
        "diagnostic_subject_sha": lineage["instrumented_subject_sha"],
        "source_provenance": provenance,
        "instrumentation_lineage": lineage,
        "benchmark_elapsed_seconds": _elapsed_ms(started) / 1000.0,
        "configuration": {
            "warmups_per_mode": warmups,
            "measured_runs_per_mode": runs,
            "window_size": size,
            "indicator_codes": [indicator.code for indicator in INDICATORS],
            "modes": list(RASTER_READ_MODES),
            "measured_sample_count": len(samples),
        },
        "timing_semantics": {
            "clock": "time.perf_counter_ns",
            "raw_sample_unit": "nanoseconds",
            "cache_state": RASTER_READ_CACHE_SEMANTICS,
            "mode_order": "measured modes rotate once per sample round",
            "open_close_outside_read_timing": True,
            "result_equivalence_outside_timing": True,
            "physical_cold_disk_claimed": False,
        },
        "gdal_runtime": {
            "version": rasterio.__gdal_version__,
            "GDAL_CACHEMAX": rasterio.env.get_gdal_config("GDAL_CACHEMAX"),
            "GDAL_NUM_THREADS": rasterio.env.get_gdal_config("GDAL_NUM_THREADS"),
            "VSI_CACHE": rasterio.env.get_gdal_config("VSI_CACHE"),
        },
        "environment": _environment_metadata(),
        "raster_dataset": {
            "directory": str(raster_dir),
            "files": _raster_metadata(raster_dir),
        },
        "raster_read_attribution": {
            "scenarios": scenarios,
            "raw_samples": samples,
            "summaries": _raster_read_summaries(samples),
        },
    }
    paths = {
        "json": output_dir / "risk-raster-read-attribution.json",
        "csv": output_dir / "risk-raster-read-attribution.csv",
        "markdown": output_dir / "risk-raster-read-attribution.md",
    }
    paths["json"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_raster_read_csv(paths["csv"], samples)
    paths["markdown"].write_text(_raster_read_markdown(result), encoding="utf-8")
    return result, paths


def _read_handle_reuse_sequence(
    opened: Sequence[tuple[Any, Any]],
    window: Window,
) -> tuple[int, list[dict[str, Any]], dict[str, np.ma.MaskedArray]]:
    timings: list[tuple[Any, int]] = []
    bands: dict[str, np.ma.MaskedArray] = {}
    sequence_started = time.perf_counter_ns()
    for indicator, dataset in opened:
        started = time.perf_counter_ns()
        band = dataset.read(1, window=window, masked=True)
        elapsed_ns = time.perf_counter_ns() - started
        bands[indicator.code] = band
        timings.append((indicator, elapsed_ns))
    sequence_elapsed_ns = time.perf_counter_ns() - sequence_started
    events = []
    for indicator, elapsed_ns in timings:
        band = bands[indicator.code]
        events.append(
            {
                "indicator_code": indicator.code,
                "filename": indicator.filename,
                "rows": int(band.shape[0]),
                "cols": int(band.shape[1]),
                "window_cells": int(band.size),
                "valid_cells": int(
                    np.count_nonzero(~np.ma.getmaskarray(band))
                ),
                "elapsed_ns": elapsed_ns,
            }
        )
    return sequence_elapsed_ns, events, bands


def _run_handle_reuse_mode(
    raster_dir: Path,
    base_window: Window,
    target_window: Window,
    mode: str,
) -> tuple[int, list[dict[str, Any]], dict[str, np.ma.MaskedArray]]:
    def open_catalog(stack: ExitStack) -> list[tuple[Any, Any]]:
        return [
            (
                indicator,
                stack.enter_context(rasterio.open(raster_dir / indicator.filename)),
            )
            for indicator in INDICATORS
        ]

    if mode == "reopen_between_requests":
        with ExitStack() as stack:
            primed = open_catalog(stack)
            for _, dataset in primed:
                dataset.read(1, window=base_window, masked=True)
        with ExitStack() as stack:
            return _read_handle_reuse_sequence(open_catalog(stack), target_window)

    if mode == "reuse_same_process_handles":
        with ExitStack() as stack:
            opened = open_catalog(stack)
            for _, dataset in opened:
                dataset.read(1, window=base_window, masked=True)
            return _read_handle_reuse_sequence(opened, target_window)

    raise ValueError(f"不支持的 DatasetReader reuse mode: {mode}")


def _verify_handle_reuse_equivalence(
    reopen: dict[str, np.ma.MaskedArray],
    reuse: dict[str, np.ma.MaskedArray],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for indicator in INDICATORS:
        reopened = reopen[indicator.code]
        reused = reuse[indicator.code]
        if reopened.shape != reused.shape or reopened.dtype != reused.dtype:
            raise RuntimeError(f"{indicator.code} 两种句柄模式的 shape 或 dtype 不一致")
        if not np.array_equal(reopened.data, reused.data, equal_nan=True):
            raise RuntimeError(f"{indicator.code} 两种句柄模式的像元值不一致")
        if not np.array_equal(
            np.ma.getmaskarray(reopened), np.ma.getmaskarray(reused)
        ):
            raise RuntimeError(f"{indicator.code} 两种句柄模式的 mask 不一致")
        records.append(
            {
                "indicator_code": indicator.code,
                "rows": int(reopened.shape[0]),
                "cols": int(reopened.shape[1]),
                "dtype": str(reopened.dtype),
                "valid_cells": int(
                    np.count_nonzero(~np.ma.getmaskarray(reopened))
                ),
                "equivalent": True,
            }
        )
    return records


def _handle_reuse_summaries(
    samples: Sequence[dict[str, Any]],
    relationships: Sequence[str],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for relationship in relationships:
        modes = {
            mode: _numeric_summary(
                [
                    sample["sequence_elapsed_ns"] / 1_000_000
                    for sample in samples
                    if sample["relationship"] == relationship
                    and sample["mode"] == mode
                ]
            )
            for mode in HANDLE_REUSE_MODES
        }
        reopen = modes["reopen_between_requests"]
        reuse = modes["reuse_same_process_handles"]
        per_indicator: list[dict[str, Any]] = []
        for indicator in INDICATORS:
            indicator_modes = {
                mode: _numeric_summary(
                    [
                        event["elapsed_ns"] / 1_000_000
                        for sample in samples
                        if sample["relationship"] == relationship
                        and sample["mode"] == mode
                        for event in sample["indicator_events"]
                        if event["indicator_code"] == indicator.code
                    ]
                )
                for mode in HANDLE_REUSE_MODES
            }
            per_indicator.append(
                {
                    "indicator_code": indicator.code,
                    "modes": indicator_modes,
                    "median_speedup": (
                        indicator_modes["reopen_between_requests"]["median"]
                        / indicator_modes["reuse_same_process_handles"]["median"]
                    ),
                }
            )
        summaries.append(
            {
                "relationship": relationship,
                "modes": modes,
                "median_speedup": reopen["median"] / reuse["median"],
                "reuse_median_below_reopen_min": reuse["median"] < reopen["min"],
                "quantitative_gate_pass": (
                    reopen["median"] / reuse["median"] >= HANDLE_REUSE_MIN_SPEEDUP
                    and reuse["median"] < reopen["min"]
                ),
                "per_indicator": per_indicator,
            }
        )
    return summaries


def _handle_reuse_markdown(result: dict[str, Any]) -> str:
    source = result["source_provenance"]
    lineage = result["instrumentation_lineage"]
    scenarios = result["handle_reuse_applicability"]["scenarios"]
    summaries = {
        item["relationship"]: item
        for item in result["handle_reuse_applicability"]["summaries"]
    }
    lines = [
        "# Risk DatasetReader Handle Reuse Applicability",
        "",
        f"- Production candidate: `{lineage['production_candidate_sha']}`",
        f"- Diagnostic subject: `{lineage['instrumented_subject_sha']}`",
        f"- Repository HEAD: `{source['repository_head_sha']}`",
        "- Source tree and diagnostic lineage verified: `true`",
        f"- Benchmark elapsed: `{result['benchmark_elapsed_seconds']:.3f}s`",
        (
            "- Repetition: warm-up "
            f"{result['configuration']['warmups_per_relationship_and_mode']} + measured "
            f"{result['configuration']['measured_runs_per_relationship_and_mode']} "
            "per relationship/mode"
        ),
        "",
        "## Timing semantics",
        "",
        f"- Cache state: `{result['timing_semantics']['cache_state']}`.",
        "- Windows OS cache is not flushed; these are not physical cold-disk timings.",
        "- Only target `read(masked=True)` calls are timed.",
        "- Open, close, base-window priming and result equivalence run outside timing.",
        "- This is a single-process, single-thread diagnostic, not full Pipeline latency.",
        "",
        "## Window relationships",
        "",
        "| Relationship | Column shift | Pixel overlap | Block cache coverage |",
        "|---|---:|---:|---:|",
    ]
    for scenario in scenarios:
        coverages = [
            item["target_block_cache_coverage_ratio"]
            for item in scenario["per_indicator_block_overlap"]
        ]
        coverage = (
            f"{coverages[0] * 100:.1f}%"
            if min(coverages) == max(coverages)
            else f"{min(coverages) * 100:.1f}%–{max(coverages) * 100:.1f}%"
        )
        lines.append(
            f"| `{scenario['relationship']}` | {scenario['column_shift']} | "
            f"{scenario['pixel_overlap_ratio'] * 100:.1f}% | {coverage} |"
        )
    lines.extend(
        [
            "",
            "## 12-TIF sequence timing",
            "",
            "All values are min/median/max milliseconds.",
            "",
            "| Relationship | Reopen | Reuse | Median speedup | Reuse median < reopen min | Gate |",
            "|---|---:|---:|---:|---|---|",
        ]
    )
    for scenario in scenarios:
        summary = summaries[scenario["relationship"]]
        lines.append(
            f"| `{scenario['relationship']}` | "
            f"{_range_text(summary['modes']['reopen_between_requests'])} | "
            f"{_range_text(summary['modes']['reuse_same_process_handles'])} | "
            f"{summary['median_speedup']:.2f}× | "
            f"{str(summary['reuse_median_below_reopen_min']).lower()} | "
            f"{str(summary['quantitative_gate_pass']).lower()} |"
        )
    lines.extend(
        [
            "",
            (
                f"The quantitative gate requires at least {HANDLE_REUSE_MIN_SPEEDUP:.1f}× "
                "median speedup and reuse median below reopen minimum. Variability and "
                "semantic equivalence still require manual review."
            ),
            "",
            "All sequence samples, per-TIF nanosecond events, environment metadata, "
            "GDAL configuration and TIF SHA-256 values are retained in JSON/CSV.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_handle_reuse_csv(
    path: Path,
    samples: Sequence[dict[str, Any]],
) -> None:
    fields = [
        "relationship",
        "column_shift",
        "mode",
        "sample_index",
        "order_index",
        "sequence_elapsed_ns",
        "indicator_code",
        "filename",
        "rows",
        "cols",
        "window_cells",
        "valid_cells",
        "elapsed_ns",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            for event in sample["indicator_events"]:
                writer.writerow(
                    {
                        **{field: sample[field] for field in fields[:6]},
                        **event,
                    }
                )


def run_handle_reuse_applicability(
    *,
    raster_dir: Path,
    output_dir: Path,
    repository_head_sha: str,
    source_tree_verified: bool,
    baseline_is_ancestor: bool,
    production_candidate_is_ancestor: bool,
    diagnostic_source_tree_verified: bool,
    subject_baseline_sha: str,
    production_candidate_sha: str = PRODUCTION_CANDIDATE_SHA,
    verification_method: str = SOURCE_TREE_VERIFICATION_METHOD,
    allowed_benchmark_paths: Sequence[str] = ALLOWED_BENCHMARK_PATHS,
    tracked_differences: Sequence[str] = (),
    untracked_paths: Sequence[str] = (),
    allowed_diagnostic_paths: Sequence[str] = ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
    diagnostic_differences: Sequence[str] = (),
    warmups: int = DEFAULT_WARMUPS,
    runs: int = DEFAULT_RUNS,
    size: int = HANDLE_REUSE_APPLICABILITY_SIZE,
    window_shifts: dict[str, int] = HANDLE_REUSE_WINDOW_SHIFTS,
) -> tuple[dict[str, Any], dict[str, Path]]:
    raster_dir = raster_dir.expanduser().resolve()
    provenance = _verified_provenance(
        subject_baseline_sha,
        repository_head_sha,
        verification_method,
        source_tree_verified,
        baseline_is_ancestor,
        allowed_benchmark_paths,
        tracked_differences,
        untracked_paths,
    )
    lineage = _verified_instrumentation_lineage(
        production_candidate_sha,
        subject_baseline_sha,
        production_candidate_is_ancestor,
        diagnostic_source_tree_verified,
        allowed_diagnostic_paths,
        diagnostic_differences,
    )
    if warmups < 0 or runs < 1 or size < 1:
        raise ValueError("warmups 必须 >= 0，runs/size 必须 >= 1")
    if tuple(window_shifts) != tuple(HANDLE_REUSE_WINDOW_SHIFTS):
        raise ValueError("DatasetReader reuse window relationships 与 Contract 不一致")

    started = time.perf_counter_ns()
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    with rasterio.open(reference_path) as reference:
        base_window, grid_center = _scenario_window(reference, size)

    scenarios: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for relationship_index, (relationship, column_shift) in enumerate(
        window_shifts.items()
    ):
        target_window = Window(
            col_off=base_window.col_off + column_shift,
            row_off=base_window.row_off,
            width=base_window.width,
            height=base_window.height,
        )
        per_indicator_overlap: list[dict[str, Any]] = []
        for indicator in INDICATORS:
            path = raster_dir / indicator.filename
            with rasterio.open(path) as dataset:
                if (
                    target_window.col_off < 0
                    or target_window.row_off < 0
                    or target_window.col_off + target_window.width > dataset.width
                    or target_window.row_off + target_window.height > dataset.height
                ):
                    raise ValueError(
                        f"{relationship} 的目标窗口超出 {indicator.code} 栅格范围"
                    )
                per_indicator_overlap.append(
                    {
                        "indicator_code": indicator.code,
                        "block_rows": dataset.block_shapes[0][0],
                        "block_cols": dataset.block_shapes[0][1],
                        **_window_overlap_metrics(
                            base_window, target_window, dataset.block_shapes[0]
                        ),
                    }
                )

        for _ in range(warmups):
            for mode in HANDLE_REUSE_MODES:
                _run_handle_reuse_mode(
                    raster_dir, base_window, target_window, mode
                )

        equivalence: list[dict[str, Any]] | None = None
        for sample_index in range(runs):
            mode_order = list(HANDLE_REUSE_MODES)
            if (relationship_index + sample_index) % 2:
                mode_order.reverse()
            pair_results: dict[str, dict[str, np.ma.MaskedArray]] = {}
            for order_index, mode in enumerate(mode_order):
                sequence_elapsed_ns, events, bands = _run_handle_reuse_mode(
                    raster_dir, base_window, target_window, mode
                )
                pair_results[mode] = bands
                samples.append(
                    {
                        "relationship": relationship,
                        "column_shift": column_shift,
                        "mode": mode,
                        "sample_index": sample_index,
                        "order_index": order_index,
                        "sequence_elapsed_ns": sequence_elapsed_ns,
                        "indicator_events": events,
                    }
                )
            equivalence = _verify_handle_reuse_equivalence(
                pair_results["reopen_between_requests"],
                pair_results["reuse_same_process_handles"],
            )

        if equivalence is None:
            raise RuntimeError("DatasetReader reuse applicability 未产生结果")
        pixel_metrics = per_indicator_overlap[0]
        scenarios.append(
            {
                "relationship": relationship,
                "column_shift": column_shift,
                "base_window": {
                    "row_off": int(base_window.row_off),
                    "col_off": int(base_window.col_off),
                    "height": int(base_window.height),
                    "width": int(base_window.width),
                },
                "target_window": {
                    "row_off": int(target_window.row_off),
                    "col_off": int(target_window.col_off),
                    "height": int(target_window.height),
                    "width": int(target_window.width),
                },
                "grid_aligned_center": list(grid_center),
                "pixel_overlap_cells": pixel_metrics["pixel_overlap_cells"],
                "pixel_overlap_ratio": pixel_metrics["pixel_overlap_ratio"],
                "per_indicator_block_overlap": per_indicator_overlap,
                "read_equivalence": equivalence,
            }
        )

    relationships = list(window_shifts)
    result = {
        "schema_version": 1,
        "benchmark": "risk-datasetreader-handle-reuse-applicability",
        "production_candidate_sha": lineage["production_candidate_sha"],
        "diagnostic_subject_sha": lineage["instrumented_subject_sha"],
        "source_provenance": provenance,
        "instrumentation_lineage": lineage,
        "benchmark_elapsed_seconds": _elapsed_ms(started) / 1000.0,
        "configuration": {
            "warmups_per_relationship_and_mode": warmups,
            "measured_runs_per_relationship_and_mode": runs,
            "window_size": size,
            "indicator_codes": [indicator.code for indicator in INDICATORS],
            "window_shifts": dict(window_shifts),
            "modes": list(HANDLE_REUSE_MODES),
            "measured_sequence_sample_count": len(samples),
            "measured_indicator_event_count": sum(
                len(sample["indicator_events"]) for sample in samples
            ),
            "minimum_decision_speedup": HANDLE_REUSE_MIN_SPEEDUP,
        },
        "timing_semantics": {
            "clock": "time.perf_counter_ns",
            "raw_sample_unit": "nanoseconds",
            "cache_state": RASTER_READ_CACHE_SEMANTICS,
            "target_operation": "dataset.read(1, window=target, masked=True)",
            "target_read_only_timed": True,
            "open_close_outside_timing": True,
            "base_window_prime_outside_timing": True,
            "result_equivalence_outside_timing": True,
            "handles_recreated_per_sample": True,
            "mode_order": "alternates by relationship and sample index",
            "execution_scope": "single_process_single_thread_diagnostic",
            "physical_cold_disk_claimed": False,
            "comparable_to_full_pipeline_latency": False,
        },
        "gdal_runtime": {
            "version": rasterio.__gdal_version__,
            "GDAL_CACHEMAX": rasterio.env.get_gdal_config("GDAL_CACHEMAX"),
            "GDAL_NUM_THREADS": rasterio.env.get_gdal_config("GDAL_NUM_THREADS"),
            "VSI_CACHE": rasterio.env.get_gdal_config("VSI_CACHE"),
        },
        "environment": _environment_metadata(),
        "raster_dataset": {
            "directory": str(raster_dir),
            "files": _raster_metadata(raster_dir),
        },
        "handle_reuse_applicability": {
            "scenarios": scenarios,
            "raw_sequence_samples": samples,
            "summaries": _handle_reuse_summaries(samples, relationships),
        },
    }
    paths = {
        "json": output_dir / "risk-handle-reuse-applicability.json",
        "csv": output_dir / "risk-handle-reuse-applicability.csv",
        "markdown": output_dir / "risk-handle-reuse-applicability.md",
    }
    paths["json"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_handle_reuse_csv(paths["csv"], samples)
    paths["markdown"].write_text(_handle_reuse_markdown(result), encoding="utf-8")
    return result, paths


def run_benchmark(
    *,
    raster_dir: Path,
    repository_head_sha: str,
    source_tree_verified: bool,
    baseline_is_ancestor: bool,
    subject_baseline_sha: str = BASELINE_SHA,
    verification_method: str = SOURCE_TREE_VERIFICATION_METHOD,
    allowed_benchmark_paths: Sequence[str] = ALLOWED_BENCHMARK_PATHS,
    tracked_differences: Sequence[str] = (),
    untracked_paths: Sequence[str] = (),
    warmups: int = DEFAULT_WARMUPS,
    runs: int = DEFAULT_RUNS,
    compute_sizes: dict[str, int] = COMPUTE_SIZES,
    spatial_sizes: dict[str, int] = SPATIAL_SIZES,
) -> dict[str, Any]:
    raster_dir = raster_dir.expanduser().resolve()
    provenance = _verified_provenance(
        subject_baseline_sha,
        repository_head_sha,
        verification_method,
        source_tree_verified,
        baseline_is_ancestor,
        allowed_benchmark_paths,
        tracked_differences,
        untracked_paths,
    )
    if warmups < 0 or runs < 1:
        raise ValueError("warmups 必须 >= 0 且 runs 必须 >= 1")
    started = time.perf_counter_ns()
    raster_records = _raster_metadata(raster_dir)
    with tempfile.TemporaryDirectory(prefix="esr-risk-benchmark-") as temporary:
        runtime_dir = Path(temporary)
        compute_scenarios, compute_samples = _run_compute(
            raster_dir=raster_dir,
            runtime_dir=runtime_dir,
            warmups=warmups,
            runs=runs,
            sizes=compute_sizes,
        )
        spatial_scenarios, spatial_samples = _run_spatial(
            raster_dir=raster_dir,
            runtime_dir=runtime_dir,
            warmups=warmups,
            runs=runs,
            sizes=spatial_sizes,
        )
    return {
        "schema_version": 1,
        "benchmark": "risk-analysis-performance-baseline",
        "subject_baseline_sha": provenance["subject_baseline_sha"],
        "source_provenance": provenance,
        "benchmark_elapsed_seconds": _elapsed_ms(started) / 1000.0,
        "configuration": {
            "warmups_per_scenario": warmups,
            "measured_runs_per_scenario": runs,
            "compute_sizes": compute_sizes,
            "spatial_sizes": spatial_sizes,
        },
        "timing_semantics": {
            "pipeline_elapsed_ms": "pipeline.run() wrapped inside the same execute()",
            "total_service_elapsed_ms": "the same RiskAnalysisJobService.execute() call",
            "validation_elapsed_ms": VALIDATION_TIMING,
            "validation_included_in_total_service": (
                VALIDATION_INCLUDED_IN_TOTAL_SERVICE
            ),
            "spatial_elapsed_ms": (
                "real Flask route via test client; includes raster validation, feature building, "
                "Pydantic validation, and JSON serialization; excludes network transport"
            ),
        },
        "environment": _environment_metadata(),
        "raster_dataset": {
            "directory": str(raster_dir),
            "files": raster_records,
        },
        "compute": {
            "scenarios": compute_scenarios,
            "raw_samples": compute_samples,
            "summaries": _summaries(
                compute_samples,
                (
                    "pipeline_elapsed_ms",
                    "validation_elapsed_ms",
                    "total_service_elapsed_ms",
                ),
            ),
        },
        "spatial": {
            "scenarios": spatial_scenarios,
            "raw_samples": spatial_samples,
            "summaries": _summaries(
                spatial_samples,
                ("spatial_elapsed_ms", "feature_count", "response_bytes"),
            ),
        },
        "hotspot_hypotheses": [
            (
                "Per-indicator raster reads, float64 copies, masks, scans, and statistics "
                "may scale with indicators × cells."
            ),
            (
                "GeoTIFF and manifest persistence may explain part of total service minus "
                "pipeline time."
            ),
            "Standalone raster validation uses a Python np.ndindex loop and a Python value list.",
            (
                "Spatial generation validates again, then builds one Polygon/Pydantic object "
                "per valid cell and serializes JSON."
            ),
        ],
    }


def _write_csv(path: Path, result: dict[str, Any]) -> None:
    fields = [
        "family",
        "aoi",
        "indicator_count",
        "indicator_codes",
        "sample_index",
        "rows",
        "cols",
        "window_cells",
        "valid_cells",
        "pipeline_elapsed_ms",
        "validation_elapsed_ms",
        "validation_timing",
        "validation_included_in_total_service",
        "total_service_elapsed_ms",
        "spatial_elapsed_ms",
        "feature_count",
        "response_bytes",
        "transport",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for family in ("compute", "spatial"):
            for sample in result[family]["raw_samples"]:
                row = dict(sample)
                row["indicator_codes"] = ",".join(row["indicator_codes"])
                writer.writerow(row)


def _range_text(summary: dict[str, float], digits: int = 3) -> str:
    return "/".join(f"{summary[key]:.{digits}f}" for key in ("min", "median", "max"))


def _markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Risk Analysis Performance Baseline",
        "",
        f"- Subject production baseline: `{result['source_provenance']['subject_baseline_sha']}`",
        f"- Repository HEAD: `{result['source_provenance']['repository_head_sha']}`",
        (
            "- Source-tree verification: "
            f"`{result['source_provenance']['source_tree_verification_method']}`"
        ),
        "- Source tree verified: `true`",
        (
            "- Verified invariant: outside the benchmark-only allowlist, the working "
            "tree matches the subject production baseline. Repository HEAD may be newer."
        ),
        f"- Benchmark elapsed: `{result['benchmark_elapsed_seconds']:.3f}s`",
        (
            "- Repetition: warm-up "
            f"{result['configuration']['warmups_per_scenario']} + measured "
            f"{result['configuration']['measured_runs_per_scenario']} per scenario"
        ),
        "",
        "## Timing semantics",
        "",
        "- `pipeline_elapsed_ms` wraps `pipeline.run()` inside the same service `execute()`.",
        "- `total_service_elapsed_ms` measures that same `execute()` call.",
        (
            "- `validation_elapsed_ms` is `standalone_post_execute_warm_cache`; "
            "`included_in_total_service=false`. It is not a decomposition of service time."
        ),
        (
            "- `spatial_elapsed_ms` calls the real Flask route through its test client. "
            "It includes response serialization but excludes network transport."
        ),
        "",
        "## Compute results",
        "",
        "Times are min/median/max milliseconds.",
        "",
        (
            "| Indicators | AOI | Rows×Cols | Cells | Valid cells | Pipeline | "
            "Validation (standalone) | Total service |"
        ),
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in result["compute"]["summaries"]:
        metrics = summary["metrics"]
        lines.append(
            f"| {summary['indicator_count']} | {summary['aoi']} | "
            f"{summary['rows']}×{summary['cols']} | {summary['window_cells']} | "
            f"{_range_text(summary['valid_cells'], 0)} | "
            f"{_range_text(metrics['pipeline_elapsed_ms'])} | "
            f"{_range_text(metrics['validation_elapsed_ms'])} | "
            f"{_range_text(metrics['total_service_elapsed_ms'])} |"
        )
    lines.extend(
        [
            "",
            "## Spatial results",
            "",
            "Latency is min/median/max milliseconds; counts and bytes are actual responses.",
            "",
            "| AOI | Rows×Cols | Cells | Valid cells | Latency | Feature count | Response bytes |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for summary in result["spatial"]["summaries"]:
        metrics = summary["metrics"]
        lines.append(
            f"| {summary['aoi']} | {summary['rows']}×{summary['cols']} | "
            f"{summary['window_cells']} | {_range_text(summary['valid_cells'], 0)} | "
            f"{_range_text(metrics['spatial_elapsed_ms'])} | "
            f"{_range_text(metrics['feature_count'], 0)} | "
            f"{_range_text(metrics['response_bytes'], 0)} |"
        )
    lines.extend(["", "## Hotspot hypotheses", ""])
    lines.extend(f"- **Hypothesis:** {item}" for item in result["hotspot_hypotheses"])
    lines.extend(
        [
            "",
            "Raw measured samples and full environment/TIF metadata are in the JSON and CSV files.",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(result: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output_dir / "risk-analysis-baseline.json",
        "csv": output_dir / "risk-analysis-baseline.csv",
        "markdown": output_dir / "risk-analysis-baseline.md",
    }
    paths["json"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_csv(paths["csv"], result)
    paths["markdown"].write_text(_markdown(result), encoding="utf-8")
    return paths


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Risk Analysis performance diagnostics.")
    parser.add_argument("--raster-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--subject-baseline-sha", default=BASELINE_SHA)
    parser.add_argument("--repository-head-sha", required=True)
    parser.add_argument(
        "--source-tree-verification-method",
        choices=(SOURCE_TREE_VERIFICATION_METHOD,),
        required=True,
    )
    parser.add_argument("--source-tree-verified", action="store_true", required=True)
    parser.add_argument("--baseline-is-ancestor", action="store_true", required=True)
    parser.add_argument("--allowed-benchmark-path", action="append", required=True)
    parser.add_argument("--tracked-difference", action="append", default=[])
    parser.add_argument("--untracked-path", action="append", default=[])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--pipeline-profile", action="store_true")
    mode.add_argument("--pipeline-read-attribution", action="store_true")
    mode.add_argument("--pipeline-handle-reuse-applicability", action="store_true")
    parser.add_argument("--production-candidate-sha")
    parser.add_argument("--production-candidate-is-ancestor", action="store_true")
    parser.add_argument("--diagnostic-source-tree-verified", action="store_true")
    parser.add_argument("--allowed-diagnostic-path", action="append")
    parser.add_argument("--diagnostic-difference", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.pipeline_handle_reuse_applicability:
        if args.production_candidate_sha is None or args.allowed_diagnostic_path is None:
            raise ValueError(
                "DatasetReader reuse applicability 需要 production candidate 和 "
                "diagnostic allowlist"
            )
        result, paths = run_handle_reuse_applicability(
            raster_dir=args.raster_dir,
            output_dir=args.output_dir,
            subject_baseline_sha=args.subject_baseline_sha,
            repository_head_sha=args.repository_head_sha,
            verification_method=args.source_tree_verification_method,
            source_tree_verified=args.source_tree_verified,
            baseline_is_ancestor=args.baseline_is_ancestor,
            allowed_benchmark_paths=args.allowed_benchmark_path,
            tracked_differences=args.tracked_difference,
            untracked_paths=args.untracked_path,
            production_candidate_sha=args.production_candidate_sha,
            production_candidate_is_ancestor=args.production_candidate_is_ancestor,
            diagnostic_source_tree_verified=args.diagnostic_source_tree_verified,
            allowed_diagnostic_paths=args.allowed_diagnostic_path,
            diagnostic_differences=args.diagnostic_difference,
        )
        for kind, path in paths.items():
            print(f"[OK] {kind}: {path}")
        print(
            "[INFO] DatasetReader reuse applicability elapsed: "
            f"{result['benchmark_elapsed_seconds']:.3f}s"
        )
        return 0
    if args.pipeline_read_attribution:
        if args.production_candidate_sha is None or args.allowed_diagnostic_path is None:
            raise ValueError(
                "raster read attribution 需要 production candidate 和 diagnostic allowlist"
            )
        result, paths = run_raster_read_attribution(
            raster_dir=args.raster_dir,
            output_dir=args.output_dir,
            subject_baseline_sha=args.subject_baseline_sha,
            repository_head_sha=args.repository_head_sha,
            verification_method=args.source_tree_verification_method,
            source_tree_verified=args.source_tree_verified,
            baseline_is_ancestor=args.baseline_is_ancestor,
            allowed_benchmark_paths=args.allowed_benchmark_path,
            tracked_differences=args.tracked_difference,
            untracked_paths=args.untracked_path,
            production_candidate_sha=args.production_candidate_sha,
            production_candidate_is_ancestor=args.production_candidate_is_ancestor,
            diagnostic_source_tree_verified=args.diagnostic_source_tree_verified,
            allowed_diagnostic_paths=args.allowed_diagnostic_path,
            diagnostic_differences=args.diagnostic_difference,
        )
        for kind, path in paths.items():
            print(f"[OK] {kind}: {path}")
        print(
            "[INFO] raster read attribution elapsed: "
            f"{result['benchmark_elapsed_seconds']:.3f}s"
        )
        return 0
    if args.pipeline_profile:
        result, paths = run_pipeline_profile(
            raster_dir=args.raster_dir,
            output_dir=args.output_dir,
            subject_baseline_sha=args.subject_baseline_sha,
            repository_head_sha=args.repository_head_sha,
            verification_method=args.source_tree_verification_method,
            source_tree_verified=args.source_tree_verified,
            baseline_is_ancestor=args.baseline_is_ancestor,
            allowed_benchmark_paths=args.allowed_benchmark_path,
            tracked_differences=args.tracked_difference,
            untracked_paths=args.untracked_path,
        )
        for kind, path in paths.items():
            print(f"[OK] {kind}: {path}")
        print(f"[INFO] profile elapsed: {result['profile_elapsed_seconds']:.3f}s")
        return 0
    result = run_benchmark(
        raster_dir=args.raster_dir,
        subject_baseline_sha=args.subject_baseline_sha,
        repository_head_sha=args.repository_head_sha,
        verification_method=args.source_tree_verification_method,
        source_tree_verified=args.source_tree_verified,
        baseline_is_ancestor=args.baseline_is_ancestor,
        allowed_benchmark_paths=args.allowed_benchmark_path,
        tracked_differences=args.tracked_difference,
        untracked_paths=args.untracked_path,
    )
    paths = write_reports(result, args.output_dir)
    for kind, path in paths.items():
        print(f"[OK] {kind}: {path}")
    print(f"[INFO] benchmark elapsed: {result['benchmark_elapsed_seconds']:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
