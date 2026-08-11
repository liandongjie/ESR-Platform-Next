<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { hasAmapConfiguration, loadAmap } from '@/map/amap'
import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'
import { RISK_VALUE_COLOR_BINS, riskColorForValue } from '@/map/riskSpatial'
import type {
  BufferGeometry,
  Coordinate,
  PolygonGeometry,
  SourceGeometry,
} from '@/types/analysisArea'
import type { RiskAnalysisSpatialResult } from '@/types/riskAnalysis'
import type { PoiDto } from '@/types/poi'
import { parseSourceGeometry } from '@/validation/sourceGeometry'

type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'

interface Props {
  sourceGeometry?: SourceGeometry | null
  bufferGeometry?: BufferGeometry | null
  riskSpatialResult?: RiskAnalysisSpatialResult | null
  poiItems?: PoiDto[]
  readOnly?: boolean
  selectionDisabled?: boolean
}

interface AMapLngLat {
  getLng: () => number
  getLat: () => number
}

interface AMapMouseEvent {
  lnglat: AMapLngLat
}

interface OverlayInstance {
  setMap: (map: MapInstance | null) => void
}

interface DrawingOverlay extends OverlayInstance {
  getPosition?: () => unknown
  getPath?: () => unknown
  getBounds?: () => unknown
}

interface AMapBounds {
  getSouthWest: () => unknown
  getNorthEast: () => unknown
}

interface MapInstance {
  on: (event: 'click', handler: (event: AMapMouseEvent) => void) => void
  off: (event: 'click', handler: (event: AMapMouseEvent) => void) => void
  setFitView: (overlays?: OverlayInstance[]) => void
  destroy: () => void
}

interface AMapNamespace {
  plugin: (name: string, callback: () => void) => void
  Map: new (
    container: HTMLElement,
    options: { zoom: number; center: Coordinate; viewMode: string },
  ) => MapInstance
  Marker: new (options: { position: Coordinate; title?: string }) => OverlayInstance
  Polyline: new (options: {
    path: Coordinate[]
    strokeColor: string
    strokeWeight: number
    strokeOpacity: number
    zIndex: number
  }) => OverlayInstance
  Polygon: new (options: {
    path: Coordinate[][]
    strokeColor: string
    strokeWeight: number
    fillColor: string
    fillOpacity: number
    zIndex: number
  }) => OverlayInstance
  MouseTool?: new (map: MapInstance) => MouseToolInstance
}

interface MouseToolInstance {
  marker: (options: Record<string, unknown>) => void
  polyline: (options: Record<string, unknown>) => void
  rectangle: (options: Record<string, unknown>) => void
  polygon: (options: Record<string, unknown>) => void
  close: (removeOverlays?: boolean) => void
  on: (event: 'draw', handler: (event: { obj: DrawingOverlay }) => void) => void
  off?: (event: 'draw', handler: (event: { obj: DrawingOverlay }) => void) => void
}

const props = withDefaults(defineProps<Props>(), {
  sourceGeometry: null,
  bufferGeometry: null,
  riskSpatialResult: null,
  poiItems: () => [],
  readOnly: false,
  selectionDisabled: false,
})
const emit = defineEmits<{
  'select-point': [coordinates: Coordinate]
  'select-geometry': [geometry: SourceGeometry]
  'drawing-mode-change': [mode: DrawingMode | null]
  'drawing-error': [message: string]
}>()

const container = ref<HTMLElement | null>(null)
const state = ref<'loading' | 'ready' | 'missing-key' | 'error'>('loading')
const errorMessage = ref('')
let map: MapInstance | null = null
let amap: AMapNamespace | null = null
let sourceOverlay: OverlayInstance | null = null
let bufferOverlays: OverlayInstance[] = []
let riskCellOverlays: OverlayInstance[] = []
let poiMarkers: OverlayInstance[] = []
const fittedRiskTaskIds = new Set<string>()
let mouseTool: MouseToolInstance | null = null
let mouseToolPluginPromise: Promise<AMapNamespace> | null = null
let activeDrawingMode: DrawingMode | null = null
let drawingRevision = 0
let suppressNextMapClick = false
let suppressMapClickTimer: number | null = null

function parseNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function removeSourceOverlay() {
  sourceOverlay?.setMap(null)
  sourceOverlay = null
}

function removeBufferOverlays() {
  bufferOverlays.forEach((overlay) => overlay.setMap(null))
  bufferOverlays = []
}

function removeRiskCellOverlays() {
  riskCellOverlays.forEach((overlay) => overlay.setMap(null))
  riskCellOverlays = []
}

function removePoiMarkers() {
  poiMarkers.forEach((poiMarker) => poiMarker.setMap(null))
  poiMarkers = []
}

function renderPoiMarkers() {
  removePoiMarkers()
  if (!map || !amap) return

  for (const poi of props.poiItems) {
    const poiMarker = new amap.Marker({
      position: wgs84ToGcj02(poi.locationWgs84),
      title: poi.name,
    })
    poiMarker.setMap(map)
    poiMarkers.push(poiMarker)
  }
}

function renderSourceGeometry() {
  removeSourceOverlay()
  if (!map || !amap || !props.sourceGeometry) return

  // Pinia/API 中保存的是 WGS84；只有创建高德覆盖物时才转换成 GCJ-02。
  if (props.sourceGeometry.type === 'Point') {
    sourceOverlay = new amap.Marker({ position: wgs84ToGcj02(props.sourceGeometry.coordinates) })
  } else if (props.sourceGeometry.type === 'LineString') {
    sourceOverlay = new amap.Polyline({
      path: props.sourceGeometry.coordinates.map(wgs84ToGcj02),
      strokeColor: '#0091ea',
      strokeWeight: 3,
      strokeOpacity: 1,
      zIndex: 40,
    })
  } else {
    sourceOverlay = new amap.Polygon({
      path: props.sourceGeometry.coordinates.map((ring) => ring.map(wgs84ToGcj02)),
      strokeColor: '#0091ea',
      strokeWeight: 2,
      fillColor: '#80d8ff',
      fillOpacity: 0.22,
      zIndex: 40,
    })
  }
  sourceOverlay.setMap(map)
}

function createPolygonOverlay(
  geometry: PolygonGeometry,
  style: {
    strokeColor: string
    strokeWeight: number
    fillColor: string
    fillOpacity: number
    zIndex: number
  },
): OverlayInstance | null {
  if (!map || !amap) return null

  const path = geometry.coordinates.map((ring) => ring.map(wgs84ToGcj02))
  const polygon = new amap.Polygon({
    path,
    ...style,
  })
  polygon.setMap(map)
  return polygon
}

function renderBufferGeometry() {
  removeBufferOverlays()
  if (!map || !amap || !props.bufferGeometry) return

  if (props.bufferGeometry.type === 'Polygon') {
    const overlay = createPolygonOverlay(props.bufferGeometry, {
      strokeColor: '#3370ff',
      strokeWeight: 2,
      fillColor: '#3370ff',
      fillOpacity: 0.12,
      zIndex: 30,
    })
    if (overlay) bufferOverlays.push(overlay)
  } else {
    for (const coordinates of props.bufferGeometry.coordinates) {
      const overlay = createPolygonOverlay(
        { type: 'Polygon', coordinates },
        {
          strokeColor: '#3370ff',
          strokeWeight: 2,
          fillColor: '#3370ff',
          fillOpacity: 0.12,
          zIndex: 30,
        },
      )
      if (overlay) bufferOverlays.push(overlay)
    }
  }

  if (
    bufferOverlays.length > 0 &&
    !props.riskSpatialResult?.feature_collection.features.length
  ) {
    map.setFitView(bufferOverlays)
  }
}

function renderRiskCells() {
  removeRiskCellOverlays()
  if (!map || !amap || !props.riskSpatialResult) return

  for (const feature of props.riskSpatialResult.feature_collection.features) {
    const color = riskColorForValue(feature.properties.value)
    if (!color) continue
    const overlay = createPolygonOverlay(feature.geometry, {
      strokeColor: color,
      strokeWeight: 0.5,
      fillColor: color,
      fillOpacity: 0.72,
      zIndex: 20,
    })
    if (overlay) riskCellOverlays.push(overlay)
  }

  const taskId = props.riskSpatialResult.task_id
  if (riskCellOverlays.length > 0 && !fittedRiskTaskIds.has(taskId)) {
    map.setFitView(riskCellOverlays)
    fittedRiskTaskIds.add(taskId)
  }
}

function handleMapClick(event: AMapMouseEvent) {
  if (props.readOnly) return
  // 异步分析没有取消能力时禁止切换研究点，避免客户端丢失仍在 Worker 中执行的 task_id。
  if (props.selectionDisabled) return
  if (activeDrawingMode) return
  if (suppressNextMapClick) {
    clearMapClickSuppression()
    return
  }

  const gcj02: Coordinate = [event.lnglat.getLng(), event.lnglat.getLat()]
  // 高德点击事件是 GCJ-02；离开地图适配层前必须转回 WGS84，后续业务状态和后端统一使用 EPSG:4326。
  emit('select-point', gcj02ToWgs84(gcj02))
}

function setActiveDrawingMode(mode: DrawingMode | null) {
  if (activeDrawingMode === mode) return
  activeDrawingMode = mode
  emit('drawing-mode-change', mode)
}

function clearMapClickSuppression() {
  suppressNextMapClick = false
  if (suppressMapClickTimer !== null) {
    window.clearTimeout(suppressMapClickTimer)
    suppressMapClickTimer = null
  }
}

function armMapClickSuppression() {
  clearMapClickSuppression()
  suppressNextMapClick = true
  // MouseTool 的 draw 与 Map click 可能来自同一次物理点击；短暂保留一次性闩锁，避免完成绘制后又选中 Point。
  suppressMapClickTimer = window.setTimeout(clearMapClickSuppression, 250)
}

function lngLatToCoordinate(value: unknown): Coordinate {
  const point = value as Partial<AMapLngLat> | null
  if (!point || typeof point.getLng !== 'function' || typeof point.getLat !== 'function') {
    throw new Error('高德绘制结果包含无效坐标')
  }
  const coordinate: Coordinate = [point.getLng(), point.getLat()]
  if (!coordinate.every(Number.isFinite)) throw new Error('高德绘制结果包含无效坐标')
  return coordinate
}

function pathCoordinates(value: unknown): Coordinate[] {
  if (!Array.isArray(value)) throw new Error('高德绘制结果缺少有效 path')
  return value.map(lngLatToCoordinate)
}

function convertCoordinates(coordinates: Coordinate[]): Coordinate[] {
  return coordinates.map(gcj02ToWgs84)
}

function geometryFromDrawing(mode: DrawingMode, overlay: DrawingOverlay): SourceGeometry {
  if (mode === 'point') {
    if (typeof overlay.getPosition !== 'function') throw new Error('高德 Point 绘制结果无效')
    return parseSourceGeometry({
      type: 'Point',
      coordinates: gcj02ToWgs84(lngLatToCoordinate(overlay.getPosition())),
    })
  }

  if (mode === 'rectangle') {
    if (typeof overlay.getBounds !== 'function') throw new Error('高德 Rectangle 绘制结果无效')
    const bounds = overlay.getBounds() as Partial<AMapBounds> | null
    if (
      !bounds ||
      typeof bounds.getSouthWest !== 'function' ||
      typeof bounds.getNorthEast !== 'function'
    ) {
      throw new Error('高德 Rectangle 绘制结果缺少 bounds')
    }
    const [west, south] = lngLatToCoordinate(bounds.getSouthWest())
    const [east, north] = lngLatToCoordinate(bounds.getNorthEast())
    const ring = convertCoordinates([
      [west, south],
      [east, south],
      [east, north],
      [west, north],
      [west, south],
    ])
    return parseSourceGeometry({ type: 'Polygon', coordinates: [ring] })
  }

  if (typeof overlay.getPath !== 'function') throw new Error('高德绘制结果缺少有效 path')
  const coordinates = convertCoordinates(pathCoordinates(overlay.getPath()))
  if (mode === 'polyline') {
    return parseSourceGeometry({ type: 'LineString', coordinates })
  }

  if (coordinates.length > 0) {
    const first = coordinates[0]!
    const last = coordinates.at(-1)!
    if (first[0] !== last[0] || first[1] !== last[1]) {
      coordinates.push([...first] as Coordinate)
    }
  }
  return parseSourceGeometry({ type: 'Polygon', coordinates: [coordinates] })
}

function handleMouseToolDraw(event: { obj: DrawingOverlay }) {
  const mode = activeDrawingMode
  if (!mode) return
  if (props.readOnly || props.selectionDisabled) {
    cancelDrawing()
    return
  }

  try {
    const geometry = geometryFromDrawing(mode, event.obj)
    armMapClickSuppression()
    drawingRevision += 1
    setActiveDrawingMode(null)
    mouseTool?.close(true)
    emit('select-geometry', geometry)
  } catch (error: unknown) {
    clearMapClickSuppression()
    drawingRevision += 1
    setActiveDrawingMode(null)
    try {
      mouseTool?.close(true)
    } catch {
      // 原始绘制错误优先返回；卸载时仍会再次清理 MouseTool。
    }
    emit('drawing-error', error instanceof Error ? error.message : '在线绘制结果处理失败')
  }
}

async function loadMouseToolNamespace(): Promise<AMapNamespace> {
  if (!amap) throw new Error('地图尚未就绪')
  if (mouseToolPluginPromise) return mouseToolPluginPromise

  const namespace = amap
  mouseToolPluginPromise = new Promise<AMapNamespace>((resolve, reject) => {
    try {
      namespace.plugin('AMap.MouseTool', () => {
        if (typeof namespace.MouseTool === 'function') resolve(namespace)
        else reject(new Error('AMap.MouseTool 插件加载失败'))
      })
    } catch (error: unknown) {
      reject(error)
    }
  }).catch((error: unknown) => {
    // 加载失败不能污染后续尝试；下一次 startDrawing 会重新调用 plugin。
    mouseToolPluginPromise = null
    throw error
  })
  return mouseToolPluginPromise
}

function startMouseTool(mode: DrawingMode) {
  if (!mouseTool) throw new Error('AMap.MouseTool 插件不可用')
  if (mode === 'point') mouseTool.marker({ anchor: 'bottom-center', draggable: false })
  else if (mode === 'polyline') {
    mouseTool.polyline({ strokeColor: '#0ccfff', strokeWeight: 3, strokeOpacity: 1, zIndex: 130 })
  } else if (mode === 'rectangle') {
    mouseTool.rectangle({
      strokeColor: '#0091ea',
      strokeWeight: 2,
      fillColor: '#80d8ff',
      fillOpacity: 0.28,
      zIndex: 130,
    })
  } else {
    mouseTool.polygon({
      strokeColor: '#0091ea',
      strokeWeight: 2,
      fillColor: '#80d8ff',
      fillOpacity: 0.28,
      zIndex: 130,
    })
  }
}

function disposeMouseTool(instance: MouseToolInstance | null = mouseTool) {
  if (instance) {
    try {
      instance.off?.('draw', handleMouseToolDraw)
    } catch {
      // best-effort：即使解绑失败也继续关闭插件覆盖物。
    }
    try {
      instance.close(true)
    } catch {
      // 失败实例必须释放引用，下一次绘制才能重新创建。
    }
  }
  if (mouseTool === instance) mouseTool = null
}

async function startDrawing(mode: DrawingMode) {
  if (props.readOnly || props.selectionDisabled) return
  if (!map || !amap) {
    emit('drawing-error', '地图尚未就绪，无法开始在线绘制')
    return
  }

  const revision = ++drawingRevision
  try {
    mouseTool?.close(true)
    setActiveDrawingMode(mode)
    const namespace = await loadMouseToolNamespace()
    if (
      revision !== drawingRevision ||
      activeDrawingMode !== mode ||
      props.readOnly ||
      props.selectionDisabled ||
      !map
    ) {
      return
    }
    if (!mouseTool) {
      const MouseTool = namespace.MouseTool
      if (!MouseTool) throw new Error('AMap.MouseTool 插件不可用')
      const instance = new MouseTool(map)
      try {
        instance.on('draw', handleMouseToolDraw)
      } catch (error: unknown) {
        disposeMouseTool(instance)
        throw error
      }
      mouseTool = instance
    }
    startMouseTool(mode)
  } catch (error: unknown) {
    if (revision !== drawingRevision) return
    // constructor 或模式启动抛错时也允许下次重新走 plugin 加载，避免缓存半初始化命名空间。
    mouseToolPluginPromise = null
    drawingRevision += 1
    setActiveDrawingMode(null)
    disposeMouseTool()
    emit('drawing-error', error instanceof Error ? error.message : 'AMap.MouseTool 加载失败')
  }
}

function cancelDrawing() {
  drawingRevision += 1
  setActiveDrawingMode(null)
  try {
    mouseTool?.close(true)
  } catch (error: unknown) {
    emit('drawing-error', error instanceof Error ? error.message : '取消在线绘制失败')
  }
}

defineExpose({ startDrawing, cancelDrawing })

watch(() => props.sourceGeometry, renderSourceGeometry, { deep: true })
watch(() => props.bufferGeometry, renderBufferGeometry, { deep: true })
watch(() => props.riskSpatialResult, renderRiskCells, { deep: true })
watch(() => props.poiItems, renderPoiMarkers, { deep: true })
watch(
  () => props.selectionDisabled,
  (disabled) => {
    if (disabled && activeDrawingMode) cancelDrawing()
  },
)

onMounted(async () => {
  if (!hasAmapConfiguration()) {
    state.value = 'missing-key'
    return
  }

  if (!container.value) {
    state.value = 'error'
    errorMessage.value = '地图容器未就绪'
    return
  }

  try {
    amap = await loadAmap<AMapNamespace>()
    map = new amap.Map(container.value, {
      zoom: parseNumber(import.meta.env.VITE_AMAP_ZOOM, 13),
      center: [
        parseNumber(import.meta.env.VITE_AMAP_CENTER_LNG, 118.9),
        parseNumber(import.meta.env.VITE_AMAP_CENTER_LAT, 32.1),
      ],
      viewMode: '2D',
    })
    map.on('click', handleMapClick)
    state.value = 'ready'
    renderSourceGeometry()
    renderBufferGeometry()
    renderRiskCells()
    renderPoiMarkers()
  } catch (error: unknown) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '地图初始化失败'
  }
})

onBeforeUnmount(() => {
  drawingRevision += 1
  clearMapClickSuppression()
  disposeMouseTool()
  if (map) {
    // AMap 实例和覆盖物只属于当前组件生命周期，不进入 Pinia；卸载时统一解除事件并销毁，避免热更新/路由切换残留监听。
    map.off('click', handleMapClick)
  }
  removeSourceOverlay()
  removeBufferOverlays()
  removeRiskCellOverlays()
  removePoiMarkers()
  map?.destroy()
  map = null
  amap = null
  mouseToolPluginPromise = null
})
</script>

<template>
  <section class="map-card">
    <div ref="container" class="map-container" />
    <div v-if="state !== 'ready'" class="map-overlay">
      <div class="map-placeholder">
        <div class="map-placeholder-icon">⌖</div>
        <h3 v-if="state === 'loading'">正在加载地图</h3>
        <template v-else-if="state === 'missing-key'">
          <h3>高德地图密钥尚未配置</h3>
          <p>在 .env 中填写 VITE_AMAP_JS_API_KEY 和 VITE_AMAP_SECURITY_JS_CODE。</p>
        </template>
        <template v-else>
          <h3>地图加载失败</h3>
          <p>{{ errorMessage }}</p>
        </template>
      </div>
    </div>
    <div v-else class="map-tip">
      {{
        props.readOnly
          ? '历史结果只读展示'
          : props.selectionDisabled
            ? '分析任务进行中，暂不可更换研究点'
            : '点击地图选择研究点'
      }}
    </div>
    <div v-if="state === 'ready' && props.riskSpatialResult" class="risk-legend">
      <strong>综合风险值</strong>
      <div v-for="bin in RISK_VALUE_COLOR_BINS" :key="bin.label" class="risk-legend-row">
        <span class="risk-legend-swatch" :style="{ backgroundColor: bin.color }" />
        <span>{{ bin.label }}</span>
      </div>
    </div>
    <div class="map-status">
      <span class="status-dot" :class="{ online: state === 'ready' }" />
      {{ state === 'ready' ? '地图已连接' : '地图待配置' }}
    </div>
  </section>
</template>

<style scoped>
.map-tip {
  position: absolute;
  top: 14px;
  left: 14px;
  z-index: 2;
  padding: 8px 11px;
  border: 1px solid rgba(220, 228, 240, 0.92);
  border-radius: 9px;
  color: #52627f;
  background: rgba(255, 255, 255, 0.92);
  font-size: 12px;
  box-shadow: 0 8px 22px rgba(43, 73, 121, 0.08);
  backdrop-filter: blur(8px);
}

.risk-legend {
  position: absolute;
  right: 14px;
  bottom: 44px;
  z-index: 2;
  display: grid;
  gap: 5px;
  padding: 10px 12px;
  border: 1px solid rgba(220, 228, 240, 0.92);
  border-radius: 9px;
  color: #52627f;
  background: rgba(255, 255, 255, 0.92);
  font-size: 11px;
  box-shadow: 0 8px 22px rgba(43, 73, 121, 0.08);
  backdrop-filter: blur(8px);
}

.risk-legend strong {
  color: var(--text);
  font-size: 12px;
}

.risk-legend-row {
  display: flex;
  align-items: center;
  gap: 7px;
}

.risk-legend-swatch {
  width: 20px;
  height: 9px;
  border-radius: 2px;
}
</style>
