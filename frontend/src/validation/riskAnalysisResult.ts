import type {
  RasterStatistics,
  RiskAnalysisResult,
  RiskAnalysisSpatialFeature,
  RiskAnalysisSpatialResult,
  RiskIndicatorResult,
} from '@/types/riskAnalysis'
import { parseRiskModelContract } from '@/validation/riskIndicatorCatalog'

const RISK_PREVIEW_PALETTE_VERSION = 'risk-viridis-5-v1'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isRasterStatistics(value: unknown): value is RasterStatistics {
  if (!isRecord(value)) return false
  return (
    typeof value.valid_pixel_count === 'number' &&
    Number.isInteger(value.valid_pixel_count) &&
    value.valid_pixel_count >= 0 &&
    isFiniteNumber(value.minimum) &&
    isFiniteNumber(value.maximum) &&
    isFiniteNumber(value.mean)
  )
}

function isIndicator(value: unknown): value is RiskIndicatorResult {
  if (!isRecord(value)) return false
  return (
    typeof value.code === 'string' &&
    value.code.length > 0 &&
    typeof value.name === 'string' &&
    value.name.length > 0 &&
    isFiniteNumber(value.weight_percent) &&
    isRasterStatistics(value.statistics)
  )
}

function isCoordinate(value: unknown): value is [number, number] {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    isFiniteNumber(value[0]) &&
    value[0] >= -180 &&
    value[0] <= 180 &&
    isFiniteNumber(value[1]) &&
    value[1] >= -90 &&
    value[1] <= 90
  )
}

function isClosedRing(value: unknown): value is [number, number][] {
  if (!Array.isArray(value) || value.length < 4 || !value.every(isCoordinate)) return false
  const first = value[0]!
  const last = value[value.length - 1]!
  return first[0] === last[0] && first[1] === last[1]
}

function isSpatialFeature(value: unknown): value is RiskAnalysisSpatialFeature {
  if (!isRecord(value) || value.type !== 'Feature') return false
  if (!isRecord(value.geometry) || value.geometry.type !== 'Polygon') return false
  const coordinates = value.geometry.coordinates
  if (
    !Array.isArray(coordinates) ||
    coordinates.length === 0 ||
    !coordinates.every(isClosedRing)
  ) {
    return false
  }
  return (
    isRecord(value.properties) &&
    isFiniteNumber(value.properties.value) &&
    value.properties.value >= 0 &&
    value.properties.value <= 1
  )
}

export function parseRiskAnalysisResult(
  value: unknown,
  expectedTaskId: string,
): RiskAnalysisResult {
  const invalid = new Error('任务结果格式不完整，无法使用当前版本展示')
  if (!isRecord(value)) throw invalid
  if (value.schema_version !== 1 || value.status !== 'SUCCEEDED') throw invalid
  if (value.task_id !== expectedTaskId || typeof value.algorithm_version !== 'string') {
    throw invalid
  }
  if (value.model_contract !== undefined && value.model_contract !== null) {
    try {
      parseRiskModelContract(value.model_contract)
    } catch {
      throw invalid
    }
  }

  if (!isRecord(value.geometry)) throw invalid
  const bounds = value.geometry.bounds
  if (
    typeof value.geometry.type !== 'string' ||
    !Array.isArray(bounds) ||
    bounds.length !== 4 ||
    !bounds.every(isFiniteNumber) ||
    bounds[0] < -180 ||
    bounds[2] > 180 ||
    bounds[1] < -90 ||
    bounds[3] > 90 ||
    bounds[0] >= bounds[2] ||
    bounds[1] >= bounds[3]
  ) {
    throw invalid
  }

  if (!isRecord(value.grid)) throw invalid
  const shape = value.grid.shape
  if (
    value.grid.crs !== 'EPSG:4326' ||
    !Array.isArray(shape) ||
    shape.length !== 2 ||
    !shape.every(
      (item) => typeof item === 'number' && Number.isInteger(item) && item > 0,
    ) ||
    !isFiniteNumber(value.grid.nodata)
  ) {
    throw invalid
  }
  if (!isRasterStatistics(value.statistics)) throw invalid
  if (!Array.isArray(value.indicators) || value.indicators.length === 0) throw invalid
  if (!value.indicators.every(isIndicator)) throw invalid

  if (
    !isRecord(value.artifacts) ||
    typeof value.artifacts.raster !== 'string' ||
    typeof value.artifacts.manifest !== 'string' ||
    (value.artifacts.preview !== undefined &&
      (typeof value.artifacts.preview !== 'string' || value.artifacts.preview.length === 0))
  ) {
    throw invalid
  }

  const gridBounds = value.grid.bounds
  const preview = value.artifacts.preview
  if (
    value.palette_version !== undefined &&
    value.palette_version !== RISK_PREVIEW_PALETTE_VERSION
  ) {
    throw invalid
  }
  if (preview !== undefined && value.palette_version !== RISK_PREVIEW_PALETTE_VERSION) {
    throw invalid
  }
  if ((gridBounds === undefined) !== (preview === undefined)) throw invalid
  if (gridBounds !== undefined) {
    if (
      value.grid.crs !== 'EPSG:4326' ||
      !Array.isArray(gridBounds) ||
      gridBounds.length !== 4 ||
      !gridBounds.every(isFiniteNumber) ||
      gridBounds[0] < -180 ||
      gridBounds[2] > 180 ||
      gridBounds[1] < -90 ||
      gridBounds[3] > 90 ||
      gridBounds[0] >= gridBounds[2] ||
      gridBounds[1] >= gridBounds[3]
    ) {
      throw invalid
    }
  }

  // 客户端只做最后一道结构防御；完整持久化 Contract 仍以后端 Pydantic 为最终权威。
  return value as unknown as RiskAnalysisResult
}

export function parseRiskAnalysisSpatialResult(
  value: unknown,
  expectedTaskId: string,
): RiskAnalysisSpatialResult {
  const invalid = new Error('空间风险结果格式不完整，无法使用当前版本展示')
  if (!isRecord(value)) throw invalid
  if (
    value.schema_version !== 1 ||
    value.task_id !== expectedTaskId ||
    value.crs !== 'EPSG:4326'
  ) {
    throw invalid
  }
  if (
    !isRecord(value.value_range) ||
    value.value_range.minimum !== 0 ||
    value.value_range.maximum !== 1
  ) {
    throw invalid
  }
  if (
    !isRecord(value.feature_collection) ||
    value.feature_collection.type !== 'FeatureCollection' ||
    !Array.isArray(value.feature_collection.features) ||
    !value.feature_collection.features.every(isSpatialFeature)
  ) {
    throw invalid
  }

  // Spatial Result 是独立的展示 Contract；不能用统计 Result 的成功状态替代其边界校验。
  return value as unknown as RiskAnalysisSpatialResult
}
