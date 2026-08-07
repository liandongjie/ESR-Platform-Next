<script setup lang="ts">
import AMapLoader from '@amap/amap-jsapi-loader'
import { onBeforeUnmount, onMounted, ref } from 'vue'

interface MapInstance {
  destroy: () => void
}

interface AMapNamespace {
  Map: new (
    container: HTMLElement,
    options: { zoom: number; center: [number, number]; viewMode: string },
  ) => MapInstance
}

const container = ref<HTMLElement | null>(null)
const state = ref<'loading' | 'ready' | 'missing-key' | 'error'>('loading')
const errorMessage = ref('')
let map: MapInstance | null = null

function parseNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

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
    const namespace = (await AMapLoader.load({
      key,
      version: '2.0',
      plugins: ['AMap.Scale', 'AMap.ToolBar'],
    })) as unknown as AMapNamespace

    map = new namespace.Map(container.value, {
      zoom: parseNumber(import.meta.env.VITE_AMAP_ZOOM, 13),
      center: [
        parseNumber(import.meta.env.VITE_AMAP_CENTER_LNG, 118.9),
        parseNumber(import.meta.env.VITE_AMAP_CENTER_LAT, 32.1),
      ],
      viewMode: '2D',
    })
    state.value = 'ready'
  } catch (error: unknown) {
    state.value = 'error'
    errorMessage.value = error instanceof Error ? error.message : '地图初始化失败'
  }
})

onBeforeUnmount(() => {
  map?.destroy()
  map = null
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

    <div class="map-status">
      <span class="status-dot" :class="{ online: state === 'ready' }" />
      {{ state === 'ready' ? '地图已连接' : '地图待配置' }}
    </div>
  </section>
</template>
