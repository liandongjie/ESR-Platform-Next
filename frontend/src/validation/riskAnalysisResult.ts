import type {
  RasterStatistics,
  RiskAnalysisResult,
  RiskIndicatorResult,
} from '@/types/riskAnalysis'

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

export function parseRiskAnalysisResult(value: unknown): RiskAnalysisResult {
  const invalid = new Error('任务结果格式不完整，无法使用当前版本展示')
  if (!isRecord(value)) throw invalid
  if (value.schema_version !== 1 || value.status !== 'SUCCEEDED') throw invalid
  if (typeof value.task_id !== 'string' || typeof value.algorithm_version !== 'string') {
    throw invalid
  }

  if (!isRecord(value.geometry)) throw invalid
  const bounds = value.geometry.bounds
  if (
    typeof value.geometry.type !== 'string' ||
    !Array.isArray(bounds) ||
    bounds.length !== 4 ||
    !bounds.every(isFiniteNumber)
  ) {
    throw invalid
  }

  if (!isRecord(value.grid)) throw invalid
  const shape = value.grid.shape
  if (
    typeof value.grid.crs !== 'string' ||
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
    typeof value.artifacts.manifest !== 'string'
  ) {
    throw invalid
  }

  // 客户端只做最后一道结构防御；完整持久化 Contract 仍以后端 Pydantic 为最终权威。
  return value as unknown as RiskAnalysisResult
}
