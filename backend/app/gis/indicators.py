from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

RiskIndicatorCategory = Literal["environment", "population", "social"]
RiskDirection = Literal["increasing"]

RISK_MODEL_CODE: Final = (
    "nimby_facility_siting_environmental_social_risk_sensitivity"
)
RISK_MODEL_NAME: Final = "邻避设施选址环境社会风险/敏感性"
RISK_SOURCE_VALUE_SEMANTICS: Final = "higher_means_higher_risk_contribution"
RISK_AGGREGATION: Final = "weighted_sum"
RISK_REQUIRED_WEIGHT_TOTAL_PERCENT: Final = 100.0

INDICATOR_CATEGORIES: Final[tuple[tuple[RiskIndicatorCategory, str], ...]] = (
    ("environment", "环境因素"),
    ("population", "人口因素"),
    ("social", "社会因素"),
)


@dataclass(frozen=True, slots=True)
class IndicatorDefinition:
    """Business and raster contract for one normalized risk indicator."""

    code: str
    name: str
    filename: str
    category: RiskIndicatorCategory
    risk_direction: RiskDirection
    risk_semantics: str
    default_selected: bool = False
    default_weight_percent: float = 0.0
    expected_min: float = 0.0
    expected_max: float = 1.0


INDICATORS: Final[tuple[IndicatorDefinition, ...]] = (
    IndicatorDefinition(
        "PM25", "细颗粒物 (PM2.5)", "PM25.tif", "environment", "increasing",
        "PM2.5 值越高，背景空气污染与健康暴露敏感性越高。", True, 30.0,
    ),
    IndicatorDefinition(
        "AQI", "空气质量指数 (AQI)", "AQI.tif", "environment", "increasing",
        "AQI 值越高，背景空气污染压力与选址环境风险越高。", True, 40.0,
    ),
    IndicatorDefinition(
        "NDVI", "归一化差值植被指数", "NDVI.tif", "environment", "increasing",
        "NDVI 值越高，植被生态敏感性越高，设施扰动风险越高。", True, 30.0,
    ),
    IndicatorDefinition(
        "hwmd", "河网密度", "hwmd.tif", "environment", "increasing",
        "河网密度越高，水环境受影响与污染扩散敏感性越高。",
    ),
    IndicatorDefinition(
        "rkmd", "人口密度", "rkmd.tif", "population", "increasing",
        "人口密度越高，潜在暴露人口与邻避冲突敏感性越高。",
    ),
    IndicatorDefinition(
        "xxmd", "学校密度", "xxmd.tif", "population", "increasing",
        "学校密度越高，敏感人群和公共设施受影响风险越高。",
    ),
    IndicatorDefinition(
        "jmdmd", "居民点密度", "jmdmd.tif", "population", "increasing",
        "居民点密度越高，居民暴露与邻避冲突敏感性越高。",
    ),
    IndicatorDefinition(
        "xspb", "刑事批捕率", "xspb.tif", "social", "increasing",
        "刑事批捕率越高，区域社会治安与稳定风险压力越高。",
    ),
    IndicatorDefinition(
        "xsqs", "刑事起诉率", "xsqs.tif", "social", "increasing",
        "刑事起诉率越高，区域社会治安与稳定风险压力越高。",
    ),
    IndicatorDefinition(
        "gyfb", "官员腐败指数", "gyfb.tif", "social", "increasing",
        "官员腐败指数越高，治理失效与项目社会风险越高。",
    ),
    IndicatorDefinition(
        "fmyl", "垃圾焚烧负面舆论占比", "fmyl.tif", "social", "increasing",
        "垃圾焚烧负面舆论占比越高，公众反对与舆情风险越高。",
    ),
    IndicatorDefinition(
        "fmts", "环境投诉负面数量占比", "fmts.tif", "social", "increasing",
        "环境投诉负面数量占比越高，环境冲突与社会敏感性越高。",
    ),
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


def risk_model_contract_payload() -> dict[str, object]:
    return {
        "code": RISK_MODEL_CODE,
        "name": RISK_MODEL_NAME,
        "source_value_semantics": RISK_SOURCE_VALUE_SEMANTICS,
        "normalized_range": {"minimum": 0.0, "maximum": 1.0},
        "aggregation": RISK_AGGREGATION,
        "required_weight_total_percent": RISK_REQUIRED_WEIGHT_TOTAL_PERCENT,
    }
