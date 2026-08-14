import { describe, expect, it } from 'vitest'

import {
  parseRiskAnalysisResult,
  parseRiskAnalysisSpatialResult,
} from '@/validation/riskAnalysisResult'
import { makeRiskIndicatorCatalog } from './fixtures/riskIndicatorCatalog'

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

function validSpatialResult() {
  return {
    schema_version: 1,
    task_id: 'task-1',
    crs: 'EPSG:4326',
    value_range: { minimum: 0, maximum: 1 },
    feature_collection: {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [118.8, 32.0],
                [118.81, 32.0],
                [118.81, 32.01],
                [118.8, 32.01],
                [118.8, 32.0],
              ],
            ],
          },
          properties: { value: 0 },
        },
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [118.81, 32.0],
                [118.82, 32.0],
                [118.82, 32.01],
                [118.81, 32.01],
                [118.81, 32.0],
              ],
            ],
          },
          properties: { value: 1 },
        },
      ],
    },
  }
}

describe('risk analysis result runtime validation', () => {
  it('accepts a complete v1 result', () => {
    expect(parseRiskAnalysisResult(validResult()).task_id).toBe('task-1')
  })

  it('accepts new model snapshots while preserving results without the optional field', () => {
    const current = { ...validResult(), model_contract: makeRiskIndicatorCatalog().model_contract }

    expect(parseRiskAnalysisResult(current).model_contract?.aggregation).toBe('weighted_sum')
    expect(parseRiskAnalysisResult(validResult()).model_contract).toBeUndefined()
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

describe('risk analysis spatial result runtime validation', () => {
  it('accepts an independent spatial contract including values zero and one', () => {
    const result = parseRiskAnalysisSpatialResult(validSpatialResult(), 'task-1')

    expect(result.feature_collection.features.map((feature) => feature.properties.value)).toEqual([
      0, 1,
    ])
  })

  it.each([
    ['task id', (value: ReturnType<typeof validSpatialResult>) => (value.task_id = 'other-task')],
    ['crs', (value: ReturnType<typeof validSpatialResult>) => (value.crs = 'EPSG:3857')],
    [
      'value range',
      (value: ReturnType<typeof validSpatialResult>) => (value.value_range.maximum = 100),
    ],
    [
      'polygon',
      (value: ReturnType<typeof validSpatialResult>) =>
        (value.feature_collection.features[0]!.geometry.coordinates = [[]]),
    ],
    [
      'longitude outside EPSG:4326',
      (value: ReturnType<typeof validSpatialResult>) => {
        const ring = value.feature_collection.features[0]!.geometry.coordinates[0]!
        ring[0]![0] = 180.1
        ring[ring.length - 1]![0] = 180.1
      },
    ],
    [
      'latitude outside EPSG:4326',
      (value: ReturnType<typeof validSpatialResult>) => {
        const ring = value.feature_collection.features[0]!.geometry.coordinates[0]!
        ring[0]![1] = 90.1
        ring[ring.length - 1]![1] = 90.1
      },
    ],
    [
      'unclosed polygon ring',
      (value: ReturnType<typeof validSpatialResult>) =>
        (value.feature_collection.features[0]!.geometry.coordinates[0]![4] = [118.79, 32.0]),
    ],
    [
      'non-finite value',
      (value: ReturnType<typeof validSpatialResult>) =>
        (value.feature_collection.features[0]!.properties.value = Number.NaN),
    ],
    [
      'out-of-range value',
      (value: ReturnType<typeof validSpatialResult>) =>
        (value.feature_collection.features[0]!.properties.value = 1.1),
    ],
  ])('rejects invalid %s metadata', (_, mutate) => {
    const value = validSpatialResult()
    mutate(value)

    expect(() => parseRiskAnalysisSpatialResult(value, 'task-1')).toThrow('空间风险结果格式不完整')
  })
})
