<script setup lang="ts">
import { computed } from 'vue'

import { useAnalysisStore } from '@/stores/analysis'

const analysisStore = useAnalysisStore()

const keyword = computed({
  get: () => analysisStore.poiKeyword,
  set: (value: string) => analysisStore.setPoiKeyword(value),
})
const pageCount = computed(() =>
  Math.min(100, Math.ceil(analysisStore.poiTotal / analysisStore.poiPageSize)),
)

function searchFirstPage() {
  void analysisStore.searchPois(1)
}

function searchPage(page: number) {
  void analysisStore.searchPois(page)
}
</script>

<template>
  <section class="poi-search">
    <div class="section-title-row">
      <strong>POI 查询</strong>
      <el-tag v-if="analysisStore.poiHasSearched" type="info" effect="plain" size="small">
        共 {{ analysisStore.poiTotal.toLocaleString() }} 条
      </el-tag>
    </div>

    <div class="poi-search-row">
      <el-input
        v-model="keyword"
        aria-label="POI 关键词"
        placeholder="例如：学校"
        clearable
        @keyup.enter="searchFirstPage"
      />
      <el-button
        type="primary"
        plain
        :loading="analysisStore.poiLoading"
        :disabled="!keyword.trim()"
        @click="searchFirstPage"
      >
        查询
      </el-button>
    </div>

    <el-alert
      v-if="analysisStore.poiError"
      :title="analysisStore.poiError"
      type="error"
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
  </section>
</template>

<style scoped>
.poi-search {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title-row,
.poi-search-row,
.poi-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-title-row > strong {
  font-size: 13px;
}

.poi-search-row :deep(.el-button) {
  flex: 0 0 auto;
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

.poi-search :deep(.el-pagination) {
  justify-content: center;
}
</style>
