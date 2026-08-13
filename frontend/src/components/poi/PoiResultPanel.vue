<script setup lang="ts">
import { computed, ref } from 'vue'

import { getApiErrorMessage } from '@/api/errors'
import { createPoiCsvArtifact, type PoiExportData } from '@/export/poiCsv'
import { useAnalysisStore } from '@/stores/analysis'

const analysisStore = useAnalysisStore()
const exportNotice = ref<string | null>(null)
const isComplexResult = computed(() => analysisStore.poiReportedCandidateCount !== null)
const pageCount = computed(() => {
  const itemCount = isComplexResult.value
    ? (analysisStore.poiRetrievedUniqueCount ?? 0)
    : analysisStore.poiTotal
  const pages = Math.ceil(itemCount / analysisStore.poiPageSize)
  return isComplexResult.value ? pages : Math.min(100, pages)
})
const truncatedMessage = computed(() => {
  if (analysisStore.poiTruncatedReason === 'provider-call-limit') {
    return '查询达到 100 次 Provider 请求上限，结果已截断；当前仅展示和导出已获取结果'
  }
  if (analysisStore.poiTruncatedReason === 'raw-row-limit') {
    return '查询达到 5,000 条 Provider 原始结果上限，结果已截断；当前仅展示和导出已获取结果'
  }
  return null
})

function searchPage(page: number) {
  void analysisStore.changePoiPage(page)
}

function downloadCsv(data: PoiExportData) {
  let objectUrl: string | null = null
  let anchor: HTMLAnchorElement | null = null

  try {
    const artifact = createPoiCsvArtifact(data, new Date())
    objectUrl = URL.createObjectURL(new Blob([artifact.content], { type: artifact.mimeType }))
    anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = artifact.filename
    document.body.appendChild(anchor)
    anchor.click()
    exportNotice.value =
      data.mode === 'current-page'
        ? `已导出当前页 ${data.exportedCount.toLocaleString()} 条 POI`
        : isComplexResult.value
          ? analysisStore.poiRetrievalComplete
            ? `已导出全部已获取结果 ${data.exportedCount.toLocaleString()} 条 POI`
            : `查询已截断；已导出已获取结果 ${data.exportedCount.toLocaleString()} 条 POI`
          : `高德报告 ${data.totalReported.toLocaleString()} 条；本次最多尝试获取 ${data.retrievableLimit.toLocaleString()} 条；实际导出 ${data.exportedCount.toLocaleString()} 条`
  } catch (error: unknown) {
    analysisStore.poiExportError = getApiErrorMessage(error, 'POI CSV 下载失败')
  } finally {
    try {
      anchor?.remove()
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }
}

function exportCurrentPage() {
  exportNotice.value = null
  const data = analysisStore.prepareCurrentPagePoiExport()
  if (data) downloadCsv(data)
}

async function exportRetrievable() {
  exportNotice.value = null
  const data = await analysisStore.collectRetrievablePoiExport()
  if (data) downloadCsv(data)
}
</script>

<template>
  <section class="poi-result">
    <div v-if="analysisStore.poiHasSearched" class="result-summary">
      <el-tag
        v-if="!isComplexResult"
        type="info"
        effect="plain"
        size="small"
      >
        高德报告 {{ analysisStore.poiTotal.toLocaleString() }} 条
      </el-tag>
      <el-tag v-else-if="analysisStore.poiHasSearched" type="info" effect="plain" size="small">
        已获取 {{ analysisStore.poiRetrievedUniqueCount?.toLocaleString() }} 条；候选报告
        {{ analysisStore.poiReportedCandidateCount?.toLocaleString() }} 条（非严格总数）
      </el-tag>
    </div>

    <el-alert
      v-if="analysisStore.poiHasSearched && truncatedMessage"
      :title="truncatedMessage"
      type="warning"
      :closable="false"
      show-icon
    />
    <el-empty
      v-else-if="analysisStore.poiHasSearched && analysisStore.poiItems.length === 0"
      description="当前缓冲区内未找到匹配 POI"
      :image-size="54"
    />

    <ol v-if="analysisStore.poiItems.length" class="poi-list">
      <li v-for="poi in analysisStore.poiItems" :key="poi.id">
        <strong>{{ poi.name }}</strong>
        <small>{{ poi.id }}</small>
      </li>
    </ol>

    <el-pagination
      v-if="pageCount > 1"
      size="small"
      background
      layout="prev, pager, next"
      :current-page="analysisStore.poiPage"
      :page-size="analysisStore.poiPageSize"
      :page-count="pageCount"
      @current-change="searchPage"
    />

    <div v-if="analysisStore.poiHasSearched && analysisStore.poiItems.length" class="poi-export-actions">
      <el-button :disabled="analysisStore.poiExportLoading" @click="exportCurrentPage">
        导出当前页
      </el-button>
      <el-button
        type="primary"
        plain
        :loading="analysisStore.poiExportLoading"
        :disabled="analysisStore.poiExportLoading"
        @click="exportRetrievable"
      >
        导出可获取结果
      </el-button>
    </div>

    <div v-if="analysisStore.poiExportLoading" class="poi-export-progress">
      <span v-if="analysisStore.poiExportProgress?.plannedPages">
        正在获取第 {{ analysisStore.poiExportProgress.currentPage }} /
        {{ analysisStore.poiExportProgress.plannedPages }} 页
      </span>
      <span v-else>正在获取第 1 页</span>
      <small
        v-if="
          analysisStore.poiExportProgress?.totalReported &&
            analysisStore.poiExportProgress.totalReported > 5000
        "
      >
        高德报告 {{ analysisStore.poiExportProgress.totalReported.toLocaleString() }} 条，本次最多尝试获取
        5,000 条
      </small>
    </div>

    <el-alert
      v-if="analysisStore.poiExportError"
      :title="analysisStore.poiExportError"
      type="error"
      :closable="false"
      show-icon
    />
    <el-alert
      v-else-if="exportNotice"
      :title="exportNotice"
      type="success"
      :closable="false"
      show-icon
    />
  </section>
</template>

<style scoped>
.poi-result {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.poi-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.result-summary {
  display: flex;
  justify-content: flex-end;
}

.poi-export-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.poi-export-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}

.poi-export-progress {
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-size: 12px;
}

.poi-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.poi-list li {
  padding: 9px 10px;
  border-radius: 8px;
  background: #f6f8fc;
}

.poi-list strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.poi-list small {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 10px;
}

.poi-result :deep(.el-pagination) {
  justify-content: center;
}
</style>
