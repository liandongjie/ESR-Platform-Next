from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import MaskFlags
from rasterio.io import DatasetReader
from rasterio.windows import Window

from app.gis.indicators import INDICATORS, IndicatorDefinition
from app.gis.raster_manifest import (
    RasterAlignment,
    RasterAuditManifest,
    RasterRecord,
    RasterSampleStats,
)

_FLOAT_ATOL = 1e-10


def _normalise_crs(dataset: DatasetReader) -> str | None:
    if dataset.crs is None:
        return None
    epsg = dataset.crs.to_epsg()
    return f"EPSG:{epsg}" if epsg is not None else dataset.crs.to_string()




def _serialise_nodata(value: float | None) -> float | str | None:
    if value is None:
        return None
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def _transform_values(transform: Affine) -> list[float]:
    return [float(value) for value in transform[:6]]


def _quick_windows(width: int, height: int, tile_size: int = 256) -> list[Window]:
    """Return deterministic windows covering corners, edges and centre.

    Quick mode is intentionally a sample. Nine windows distribute reads over the
    raster instead of inspecting only the upper-left corner, while keeping the
    audit cheap enough to run repeatedly during development.
    """

    tile_width = min(tile_size, width)
    tile_height = min(tile_size, height)

    max_col = max(width - tile_width, 0)
    max_row = max(height - tile_height, 0)
    cols = sorted({0, max_col // 2, max_col})
    rows = sorted({0, max_row // 2, max_row})

    return [
        Window(col_off=col, row_off=row, width=tile_width, height=tile_height)
        for row in rows
        for col in cols
    ]


def _iter_windows(dataset: DatasetReader, mode: str) -> Iterable[Window]:
    if mode == "quick":
        return _quick_windows(dataset.width, dataset.height)
    return (window for _, window in dataset.block_windows(1))


def _scan_stats(
    dataset: DatasetReader,
    mode: str,
    expected_min: float,
    expected_max: float,
) -> RasterSampleStats:
    sampled_value_count = 0
    valid_value_count = 0
    nodata_or_masked_count = 0
    nan_count = 0
    inf_count = 0
    below_expected_min_count = 0
    above_expected_max_count = 0
    running_sum = 0.0
    minimum = math.inf
    maximum = -math.inf

    for window in _iter_windows(dataset, mode):
        array = dataset.read(1, window=window, masked=True)
        sampled_value_count += int(array.size)
        mask = np.ma.getmaskarray(array)
        nodata_or_masked_count += int(mask.sum())

        values = np.asarray(array.compressed(), dtype=np.float64)
        if values.size == 0:
            continue

        nan_mask = np.isnan(values)
        inf_mask = np.isinf(values)
        nan_count += int(nan_mask.sum())
        inf_count += int(inf_mask.sum())

        finite_values = values[np.isfinite(values)]
        if finite_values.size == 0:
            continue

        valid_value_count += int(finite_values.size)
        below_expected_min_count += int((finite_values < expected_min).sum())
        above_expected_max_count += int((finite_values > expected_max).sum())
        running_sum += float(finite_values.sum(dtype=np.float64))
        minimum = min(minimum, float(finite_values.min()))
        maximum = max(maximum, float(finite_values.max()))

    has_valid_values = valid_value_count > 0
    within_expected_range = (
        has_valid_values
        and nan_count == 0
        and inf_count == 0
        and below_expected_min_count == 0
        and above_expected_max_count == 0
    )

    return RasterSampleStats(
        method="quick-window-sample" if mode == "quick" else "full-block-scan",
        sampled_value_count=sampled_value_count,
        valid_value_count=valid_value_count,
        nodata_or_masked_count=nodata_or_masked_count,
        nan_count=nan_count,
        inf_count=inf_count,
        below_expected_min_count=below_expected_min_count,
        above_expected_max_count=above_expected_max_count,
        minimum=minimum if has_valid_values else None,
        maximum=maximum if has_valid_values else None,
        mean=(running_sum / valid_value_count) if has_valid_values else None,
        within_expected_range=within_expected_range if has_valid_values else None,
    )


def _allclose(left: Sequence[float], right: Sequence[float]) -> bool:
    return bool(np.allclose(left, right, rtol=0.0, atol=_FLOAT_ATOL, equal_nan=True))


def _alignment(record: RasterRecord, reference: RasterRecord) -> RasterAlignment:
    crs_match = record.crs == reference.crs
    shape_match = record.width == reference.width and record.height == reference.height
    resolution_match = bool(
        record.resolution
        and reference.resolution
        and _allclose(record.resolution, reference.resolution)
    )
    transform_match = bool(
        record.transform
        and reference.transform
        and _allclose(record.transform, reference.transform)
    )
    bounds_match = bool(
        record.bounds and reference.bounds and _allclose(record.bounds, reference.bounds)
    )

    mismatch_reasons: list[str] = []
    if not crs_match:
        mismatch_reasons.append("CRS 不一致")
    if not shape_match:
        mismatch_reasons.append("width/height 不一致")
    if not resolution_match:
        mismatch_reasons.append("像元分辨率不一致")
    if not transform_match:
        mismatch_reasons.append("Affine transform 不一致，像元网格未完全对齐")
    if not bounds_match:
        mismatch_reasons.append("空间范围 bounds 不一致")

    # Transform + shape are the decisive grid-alignment conditions. Resolution and
    # bounds are also reported because they make a mismatch easier to diagnose.
    aligned = crs_match and shape_match and transform_match

    return RasterAlignment(
        reference_file=reference.filename,
        crs_match=crs_match,
        shape_match=shape_match,
        resolution_match=resolution_match,
        transform_match=transform_match,
        bounds_match=bounds_match,
        aligned=aligned,
        mismatch_reasons=mismatch_reasons,
    )


def audit_raster_directory(
    raster_dir: Path,
    *,
    mode: str = "quick",
    indicators: Sequence[IndicatorDefinition] = INDICATORS,
) -> RasterAuditManifest:
    if mode not in {"quick", "full"}:
        raise ValueError("mode 必须是 quick 或 full")

    raster_dir = raster_dir.expanduser().resolve()
    if not raster_dir.exists():
        raise FileNotFoundError(f"栅格目录不存在: {raster_dir}")
    if not raster_dir.is_dir():
        raise NotADirectoryError(f"不是目录: {raster_dir}")

    expected_names = {indicator.filename for indicator in indicators}
    actual_tifs = {
        path.name
        for path in raster_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".tif", ".tiff"}
    }
    missing_files = sorted(expected_names - actual_tifs)
    unexpected_tif_files = sorted(actual_tifs - expected_names)

    records: list[RasterRecord] = []
    for indicator in indicators:
        path = raster_dir / indicator.filename
        if not path.exists():
            records.append(
                RasterRecord(
                    code=indicator.code,
                    name=indicator.name,
                    filename=indicator.filename,
                    exists=False,
                    errors=["文件不存在"],
                )
            )
            continue

        try:
            with rasterio.open(path) as dataset:
                warnings: list[str] = []
                if dataset.crs is None:
                    warnings.append("CRS 缺失，无法参与可靠的空间对齐和后续裁剪")
                if dataset.count != 1:
                    warnings.append(f"预期单波段指标栅格，实际 band_count={dataset.count}")

                stats = _scan_stats(
                    dataset,
                    mode=mode,
                    expected_min=indicator.expected_min,
                    expected_max=indicator.expected_max,
                )
                mask_flags = dataset.mask_flag_enums[0] if dataset.count else []
                has_dataset_mask = any(flag != MaskFlags.all_valid for flag in mask_flags)
                records.append(
                    RasterRecord(
                        code=indicator.code,
                        name=indicator.name,
                        filename=indicator.filename,
                        exists=True,
                        size_bytes=path.stat().st_size,
                        driver=dataset.driver,
                        band_count=dataset.count,
                        width=dataset.width,
                        height=dataset.height,
                        dtype=dataset.dtypes[0] if dataset.count else None,
                        crs=_normalise_crs(dataset),
                        transform=_transform_values(dataset.transform),
                        resolution=[float(abs(dataset.res[0])), float(abs(dataset.res[1]))],
                        bounds=[float(value) for value in dataset.bounds],
                        nodata=_serialise_nodata(dataset.nodata),
                        has_dataset_mask=has_dataset_mask,
                        stats=stats,
                        warnings=warnings,
                    )
                )
        except Exception as exc:  # noqa: BLE001 - audit must report per-file failures
            records.append(
                RasterRecord(
                    code=indicator.code,
                    name=indicator.name,
                    filename=indicator.filename,
                    exists=True,
                    size_bytes=path.stat().st_size,
                    errors=[f"Rasterio 读取失败: {type(exc).__name__}: {exc}"],
                )
            )

    readable_records = [
        record
        for record in records
        if record.exists and not record.errors and record.crs is not None
    ]
    reference = readable_records[0] if readable_records else None

    if reference is not None:
        for record in readable_records:
            record.alignment = _alignment(record, reference)

    found_raster_count = sum(1 for record in records if record.exists)
    all_rasters_readable = all(record.exists and not record.errors for record in records)
    all_rasters_aligned = (
        all(
            record.alignment is not None and record.alignment.aligned
            for record in readable_records
        )
        if len(readable_records) == len(indicators) and readable_records
        else None
    )

    crs_values = {record.crs for record in readable_records}
    common_crs = next(iter(crs_values)) if len(crs_values) == 1 else None

    stats_records = [record.stats for record in readable_records if record.stats is not None]
    range_failures = [stats for stats in stats_records if stats.within_expected_range is False]
    range_unknowns = [stats for stats in stats_records if stats.within_expected_range is None]
    if range_failures or (mode == "full" and range_unknowns):
        normalized_range_check = "failed"
        normalized_range_note = (
            "至少一个已读取样本/完整扫描发现 NaN、Inf、超出 [0, 1] 的有效像元，"
            "或在完整扫描中没有可用于验证的有效像元。"
        )
    elif mode == "full" and len(stats_records) == len(indicators):
        normalized_range_check = "passed"
        normalized_range_note = (
            f"{len(indicators)} 个栅格已完成逐块完整扫描，所有有限有效像元均位于 [0, 1]。"
        )
    else:
        normalized_range_check = "not-complete"
        normalized_range_note = (
            "quick 模式只检查分布在影像上的确定性窗口；未发现异常只能说明抽样通过，"
            "不能证明整幅影像全部位于 [0, 1]。需要 full 模式才能给出完整结论。"
        )

    return RasterAuditManifest(
        generated_at=datetime.now(UTC),
        audit_mode=mode,
        expected_raster_count=len(indicators),
        found_raster_count=found_raster_count,
        missing_files=missing_files,
        unexpected_tif_files=unexpected_tif_files,
        reference_file=reference.filename if reference else None,
        common_crs=common_crs,
        all_expected_files_present=not missing_files and found_raster_count == len(indicators),
        all_rasters_readable=all_rasters_readable,
        all_rasters_aligned=all_rasters_aligned,
        normalized_range_check=normalized_range_check,
        normalized_range_note=normalized_range_note,
        rasters=records,
    )
