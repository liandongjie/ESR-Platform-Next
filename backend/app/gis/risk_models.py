from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from affine import Affine
from rasterio.crs import CRS


class RiskAnalysisError(Exception):
    """Base exception for deterministic risk-analysis failures."""


class RiskAnalysisValidationError(RiskAnalysisError, ValueError):
    """Raised when the requested geometry or indicator weights are invalid."""


class RasterCompatibilityError(RiskAnalysisError):
    """Raised when source rasters cannot be safely combined pixel by pixel."""


@dataclass(frozen=True, slots=True)
class IndicatorWeight:
    """One selected indicator and its percentage contribution to the final score."""

    code: str
    weight_percent: float


@dataclass(frozen=True, slots=True)
class RasterStatistics:
    """Statistics computed only from valid pixels inside the requested geometry."""

    valid_pixel_count: int
    minimum: float
    maximum: float
    mean: float


@dataclass(frozen=True, slots=True)
class IndicatorAnalysis:
    """Per-indicator result retained for later API/report presentation."""

    code: str
    name: str
    weight_percent: float
    stats: RasterStatistics


@dataclass(slots=True)
class RiskAnalysisResult:
    """In-memory output of the deterministic weighted-overlay pipeline.

    ``array`` uses NaN for pixels that are outside the geometry or are not valid in
    every positively weighted indicator. ``write_risk_geotiff`` converts those NaNs
    to the explicit output NoData value when a GeoTIFF is persisted.
    """

    array: np.ndarray
    transform: Affine
    crs: CRS
    stats: RasterStatistics
    indicators: tuple[IndicatorAnalysis, ...]
    nodata: float = -9999.0
