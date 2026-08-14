import type { BufferGeometry, PolygonGeometry } from '@/types/analysisArea'

export interface RiskIndicatorWeightInput {
  code: string
  weight_percent: number
}

export type RiskIndicatorCategoryCode = 'environment' | 'population' | 'social'

export interface RiskAnalysisNormalizedRange {
  minimum: 0
  maximum: 1
}

export interface RiskModelContract {
  code: 'nimby_facility_siting_environmental_social_risk_sensitivity'
  name: string
  source_value_semantics: 'higher_means_higher_risk_contribution'
  normalized_range: RiskAnalysisNormalizedRange
  aggregation: 'weighted_sum'
  required_weight_total_percent: 100
}

export interface RiskIndicatorCategory {
  code: RiskIndicatorCategoryCode
  name: string
  order: number
}

export interface RiskIndicatorDefinition {
  code: string
  name: string
  category: RiskIndicatorCategoryCode
  source_tif: string
  normalized_range: RiskAnalysisNormalizedRange
  risk_direction: 'increasing'
  risk_semantics: string
  legacy_mvp_default_selected: boolean
  legacy_mvp_default_weight_percent: number
}

export interface RiskIndicatorCatalog {
  schema_version: 1
  model_contract: RiskModelContract
  categories: RiskIndicatorCategory[]
  indicators: RiskIndicatorDefinition[]
}

export interface RiskAnalysisJobRequest {
  geometry: BufferGeometry
  weights: RiskIndicatorWeightInput[]
}

export interface RiskAnalysisSubmissionDetail {
  task_id: string
  submitted_at: string
  request: RiskAnalysisJobRequest
}

export type RiskJobStatus =
  | 'QUEUED'
  | 'RUNNING'
  | 'RETRYING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'CANCELED'

export interface RiskAnalysisJobCreated {
  task_id: string
  status: 'QUEUED'
  submitted_at: string
  status_url: string
  result_url: string
}

export interface RiskAnalysisJobStatus {
  task_id: string
  status: RiskJobStatus
  stage: string
  progress: number | null
  result_available: boolean
  submitted_at: string | null
  error?: {
    code?: string
    message?: string
  }
}

export interface RiskAnalysisJobRequestSummary {
  geometry_type: string | null
  weights: RiskIndicatorWeightInput[]
}

export interface RiskAnalysisJobHistoryItem extends RiskAnalysisJobStatus {
  request_summary: RiskAnalysisJobRequestSummary
}

export interface RiskAnalysisJobHistoryResponse {
  items: RiskAnalysisJobHistoryItem[]
  limit: number
  offset: number
  total: number
}

export interface RasterStatistics {
  valid_pixel_count: number
  minimum: number
  maximum: number
  mean: number
}

export interface RiskIndicatorResult {
  code: string
  name: string
  weight_percent: number
  statistics: RasterStatistics
}

export interface RiskAnalysisResult {
  schema_version: 1
  task_id: string
  status: 'SUCCEEDED'
  algorithm_version: string
  model_contract?: RiskModelContract | null
  geometry: {
    type: string
    bounds: number[]
  }
  grid: {
    crs: string
    shape: [number, number]
    nodata: number
  }
  statistics: RasterStatistics
  indicators: RiskIndicatorResult[]
  artifacts: {
    raster: string
    manifest: string
  }
}

export interface RiskAnalysisSpatialFeature {
  type: 'Feature'
  geometry: PolygonGeometry
  properties: {
    value: number
  }
}

export interface RiskAnalysisSpatialResult {
  schema_version: 1
  task_id: string
  crs: 'EPSG:4326'
  value_range: {
    minimum: 0
    maximum: 1
  }
  feature_collection: {
    type: 'FeatureCollection'
    features: RiskAnalysisSpatialFeature[]
  }
}
