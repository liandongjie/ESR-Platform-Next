import type {
  RiskIndicatorCatalog,
  RiskIndicatorCategoryCode,
  RiskModelContract,
} from '@/types/riskAnalysis'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isCategoryCode(value: unknown): value is RiskIndicatorCategoryCode {
  return value === 'environment' || value === 'population' || value === 'social'
}

function hasNormalizedRange(value: unknown): boolean {
  return isRecord(value) && value.minimum === 0 && value.maximum === 1
}

export function parseRiskModelContract(value: unknown): RiskModelContract {
  if (
    !isRecord(value) ||
    value.code !== 'nimby_facility_siting_environmental_social_risk_sensitivity' ||
    typeof value.name !== 'string' ||
    !value.name ||
    value.source_value_semantics !== 'higher_means_higher_risk_contribution' ||
    !hasNormalizedRange(value.normalized_range) ||
    value.aggregation !== 'weighted_sum' ||
    value.required_weight_total_percent !== 100
  ) {
    throw new Error('风险模型元数据格式不受支持')
  }
  return value as unknown as RiskModelContract
}

export function parseRiskIndicatorCatalog(value: unknown): RiskIndicatorCatalog {
  const invalid = new Error('风险指标目录格式不完整，无法创建新分析')
  if (!isRecord(value) || value.schema_version !== 1) throw invalid
  parseRiskModelContract(value.model_contract)

  if (!Array.isArray(value.categories) || value.categories.length !== 3) throw invalid
  const categoryCodes = new Set<RiskIndicatorCategoryCode>()
  for (const category of value.categories) {
    if (
      !isRecord(category) ||
      !isCategoryCode(category.code) ||
      typeof category.name !== 'string' ||
      !category.name ||
      typeof category.order !== 'number' ||
      !Number.isInteger(category.order) ||
      category.order < 0
    ) {
      throw invalid
    }
    categoryCodes.add(category.code)
  }
  if (categoryCodes.size !== 3) throw invalid

  if (!Array.isArray(value.indicators) || value.indicators.length !== 12) throw invalid
  const indicatorCodes = new Set<string>()
  for (const indicator of value.indicators) {
    if (
      !isRecord(indicator) ||
      typeof indicator.code !== 'string' ||
      !indicator.code ||
      indicatorCodes.has(indicator.code) ||
      typeof indicator.name !== 'string' ||
      !indicator.name ||
      !isCategoryCode(indicator.category) ||
      !categoryCodes.has(indicator.category) ||
      typeof indicator.source_tif !== 'string' ||
      !indicator.source_tif ||
      !hasNormalizedRange(indicator.normalized_range) ||
      indicator.risk_direction !== 'increasing' ||
      typeof indicator.risk_semantics !== 'string' ||
      !indicator.risk_semantics ||
      typeof indicator.legacy_mvp_default_selected !== 'boolean' ||
      typeof indicator.legacy_mvp_default_weight_percent !== 'number' ||
      !Number.isFinite(indicator.legacy_mvp_default_weight_percent) ||
      indicator.legacy_mvp_default_weight_percent < 0 ||
      indicator.legacy_mvp_default_weight_percent > 100
    ) {
      throw invalid
    }
    indicatorCodes.add(indicator.code)
  }

  return value as unknown as RiskIndicatorCatalog
}
