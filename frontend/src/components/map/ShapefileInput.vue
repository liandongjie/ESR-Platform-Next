<script setup lang="ts">
import type { UploadFile, UploadInstance } from 'element-plus'
import { onBeforeUnmount, ref, watch } from 'vue'

import { importShapefile } from '@/api/analysisAreas'
import { getApiErrorMessage } from '@/api/errors'
import type { SourceGeometry } from '@/types/analysisArea'

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ confirm: [geometry: SourceGeometry] }>()

const loading = ref(false)
const error = ref<string | null>(null)
const uploadRef = ref<UploadInstance>()
let requestRevision = 0

function invalidateRequest() {
  requestRevision += 1
  loading.value = false
}

async function selectFile(file: File | undefined) {
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

function handleFileChange(uploadFile: UploadFile) {
  // ElUpload 只负责选择文件；立即清空列表，允许失败后重新选择同一个 ZIP。
  uploadRef.value?.clearFiles()
  void selectFile(uploadFile.raw)
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

    <el-upload
      ref="uploadRef"
      class="shapefile-upload"
      accept=".zip,application/zip"
      :auto-upload="false"
      :show-file-list="false"
      :limit="1"
      :disabled="disabled || loading"
      :on-change="handleFileChange"
    >
      <el-button :loading="loading" :disabled="disabled || loading">
        选择 ZIP 文件
      </el-button>
      <template #tip>
        <small class="section-hint">仅选择一个包含完整 Shapefile 的 ZIP 文件</small>
      </template>
    </el-upload>
    <small v-if="loading" class="section-hint">正在校验并导入研究区…</small>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  </div>
</template>

<style scoped>
.shapefile-input {
  display: grid;
  gap: 0.75rem;
}

.shapefile-upload :deep(.el-upload),
.shapefile-upload :deep(.el-button) {
  width: 100%;
}

.shapefile-upload :deep(.el-upload__tip) {
  margin-top: 6px;
}
</style>
