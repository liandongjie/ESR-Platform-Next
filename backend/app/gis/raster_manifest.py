from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RasterSampleStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["quick-window-sample", "full-block-scan"]
    sampled_value_count: int = 0
    valid_value_count: int = 0
    nodata_or_masked_count: int = 0
    nan_count: int = 0
    inf_count: int = 0
    below_expected_min_count: int = 0
    above_expected_max_count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    within_expected_range: bool | None = None


class RasterAlignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reference_file: str
    crs_match: bool
    shape_match: bool
    resolution_match: bool
    transform_match: bool
    bounds_match: bool
    aligned: bool
    mismatch_reasons: list[str] = Field(default_factory=list)


class RasterRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    filename: str
    exists: bool
    size_bytes: int | None = None
    driver: str | None = None
    band_count: int | None = None
    width: int | None = None
    height: int | None = None
    dtype: str | None = None
    crs: str | None = None
    transform: list[float] | None = None
    resolution: list[float] | None = None
    bounds: list[float] | None = None
    nodata: float | str | None = None
    has_dataset_mask: bool | None = None
    stats: RasterSampleStats | None = None
    alignment: RasterAlignment | None = None
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RasterAuditManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0"
    generated_at: datetime
    audit_mode: Literal["quick", "full"]
    expected_raster_count: int
    found_raster_count: int
    missing_files: list[str]
    unexpected_tif_files: list[str]
    reference_file: str | None
    common_crs: str | None
    all_expected_files_present: bool
    all_rasters_readable: bool
    all_rasters_aligned: bool | None
    normalized_range_check: Literal["passed", "failed", "not-complete"]
    normalized_range_note: str
    rasters: list[RasterRecord]
