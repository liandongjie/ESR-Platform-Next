<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import { importShapefile } from '@/api/analysisAreas'
import { getApiErrorMessage } from '@/api/errors'
import type { SourceGeometry } from '@/types/analysisArea'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ confirm: [geometry: SourceGeometry] }>()

const loading = ref(false)
const error = ref<string | null>(null)
let requestRevision = 0

function invalidateRequest() {
  requestRevision += 1
  loading.value = false
}

async function selectFile(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  // 立即清空 input，允许失败后重新选择同一个 ZIP；File 只保留到本次请求结束。
  input.value = ''
  if (props.disabled || loading.value || !file) return
  if (!file.name.toLowerCase().endsWith('.zip')) {
    error.value = '请选择 ZIP 格式的 Shapefile 文件'
    return
  }

  const revision = ++requestRevision
  loading.value = true
  error.value = null
  try {
    const imported = await importShapefile(file)
    if (revision !== requestRevision || props.disabled) return
    emit('confirm', imported.geometry)
  } catch (caught: unknown) {
    if (revision !== requestRevision || props.disabled) return
    error.value = getApiErrorMessage(caught, 'Shapefile 导入失败')
  } finally {
    if (revision === requestRevision) loading.value = false
  }
}

function handleFileChange(event: Event) {
  void selectFile(event)
}

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) invalidateRequest()
  },
)

onBeforeUnmount(invalidateRequest)
</script>

<template>
  <div class="shapefile-input">
    <div class="section-title-row">
      <strong>上传 Shapefile</strong>
      <small>单个 ZIP · CRS 必填</small>
    </div>

    <input
      class="shapefile-file-input"
      type="file"
      accept=".zip,application/zip"
      aria-label="上传 Shapefile ZIP"
      :disabled="disabled || loading"
      @change="handleFileChange"
    >
    <small v-if="loading" class="section-hint">正在校验并导入研究区…</small>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  </div>
</template>

<style scoped>
.shapefile-input {
  display: grid;
  gap: 0.75rem;
}

.shapefile-file-input {
  min-width: 0;
  color: var(--el-text-color-regular);
}
</style>
