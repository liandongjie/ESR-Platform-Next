<script setup lang="ts">
import AMapLoader from '@amap/amap-jsapi-loader'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { gcj02ToWgs84, wgs84ToGcj02 } from '@/map/coordinates'
import type {
  BufferGeometry,
  Coordinate,
  PointGeometry,
  PolygonGeometry,
} from '@/types/analysisArea'

interface Props {
  sourcePoint?: PointGeometry | null
  bufferGeometry?: BufferGeometry | null
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

interface MapInstance {
  on: (event: 'click', handler: (event: AMapMouseEvent) => void) => void
  off: (event: 'click', handler: (event: AMapMouseEvent) => void) => void
  setFitView: (overlays?: OverlayInstance[]) => void
  destroy: () => void
}

interface AMapNamespace {
  Map: new (
    container: HTMLElement,
    options: { zoom: number; center: Coordinate; viewMode: string },
  ) => MapInstance
  Marker: new (options: { position: Coordinate }) => OverlayInstance
  Polygon: new (options: {
    path: Coordinate[][]
    strokeColor: string
    strokeWeight: number
    fillColor: string
    fillOpacity: number
  }) => OverlayInstance
}

const props = withDefaults(defineProps<Props>(), {
  sourcePoint: null,
  bufferGeometry: null,
  selectionDisabled: false,
})
const emit = defineEmits<{
  'select-point': [coordinates: Coordinate]
}>()

const container = ref<HTMLElement | null>(null)
const state = ref<'loading' | 'ready' | 'missing-key' | 'error'>('loading')
const errorMessage = ref('')
let map: MapInstance | null = null
let amap: AMapNamespace | null = null
let marker: OverlayInstance | null = null
let bufferOverlays: OverlayInstance[] = []

function parseNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function removeMarker() {
  marker?.setMap(null)
  marker = null
}

function removeBufferOverlays() {
  bufferOverlays.forEach((overlay) => overlay.setMap(null))
  bufferOverlays = []
}

function renderSourcePoint() {
  removeMarker()
  if (!map || !amap || !props.sourcePoint) return

  // Pinia/API 中保存的是 WGS84；只有创建高德覆盖物时才转换成 GCJ-02。
  const position = wgs84ToGcj02(props.sourcePoint.coordinates)
  marker = new amap.Marker({ position })
  marker.setMap(map)
}

function createPolygonOverlay(geometry: PolygonGeometry): OverlayInstance | null {
  if (!map || !amap) return null

  const path = geometry.coordinates.map((ring) => ring.map(wgs84ToGcj02))
  const polygon = new amap.Polygon({
    path,
    strokeColor: '#3370ff',
    strokeWeight: 2,
    fillColor: '#3370ff',
    fillOpacity: 0.16,
  })
  polygon.setMap(map)
  return polygon
}

function renderBufferGeometry() {
  removeBufferOverlays()
  if (!map || !amap || !props.bufferGeometry) return

  if (props.bufferGeometry.type === 'Polygon') {
    const overlay = createPolygonOverlay(props.bufferGeometry)
    if (overlay) bufferOverlays.push(overlay)
  } else {
    for (const coordinates of props.bufferGeometry.coordinates) {
      const overlay = createPolygonOverlay({ type: 'Polygon', coordinates })
      if (overlay) bufferOverlays.push(overlay)
    }
  }

  if (bufferOverlays.length > 0) {
    map.setFitView(bufferOverlays)
  }
}

function handleMapClick(event: AMapMouseEvent) {
  // 异步分析没有取消能力时禁止切换研究点，避免客户端丢失仍在 Worker 中执行的 task_id。
  if (props.selectionDisabled) return

  const gcj02: Coordinate = [event.lnglat.getLng(), event.lnglat.getLat()]
  // 高德点击事件是 GCJ-02；离开地图适配层前必须转回 WGS84，后续业务状态和后端统一使用 EPSG:4326。
  emit('select-point', gcj02ToWgs84(gcj02))
}

watch(() => props.sourcePoint, renderSourcePoint, { deep: true })
watch(() => props.bufferGeometry, renderBufferGeometry, { deep: true })

onMounted(async () => {
  const key = import.meta.env.VITE_AMAP_JS_API_KEY?.trim()
  const securityCode = import.meta.env.VITE_AMAP_SECURITY_JS_CODE?.trim()
  if (!key || !securityCode) {
    state.value = 'missing-key'
    return
  }

  if (!container.value) {
    state.value = 'error'
    errorMessage.value = '地图容器未就绪'
    return
  }

  window._AMapSecurityConfig = { securityJsCode: securityCode }

  try {
    amap = (await AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar'],
    })) as unknown as AMapNamespace
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
    renderSourcePoint()
    renderBufferGeometry()
  } catch (error: unknown) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '地图初始化失败'
  }
})

onBeforeUnmount(() => {
  if (map) {
    // AMap 实例和覆盖物只属于当前组件生命周期，不进入 Pinia；卸载时统一解除事件并销毁，避免热更新/路由切换残留监听。
    map.off('click', handleMapClick)
  }
  removeMarker()
  removeBufferOverlays()
  map?.destroy()
  map = null
  amap = null
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
      {{ props.selectionDisabled ? '分析任务进行中，暂不可更换研究点' : '点击地图选择研究点' }}
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
</style>
