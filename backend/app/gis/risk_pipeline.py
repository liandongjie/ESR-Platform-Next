from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.features import geometry_mask, geometry_window
from rasterio.io import DatasetReader
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.gis.indicators import INDICATORS, IndicatorDefinition
from app.gis.risk_models import (
    IndicatorAnalysis,
    IndicatorWeight,
    RasterCompatibilityError,
    RasterStatistics,
    RiskAnalysisResult,
    RiskAnalysisValidationError,
)

_WEIGHT_SUM_PERCENT = 100.0
_WEIGHT_SUM_ATOL = 1e-6
_GRID_ATOL = 1e-10
_OUTPUT_NODATA = -9999.0

type _StageTimingCallback = Callable[[str, str | None, int], None]


@contextmanager
def _measure_stage(
    callback: _StageTimingCallback | None,
    stage: str,
    indicator_code: str | None = None,
) -> Iterator[None]:
    if callback is None:
        yield
        return

    started = time.perf_counter_ns()
    yield
    callback(stage, indicator_code, time.perf_counter_ns() - started)


def _validate_geometry(geometry: BaseGeometry) -> None:
    """Validate only geometry properties that the raster core can prove locally.

    Business limits such as buffer distance and maximum analysis area belong to the
    research-area phase. Keeping them out of this module prevents the raster engine
    from silently owning product rules that have not yet been verified.
    """

    if geometry.is_empty:
        raise RiskAnalysisValidationError("研究区 geometry 不能为空")
    if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        raise RiskAnalysisValidationError(
            "研究区 geometry 必须是 Polygon 或 MultiPolygon"
        )
    if not geometry.is_valid:
        raise RiskAnalysisValidationError(
            "研究区 geometry 不是合法的 Polygon/MultiPolygon"
        )


def _validate_weights(
    weights: Sequence[IndicatorWeight],
    indicator_by_code: dict[str, IndicatorDefinition],
) -> tuple[IndicatorWeight, ...]:
    """Validate the business weight contract before any raster file is opened."""

    if not weights:
        raise RiskAnalysisValidationError("至少需要选择一个风险指标")

    seen_codes: set[str] = set()
    validated: list[IndicatorWeight] = []
    total = 0.0

    for item in weights:
        if item.code in seen_codes:
            raise RiskAnalysisValidationError(f"指标重复: {item.code}")
        seen_codes.add(item.code)

        if item.code not in indicator_by_code:
            raise RiskAnalysisValidationError(f"未知指标: {item.code}")

        try:
            weight = float(item.weight_percent)
        except (TypeError, ValueError) as exc:
            raise RiskAnalysisValidationError(
                f"指标 {item.code} 的权重不是合法数字"
            ) from exc

        if not math.isfinite(weight):
            raise RiskAnalysisValidationError(f"指标 {item.code} 的权重必须是有限数字")
        if weight < 0:
            raise RiskAnalysisValidationError(f"指标 {item.code} 的权重不能为负数")

        validated.append(IndicatorWeight(code=item.code, weight_percent=weight))
        total += weight

    if not math.isclose(
        total, _WEIGHT_SUM_PERCENT, rel_tol=0.0, abs_tol=_WEIGHT_SUM_ATOL
    ):
        raise RiskAnalysisValidationError(f"指标权重总和必须为 100，当前为 {total:g}")

    # A zero-weight indicator has no mathematical contribution. Excluding it from
    # raster I/O also prevents its NoData mask from incorrectly removing pixels from
    # the result. The original request is still validated above, including its code.
    active = tuple(item for item in validated if item.weight_percent > 0)
    if not active:
        raise RiskAnalysisValidationError("至少需要一个权重大于 0 的指标")
    return active


def _same_transform(left, right) -> bool:
    return bool(
        np.allclose(
            tuple(left)[:6],
            tuple(right)[:6],
            rtol=0.0,
            atol=_GRID_ATOL,
        )
    )


def _assert_compatible_grid(dataset: DatasetReader, reference: DatasetReader) -> None:
    """Reject implicit reprojection/resampling by requiring one identical pixel grid."""

    if dataset.crs != reference.crs:
        raise RasterCompatibilityError(
            f"栅格 {Path(dataset.name).name} 的 CRS 与参考栅格不一致"
        )
    if dataset.width != reference.width or dataset.height != reference.height:
        raise RasterCompatibilityError(
            f"栅格 {Path(dataset.name).name} 的 width/height 与参考栅格不一致"
        )
    if not _same_transform(dataset.transform, reference.transform):
        raise RasterCompatibilityError(
            f"栅格 {Path(dataset.name).name} 的 Affine transform 与参考栅格不一致"
        )


def _stats(values: np.ndarray) -> RasterStatistics:
    if values.size == 0:
        raise RasterCompatibilityError("研究区内没有可用于统计的有效像元")
    return RasterStatistics(
        valid_pixel_count=int(values.size),
        minimum=float(values.min()),
        maximum=float(values.max()),
        mean=float(values.mean(dtype=np.float64)),
    )


def _analysis_window(reference: DatasetReader, geometry: BaseGeometry) -> Window:
    raster_crs = reference.crs
    if raster_crs is None:
        raise RasterCompatibilityError("参考栅格缺少 CRS，无法进行空间裁剪")

    expected_crs = CRS.from_epsg(4326)
    if raster_crs != expected_crs:
        raise RasterCompatibilityError(
            f"当前管线要求 EPSG:4326 源栅格，实际为 {raster_crs.to_string()}"
        )

    raster_bounds = reference.bounds
    left, bottom, right, top = geometry.bounds
    if (
        left < raster_bounds.left
        or bottom < raster_bounds.bottom
        or right > raster_bounds.right
        or top > raster_bounds.top
    ):
        # Do not silently return a partial analysis when the requested study area
        # extends outside the available raster rectangle.
        raise RasterCompatibilityError("研究区超出源栅格覆盖范围")

    try:
        window = geometry_window(reference, [mapping(geometry)])
    except Exception as exc:  # rasterio raises WindowError for non-overlap
        raise RasterCompatibilityError("研究区与源栅格没有有效空间交集") from exc

    # geometry_window normally returns integer offsets/sizes; rounding here makes
    # that contract explicit before the same window is reused across all rasters.
    return window.round_offsets().round_lengths()


class RiskAnalysisPipeline:
    """Deterministic weighted-overlay engine for already-normalized source rasters.

    This class deliberately has no Flask, database, Celery or HTTP dependency. The
    algorithm must be independently testable before asynchronous task orchestration
    is added around it in a later phase.
    """

    def __init__(
        self,
        raster_dir: Path,
        *,
        indicators: Sequence[IndicatorDefinition] = INDICATORS,
    ) -> None:
        self.raster_dir = Path(raster_dir).expanduser().resolve()
        self.indicators = tuple(indicators)
        self.indicator_by_code = {
            indicator.code: indicator for indicator in self.indicators
        }

        if len(self.indicator_by_code) != len(self.indicators):
            raise ValueError("指标目录中存在重复 code")

    def run(
        self,
        *,
        geometry: BaseGeometry,
        weights: Sequence[IndicatorWeight],
        _stage_timing_callback: _StageTimingCallback | None = None,
    ) -> RiskAnalysisResult:
        with _measure_stage(_stage_timing_callback, "input_validation"):
            _validate_geometry(geometry)
            active_weights = _validate_weights(weights, self.indicator_by_code)

            if not self.raster_dir.is_dir():
                raise RasterCompatibilityError(f"栅格目录不存在: {self.raster_dir}")

        with ExitStack() as stack:
            opened: list[tuple[IndicatorDefinition, IndicatorWeight, DatasetReader]] = (
                []
            )
            for item in active_weights:
                definition = self.indicator_by_code[item.code]
                with _measure_stage(
                    _stage_timing_callback, "source_open", definition.code
                ):
                    path = self.raster_dir / definition.filename
                    if not path.is_file():
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 对应的栅格文件不存在: {path}"
                        )

                    try:
                        dataset = stack.enter_context(rasterio.open(path))
                    except Exception as exc:
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 的栅格无法读取: {path}"
                        ) from exc

                    if dataset.count != 1:
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 必须是单波段栅格，实际为 {dataset.count} 波段"
                        )
                    opened.append((definition, item, dataset))

            with _measure_stage(_stage_timing_callback, "grid_validation"):
                reference = opened[0][2]
                for _, _, dataset in opened[1:]:
                    _assert_compatible_grid(dataset, reference)

            with _measure_stage(_stage_timing_callback, "window_geometry_setup"):
                window = _analysis_window(reference, geometry)
                out_transform = window_transform(window, reference.transform)
                out_shape = (int(window.height), int(window.width))

                # Geometry masking is computed once on the reference grid and reused for
                # all aligned rasters. ``all_touched=False`` matches Rasterio's default:
                # a pixel participates when its centre is inside the polygon.
                inside_geometry = geometry_mask(
                    [mapping(geometry)],
                    out_shape=out_shape,
                    transform=out_transform,
                    invert=True,
                    all_touched=False,
                )
                if not inside_geometry.any():
                    raise RasterCompatibilityError("研究区没有覆盖任何栅格像元中心")

                weighted_sum = np.zeros(out_shape, dtype=np.float64)
                common_valid_mask = inside_geometry.copy()
                indicator_results: list[IndicatorAnalysis] = []

            for definition, item, dataset in opened:
                with _measure_stage(
                    _stage_timing_callback, "raster_read", definition.code
                ):
                    band = dataset.read(1, window=window, masked=True)

                with _measure_stage(
                    _stage_timing_callback, "mask_preparation", definition.code
                ):
                    data = np.asarray(band.filled(np.nan), dtype=np.float64)
                    source_mask = np.ma.getmaskarray(band)
                    finite_mask = np.isfinite(data)
                    valid_mask = inside_geometry & ~source_mask & finite_mask

                    # NaN/Inf that are not explicitly masked are treated as corrupted
                    # normalized data, not as ordinary NoData.
                    invalid_finite = inside_geometry & ~source_mask & ~finite_mask
                    if invalid_finite.any():
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 在研究区内存在未屏蔽的 NaN/Inf"
                        )

                with _measure_stage(
                    _stage_timing_callback,
                    "value_validation_and_stats",
                    definition.code,
                ):
                    values = data[valid_mask]
                    if values.size == 0:
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 在研究区内没有有效像元"
                        )

                    below = values < definition.expected_min
                    above = values > definition.expected_max
                    if below.any() or above.any():
                        raise RasterCompatibilityError(
                            f"指标 {definition.code} 在研究区内存在超出 "
                            f"[{definition.expected_min}, {definition.expected_max}] 的值"
                        )

                    indicator_results.append(
                        IndicatorAnalysis(
                            code=definition.code,
                            name=definition.name,
                            weight_percent=item.weight_percent,
                            stats=_stats(values),
                        )
                    )

                with _measure_stage(
                    _stage_timing_callback, "weighted_accumulation", definition.code
                ):
                    # Invalid pixels are temporarily treated as zero only for the
                    # accumulation step; ``common_valid_mask`` removes them from the
                    # final result, so missing data can never become "zero risk".
                    weighted_sum[valid_mask] += values * (item.weight_percent / 100.0)
                    common_valid_mask &= valid_mask

            with _measure_stage(_stage_timing_callback, "result_finalization"):
                if not common_valid_mask.any():
                    raise RasterCompatibilityError("所选指标在研究区内没有共同有效像元")

                result_values = weighted_sum[common_valid_mask]
                # With non-negative weights summing to 100 and normalized [0,1] inputs,
                # the weighted result should stay in [0,1]. Allow only floating noise.
                if result_values.min() < -1e-12 or result_values.max() > 1.0 + 1e-12:
                    raise RasterCompatibilityError("综合风险结果超出预期的 [0,1] 范围")

                result_array = np.full(out_shape, np.nan, dtype=np.float32)
                result_array[common_valid_mask] = result_values.astype(np.float32)

                return RiskAnalysisResult(
                    array=result_array,
                    transform=out_transform,
                    crs=reference.crs,
                    stats=_stats(result_values),
                    indicators=tuple(indicator_results),
                    nodata=_OUTPUT_NODATA,
                )


def write_risk_geotiff(result: RiskAnalysisResult, output_path: Path) -> Path:
    """Persist a pipeline result without changing its grid, CRS or valid pixels."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = np.where(np.isfinite(result.array), result.array, result.nodata).astype(
        "float32"
    )
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        width=data.shape[1],
        height=data.shape[0],
        count=1,
        dtype="float32",
        crs=result.crs,
        transform=result.transform,
        nodata=result.nodata,
    ) as dataset:
        dataset.write(data, 1)

    return output_path
