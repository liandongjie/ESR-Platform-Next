from __future__ import annotations

import csv
import inspect
import json
import pstats
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from app.gis.indicators import INDICATORS
from app.gis.risk_benchmark import (
    ALLOWED_BENCHMARK_PATHS,
    ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
    BASELINE_SHA,
    COMPUTE_SIZES,
    DEFAULT_RUNS,
    DEFAULT_WARMUPS,
    INDICATOR_GROUPS,
    PIPELINE_PROFILE_SIZE,
    PIPELINE_PROFILE_TOP_N,
    PIPELINE_STAGE_TIMING_SIZE,
    PIPELINE_STAGES,
    PRODUCTION_CANDIDATE_SHA,
    RASTER_READ_ATTRIBUTION_SIZE,
    RASTER_READ_CACHE_SEMANTICS,
    RASTER_READ_MODES,
    SOURCE_TREE_VERIFICATION_METHOD,
    SPATIAL_SIZES,
    VALIDATION_INCLUDED_IN_TOTAL_SERVICE,
    VALIDATION_TIMING,
    _parse_args,
    _verified_instrumentation_lineage,
    _verified_provenance,
    _window_block_metrics,
    run_benchmark,
    run_pipeline_profile,
    run_pipeline_stage_timing,
    run_raster_read_attribution,
    write_reports,
)


def _write_catalog_rasters(raster_dir: Path) -> None:
    raster_dir.mkdir()
    values = np.full((4, 4), 0.5, dtype="float32")
    for indicator in INDICATORS:
        with rasterio.open(
            raster_dir / indicator.filename,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=from_origin(118.88, 32.12, 0.01, 0.01),
            nodata=-9999.0,
        ) as dataset:
            dataset.write(values, 1)


def test_benchmark_keeps_raw_samples_and_writes_all_reports(tmp_path: Path):
    raster_dir = tmp_path / "rasters"
    _write_catalog_rasters(raster_dir)

    result = run_benchmark(
        raster_dir=raster_dir,
        repository_head_sha=BASELINE_SHA,
        source_tree_verified=True,
        baseline_is_ancestor=True,
        tracked_differences=("M:backend/app/gis/risk_benchmark.py",),
        untracked_paths=("docs/performance/result.json",),
        warmups=0,
        runs=1,
        compute_sizes={"tiny": 2},
        spatial_sizes={"tiny": 2},
    )
    paths = write_reports(result, tmp_path / "reports")

    assert len(result["compute"]["raw_samples"]) == 3
    assert len(result["spatial"]["raw_samples"]) == 1
    assert all(sample["window_cells"] == 4 for sample in result["compute"]["raw_samples"])
    assert all(sample["valid_cells"] == 4 for sample in result["compute"]["raw_samples"])
    assert all(
        sample["validation_timing"] == "standalone_post_execute_warm_cache"
        and sample["validation_included_in_total_service"] is False
        for sample in result["compute"]["raw_samples"]
    )
    spatial = result["spatial"]["raw_samples"][0]
    assert spatial["feature_count"] == 4
    assert spatial["response_bytes"] > 0
    assert result["subject_baseline_sha"] == BASELINE_SHA
    assert result["source_provenance"] == {
        "subject_baseline_sha": BASELINE_SHA,
        "repository_head_sha": BASELINE_SHA,
        "source_tree_verification_method": SOURCE_TREE_VERIFICATION_METHOD,
        "source_tree_verified": True,
        "baseline_is_head_ancestor": True,
        "allowed_benchmark_paths": list(ALLOWED_BENCHMARK_PATHS),
        "detected_allowed_diff_paths": [
            "backend/app/gis/risk_benchmark.py",
            "docs/performance/result.json",
        ],
        "tracked_differences": [
            {"status": "M", "path": "backend/app/gis/risk_benchmark.py"}
        ],
        "untracked_paths": ["docs/performance/result.json"],
    }
    assert len(result["raster_dataset"]["files"]) == 12
    assert all(len(record["sha256"]) == 64 for record in result["raster_dataset"]["files"])

    persisted = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert persisted["compute"]["raw_samples"] == result["compute"]["raw_samples"]
    with paths["csv"].open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 4
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "standalone_post_execute_warm_cache" in markdown
    assert "not a decomposition of service time" in markdown
    assert "Repository HEAD" in markdown
    assert "Repository HEAD may be newer" in markdown
    assert SOURCE_TREE_VERIFICATION_METHOD in markdown


def test_formal_p3a_benchmark_contract_is_locked():
    assert BASELINE_SHA == "5810240e14d1d5a86562d73d6b85f2cdd2083cc4"
    assert PRODUCTION_CANDIDATE_SHA == "8f85c420dcc07edbcbf03674478b973c108e6746"
    assert COMPUTE_SIZES == {"small": 128, "medium": 384, "large": 1024}
    assert SPATIAL_SIZES == {"small": 32, "medium": 64, "large": 128}
    assert INDICATOR_GROUPS == {
        3: ("PM25", "AQI", "NDVI"),
        6: ("PM25", "AQI", "NDVI", "rkmd", "gyfb", "fmyl"),
        12: tuple(indicator.code for indicator in INDICATORS),
    }
    assert DEFAULT_WARMUPS == 1
    assert DEFAULT_RUNS == 5
    assert inspect.signature(run_benchmark).parameters["warmups"].default == 1
    assert inspect.signature(run_benchmark).parameters["runs"].default == 5
    assert VALIDATION_TIMING == "standalone_post_execute_warm_cache"
    assert VALIDATION_INCLUDED_IN_TOTAL_SERVICE is False
    assert PIPELINE_PROFILE_SIZE == 1024
    assert PIPELINE_PROFILE_TOP_N == 30
    assert inspect.signature(run_pipeline_profile).parameters["warmups"].default == 1
    assert inspect.signature(run_pipeline_profile).parameters["runs"].default == 5
    assert inspect.signature(run_pipeline_profile).parameters["size"].default == 1024
    assert PIPELINE_STAGE_TIMING_SIZE == 1024
    assert inspect.signature(run_pipeline_stage_timing).parameters["warmups"].default == 1
    assert inspect.signature(run_pipeline_stage_timing).parameters["runs"].default == 5
    assert inspect.signature(run_pipeline_stage_timing).parameters["size"].default == 1024
    assert RASTER_READ_ATTRIBUTION_SIZE == 1024
    assert inspect.signature(run_raster_read_attribution).parameters["warmups"].default == 1
    assert inspect.signature(run_raster_read_attribution).parameters["runs"].default == 5
    assert inspect.signature(run_raster_read_attribution).parameters["size"].default == 1024
    assert RASTER_READ_MODES == (
        "open_only",
        "masked_read_new_handle",
        "masked_reread_same_handle",
        "data_read",
        "mask_read",
        "data_plus_mask",
    )
    assert RASTER_READ_CACHE_SEMANTICS == (
        "warm_process_and_os_cache_not_explicitly_flushed"
    )
    assert PIPELINE_STAGES == (
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
    assert ALLOWED_BENCHMARK_PATHS == (
        "backend/app/gis/risk_benchmark.py",
        "backend/tests/test_risk_benchmark.py",
        "scripts/benchmark-risk-analysis.ps1",
        "docs/performance/",
    )
    assert ALLOWED_PIPELINE_DIAGNOSTIC_PATHS == (
        "backend/app/gis/risk_pipeline.py",
        "backend/tests/test_risk_pipeline.py",
        *ALLOWED_BENCHMARK_PATHS,
    )


def test_window_block_metrics_cover_aligned_and_unaligned_windows():
    aligned = _window_block_metrics(Window(128, 128, 256, 256), (128, 128), "float32")
    assert aligned == {
        "touched_block_count": 4,
        "estimated_decoded_cells": 65536,
        "estimated_uncompressed_bytes": 262144,
        "read_amplification_ratio": 1.0,
    }
    unaligned = _window_block_metrics(Window(1, 1, 128, 128), (128, 128), "float32")
    assert unaligned == {
        "touched_block_count": 4,
        "estimated_decoded_cells": 65536,
        "estimated_uncompressed_bytes": 262144,
        "read_amplification_ratio": 4.0,
    }


def test_raster_read_attribution_keeps_raw_samples_and_reports(tmp_path: Path):
    raster_dir = tmp_path / "rasters"
    _write_catalog_rasters(raster_dir)
    diagnostic_sha = "2" * 40

    result, paths = run_raster_read_attribution(
        raster_dir=raster_dir,
        output_dir=tmp_path / "read-attribution",
        subject_baseline_sha=diagnostic_sha,
        repository_head_sha=diagnostic_sha,
        source_tree_verified=True,
        baseline_is_ancestor=True,
        production_candidate_is_ancestor=True,
        diagnostic_source_tree_verified=True,
        diagnostic_differences=("M:backend/app/gis/risk_benchmark.py",),
        warmups=0,
        runs=1,
        size=2,
    )

    assert result["benchmark"] == "risk-raster-read-attribution"
    assert result["production_candidate_sha"] == PRODUCTION_CANDIDATE_SHA
    assert result["diagnostic_subject_sha"] == diagnostic_sha
    assert result["configuration"] == {
        "warmups_per_mode": 0,
        "measured_runs_per_mode": 1,
        "window_size": 2,
        "indicator_codes": [indicator.code for indicator in INDICATORS],
        "modes": list(RASTER_READ_MODES),
        "measured_sample_count": 72,
    }
    assert result["timing_semantics"]["cache_state"] == RASTER_READ_CACHE_SEMANTICS
    assert result["timing_semantics"]["physical_cold_disk_claimed"] is False
    assert result["gdal_runtime"]["version"]
    scenarios = result["raster_read_attribution"]["scenarios"]
    samples = result["raster_read_attribution"]["raw_samples"]
    assert len(scenarios) == 12
    assert len(samples) == 72
    assert len(result["raster_read_attribution"]["summaries"]) == 12
    assert all(scenario["read_equivalence"]["equivalent"] for scenario in scenarios)
    assert all(
        sample["rows"] == 2
        and sample["cols"] == 2
        and sample["window_cells"] == 4
        and isinstance(sample["elapsed_ns"], int)
        and sample["elapsed_ns"] >= 0
        for sample in samples
    )
    assert {(sample["indicator_code"], sample["mode"]) for sample in samples} == {
        (indicator.code, mode) for indicator in INDICATORS for mode in RASTER_READ_MODES
    }
    persisted = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert persisted["raster_read_attribution"]["raw_samples"] == samples
    with paths["csv"].open(encoding="utf-8", newline="") as stream:
        assert len(list(csv.DictReader(stream))) == 72
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Windows OS cache is not flushed" in markdown
    assert "Masked/new" in markdown
    assert "Raw nanosecond samples" in markdown


def test_pipeline_stage_timing_keeps_raw_events_and_reports(tmp_path: Path):
    raster_dir = tmp_path / "rasters"
    _write_catalog_rasters(raster_dir)
    instrumented_sha = "2" * 40

    result, paths = run_pipeline_stage_timing(
        raster_dir=raster_dir,
        output_dir=tmp_path / "stage-timing",
        subject_baseline_sha=instrumented_sha,
        repository_head_sha=instrumented_sha,
        source_tree_verified=True,
        baseline_is_ancestor=True,
        production_candidate_is_ancestor=True,
        diagnostic_source_tree_verified=True,
        diagnostic_differences=("M:backend/app/gis/risk_pipeline.py",),
        warmups=0,
        runs=1,
        size=2,
    )

    assert result["benchmark"] == "risk-analysis-pipeline-stage-timing"
    assert result["production_candidate_sha"] == PRODUCTION_CANDIDATE_SHA
    assert result["instrumented_subject_sha"] == instrumented_sha
    assert result["configuration"] == {
        "warmups_per_scenario": 0,
        "measured_runs_per_scenario": 1,
        "stage_timing_size": 2,
        "indicator_groups": {
            "3": ["PM25", "AQI", "NDVI"],
            "6": ["PM25", "AQI", "NDVI", "rkmd", "gyfb", "fmyl"],
            "12": [indicator.code for indicator in INDICATORS],
        },
        "stages": list(PIPELINE_STAGES),
    }
    samples = result["pipeline_stage_timing"]["raw_samples"]
    assert len(samples) == 3
    for sample in samples:
        assert sample["rows"] == 2
        assert sample["cols"] == 2
        assert sample["window_cells"] == 4
        assert sample["valid_cells"] == 4
        assert sample["output_statistics"] == pytest.approx(
            {"minimum": 0.5, "maximum": 0.5, "mean": 0.5}
        )
        assert len(sample["stage_events"]) == 4 + 5 * sample["indicator_count"]
        assert all(event["elapsed_ns"] >= 0 for event in sample["stage_events"])
        assert sample["attributed_ns"] <= sample["pipeline_elapsed_ns"]
        assert sample["unattributed_ns"] == (
            sample["pipeline_elapsed_ns"] - sample["attributed_ns"]
        )
    assert len(result["pipeline_stage_timing"]["summaries"]) == 3
    assert len(result["raster_dataset"]["files"]) == 12
    persisted = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert persisted["pipeline_stage_timing"]["raw_samples"] == samples
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Production candidate" in markdown
    assert "Instrumented subject" in markdown
    assert "unattributed" in markdown
    assert "diagnostic and is not a replacement latency baseline" in markdown


def test_pipeline_diagnostic_lineage_contract():
    instrumented_sha = "2" * 40
    lineage = _verified_instrumentation_lineage(
        PRODUCTION_CANDIDATE_SHA,
        instrumented_sha,
        True,
        True,
        ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
        (
            "M:backend/app/gis/risk_pipeline.py",
            "M:backend/tests/test_risk_pipeline.py",
            "A:docs/performance/p3b-pipeline-stage-timing/result.json",
        ),
    )
    assert lineage["production_candidate_sha"] == PRODUCTION_CANDIDATE_SHA
    assert lineage["instrumented_subject_sha"] == instrumented_sha
    assert lineage["diagnostic_source_tree_verified"] is True

    with pytest.raises(ValueError, match="ancestor"):
        _verified_instrumentation_lineage(
            PRODUCTION_CANDIDATE_SHA,
            instrumented_sha,
            False,
            True,
            ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
            (),
        )
    with pytest.raises(ValueError, match="非 diagnostic"):
        _verified_instrumentation_lineage(
            PRODUCTION_CANDIDATE_SHA,
            instrumented_sha,
            True,
            True,
            ALLOWED_PIPELINE_DIAGNOSTIC_PATHS,
            ("M:backend/app/services/risk_analysis_jobs.py",),
        )


@pytest.mark.parametrize(
    "modes",
    [
        ("--pipeline-profile", "--pipeline-stage-timing"),
        ("--pipeline-profile", "--pipeline-read-attribution"),
        ("--pipeline-stage-timing", "--pipeline-read-attribution"),
    ],
)
def test_pipeline_profile_modes_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
    modes: tuple[str, str],
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "risk-benchmark",
            "--raster-dir",
            "rasters",
            "--output-dir",
            "reports",
            "--repository-head-sha",
            BASELINE_SHA,
            "--source-tree-verification-method",
            SOURCE_TREE_VERIFICATION_METHOD,
            "--source-tree-verified",
            "--baseline-is-ancestor",
            "--allowed-benchmark-path",
            ALLOWED_BENCHMARK_PATHS[0],
            *modes,
        ],
    )
    with pytest.raises(SystemExit):
        _parse_args()


def test_pipeline_profile_keeps_raw_samples_and_writes_loadable_profiles(tmp_path: Path):
    raster_dir = tmp_path / "rasters"
    _write_catalog_rasters(raster_dir)

    result, paths = run_pipeline_profile(
        raster_dir=raster_dir,
        output_dir=tmp_path / "profiles",
        repository_head_sha=BASELINE_SHA,
        source_tree_verified=True,
        baseline_is_ancestor=True,
        warmups=0,
        runs=1,
        size=2,
        top_n=5,
    )

    assert result["benchmark"] == "risk-analysis-pipeline-cprofile"
    assert result["configuration"] == {
        "warmups_per_scenario": 0,
        "measured_runs_per_scenario": 1,
        "profile_size": 2,
        "indicator_groups": {
            "3": ["PM25", "AQI", "NDVI"],
            "6": ["PM25", "AQI", "NDVI", "rkmd", "gyfb", "fmyl"],
            "12": [indicator.code for indicator in INDICATORS],
        },
        "top_entries_per_sort": 5,
    }
    assert result["profiling_semantics"]["wall_time_includes_profiler_overhead"] is True
    assert result["profiling_semantics"]["wall_time_comparable_to_unprofiled_benchmark"] is False
    assert len(result["pipeline_profile"]["raw_samples"]) == 3
    assert all(
        sample["rows"] == 2
        and sample["cols"] == 2
        and sample["valid_cells"] == 4
        and sample["profiled_pipeline_elapsed_ms"] >= 0
        for sample in result["pipeline_profile"]["raw_samples"]
    )
    assert len(result["raster_dataset"]["files"]) == 12
    for count in (3, 6, 12):
        profile_path = paths[f"profile_{count}"]
        stats = pstats.Stats(str(profile_path))
        assert stats.total_calls > 0
        scenario = next(
            item
            for item in result["pipeline_profile"]["scenarios"]
            if item["indicator_count"] == count
        )
        assert any(entry["function"] == "run" for entry in scenario["top_cumulative"])
        assert all(entry["self_seconds"] >= 0 for entry in scenario["top_self"])
    persisted = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert persisted["pipeline_profile"]["raw_samples"] == result["pipeline_profile"][
        "raw_samples"
    ]
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "cProfile overhead" in markdown
    assert "must not be compared with baseline latency" in markdown


@pytest.mark.parametrize(
    (
        "case",
        "repository_head_sha",
        "baseline_is_ancestor",
        "tracked_differences",
        "untracked_paths",
        "should_pass",
    ),
    [
        (
            "baseline-and-benchmark-only-differences",
            BASELINE_SHA,
            True,
            ("M:backend/app/gis/risk_benchmark.py",),
            ("docs/performance/result.json",),
            True,
        ),
        (
            "production-tracked-modification",
            BASELINE_SHA,
            True,
            ("M:backend/app/gis/risk_pipeline.py",),
            (),
            False,
        ),
        (
            "production-staged-or-unstaged-difference",
            BASELINE_SHA,
            True,
            ("M:backend/pyproject.toml",),
            (),
            False,
        ),
        (
            "production-committed-difference",
            "1" * 40,
            True,
            ("M:docker-compose.yml",),
            (),
            False,
        ),
        (
            "non-allowed-untracked-file",
            BASELINE_SHA,
            True,
            (),
            ("docs/performance_extra/result.json",),
            False,
        ),
        (
            "committed-benchmark-harness-above-baseline",
            "1" * 40,
            True,
            (
                "A:backend/app/gis/risk_benchmark.py",
                "A:backend/tests/test_risk_benchmark.py",
            ),
            (),
            True,
        ),
        (
            "production-rename-or-delete",
            "1" * 40,
            True,
            (
                "D:backend/app/gis/risk_pipeline.py",
                "A:backend/app/gis/risk_pipeline_renamed.py",
            ),
            (),
            False,
        ),
        (
            "baseline-not-head-ancestor",
            "1" * 40,
            False,
            (),
            (),
            False,
        ),
    ],
)
def test_source_tree_provenance_contract(
    case: str,
    repository_head_sha: str,
    baseline_is_ancestor: bool,
    tracked_differences: tuple[str, ...],
    untracked_paths: tuple[str, ...],
    should_pass: bool,
):
    arguments = {
        "subject_baseline_sha": BASELINE_SHA,
        "repository_head_sha": repository_head_sha,
        "verification_method": SOURCE_TREE_VERIFICATION_METHOD,
        "source_tree_verified": True,
        "baseline_is_ancestor": baseline_is_ancestor,
        "allowed_benchmark_paths": ALLOWED_BENCHMARK_PATHS,
        "tracked_differences": tracked_differences,
        "untracked_paths": untracked_paths,
    }
    if should_pass:
        provenance = _verified_provenance(**arguments)
        assert provenance["source_tree_verified"] is True, case
    else:
        with pytest.raises(ValueError):
            _verified_provenance(**arguments)
