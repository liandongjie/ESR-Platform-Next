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
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import rasterio
from rasterio.windows import Window
from rasterio.windows import bounds as window_bounds
from shapely.geometry import box, mapping

from app import create_app
from app.gis.geojson import parse_geojson_geometry
from app.gis.indicators import INDICATOR_BY_CODE, INDICATORS
from app.gis.risk_models import IndicatorWeight
from app.gis.risk_pipeline import RiskAnalysisPipeline
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
PIPELINE_STAGE_TIMING_SIZE = COMPUTE_SIZES["large"]
PIPELINE_STAGES = (
    "input_validation",
    "source_open",
    "grid_validation",
    "window_geometry_setup",
    "raster_read",
    "mask_preparation",
    "value_validation_and_stats",
    "weighted_accumulation",
    "result_finalization",
)
SOURCE_TREE_VERIFICATION_METHOD = "host_git_diff_and_untracked_allowlist_v1"
ALLOWED_BENCHMARK_PATHS = (
    "backend/app/gis/risk_benchmark.py",
    "backend/tests/test_risk_benchmark.py",
    "scripts/benchmark-risk-analysis.ps1",
    "docs/performance/",
)
ALLOWED_PIPELINE_DIAGNOSTIC_PATHS = (
    "backend/app/gis/risk_pipeline.py",
    "backend/tests/test_risk_pipeline.py",
    *ALLOWED_BENCHMARK_PATHS,
)


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
        left, bottom, right, top = window_bounds(window, reference.transform)
        center = reference.transform * (col_edge, row_edge)
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
    app = create_app("testing")
    app.config.update(RUNTIME_DATA_DIR=runtime_dir, TESTING=True)
    client = app.test_client()
    codes = INDICATOR_GROUPS[12]
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    scenarios: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for aoi_name, size in sizes.items():
        request, aoi = _request(reference_path, size, codes)
        task_id = f"spatial-12-{aoi_name}"
        payload = RiskAnalysisJobService(raster_dir, runtime_dir).execute(
            task_id=task_id,
            request=request,
        )
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


def _pipeline_stage_summaries(
    samples: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for indicator_count in INDICATOR_GROUPS:
        group = [
            sample for sample in samples if sample["indicator_count"] == indicator_count
        ]
        stage_records: list[dict[str, Any]] = []
        for stage in PIPELINE_STAGES:
            elapsed_ms: list[float] = []
            shares: list[float] = []
            call_counts: list[int] = []
            for sample in group:
                events = [event for event in sample["stage_events"] if event["stage"] == stage]
                stage_ns = sum(event["elapsed_ns"] for event in events)
                elapsed_ms.append(stage_ns / 1_000_000)
                shares.append(stage_ns / sample["pipeline_elapsed_ns"] * 100.0)
                call_counts.append(len(events))
            stage_records.append(
                {
                    "stage": stage,
                    "calls_per_sample": {
                        "min": min(call_counts),
                        "median": statistics.median(call_counts),
                        "max": max(call_counts),
                    },
                    "elapsed_ms": _numeric_summary(elapsed_ms),
                    "pipeline_share_percent": _numeric_summary(shares),
                }
            )

        per_indicator: list[dict[str, Any]] = []
        for stage in PIPELINE_STAGES:
            for code in INDICATOR_GROUPS[indicator_count]:
                values = [
                    event["elapsed_ns"] / 1_000_000
                    for sample in group
                    for event in sample["stage_events"]
                    if event["stage"] == stage and event["indicator_code"] == code
                ]
                if values:
                    per_indicator.append(
                        {
                            "stage": stage,
                            "indicator_code": code,
                            "sample_count": len(values),
                            "elapsed_ms": _numeric_summary(values),
                        }
                    )

        first = group[0]
        summaries.append(
            {
                "indicator_count": indicator_count,
                "rows": first["rows"],
                "cols": first["cols"],
                "window_cells": first["window_cells"],
                "valid_cells": _numeric_summary(
                    [float(sample["valid_cells"]) for sample in group]
                ),
                "pipeline_elapsed_ms": _numeric_summary(
                    [sample["pipeline_elapsed_ns"] / 1_000_000 for sample in group]
                ),
                "unattributed_ms": _numeric_summary(
                    [sample["unattributed_ns"] / 1_000_000 for sample in group]
                ),
                "unattributed_percent": _numeric_summary(
                    [
                        sample["unattributed_ns"]
                        / sample["pipeline_elapsed_ns"]
                        * 100.0
                        for sample in group
                    ]
                ),
                "stages": stage_records,
                "per_indicator_stages": per_indicator,
            }
        )
    return summaries


def _stage_timing_markdown(result: dict[str, Any]) -> str:
    lineage = result["instrumentation_lineage"]
    source = result["source_provenance"]
    lines = [
        "# Risk Analysis Pipeline Stage Timing",
        "",
        f"- Production candidate: `{lineage['production_candidate_sha']}`",
        f"- Instrumented subject: `{lineage['instrumented_subject_sha']}`",
        f"- Repository HEAD: `{source['repository_head_sha']}`",
        f"- Source-tree verification: `{source['source_tree_verification_method']}`",
        "- Source tree and instrumentation lineage verified: `true`",
        f"- Benchmark elapsed: `{result['benchmark_elapsed_seconds']:.3f}s`",
        (
            "- Repetition: warm-up "
            f"{result['configuration']['warmups_per_scenario']} + measured "
            f"{result['configuration']['measured_runs_per_scenario']} per scenario"
        ),
        "",
        "## Timing semantics",
        "",
        "- Timers wrap non-overlapping stages inside `RiskAnalysisPipeline.run()`.",
        "- Stage timing is diagnostic and is not a replacement latency baseline.",
        (
            "- `unattributed` is pipeline wall time minus timed stages; it includes "
            "resource cleanup, control flow, callback and timer overhead."
        ),
        "- Raw integer nanosecond events and output statistics are retained in JSON.",
        "",
        "## Scenarios",
        "",
        "All timings are min/median/max milliseconds unless stated otherwise.",
        "",
        (
            "| Indicators | Rows×Cols | Cells | Valid cells | Pipeline | "
            "Unattributed | Unattributed % |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in result["pipeline_stage_timing"]["summaries"]:
        lines.append(
            f"| {summary['indicator_count']} | {summary['rows']}×{summary['cols']} | "
            f"{summary['window_cells']} | {_range_text(summary['valid_cells'], 0)} | "
            f"{_range_text(summary['pipeline_elapsed_ms'])} | "
            f"{_range_text(summary['unattributed_ms'])} | "
            f"{_range_text(summary['unattributed_percent'])} |"
        )
    for summary in result["pipeline_stage_timing"]["summaries"]:
        lines.extend(
            [
                "",
                f"## {summary['indicator_count']}-indicator stages",
                "",
                "| Stage | Calls/sample | Elapsed ms | Pipeline share % |",
                "|---|---:|---:|---:|",
            ]
        )
        for stage in summary["stages"]:
            lines.append(
                f"| `{stage['stage']}` | "
                f"{_range_text(stage['calls_per_sample'], 0)} | "
                f"{_range_text(stage['elapsed_ms'])} | "
                f"{_range_text(stage['pipeline_share_percent'])} |"
            )
    lines.extend(
        [
            "",
            "Per-indicator stage timings, all raw samples, environment metadata and TIF "
            "SHA-256 values are retained in JSON.",
            "",
        ]
    )
    return "\n".join(lines)


def run_pipeline_stage_timing(
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
    size: int = PIPELINE_STAGE_TIMING_SIZE,
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
    reference_path = raster_dir / INDICATOR_BY_CODE["PM25"].filename
    scenarios: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    for indicator_count, codes in INDICATOR_GROUPS.items():
        request, aoi = _request(reference_path, size, codes)
        geometry = parse_geojson_geometry(request.geometry)
        weights = tuple(
            IndicatorWeight(item.code, float(item.weight_percent)) for item in request.weights
        )
        pipeline = RiskAnalysisPipeline(raster_dir)
        for _ in range(warmups):
            pipeline.run(geometry=geometry, weights=weights)

        last_result = None
        for sample_index in range(runs):
            events: list[dict[str, Any]] = []

            def record_stage(
                stage: str,
                indicator_code: str | None,
                elapsed_ns: int,
                target: list[dict[str, Any]] = events,
            ) -> None:
                target.append(
                    {
                        "stage": stage,
                        "indicator_code": indicator_code,
                        "elapsed_ns": elapsed_ns,
                    }
                )

            sample_started = time.perf_counter_ns()
            last_result = pipeline.run(
                geometry=geometry,
                weights=weights,
                _stage_timing_callback=record_stage,
            )
            pipeline_elapsed_ns = time.perf_counter_ns() - sample_started
            attributed_ns = sum(event["elapsed_ns"] for event in events)
            if attributed_ns > pipeline_elapsed_ns:
                raise RuntimeError("Pipeline stage timing 总和超过外层 pipeline elapsed")
            samples.append(
                {
                    "family": "pipeline_stage_timing",
                    "aoi": "large",
                    "indicator_count": indicator_count,
                    "indicator_codes": list(codes),
                    "sample_index": sample_index,
                    "rows": int(last_result.array.shape[0]),
                    "cols": int(last_result.array.shape[1]),
                    "window_cells": int(last_result.array.size),
                    "valid_cells": last_result.stats.valid_pixel_count,
                    "output_statistics": {
                        "minimum": last_result.stats.minimum,
                        "maximum": last_result.stats.maximum,
                        "mean": last_result.stats.mean,
                    },
                    "pipeline_elapsed_ns": pipeline_elapsed_ns,
                    "attributed_ns": attributed_ns,
                    "unattributed_ns": pipeline_elapsed_ns - attributed_ns,
                    "stage_events": events,
                }
            )
        if last_result is None:
            raise RuntimeError("Pipeline stage timing 未产生结果")
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
                "output_statistics": {
                    "minimum": last_result.stats.minimum,
                    "maximum": last_result.stats.maximum,
                    "mean": last_result.stats.mean,
                },
                **aoi,
            }
        )

    result = {
        "schema_version": 1,
        "benchmark": "risk-analysis-pipeline-stage-timing",
        "production_candidate_sha": lineage["production_candidate_sha"],
        "instrumented_subject_sha": lineage["instrumented_subject_sha"],
        "source_provenance": provenance,
        "instrumentation_lineage": lineage,
        "benchmark_elapsed_seconds": _elapsed_ms(started) / 1000.0,
        "configuration": {
            "warmups_per_scenario": warmups,
            "measured_runs_per_scenario": runs,
            "stage_timing_size": size,
            "indicator_groups": {
                str(count): list(codes) for count, codes in INDICATOR_GROUPS.items()
            },
            "stages": list(PIPELINE_STAGES),
        },
        "timing_semantics": {
            "target": "RiskAnalysisPipeline.run() only",
            "clock": "time.perf_counter_ns",
            "events_are_non_overlapping": True,
            "raw_event_unit": "nanoseconds",
            "comparable_to_uninstrumented_latency_baseline": False,
            "unattributed_definition": "pipeline_elapsed_ns - sum(stage elapsed_ns)",
        },
        "environment": _environment_metadata(),
        "raster_dataset": {
            "directory": str(raster_dir),
            "files": _raster_metadata(raster_dir),
        },
        "pipeline_stage_timing": {
            "scenarios": scenarios,
            "raw_samples": samples,
            "summaries": _pipeline_stage_summaries(samples),
        },
    }
    paths = {
        "json": output_dir / "risk-pipeline-stage-timing.json",
        "markdown": output_dir / "risk-pipeline-stage-timing.md",
    }
    paths["json"].write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["markdown"].write_text(_stage_timing_markdown(result), encoding="utf-8")
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
    mode.add_argument("--pipeline-stage-timing", action="store_true")
    parser.add_argument("--production-candidate-sha")
    parser.add_argument("--production-candidate-is-ancestor", action="store_true")
    parser.add_argument("--diagnostic-source-tree-verified", action="store_true")
    parser.add_argument("--allowed-diagnostic-path", action="append")
    parser.add_argument("--diagnostic-difference", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.pipeline_stage_timing:
        if args.production_candidate_sha is None or args.allowed_diagnostic_path is None:
            raise ValueError(
                "pipeline stage timing 需要 production candidate 和 diagnostic allowlist"
            )
        result, paths = run_pipeline_stage_timing(
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
        print(f"[INFO] stage timing elapsed: {result['benchmark_elapsed_seconds']:.3f}s")
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
