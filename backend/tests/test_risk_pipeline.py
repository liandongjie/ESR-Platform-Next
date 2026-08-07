from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Polygon, box

from app.gis.indicators import IndicatorDefinition
from app.gis.risk_models import (
    IndicatorWeight,
    RasterCompatibilityError,
    RiskAnalysisValidationError,
)
from app.gis.risk_pipeline import RiskAnalysisPipeline, write_risk_geotiff


def _write_raster(
    path: Path,
    values: np.ndarray,
    *,
    transform=None,
    nodata: float = -9999.0,
) -> None:
    transform = transform or from_origin(118.0, 32.0, 0.01, 0.01)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
    ) as dataset:
        dataset.write(values.astype("float32"), 1)


def _catalog(*names: str) -> tuple[IndicatorDefinition, ...]:
    return tuple(
        IndicatorDefinition(code=name, name=name, filename=f"{name}.tif") for name in names
    )


def _full_extent() -> Polygon:
    return box(118.0, 31.98, 118.02, 32.0)


def test_weighted_overlay_matches_hand_calculated_values(tmp_path: Path):
    values_a = np.array([[0.2, 0.4], [0.6, 0.8]], dtype="float32")
    values_b = np.array([[0.8, 0.6], [0.4, 0.2]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values_a)
    _write_raster(tmp_path / "b.tif", values_b)

    result = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a", "b")).run(
        geometry=_full_extent(),
        weights=[IndicatorWeight("a", 25.0), IndicatorWeight("b", 75.0)],
    )

    expected = np.array([[0.65, 0.55], [0.45, 0.35]], dtype="float32")
    np.testing.assert_allclose(result.array, expected, rtol=0, atol=1e-6)
    assert result.stats.minimum == pytest.approx(0.35)
    assert result.stats.maximum == pytest.approx(0.65)
    assert result.stats.mean == pytest.approx(0.5)
    assert result.stats.valid_pixel_count == 4


def test_common_valid_mask_keeps_nodata_as_missing_instead_of_zero_risk(tmp_path: Path):
    nodata = -9999.0
    values_a = np.array([[nodata, 0.4], [0.6, 0.8]], dtype="float32")
    values_b = np.array([[0.8, 0.6], [0.4, 0.2]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values_a, nodata=nodata)
    _write_raster(tmp_path / "b.tif", values_b, nodata=nodata)

    result = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a", "b")).run(
        geometry=_full_extent(),
        weights=[IndicatorWeight("a", 50.0), IndicatorWeight("b", 50.0)],
    )

    assert np.isnan(result.array[0, 0])
    np.testing.assert_allclose(
        result.array[~np.isnan(result.array)],
        np.array([0.5, 0.5, 0.5], dtype="float32"),
    )
    assert result.stats.valid_pixel_count == 3


def test_geometry_is_cropped_to_reference_pixel_window(tmp_path: Path):
    values = np.arange(16, dtype="float32").reshape(4, 4) / 15.0
    _write_raster(tmp_path / "a.tif", values)

    result = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a")).run(
        geometry=box(118.010001, 31.970001, 118.029999, 31.989999),
        weights=[IndicatorWeight("a", 100.0)],
    )

    assert result.array.shape == (2, 2)
    np.testing.assert_allclose(result.array, values[1:3, 1:3])
    assert result.transform == from_origin(118.01, 31.99, 0.01, 0.01)


def test_misaligned_source_raster_is_rejected_before_overlay(tmp_path: Path):
    values = np.full((2, 2), 0.5, dtype="float32")
    _write_raster(tmp_path / "a.tif", values)
    _write_raster(
        tmp_path / "b.tif",
        values,
        transform=from_origin(118.005, 32.0, 0.01, 0.01),
    )

    with pytest.raises(RasterCompatibilityError, match="Affine transform"):
        RiskAnalysisPipeline(tmp_path, indicators=_catalog("a", "b")).run(
            geometry=_full_extent(),
            weights=[IndicatorWeight("a", 50.0), IndicatorWeight("b", 50.0)],
        )


@pytest.mark.parametrize(
    ("weights", "message"),
    [
        ([IndicatorWeight("a", 60.0)], "权重总和必须为 100"),
        (
            [IndicatorWeight("a", 50.0), IndicatorWeight("a", 50.0)],
            "指标重复",
        ),
        ([IndicatorWeight("missing", 100.0)], "未知指标"),
        (
            [IndicatorWeight("a", -1.0), IndicatorWeight("b", 101.0)],
            "权重不能为负数",
        ),
        ([IndicatorWeight("a", float("nan"))], "权重必须是有限数字"),
    ],
)
def test_invalid_weights_are_rejected_before_raster_io(
    tmp_path: Path,
    weights: list[IndicatorWeight],
    message: str,
):
    pipeline = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a", "b"))

    with pytest.raises(RiskAnalysisValidationError, match=message):
        pipeline.run(geometry=_full_extent(), weights=weights)


def test_zero_weight_indicator_does_not_constrain_common_valid_mask(tmp_path: Path):
    values = np.full((2, 2), 0.5, dtype="float32")
    _write_raster(tmp_path / "a.tif", values)
    # b.tif intentionally does not exist. A zero-weight indicator must not trigger
    # file I/O or remove otherwise valid pixels from the mathematical result.

    result = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a", "b")).run(
        geometry=_full_extent(),
        weights=[IndicatorWeight("a", 100.0), IndicatorWeight("b", 0.0)],
    )

    np.testing.assert_allclose(result.array, values)
    assert [item.code for item in result.indicators] == ["a"]


def test_invalid_or_out_of_extent_geometry_is_rejected(tmp_path: Path):
    values = np.full((2, 2), 0.5, dtype="float32")
    _write_raster(tmp_path / "a.tif", values)
    pipeline = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a"))

    invalid_polygon = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    with pytest.raises(RiskAnalysisValidationError, match="不是合法"):
        pipeline.run(
            geometry=invalid_polygon,
            weights=[IndicatorWeight("a", 100.0)],
        )

    with pytest.raises(RasterCompatibilityError, match="超出源栅格覆盖范围"):
        pipeline.run(
            geometry=box(117.0, 30.0, 117.1, 30.1),
            weights=[IndicatorWeight("a", 100.0)],
        )


def test_out_of_range_source_value_is_rejected(tmp_path: Path):
    values = np.array([[0.2, 1.2], [0.4, 0.6]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values)

    with pytest.raises(RasterCompatibilityError, match="超出"):
        RiskAnalysisPipeline(tmp_path, indicators=_catalog("a")).run(
            geometry=_full_extent(),
            weights=[IndicatorWeight("a", 100.0)],
        )


def test_written_geotiff_preserves_grid_crs_nodata_and_values(tmp_path: Path):
    values = np.array([[0.2, -9999.0], [0.6, 0.8]], dtype="float32")
    _write_raster(tmp_path / "a.tif", values)
    pipeline = RiskAnalysisPipeline(tmp_path, indicators=_catalog("a"))
    result = pipeline.run(
        geometry=_full_extent(),
        weights=[IndicatorWeight("a", 100.0)],
    )

    output_path = write_risk_geotiff(result, tmp_path / "output" / "risk.tif")

    with rasterio.open(output_path) as dataset:
        written = dataset.read(1, masked=True)
        assert dataset.crs.to_string() == "EPSG:4326"
        assert dataset.transform == result.transform
        assert dataset.nodata == pytest.approx(-9999.0)
        assert written.mask[0, 1]
        np.testing.assert_allclose(written.compressed(), np.array([0.2, 0.6, 0.8]))
