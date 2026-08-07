from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    """Static contract between a business indicator and its source raster.

    Phase 1A deliberately keeps the legacy indicator keys. They are already used by
    the historical backend and therefore let us audit the real data without adding
    a second, unverified naming system.
    """

    code: str
    name: str
    filename: str
    default_selected: bool = False
    default_weight_percent: float = 0.0
    expected_min: float = 0.0
    expected_max: float = 1.0


INDICATORS: Final[tuple[IndicatorDefinition, ...]] = (
    IndicatorDefinition("PM25", "细颗粒物 (PM2.5)", "PM25.tif", True, 30.0),
    IndicatorDefinition("AQI", "空气质量指数 (AQI)", "AQI.tif", True, 40.0),
    IndicatorDefinition("NDVI", "归一化差值植被指数", "NDVI.tif", True, 30.0),
    IndicatorDefinition("hwmd", "河网密度", "hwmd.tif"),
    IndicatorDefinition("rkmd", "人口密度", "rkmd.tif"),
    IndicatorDefinition("xxmd", "学校密度", "xxmd.tif"),
    IndicatorDefinition("jmdmd", "居民点密度", "jmdmd.tif"),
    IndicatorDefinition("xspb", "刑事批捕率", "xspb.tif"),
    IndicatorDefinition("xsqs", "刑事起诉率", "xsqs.tif"),
    IndicatorDefinition("gyfb", "官员腐败指数", "gyfb.tif"),
    IndicatorDefinition("fmyl", "垃圾焚烧负面舆论占比", "fmyl.tif"),
    IndicatorDefinition("fmts", "环境投诉负面数量占比", "fmts.tif"),
)

INDICATOR_BY_CODE: Final[dict[str, IndicatorDefinition]] = {
    indicator.code: indicator for indicator in INDICATORS
}


def get_indicator(code: str) -> IndicatorDefinition:
    try:
        return INDICATOR_BY_CODE[code]
    except KeyError as exc:
        raise KeyError(f"未知指标: {code}") from exc


def legacy_default_weights() -> dict[str, float]:
    """Return the currently verified legacy default selection and weights."""

    return {
        indicator.code: indicator.default_weight_percent
        for indicator in INDICATORS
        if indicator.default_selected
    }
