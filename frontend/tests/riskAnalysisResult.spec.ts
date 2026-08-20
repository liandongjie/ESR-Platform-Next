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
    expect(parseRiskAnalysisResult(validResult(), 'task-1').task_id).toBe('task-1')
  })

  it('accepts new model snapshots while preserving results without the optional field', () => {
    const current = { ...validResult(), model_contract: makeRiskIndicatorCatalog().model_contract }

    expect(parseRiskAnalysisResult(current, 'task-1').model_contract?.aggregation).toBe(
      'weighted_sum',
    )
    expect(parseRiskAnalysisResult(validResult(), 'task-1').model_contract).toBeUndefined()
  })

  it('accepts optional preview metadata and rejects inverted grid bounds', () => {
    const preview = validResult()
    Object.assign(preview, { palette_version: 'risk-viridis-5-v1' })
    Object.assign(preview.grid, { bounds: [118.8, 32.0, 118.9, 32.1] })
    Object.assign(preview.artifacts, { preview: 'risk-analysis/task-1/preview.png' })

    expect(parseRiskAnalysisResult(preview, 'task-1').artifacts.preview).toContain('preview.png')

    Object.assign(preview.grid, { bounds: [118.9, 32.0, 118.8, 32.1] })
    expect(() => parseRiskAnalysisResult(preview, 'task-1')).toThrow('任务结果格式不完整')
  })

  it('keeps legacy manifests without preview or palette version compatible', () => {
    const legacy = validResult()

    expect(parseRiskAnalysisResult(legacy, 'task-1').palette_version).toBeUndefined()
  })

  it.each([undefined, 'risk-viridis-5-v2'])(
    'rejects preview metadata with palette version %s',
    (paletteVersion) => {
      const preview = validResult()
      Object.assign(preview, { palette_version: paletteVersion })
      Object.assign(preview.grid, { bounds: [118.8, 32.0, 118.9, 32.1] })
      Object.assign(preview.artifacts, { preview: 'risk-analysis/task-1/preview.png' })

      expect(() => parseRiskAnalysisResult(preview, 'task-1')).toThrow('任务结果格式不完整')
    },
  )

  it('binds the response to the requested task id', () => {
    expect(() => parseRiskAnalysisResult(validResult(), 'task-2')).toThrow(
      '任务结果格式不完整',
    )
  })

  it.each([
    ['grid CRS', (value: ReturnType<typeof validResult>) => (value.grid.crs = 'EPSG:3857')],
    [
      'inverted geometry bounds',
      (value: ReturnType<typeof validResult>) => (value.geometry.bounds = [118.9, 32, 118.8, 32.1]),
    ],
    [
      'geometry longitude outside WGS84',
      (value: ReturnType<typeof validResult>) => (value.geometry.bounds = [-181, 32, 118.9, 32.1]),
    ],
    [
      'geometry latitude outside WGS84',
      (value: ReturnType<typeof validResult>) => (value.geometry.bounds = [118.8, -91, 118.9, 32.1]),
    ],
  ])('rejects invalid base spatial metadata: %s', (_, mutate) => {
    const value = validResult()
    mutate(value)

    expect(() => parseRiskAnalysisResult(value, 'task-1')).toThrow('任务结果格式不完整')
  })

  it.each([
    ['preview without bounds', undefined, 'risk-analysis/task-1/preview.png', 'EPSG:4326'],
    ['bounds without preview', [118.8, 32, 118.9, 32.1], undefined, 'EPSG:4326'],
    ['wrong CRS', [118.8, 32, 118.9, 32.1], 'preview.png', 'EPSG:3857'],
    ['longitude outside WGS84', [-181, 32, 118.9, 32.1], 'preview.png', 'EPSG:4326'],
    ['latitude outside WGS84', [118.8, -91, 118.9, 32.1], 'preview.png', 'EPSG:4326'],
  ])('rejects invalid preview metadata: %s', (_, bounds, preview, crs) => {
    const value = validResult()
    value.grid.crs = crs
    Object.assign(value.grid, { bounds })
    Object.assign(value.artifacts, { preview })

    expect(() => parseRiskAnalysisResult(value, 'task-1')).toThrow('任务结果格式不完整')
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
      }, 'legacy-test-pollution'),
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
