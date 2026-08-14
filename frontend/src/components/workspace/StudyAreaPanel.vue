<script setup lang="ts">
import { computed } from 'vue'

import AdministrativeRegionInput from '@/components/map/AdministrativeRegionInput.vue'
import ShapefileInput from '@/components/map/ShapefileInput.vue'
import StudyAreaCoordinateInput from '@/components/workspace/StudyAreaCoordinateInput.vue'
import StudyAreaDrawInput from '@/components/workspace/StudyAreaDrawInput.vue'
import StudyAreaSearchInput from '@/components/workspace/StudyAreaSearchInput.vue'
import type { SourceGeometry } from '@/types/analysisArea'

type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'
type StudyAreaMethod = 'draw' | 'coordinate' | 'search' | 'administrative' | 'file'

const props = defineProps<{
  disabled: boolean
  sourceGeometry: SourceGeometry | null
  activeDrawingMode: DrawingMode | null
  drawingError: string | null
  activeMethod: StudyAreaMethod
}>()

const emit = defineEmits<{
  confirm: [geometry: SourceGeometry]
  'start-drawing': [mode: DrawingMode]
  'cancel-drawing': []
  'update:activeMethod': [method: StudyAreaMethod]
  clear: []
}>()

const tabs: Array<{ mode: StudyAreaMethod; label: string }> = [
  { mode: 'draw', label: '绘制' },
  { mode: 'coordinate', label: '坐标' },
  { mode: 'search', label: '搜索' },
  { mode: 'administrative', label: '行政区' },
  { mode: 'file', label: '文件' },
]

const sourceGeometrySummary = computed(() => {
  const geometry = props.sourceGeometry
  if (!geometry) return '尚未确认研究区'
  if (geometry.type === 'Point') {
    return `${geometry.coordinates[0].toFixed(6)}, ${geometry.coordinates[1].toFixed(6)}`
  }
  if (geometry.type === 'LineString') {
    return `LineString · ${geometry.coordinates.length} 个顶点`
  }
  if (geometry.type === 'Polygon') {
    const vertexCount = Math.max(0, geometry.coordinates[0]?.length ?? 1) - 1
    const holeCount = Math.max(0, geometry.coordinates.length - 1)
    return holeCount > 0
      ? `Polygon · ${vertexCount} 个外环顶点 · ${holeCount} 个孔洞`
      : `Polygon · ${vertexCount} 个顶点`
  }
  const holeCount = geometry.coordinates.reduce(
    (total, polygon) => total + Math.max(0, polygon.length - 1),
    0,
  )
  return `MultiPolygon · ${geometry.coordinates.length} 个面 · ${holeCount} 个孔洞`
})

function selectMode(mode: StudyAreaMethod) {
  if (mode === props.activeMethod) return
  emit('update:activeMethod', mode)
}
</script>

<template>
  <section class="study-area-panel">
    <div class="section-title-row">
      <strong>研究区</strong>
      <small>WGS84 / EPSG:4326</small>
    </div>

    <div class="study-area-tabs" role="group" aria-label="研究区输入方式">
      <button
        v-for="tab in tabs"
        :key="tab.mode"
        type="button"
        class="study-area-tab"
        :class="{ active: activeMethod === tab.mode }"
        :aria-pressed="activeMethod === tab.mode"
        @click="selectMode(tab.mode)"
      >
        {{ tab.label }}
      </button>
    </div>

    <div class="study-area-input-content">
      <StudyAreaDrawInput
        v-if="activeMethod === 'draw'"
        :disabled="disabled"
        :active-drawing-mode="activeDrawingMode"
        :drawing-error="drawingError"
        @start-drawing="emit('start-drawing', $event)"
        @cancel-drawing="emit('cancel-drawing')"
      />
      <StudyAreaCoordinateInput
        v-else-if="activeMethod === 'coordinate'"
        :disabled="disabled"
        @confirm="emit('confirm', $event)"
      />
      <StudyAreaSearchInput
        v-else-if="activeMethod === 'search'"
        :disabled="disabled"
        :source-geometry="sourceGeometry"
        @confirm="emit('confirm', $event)"
      />
      <AdministrativeRegionInput
        v-else-if="activeMethod === 'administrative'"
        :disabled="disabled"
        @confirm="emit('confirm', $event)"
      />
      <ShapefileInput
        v-else
        :disabled="disabled"
        @confirm="emit('confirm', $event)"
      />
    </div>

    <div class="study-area-summary">
      <div>
        <span>当前研究区</span>
        <strong>{{ sourceGeometrySummary }}</strong>
        <small v-if="sourceGeometry">
          业务坐标系：WGS84 / EPSG:4326；地图显示坐标转换由适配层处理。
        </small>
      </div>
      <el-button
        type="danger"
        plain
        :disabled="disabled || !sourceGeometry"
        @click="emit('clear')"
      >
        清除研究区
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.study-area-panel,
.study-area-input-content {
  display: grid;
  gap: 10px;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row > strong {
  font-size: 13px;
}

.section-title-row small,
.study-area-summary span,
.study-area-summary small {
  color: var(--muted);
  font-size: 11px;
}

.study-area-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 5px;
}

.study-area-tab {
  min-width: 0;
  padding: 7px 3px;
  border: 0;
  border-right: 1px solid var(--border);
  background: #fff;
  color: var(--muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.study-area-tab:last-child {
  border-right: 0;
}

.study-area-tab.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
}

.study-area-tab:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

.study-area-input-content {
  min-height: 120px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-subtle);
}

.study-area-input-content :deep(.section-title-row) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.study-area-input-content :deep(.section-title-row > strong) {
  font-size: 13px;
}

.study-area-input-content :deep(.section-title-row small),
.study-area-input-content :deep(.section-hint) {
  color: var(--muted);
  font-size: 11px;
}

.study-area-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-subtle);
}

.study-area-summary > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.study-area-summary strong {
  font-size: 13px;
  word-break: break-all;
}
</style>
