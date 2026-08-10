<script setup lang="ts">
import { reactive } from 'vue'

import { getApiErrorMessage } from '@/api/errors'
import { downloadRiskAnalysisArtifact, type RiskAnalysisArtifactKind } from '@/api/riskAnalysis'

defineProps<{
  taskId: string
}>()

const loading = reactive<Record<RiskAnalysisArtifactKind, boolean>>({
  raster: false,
  manifest: false,
})
const warnings = reactive<Record<RiskAnalysisArtifactKind, string | null>>({
  raster: null,
  manifest: null,
})

const errorFallbacks: Record<RiskAnalysisArtifactKind, string> = {
  raster: '下载 GeoTIFF 失败',
  manifest: '下载结果 JSON 失败',
}

async function download(taskId: string, kind: RiskAnalysisArtifactKind) {
  if (loading[kind]) return

  loading[kind] = true
  warnings[kind] = null
  let objectUrl: string | null = null
  let anchor: HTMLAnchorElement | null = null

  try {
    const artifact = await downloadRiskAnalysisArtifact(taskId, kind)
    objectUrl = URL.createObjectURL(artifact.blob)
    anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = artifact.filename
    document.body.appendChild(anchor)
    anchor.click()
  } catch (error: unknown) {
    warnings[kind] = getApiErrorMessage(error, errorFallbacks[kind])
  } finally {
    try {
      anchor?.remove()
    } finally {
      try {
        if (objectUrl) URL.revokeObjectURL(objectUrl)
      } finally {
        loading[kind] = false
      }
    }
  }
}
</script>

<template>
  <div class="result-downloads">
    <div class="download-actions">
      <el-button
        type="primary"
        plain
        :loading="loading.raster"
        :disabled="loading.raster"
        @click="download(taskId, 'raster')"
      >
        下载 GeoTIFF
      </el-button>
      <el-button
        plain
        :loading="loading.manifest"
        :disabled="loading.manifest"
        @click="download(taskId, 'manifest')"
      >
        下载结果 JSON
      </el-button>
    </div>

    <el-alert
      v-if="warnings.raster"
      :title="warnings.raster"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-alert
      v-if="warnings.manifest"
      :title="warnings.manifest"
      type="warning"
      :closable="false"
      show-icon
    />
  </div>
</template>

<style scoped>
.result-downloads {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.download-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.download-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
