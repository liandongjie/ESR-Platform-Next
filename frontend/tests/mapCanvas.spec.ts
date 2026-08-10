import AMapLoader from '@amap/amap-jsapi-loader'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MapCanvas from '@/components/map/MapCanvas.vue'
import { wgs84ToGcj02 } from '@/map/coordinates'
import { RISK_VALUE_COLOR_BINS, riskColorForValue } from '@/map/riskSpatial'
import type { BufferGeometry } from '@/types/analysisArea'
import type { RiskAnalysisSpatialResult } from '@/types/riskAnalysis'

vi.mock('@amap/amap-jsapi-loader', () => ({
  default: { load: vi.fn() },
}))

interface PolygonOptions {
  path: number[][][]
  strokeColor: string
  strokeWeight: number
  fillColor: string
  fillOpacity: number
  zIndex: number
}

const polygonOptions: PolygonOptions[] = []
const polygonSetMapCalls: ReturnType<typeof vi.fn>[] = []
const setFitView = vi.fn()

class FakeMap {
  on = vi.fn()
  off = vi.fn()
  setFitView = setFitView
  destroy = vi.fn()
}

class FakeMarker {
  setMap = vi.fn()
}

class FakePolygon {
  setMap = vi.fn()

  constructor(options: PolygonOptions) {
    polygonOptions.push(options)
    polygonSetMapCalls.push(this.setMap)
  }
}

const bufferGeometry: BufferGeometry = {
  type: 'Polygon',
  coordinates: [
    [
      [118.8, 32.0],
      [118.83, 32.0],
      [118.83, 32.03],
      [118.8, 32.03],
      [118.8, 32.0],
    ],
  ],
}

function spatialResult(
  taskId: string,
  values: number[] = [0],
): RiskAnalysisSpatialResult {
  return {
    schema_version: 1,
    task_id: taskId,
    crs: 'EPSG:4326',
    value_range: { minimum: 0, maximum: 1 },
    feature_collection: {
      type: 'FeatureCollection',
      features: values.map((value, index) => ({
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [
            [
              [118.8 + index * 0.01, 32.0],
              [118.81 + index * 0.01, 32.0],
              [118.81 + index * 0.01, 32.01],
              [118.8 + index * 0.01, 32.01],
              [118.8 + index * 0.01, 32.0],
            ],
          ],
        },
        properties: { value },
      })),
    },
  }
}

describe('risk spatial color scale', () => {
  it('uses explicit equal-width boundaries including zero and one', () => {
    expect([0, 0.2, 0.4, 0.6, 0.8, 1].map(riskColorForValue)).toEqual([
      RISK_VALUE_COLOR_BINS[0]!.color,
      RISK_VALUE_COLOR_BINS[1]!.color,
      RISK_VALUE_COLOR_BINS[2]!.color,
      RISK_VALUE_COLOR_BINS[3]!.color,
      RISK_VALUE_COLOR_BINS[4]!.color,
      RISK_VALUE_COLOR_BINS[4]!.color,
    ])
  })
})

describe('MapCanvas risk cells', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AMAP_JS_API_KEY', 'test-key')
    vi.stubEnv('VITE_AMAP_SECURITY_JS_CODE', 'test-security-code')
    polygonOptions.length = 0
    polygonSetMapCalls.length = 0
    setFitView.mockReset()
    vi.mocked(AMapLoader.load).mockReset()
    vi.mocked(AMapLoader.load).mockResolvedValue({
      Map: FakeMap,
      Marker: FakeMarker,
      Polygon: FakePolygon,
    } as never)
  })

  it('converts WGS84 cells, colors zero, and keeps the buffer outline above risk fills', async () => {
    const wrapper = mount(MapCanvas, {
      props: {
        bufferGeometry,
        riskSpatialResult: spatialResult('task-1'),
      },
    })
    await flushPromises()

    const buffer = polygonOptions.find((options) => options.zIndex === 30)
    const risk = polygonOptions.find((options) => options.zIndex === 20)
    expect(buffer?.strokeWeight).toBe(2)
    expect(risk?.fillColor).toBe(RISK_VALUE_COLOR_BINS[0]!.color)
    expect(risk?.path[0]?.[0]).toEqual(wgs84ToGcj02([118.8, 32.0]))
    expect(wrapper.text()).toContain('[0.0, 0.2)')
    expect(wrapper.text()).toContain('[0.8, 1.0]')
    expect(wrapper.text()).not.toMatch(/低风险|中风险|高风险/)

    wrapper.unmount()
  })

  it('fits each new task once only when it has cells and removes stale overlays', async () => {
    const wrapper = mount(MapCanvas, {
      props: { riskSpatialResult: spatialResult('task-1') },
    })
    await flushPromises()
    expect(setFitView).toHaveBeenCalledTimes(1)
    const firstRiskSetMap = polygonSetMapCalls[0]!

    await wrapper.setProps({ riskSpatialResult: spatialResult('task-1', [0.2]) })
    expect(setFitView).toHaveBeenCalledTimes(1)
    expect(firstRiskSetMap).toHaveBeenCalledWith(null)

    await wrapper.setProps({ riskSpatialResult: spatialResult('task-empty', []) })
    expect(setFitView).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ riskSpatialResult: spatialResult('task-2', [1]) })
    expect(setFitView).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })
})
