import type {
  RiskIndicatorCatalog,
  RiskIndicatorCategoryCode,
} from '@/types/riskAnalysis'

const definitions: Array<[string, string, RiskIndicatorCategoryCode]> = [
  ['PM25', '细颗粒物 (PM2.5)', 'environment'],
  ['AQI', '空气质量指数 (AQI)', 'environment'],
  ['NDVI', '归一化差值植被指数', 'environment'],
  ['hwmd', '河网密度', 'environment'],
  ['rkmd', '人口密度', 'population'],
  ['xxmd', '学校密度', 'population'],
  ['jmdmd', '居民点密度', 'population'],
  ['xspb', '刑事批捕率', 'social'],
  ['xsqs', '刑事起诉率', 'social'],
  ['gyfb', '官员腐败指数', 'social'],
  ['fmyl', '垃圾焚烧负面舆论占比', 'social'],
  ['fmts', '环境投诉负面数量占比', 'social'],
]

export function makeRiskIndicatorCatalog(): RiskIndicatorCatalog {
  return {
    schema_version: 1,
    model_contract: {
      code: 'nimby_facility_siting_environmental_social_risk_sensitivity',
      name: '邻避设施选址环境社会风险/敏感性',
      source_value_semantics: 'higher_means_higher_risk_contribution',
      normalized_range: { minimum: 0, maximum: 1 },
      aggregation: 'weighted_sum',
      required_weight_total_percent: 100,
    },
    categories: [
      { code: 'environment', name: '环境因素', order: 0 },
      { code: 'population', name: '人口因素', order: 1 },
      { code: 'social', name: '社会因素', order: 2 },
    ],
    indicators: definitions.map(([code, name, category]) => ({
      code,
      name,
      category,
      source_tif: `${code}.tif`,
      normalized_range: { minimum: 0, maximum: 1 },
      risk_direction: 'increasing',
      risk_semantics: `${name}值越高，风险贡献越高。`,
      legacy_mvp_default_selected: ['PM25', 'AQI', 'NDVI'].includes(code),
      legacy_mvp_default_weight_percent:
        code === 'PM25' ? 30 : code === 'AQI' ? 40 : code === 'NDVI' ? 30 : 0,
    })),
  }
}
