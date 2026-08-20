from __future__ import annotations

import csv
import inspect
import json
import pstats
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.gis.indicators import INDICATORS
from app.gis.risk_benchmark import (
    ALLOWED_BENCHMARK_PATHS,
    BASELINE_SHA,
    COMPUTE_SIZES,
    DEFAULT_RUNS,
    DEFAULT_WARMUPS,
    INDICATOR_GROUPS,
    PIPELINE_PROFILE_SIZE,
    PIPELINE_PROFILE_TOP_N,
    SOURCE_TREE_VERIFICATION_METHOD,
    SPATIAL_SIZES,
    VALIDATION_INCLUDED_IN_TOTAL_SERVICE,
    VALIDATION_TIMING,
    _verified_provenance,
    run_benchmark,
    run_pipeline_profile,
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
    assert ALLOWED_BENCHMARK_PATHS == (
        "backend/app/gis/risk_benchmark.py",
        "backend/tests/test_risk_benchmark.py",
        "scripts/benchmark-risk-analysis.ps1",
        "docs/performance/",
    )


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
