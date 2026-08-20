"""
Author: liandongjie
Date: 2026-08-07 16:59:18
LastEditors: liandongjie
LastEditTime: 2026-08-07 17:51:55
Description:
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, FiniteFloat, PositiveInt, field_validator, model_validator

from app.gis.geojson import GeoJsonValidationError, parse_geojson_geometry
from app.schemas.common import ApiModel


class RiskIndicatorWeightInput(ApiModel):
    """JSON-safe weight item accepted at the asynchronous job boundary."""

    code: str = Field(min_length=1, max_length=64)
    weight_percent: FiniteFloat = Field(ge=0.0, le=100.0)


class RiskAnalysisJobRequest(ApiModel):
    """Serializable request passed from the API process to a Celery worker.

    Geometry stays as GeoJSON at the transport boundary. The worker converts it to
    Shapely only after deserialization, which keeps the Celery message JSON-only and
    avoids sending Python/GDAL objects through Redis.
    """

    geometry: dict[str, Any]
    weights: list[RiskIndicatorWeightInput] = Field(min_length=1, max_length=12)

    @field_validator("geometry")
    @classmethod
    def validate_geojson_geometry(cls, value: dict[str, Any]) -> dict[str, Any]:
        """在任务入队前拒绝无法解析的 GeoJSON，避免浪费 Worker 槽位。"""

        try:
            parse_geojson_geometry(value)
        except GeoJsonValidationError as exc:
            # 转成 ValueError 后由 Pydantic 统一包装成 API 可返回的 422 校验错误。
            raise ValueError(str(exc)) from exc
        return value


class RiskAnalysisSubmissionRecord(ApiModel):
    """Persisted immutable envelope written before the task is enqueued."""

    task_id: str = Field(min_length=1)
    status: Literal["QUEUED"]
    submitted_at: str = Field(min_length=1)
    request: RiskAnalysisJobRequest


class RasterStatisticsOutput(ApiModel):
    """持久化结果中的栅格统计；成功 manifest 缺字段时必须视为无效结果。"""

    valid_pixel_count: int = Field(ge=0)
    minimum: FiniteFloat
    maximum: FiniteFloat
    mean: FiniteFloat


class RiskAnalysisGeometrySummary(ApiModel):
    type: str = Field(min_length=1)
    bounds: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat]


class RiskAnalysisGridSummary(ApiModel):
    crs: str = Field(min_length=1)
    shape: tuple[PositiveInt, PositiveInt]
    nodata: FiniteFloat
    bounds: tuple[FiniteFloat, FiniteFloat, FiniteFloat, FiniteFloat] | None = None

    @field_validator("bounds")
    @classmethod
    def validate_wgs84_bounds(
        cls, value: tuple[float, float, float, float] | None
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        minimum_x, minimum_y, maximum_x, maximum_y = value
        if not (
            -180 <= minimum_x < maximum_x <= 180
            and -90 <= minimum_y < maximum_y <= 90
        ):
            raise ValueError("风险预览边界必须是有效 WGS84 bbox")
        return value


class RiskAnalysisIndicatorOutput(ApiModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    weight_percent: FiniteFloat = Field(ge=0.0, le=100.0)
    statistics: RasterStatisticsOutput


class RiskAnalysisArtifactOutput(ApiModel):
    raster: str = Field(min_length=1)
    manifest: str = Field(min_length=1)
    preview: str | None = Field(default=None, min_length=1)


class RiskAnalysisNormalizedRange(ApiModel):
    minimum: Literal[0.0] = 0.0
    maximum: Literal[1.0] = 1.0


class RiskModelContractOutput(ApiModel):
    code: Literal["nimby_facility_siting_environmental_social_risk_sensitivity"]
    name: str = Field(min_length=1)
    source_value_semantics: Literal["higher_means_higher_risk_contribution"]
    normalized_range: RiskAnalysisNormalizedRange
    aggregation: Literal["weighted_sum"]
    required_weight_total_percent: Literal[100.0] = 100.0


class RiskIndicatorCategoryOutput(ApiModel):
    code: Literal["environment", "population", "social"]
    name: str = Field(min_length=1)
    order: int = Field(ge=0)


class RiskIndicatorCatalogItemOutput(ApiModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1)
    category: Literal["environment", "population", "social"]
    source_tif: str = Field(min_length=1)
    normalized_range: RiskAnalysisNormalizedRange
    risk_direction: Literal["increasing"]
    risk_semantics: str = Field(min_length=1)
    legacy_mvp_default_selected: bool
    legacy_mvp_default_weight_percent: FiniteFloat = Field(ge=0.0, le=100.0)


class RiskIndicatorCatalogOutput(ApiModel):
    schema_version: Literal[1] = 1
    model_contract: RiskModelContractOutput
    categories: list[RiskIndicatorCategoryOutput] = Field(min_length=3, max_length=3)
    indicators: list[RiskIndicatorCatalogItemOutput] = Field(
        min_length=12, max_length=12
    )


class RiskAnalysisSuccessResult(ApiModel):
    """成功任务的持久化结果契约；完整但无版本号的历史结果按 v1 兼容读取。"""

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    status: Literal["SUCCEEDED"]
    algorithm_version: str = Field(min_length=1)
    geometry: RiskAnalysisGeometrySummary
    grid: RiskAnalysisGridSummary
    statistics: RasterStatisticsOutput
    indicators: list[RiskAnalysisIndicatorOutput] = Field(min_length=1, max_length=12)
    artifacts: RiskAnalysisArtifactOutput
    palette_version: Literal["risk-viridis-5-v1"] | None = None
    model_contract: RiskModelContractOutput | None = None

    @model_validator(mode="after")
    def validate_preview_contract(self) -> RiskAnalysisSuccessResult:
        has_preview = self.artifacts.preview is not None
        if has_preview != (self.grid.bounds is not None):
            raise ValueError("风险预览文件与栅格边界必须同时存在")
        if has_preview and self.grid.crs != "EPSG:4326":
            raise ValueError("风险预览边界必须使用 EPSG:4326")
        if has_preview and self.palette_version != "risk-viridis-5-v1":
            raise ValueError("风险预览色带版本无效")
        return self


class RiskAnalysisSpatialValueScale(ApiModel):
    """固定归一化数值范围；不在没有业务依据时附加风险等级名称。"""

    minimum: Literal[0.0] = 0.0
    maximum: Literal[1.0] = 1.0


class RiskAnalysisSpatialFeatureProperties(ApiModel):
    value: FiniteFloat = Field(ge=0.0, le=1.0)


class RiskAnalysisSpatialPolygon(ApiModel):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[FiniteFloat, FiniteFloat]]]


class RiskAnalysisSpatialFeature(ApiModel):
    type: Literal["Feature"]
    geometry: RiskAnalysisSpatialPolygon
    properties: RiskAnalysisSpatialFeatureProperties


class RiskAnalysisSpatialFeatureCollection(ApiModel):
    """标准 GeoJSON 内容；项目元数据保留在外层 SpatialResult。"""

    type: Literal["FeatureCollection"]
    features: list[RiskAnalysisSpatialFeature]


class RiskAnalysisSpatialResult(ApiModel):
    """由任务 GeoTIFF 按需派生的前端空间展示 Contract。"""

    schema_version: Literal[1] = 1
    task_id: str = Field(min_length=1)
    crs: Literal["EPSG:4326"]
    value_range: RiskAnalysisSpatialValueScale
    feature_collection: RiskAnalysisSpatialFeatureCollection
