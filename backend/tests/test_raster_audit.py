from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.gis.indicators import IndicatorDefinition
from app.gis.raster_audit import audit_raster_directory


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    transform=None,
    crs: str = "EPSG:4326",
    nodata: float = -9999.0,
) -> None:
    transform = transform or from_origin(118.9, 32.2, 0.001, 0.001)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def _catalog(*names: str) -> tuple[IndicatorDefinition, ...]:
    return tuple(
        IndicatorDefinition(
            code=name,
            name=name,
            filename=f"{name}.tif",
            category="environment",
            risk_direction="increasing",
            risk_semantics="测试指标值越高，风险贡献越高。",
        )
        for name in names
    )


def test_full_audit_reports_aligned_normalized_rasters(tmp_path: Path):
    values_a = np.array([[0.2, 0.4], [0.6, 0.8]], dtype="float32")
    values_b = np.array([[0.1, 0.3], [0.5, 0.7]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values_a)
    _write_raster(tmp_path / "b.tif", values_b)

    manifest = audit_raster_directory(
        tmp_path,
        mode="full",
        indicators=_catalog("a", "b"),
    )

    assert manifest.all_expected_files_present is True
    assert manifest.all_rasters_readable is True
    assert manifest.all_rasters_aligned is True
    assert manifest.common_crs == "EPSG:4326"
    assert manifest.normalized_range_check == "passed"
    assert manifest.rasters[0].stats is not None
    assert manifest.rasters[0].stats.minimum == pytest.approx(0.2)
    assert manifest.rasters[0].stats.maximum == pytest.approx(0.8)
    assert manifest.rasters[0].stats.mean == pytest.approx(0.5)


def test_same_crs_and_resolution_but_shifted_origin_is_not_aligned(tmp_path: Path):
    values = np.full((4, 4), 0.5, dtype="float32")
    _write_raster(tmp_path / "a.tif", values)
    _write_raster(
        tmp_path / "b.tif",
        values,
        transform=from_origin(118.9005, 32.2, 0.001, 0.001),
    )

    manifest = audit_raster_directory(
        tmp_path,
        mode="full",
        indicators=_catalog("a", "b"),
    )

    assert manifest.common_crs == "EPSG:4326"
    assert manifest.rasters[1].alignment is not None
    assert manifest.rasters[1].alignment.resolution_match is True
    assert manifest.rasters[1].alignment.transform_match is False
    assert manifest.rasters[1].alignment.aligned is False
    assert manifest.all_rasters_aligned is False


def test_full_audit_detects_values_outside_normalized_range(tmp_path: Path):
    values = np.array([[-0.1, 0.2], [0.8, 1.2]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values)

    manifest = audit_raster_directory(
        tmp_path,
        mode="full",
        indicators=_catalog("a"),
    )

    stats = manifest.rasters[0].stats
    assert stats is not None
    assert stats.below_expected_min_count == 1
    assert stats.above_expected_max_count == 1
    assert stats.within_expected_range is False
    assert manifest.normalized_range_check == "failed"


def test_quick_audit_does_not_overclaim_normalization(tmp_path: Path):
    values = np.full((20, 20), 0.5, dtype="float32")
    _write_raster(tmp_path / "a.tif", values)

    manifest = audit_raster_directory(
        tmp_path,
        mode="quick",
        indicators=_catalog("a"),
    )

    assert manifest.rasters[0].stats is not None
    assert manifest.rasters[0].stats.within_expected_range is True
    assert manifest.normalized_range_check == "not-complete"


def test_audit_reports_missing_expected_file_without_crashing(tmp_path: Path):
    _write_raster(tmp_path / "a.tif", np.full((2, 2), 0.5, dtype="float32"))

    manifest = audit_raster_directory(
        tmp_path,
        mode="quick",
        indicators=_catalog("a", "b"),
    )

    assert manifest.found_raster_count == 1
    assert manifest.missing_files == ["b.tif"]
    assert manifest.all_expected_files_present is False
    assert manifest.all_rasters_aligned is None
