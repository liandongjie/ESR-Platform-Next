<script setup lang="ts">
import { ref } from 'vue'

import type { SourceGeometry } from '@/types/analysisArea'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ confirm: [geometry: SourceGeometry] }>()

const decimalDegreesPattern = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/
const longitudeInput = ref('')
const latitudeInput = ref('')
const error = ref<string | null>(null)

function confirmCoordinate() {
  if (props.disabled) return

  const longitudeText = longitudeInput.value.trim()
  const latitudeText = latitudeInput.value.trim()
  if (!longitudeText || !latitudeText) {
    error.value = '请输入经度和纬度'
    return
  }
  if (!decimalDegreesPattern.test(longitudeText) || !decimalDegreesPattern.test(latitudeText)) {
    error.value = '经纬度只接受普通十进制度文本'
    return
  }

  const longitude = Number(longitudeText)
  const latitude = Number(latitudeText)
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
    error.value = '经纬度必须是有限数值'
    return
  }
  if (longitude < -180 || longitude > 180) {
    error.value = '经度必须在 -180 至 180 之间'
    return
  }
  if (latitude < -90 || latitude > 90) {
    error.value = '纬度必须在 -90 至 90 之间'
    return
  }

  error.value = null
  emit('confirm', { type: 'Point', coordinates: [longitude, latitude] })
}
</script>

<template>
  <div class="study-area-coordinate-input">
    <div class="study-area-input-heading">
      <strong>输入研究点</strong>
      <small>WGS84 / EPSG:4326</small>
    </div>
    <div class="coordinate-input-grid">
      <el-input
        v-model="longitudeInput"
        aria-label="研究点经度"
        placeholder="经度 [-180, 180]"
        :disabled="disabled"
      />
      <el-input
        v-model="latitudeInput"
        aria-label="研究点纬度"
        placeholder="纬度 [-90, 90]"
        :disabled="disabled"
      />
    </div>
    <small class="study-area-input-hint">仅支持普通十进制度，不支持科学计数法等格式。</small>
    <el-button type="primary" plain :disabled="disabled" @click="confirmCoordinate">
      使用该坐标
    </el-button>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  </div>
</template>

<style scoped>
.study-area-coordinate-input {
  display: grid;
  gap: 10px;
}

.study-area-input-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.study-area-input-heading > strong {
  font-size: 13px;
}

.study-area-input-heading small,
.study-area-input-hint {
  color: var(--muted);
  font-size: 11px;
}

.coordinate-input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}
</style>
