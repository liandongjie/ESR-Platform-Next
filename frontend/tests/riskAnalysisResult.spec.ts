import { describe, expect, it } from 'vitest'

import { parseRiskAnalysisResult } from '@/validation/riskAnalysisResult'

function validResult() {
  return {
    schema_version: 1,
    task_id: 'task-1',
    status: 'SUCCEEDED',
    algorithm_version: 'weighted-overlay-v1',
    geometry: {
      type: 'Polygon',
      bounds: [118.8, 32.0, 118.9, 32.1],
    },
    grid: {
      crs: 'EPSG:4326',
      shape: [6, 7],
      nodata: -9999,
    },
    statistics: {
      valid_pixel_count: 27,
      minimum: 0.35,
      maximum: 0.48,
      mean: 0.39,
    },
    indicators: [
      {
        code: 'PM25',
        name: '细颗粒物 (PM2.5)',
        weight_percent: 100,
        statistics: {
          valid_pixel_count: 27,
          minimum: 0.2,
          maximum: 0.3,
          mean: 0.26,
        },
      },
    ],
    artifacts: {
      raster: 'risk-analysis/task-1/risk.tif',
      manifest: 'risk-analysis/task-1/result.json',
    },
  }
}

describe('risk analysis result runtime validation', () => {
  it('accepts a complete v1 result', () => {
    expect(parseRiskAnalysisResult(validResult()).task_id).toBe('task-1')
  })

  it('rejects the incomplete success manifest that previously crashed the task drawer', () => {
    expect(() =>
      parseRiskAnalysisResult({
        task_id: 'legacy-test-pollution',
        status: 'SUCCEEDED',
        statistics: {
          valid_pixel_count: 9,
          mean: 0.37,
        },
      }),
    ).toThrow('任务结果格式不完整')
  })
})
