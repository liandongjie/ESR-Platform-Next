export interface LiveHealth {
  status: 'ok'
  service: string
  environment: string
}

export interface Capabilities {
  project: string
  stage: string
  coordinate_system: string
  result_ttl_hours: number
  limits: {
    max_buffer_meters: number
    max_analysis_area_km2: number
  }
  implemented: string[]
  planned: string[]
}
