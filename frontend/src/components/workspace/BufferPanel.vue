<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { AnalysisAreaBufferResponse } from '@/types/analysisArea'

const props = defineProps<{
  committedDistance: number
  maxDistance?: number
  disabled: boolean
  loading: boolean
  error: string | null
  result: AnalysisAreaBufferResponse | null
}>()

const emit = defineEmits<{ generate: [distance: number] }>()

const bufferDistanceDraft = ref<number | undefined>(props.committedDistance)

const distanceValid = computed(() => {
  const distance = bufferDistanceDraft.value
  if (typeof distance !== 'number' || !Number.isFinite(distance) || distance <= 0) return false
  return props.maxDistance === undefined || distance <= props.maxDistance
})

const bufferLimitText = computed(() => {
  if (props.maxDistance === undefined) return '上限以服务端校验为准'
  return `服务端当前上限 ${props.maxDistance.toLocaleString()} 米`
})

watch(
  () => props.committedDistance,
  (distance) => {
    bufferDistanceDraft.value = distance
  },
)

function generateBuffer() {
  if (props.disabled || props.loading || !distanceValid.value) return
  emit('generate', bufferDistanceDraft.value as number)
}
</script>

<template>
  <section class="buffer-panel">
    <div class="buffer-panel-heading">
      <strong>缓冲区</strong>
      <small>{{ bufferLimitText }}</small>
    </div>

    <el-input-number
      v-model="bufferDistanceDraft"
      aria-label="缓冲距离"
      :min="1"
      :max="maxDistance"
      :step="100"
      :precision="0"
      :disabled="disabled"
      controls-position="right"
    />
    <el-button
      type="primary"
      plain
      :loading="loading"
      :disabled="disabled || loading || !distanceValid"
      @click="generateBuffer"
    >
      {{ result ? '重新生成缓冲区' : '生成缓冲区' }}
    </el-button>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <div v-if="result" class="buffer-result-summary">
      <div>
        <span>面积</span>
        <strong>{{ result.buffer.area_km2.toFixed(3) }} km²</strong>
      </div>
      <div>
        <span>实际距离</span>
        <strong>{{ result.buffer.distance_m.toLocaleString() }} m</strong>
      </div>
      <div>
        <span>米制工作 CRS</span>
        <strong>{{ result.buffer.working_crs }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.buffer-panel {
  display: grid;
  gap: 10px;
}

.buffer-panel :deep(.el-input-number) {
  width: 100%;
}

.buffer-panel-heading,
.buffer-result-summary > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.buffer-panel-heading > strong {
  font-size: 13px;
}

.buffer-panel-heading small,
.buffer-result-summary span {
  color: var(--muted);
  font-size: 11px;
}

.buffer-result-summary {
  display: grid;
  gap: 9px;
  padding: 11px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface-subtle);
}

.buffer-result-summary strong {
  font-size: 12px;
  text-align: right;
}
</style>
