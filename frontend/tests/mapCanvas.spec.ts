import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MapCanvas from '../src/components/map/MapCanvas.vue'
import { gcj02ToWgs84, wgs84ToGcj02 } from '../src/map/coordinates'
import { RISK_VALUE_COLOR_BINS, riskColorForValue } from '../src/map/riskSpatial'
import type { MultiPolygonGeometry, PolygonGeometry } from '../src/types/analysisArea'
import type { RiskAnalysisSpatialResult } from '../src/types/riskAnalysis'

type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'

const markerOptions: Array<Record<string, unknown>> = []
const polygonOptions: Array<Record<string, unknown>> = []
const polylineOptions: Array<Record<string, unknown>> = []
const markers: FakeMarker[] = []
const polygons: FakePolygon[] = []
const polylines: FakePolyline[] = []
const mouseTools: FakeMouseTool[] = []
const maps: FakeMap[] = []
let mapClickHandler: ((event: unknown) => void) | undefined
let drawHandler: ((event: { obj: unknown }) => void) | undefined
let failNextDrawListenerRegistration = false
let failNextDrawingMode: DrawingMode | null = null

class FakeMap {
  on = vi.fn((eventName: string, handler: (event: unknown) => void) => {
    if (eventName === 'click') {
      mapClickHandler = handler
    }
  })

  off = vi.fn()
  destroy = vi.fn()
  setFitView = vi.fn()

  constructor() {
    maps.push(this)
  }
}

class FakeMarker {
  setMap = vi.fn()

  constructor(options: Record<string, unknown>) {
    markerOptions.push(options)
    markers.push(this)
  }
}

class FakePolygon {
  setMap = vi.fn()

  constructor(options: Record<string, unknown>) {
    polygonOptions.push(options)
    polygons.push(this)
  }
}

class FakePolyline {
  setMap = vi.fn()

  constructor(options: Record<string, unknown>) {
    polylineOptions.push(options)
    polylines.push(this)
  }
}

class FakeMouseTool {
  marker = vi.fn(() => this.failModeStart('point'))
  polyline = vi.fn(() => this.failModeStart('polyline'))
  rectangle = vi.fn(() => this.failModeStart('rectangle'))
  polygon = vi.fn(() => this.failModeStart('polygon'))
  close = vi.fn()
  on = vi.fn((eventName: string, handler: (event: { obj: unknown }) => void) => {
    if (failNextDrawListenerRegistration) {
      failNextDrawListenerRegistration = false
      throw new Error('draw listener 注册失败')
    }
    if (eventName === 'draw') {
      drawHandler = handler
    }
  })
  off = vi.fn((eventName: string, handler: (event: { obj: unknown }) => void) => {
    if (eventName === 'draw' && drawHandler === handler) {
      drawHandler = undefined
    }
  })

  constructor() {
    mouseTools.push(this)
  }

  private failModeStart(mode: DrawingMode) {
    if (failNextDrawingMode !== mode) return
    failNextDrawingMode = null
    throw new Error(`${mode} 启动失败`)
  }
}

interface TestAmapNamespace {
  Map: typeof FakeMap
  Marker: typeof FakeMarker
  Polygon: typeof FakePolygon
  Polyline: typeof FakePolyline
  MouseTool?: typeof FakeMouseTool
  plugin: ReturnType<typeof vi.fn>
}

let amapNamespace: TestAmapNamespace

vi.mock('../src/map/amap', () => ({
  hasAmapConfiguration: vi.fn(() => true),
  loadAmap: vi.fn(async () => amapNamespace),
}))

interface DrawingApi {
  startDrawing: (mode: DrawingMode) => Promise<void>
  cancelDrawing: () => void
}

function drawingApi(wrapper: VueWrapper): DrawingApi {
  return wrapper.vm as unknown as DrawingApi
}

function lngLat(lng: number, lat: number) {
  return {
    getLng: () => lng,
    getLat: () => lat,
  }
}

function riskSpatialResult(taskId = 'task-1', values = [0.8]): RiskAnalysisSpatialResult {
  return {
    schema_version: 1 as const,
    task_id: taskId,
    crs: 'EPSG:4326' as const,
    value_range: { minimum: 0 as const, maximum: 1 as const },
    feature_collection: {
      type: 'FeatureCollection' as const,
      features: values.map((value, index) =>
        ({
          type: 'Feature' as const,
          geometry: {
            type: 'Polygon' as const,
            coordinates: [
              [
                [116.397 + index * 0.01, 39.908],
                [116.407 + index * 0.01, 39.908],
                [116.407 + index * 0.01, 39.918],
                [116.397 + index * 0.01, 39.918],
                [116.397 + index * 0.01, 39.908],
              ],
            ],
          },
          properties: { value },
        }) as RiskAnalysisSpatialResult['feature_collection']['features'][number],
      ),
    },
  }
}

async function mountReady(props: Record<string, unknown> = {}) {
  const wrapper = mount(MapCanvas, {
    props: {
      sourceGeometry: null,
      bufferGeometry: null,
      poiItems: [],
      selectedPoiId: null,
      riskSpatialResult: null,
      ...props,
    },
  })
  await flushPromises()
  return wrapper
}

function completeDraw(obj: unknown) {
  expect(drawHandler).toBeTypeOf('function')
  drawHandler?.({ obj })
}

beforeEach(() => {
  markerOptions.length = 0
  polygonOptions.length = 0
  polylineOptions.length = 0
  markers.length = 0
  polygons.length = 0
  polylines.length = 0
  mouseTools.length = 0
  maps.length = 0
  mapClickHandler = undefined
  drawHandler = undefined
  failNextDrawListenerRegistration = false
  failNextDrawingMode = null
  amapNamespace = {
    Map: FakeMap,
    Marker: FakeMarker,
    Polygon: FakePolygon,
    Polyline: FakePolyline,
    MouseTool: FakeMouseTool,
    plugin: vi.fn((_plugins: string | string[], callback: () => void) => callback()),
  }
})

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

describe('MapCanvas source and spatial overlays', () => {
  it('converts WGS84 source coordinates to GCJ-02 without mutating the source geometry', async () => {
    const sourceGeometry = {
      type: 'Point' as const,
      coordinates: [116.397, 39.908] as [number, number],
    }
    const originalCoordinates = [...sourceGeometry.coordinates]

    const wrapper = await mountReady({ sourceGeometry })

    expect(markerOptions[0]?.position).toEqual(wgs84ToGcj02(sourceGeometry.coordinates))
    expect(sourceGeometry.coordinates).toEqual(originalCoordinates)
    wrapper.unmount()
  })

  it('renders and replaces Point, LineString, and Polygon source overlays independently', async () => {
    const wrapper = await mountReady({
      sourceGeometry: { type: 'Point', coordinates: [116.397, 39.908] },
      bufferGeometry: {
        type: 'Polygon',
        coordinates: [
          [
            [116.39, 39.9],
            [116.4, 39.9],
            [116.4, 39.91],
            [116.39, 39.9],
          ],
        ],
      },
    })
    const sourceMarker = markers[0]
    const bufferPolygon = polygons.find((_polygon, index) => polygonOptions[index]?.zIndex === 30)

    await wrapper.setProps({
      sourceGeometry: {
        type: 'LineString',
        coordinates: [
          [116.397, 39.908],
          [116.407, 39.918],
        ],
      },
    })

    expect(sourceMarker?.setMap).toHaveBeenCalledWith(null)
    expect(polylineOptions.at(-1)?.path).toEqual([
      wgs84ToGcj02([116.397, 39.908]),
      wgs84ToGcj02([116.407, 39.918]),
    ])

    const sourcePolyline = polylines.at(-1)
    await wrapper.setProps({
      sourceGeometry: {
        type: 'Polygon',
        coordinates: [
          [
            [116.397, 39.908],
            [116.407, 39.908],
            [116.407, 39.918],
            [116.397, 39.908],
          ],
        ],
      },
    })

    expect(sourcePolyline?.setMap).toHaveBeenCalledWith(null)
    expect(polygonOptions.at(-1)?.path).toEqual([
      [
        wgs84ToGcj02([116.397, 39.908]),
        wgs84ToGcj02([116.407, 39.908]),
        wgs84ToGcj02([116.407, 39.918]),
        wgs84ToGcj02([116.397, 39.908]),
      ],
    ])
    expect(bufferPolygon?.setMap).not.toHaveBeenCalledWith(null)
    wrapper.unmount()
  })

  it('renders every source Polygon ring and MultiPolygon member and clears their lifecycle', async () => {
    const polygonWithHole: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [116.39, 39.9],
          [116.42, 39.9],
          [116.42, 39.93],
          [116.39, 39.9],
        ],
        [
          [116.4, 39.91],
          [116.41, 39.91],
          [116.41, 39.92],
          [116.4, 39.91],
        ],
      ],
    }
    const multiPolygon: MultiPolygonGeometry = {
      type: 'MultiPolygon',
      coordinates: [
        polygonWithHole.coordinates,
        [
          [
            [116.44, 39.94],
            [116.46, 39.94],
            [116.46, 39.96],
            [116.44, 39.94],
          ],
        ],
      ],
    }
    const originalMultiPolygon = structuredClone(multiPolygon)
    const wrapper = await mountReady({ sourceGeometry: polygonWithHole })
    const polygonOverlay = polygons[0]!

    expect(polygonOptions[0]?.path).toEqual(
      polygonWithHole.coordinates.map((ring) => ring.map(wgs84ToGcj02)),
    )

    await wrapper.setProps({ sourceGeometry: multiPolygon })

    expect(polygonOverlay.setMap).toHaveBeenCalledWith(null)
    expect(polygonOptions.slice(1).map((options) => options.path)).toEqual(
      multiPolygon.coordinates.map((member) => member.map((ring) => ring.map(wgs84ToGcj02))),
    )
    expect(multiPolygon).toEqual(originalMultiPolygon)

    const multiPolygonOverlays = polygons.slice(1)
    await wrapper.setProps({ sourceGeometry: null })
    multiPolygonOverlays.forEach((overlay) => expect(overlay.setMap).toHaveBeenCalledWith(null))

    await wrapper.setProps({ sourceGeometry: multiPolygon })
    const remountedOverlays = polygons.slice(-2)
    wrapper.unmount()
    remountedOverlays.forEach((overlay) => expect(overlay.setMap).toHaveBeenCalledWith(null))
    expect(multiPolygon).toEqual(originalMultiPolygon)
  })

  it('clears replaced buffer overlays', async () => {
    const firstGeometry: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [116.39, 39.9],
          [116.4, 39.9],
          [116.4, 39.91],
          [116.39, 39.9],
        ],
      ],
    }
    const secondGeometry: PolygonGeometry = {
      type: 'Polygon',
      coordinates: [
        [
          [116.41, 39.92],
          [116.42, 39.92],
          [116.42, 39.93],
          [116.41, 39.92],
        ],
      ],
    }

    const wrapper = await mountReady({ bufferGeometry: firstGeometry })
    const firstOverlay = polygons[0]

    await wrapper.setProps({ bufferGeometry: secondGeometry })

    expect(firstOverlay?.setMap).toHaveBeenCalledWith(null)
    expect(polygonOptions).toHaveLength(2)
    wrapper.unmount()
  })

  it('replaces WGS84 POIs with GCJ-02 markers and clears their lifecycle', async () => {
    const wrapper = await mountReady({
      poiItems: [
        {
          id: 'poi-1',
          name: '学校',
          type: '',
          typeCode: '',
          address: '',
          locationWgs84: [116.397, 39.908],
        },
      ],
    })

    expect(markerOptions).toHaveLength(1)
    expect(markerOptions[0]?.position).toEqual(wgs84ToGcj02([116.397, 39.908]))
    expect(markerOptions[0]?.title).toBe('学校')
    const firstMarker = markers[0]

    await wrapper.setProps({
      poiItems: [
        {
          id: 'poi-2',
          name: '医院',
          type: '',
          typeCode: '',
          address: '',
          locationWgs84: [116.407, 39.918],
        },
      ],
    })

    expect(firstMarker?.setMap).toHaveBeenCalledWith(null)
    expect(markerOptions[1]?.position).toEqual(wgs84ToGcj02([116.407, 39.918]))
    const secondMarker = markers[1]
    wrapper.unmount()
    expect(secondMarker?.setMap).toHaveBeenCalledWith(null)
  })

  it('converts risk cells to GCJ-02 and keeps the Buffer above the colored risk fill', async () => {
    const wrapper = await mountReady({
      bufferGeometry: {
        type: 'Polygon',
        coordinates: [
          [
            [116.39, 39.9],
            [116.42, 39.9],
            [116.42, 39.93],
            [116.39, 39.9],
          ],
        ],
      },
      riskSpatialResult: riskSpatialResult('task-1', [0]),
    })

    const buffer = polygonOptions.find((options) => options.zIndex === 30)
    const risk = polygonOptions.find((options) => options.zIndex === 20)
    const riskPath = risk?.path as Array<Array<[number, number]>> | undefined
    expect(buffer?.strokeWeight).toBe(2)
    expect(risk?.fillColor).toBe(RISK_VALUE_COLOR_BINS[0]!.color)
    expect(riskPath?.[0]?.[0]).toEqual(wgs84ToGcj02([116.397, 39.908]))
    expect(wrapper.text()).toContain('[0.0, 0.2)')
    expect(wrapper.text()).toContain('[0.8, 1.0]')
    expect(wrapper.text()).not.toMatch(/低风险|中风险|高风险/)
    wrapper.unmount()
  })

  it('fits each task once and replaces or clears stale risk overlays', async () => {
    const wrapper = await mountReady({ riskSpatialResult: riskSpatialResult('task-1', [0]) })
    const map = maps[0]!
    const firstRiskPolygon = polygons[0]!

    expect(map.setFitView).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ riskSpatialResult: riskSpatialResult('task-1', [0.2]) })
    expect(map.setFitView).toHaveBeenCalledTimes(1)
    expect(firstRiskPolygon.setMap).toHaveBeenCalledWith(null)

    const replacementRiskPolygon = polygons.at(-1)!
    await wrapper.setProps({ riskSpatialResult: riskSpatialResult('task-empty', []) })
    expect(map.setFitView).toHaveBeenCalledTimes(1)
    expect(replacementRiskPolygon.setMap).toHaveBeenCalledWith(null)

    await wrapper.setProps({ riskSpatialResult: riskSpatialResult('task-2', [1]) })
    expect(map.setFitView).toHaveBeenCalledTimes(2)
    const newTaskRiskPolygon = polygons.at(-1)!

    await wrapper.setProps({ riskSpatialResult: null })

    expect(newTaskRiskPolygon.setMap).toHaveBeenCalledWith(null)
    wrapper.unmount()
  })

  it('converts a normal map click to WGS84 and emits select-point', async () => {
    const wrapper = await mountReady()

    mapClickHandler?.({ lnglat: lngLat(116.403, 39.91) })

    expect(wrapper.emitted('select-point')?.[0]?.[0]).toEqual(gcj02ToWgs84([116.403, 39.91]))
    wrapper.unmount()
  })

  it.each([
    [{ readOnly: true, selectionDisabled: false }, '历史结果只读展示'],
    [{ readOnly: false, selectionDisabled: true }, '分析任务进行中，暂不可更换研究点'],
  ])('blocks ordinary map selection in guarded mode', async (mode, expectedTip) => {
    const wrapper = await mountReady(mode)

    mapClickHandler?.({ lnglat: lngLat(116.403, 39.91) })

    expect(wrapper.text()).toContain(expectedTip)
    expect(wrapper.emitted('select-point')).toBeUndefined()
    wrapper.unmount()
  })
})

describe('MapCanvas MouseTool drawing', () => {
  it.each([
    ['point', 'marker'],
    ['polyline', 'polyline'],
    ['rectangle', 'rectangle'],
    ['polygon', 'polygon'],
  ] as const)('starts %s drawing with the corresponding MouseTool method', async (mode, method) => {
    const wrapper = await mountReady()

    await drawingApi(wrapper).startDrawing(mode)

    expect(amapNamespace.plugin).toHaveBeenCalledWith('AMap.MouseTool', expect.any(Function))
    expect(mouseTools).toHaveLength(1)
    expect(mouseTools[0]?.[method]).toHaveBeenCalledOnce()
    expect(wrapper.emitted('drawing-mode-change')?.at(-1)?.[0]).toBe(mode)
    wrapper.unmount()
  })

  it('converts Point, LineString, Polygon, and Rectangle drawing results to WGS84 geometries', async () => {
    const wrapper = await mountReady()
    const point = [116.403, 39.91] as [number, number]
    const path = [
      [116.403, 39.91],
      [116.413, 39.92],
      [116.423, 39.91],
    ] as Array<[number, number]>

    await drawingApi(wrapper).startDrawing('point')
    completeDraw({ getPosition: () => lngLat(...point), setMap: vi.fn() })

    await drawingApi(wrapper).startDrawing('polyline')
    completeDraw({ getPath: () => path.map(([lng, lat]) => lngLat(lng, lat)), setMap: vi.fn() })

    await drawingApi(wrapper).startDrawing('polygon')
    completeDraw({ getPath: () => path.map(([lng, lat]) => lngLat(lng, lat)), setMap: vi.fn() })

    await drawingApi(wrapper).startDrawing('rectangle')
    completeDraw({
      getBounds: () => ({
        getSouthWest: () => lngLat(116.403, 39.91),
        getNorthEast: () => lngLat(116.423, 39.92),
      }),
      setMap: vi.fn(),
    })

    const emitted = wrapper.emitted('select-geometry')?.map((events) => events[0])
    expect(emitted).toEqual([
      { type: 'Point', coordinates: gcj02ToWgs84(point) },
      { type: 'LineString', coordinates: path.map(gcj02ToWgs84) },
      {
        type: 'Polygon',
        coordinates: [[...path.map(gcj02ToWgs84), gcj02ToWgs84(path[0])]],
      },
      {
        type: 'Polygon',
        coordinates: [
          [
            gcj02ToWgs84([116.403, 39.91]),
            gcj02ToWgs84([116.423, 39.91]),
            gcj02ToWgs84([116.423, 39.92]),
            gcj02ToWgs84([116.403, 39.92]),
            gcj02ToWgs84([116.403, 39.91]),
          ],
        ],
      },
    ])
    expect(mouseTools[0]?.close).toHaveBeenCalledWith(true)
    wrapper.unmount()
  })

  it.each(['point', 'polygon'] as const)(
    'suppresses the map click from the same physical %s draw completion',
    async (mode) => {
      const wrapper = await mountReady()
      const path = [
        [116.403, 39.91],
        [116.413, 39.92],
        [116.423, 39.91],
      ] as Array<[number, number]>

      await drawingApi(wrapper).startDrawing(mode)
      if (mode === 'point') {
        completeDraw({ getPosition: () => lngLat(116.403, 39.91), setMap: vi.fn() })
      } else {
        completeDraw({ getPath: () => path.map(([lng, lat]) => lngLat(lng, lat)), setMap: vi.fn() })
      }
      mapClickHandler?.({ lnglat: lngLat(116.403, 39.91) })

      expect(wrapper.emitted('select-geometry')).toHaveLength(1)
      expect(wrapper.emitted('select-point')).toBeUndefined()
      wrapper.unmount()
    },
  )

  it('suppresses ordinary map selection while drawing is active', async () => {
    const wrapper = await mountReady()

    await drawingApi(wrapper).startDrawing('point')
    mapClickHandler?.({ lnglat: lngLat(116.403, 39.91) })

    expect(wrapper.emitted('select-point')).toBeUndefined()
    wrapper.unmount()
  })

  it('cancels only the pending draw and preserves the committed source overlay', async () => {
    const wrapper = await mountReady({
      sourceGeometry: { type: 'Point', coordinates: [116.397, 39.908] },
    })
    const sourceMarker = markers[0]

    await drawingApi(wrapper).startDrawing('polygon')
    drawingApi(wrapper).cancelDrawing()

    expect(mouseTools[0]?.close).toHaveBeenCalledWith(true)
    expect(sourceMarker?.setMap).not.toHaveBeenCalledWith(null)
    expect(wrapper.emitted('select-geometry')).toBeUndefined()
    expect(wrapper.emitted('drawing-mode-change')?.at(-1)?.[0]).toBeNull()
    wrapper.unmount()
  })

  it('switches modes without creating duplicate MouseTool instances or draw listeners', async () => {
    const wrapper = await mountReady()

    await drawingApi(wrapper).startDrawing('point')
    await drawingApi(wrapper).startDrawing('polygon')
    await drawingApi(wrapper).startDrawing('rectangle')

    expect(mouseTools).toHaveLength(1)
    expect(mouseTools[0]?.on).toHaveBeenCalledOnce()
    expect(mouseTools[0]?.close).toHaveBeenCalledTimes(2)
    expect(mouseTools[0]?.rectangle).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('retries MouseTool plugin loading after a failed attempt', async () => {
    const wrapper = await mountReady()
    amapNamespace.MouseTool = undefined

    await drawingApi(wrapper).startDrawing('point')

    expect(wrapper.emitted('drawing-error')?.at(-1)?.[0]).toContain('加载失败')
    expect(amapNamespace.plugin).toHaveBeenCalledTimes(1)

    amapNamespace.MouseTool = FakeMouseTool
    await drawingApi(wrapper).startDrawing('point')

    expect(amapNamespace.plugin).toHaveBeenCalledTimes(2)
    expect(mouseTools[0]?.marker).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('reloads the plugin after the MouseTool constructor throws', async () => {
    const wrapper = await mountReady()
    class ThrowingMouseTool {
      constructor() {
        throw new Error('MouseTool 构造失败')
      }
    }
    amapNamespace.MouseTool = ThrowingMouseTool as unknown as typeof FakeMouseTool

    await drawingApi(wrapper).startDrawing('point')

    expect(wrapper.emitted('drawing-error')?.at(-1)?.[0]).toContain('构造失败')
    expect(amapNamespace.plugin).toHaveBeenCalledTimes(1)

    amapNamespace.MouseTool = FakeMouseTool
    await drawingApi(wrapper).startDrawing('point')

    expect(amapNamespace.plugin).toHaveBeenCalledTimes(2)
    expect(mouseTools[0]?.marker).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('creates a new MouseTool after draw listener registration fails', async () => {
    const wrapper = await mountReady()
    failNextDrawListenerRegistration = true

    await drawingApi(wrapper).startDrawing('point')

    expect(mouseTools).toHaveLength(1)
    expect(mouseTools[0]?.off).toHaveBeenCalledWith('draw', expect.any(Function))
    expect(mouseTools[0]?.close).toHaveBeenCalledWith(true)
    expect(wrapper.emitted('drawing-error')?.at(-1)?.[0]).toContain('listener 注册失败')

    await drawingApi(wrapper).startDrawing('point')

    expect(mouseTools).toHaveLength(2)
    expect(mouseTools[1]?.on).toHaveBeenCalledOnce()
    expect(mouseTools[1]?.marker).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('creates a new MouseTool after starting a drawing mode fails', async () => {
    const wrapper = await mountReady()
    failNextDrawingMode = 'polygon'

    await drawingApi(wrapper).startDrawing('polygon')

    expect(mouseTools).toHaveLength(1)
    expect(mouseTools[0]?.off).toHaveBeenCalledWith('draw', expect.any(Function))
    expect(mouseTools[0]?.close).toHaveBeenCalledWith(true)
    expect(wrapper.emitted('drawing-error')?.at(-1)?.[0]).toContain('polygon 启动失败')

    await drawingApi(wrapper).startDrawing('polygon')

    expect(mouseTools).toHaveLength(2)
    expect(mouseTools[1]?.on).toHaveBeenCalledOnce()
    expect(mouseTools[1]?.polygon).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('rejects malformed drawing output without replacing the old source', async () => {
    const wrapper = await mountReady({
      sourceGeometry: { type: 'Point', coordinates: [116.397, 39.908] },
    })
    const sourceMarker = markers[0]
    const pendingOverlay = { getPath: () => [lngLat(116.403, 39.91)], setMap: vi.fn() }

    await drawingApi(wrapper).startDrawing('polyline')
    completeDraw(pendingOverlay)

    expect(wrapper.emitted('select-geometry')).toBeUndefined()
    expect(wrapper.emitted('drawing-error')?.at(-1)?.[0]).toContain('至少需要两个不同点')
    expect(mouseTools[0]?.close).toHaveBeenCalledWith(true)
    expect(sourceMarker?.setMap).not.toHaveBeenCalledWith(null)
    wrapper.unmount()
  })

  it('guards start and late draw callbacks when selection is locked', async () => {
    const lockedWrapper = await mountReady({ selectionDisabled: true })

    await drawingApi(lockedWrapper).startDrawing('point')

    expect(amapNamespace.plugin).not.toHaveBeenCalled()
    lockedWrapper.unmount()

    const wrapper = await mountReady()
    await drawingApi(wrapper).startDrawing('point')
    const lateHandler = drawHandler

    await wrapper.setProps({ selectionDisabled: true })
    lateHandler?.({ obj: { getPosition: () => lngLat(116.403, 39.91), setMap: vi.fn() } })

    expect(mouseTools.at(-1)?.close).toHaveBeenCalledWith(true)
    expect(wrapper.emitted('select-geometry')).toBeUndefined()
    wrapper.unmount()
  })
})
