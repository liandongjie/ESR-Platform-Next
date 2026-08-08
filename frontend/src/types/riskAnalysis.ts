import type { BufferGeometry } from '@/types/analysisArea'

export interface RiskIndicatorWeightInput {
  code: string
  weight_percent: number
}

export interface RiskAnalysisJobRequest {
  geometry: BufferGeometry
  weights: RiskIndicatorWeightInput[]
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
  task_id: string
  status: 'SUCCEEDED'
  algorithm_version: string
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
