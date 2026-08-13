<script setup lang="ts">
import { ref, watch } from 'vue'

import { useAnalysisStore } from '@/stores/analysis'

const analysisStore = useAnalysisStore()
const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{
  'query-success': []
  'open-result': []
}>()
const keywordDraft = ref(analysisStore.poiKeyword)

watch(
  () => analysisStore.poiKeyword,
  (keyword) => {
    keywordDraft.value = keyword
  },
)

async function searchFirstPage() {
  if (props.disabled || analysisStore.poiLoading) return
  const keyword = keywordDraft.value.trim()
  analysisStore.setPoiKeyword(keywordDraft.value)
  await analysisStore.searchPois(1)
  if (analysisStore.poiHasSearched && analysisStore.poiCommittedKeyword === keyword) {
    emit('query-success')
  }
}
</script>

<template>
  <section class="poi-search">
    <div class="poi-search-heading">
      <strong>POI 查询</strong>
      <el-button
        v-if="analysisStore.poiHasSearched"
        type="primary"
        link
        @click="$emit('open-result')"
      >
        查看结果
      </el-button>
    </div>
    <div class="poi-search-row">
      <el-input
        v-model="keywordDraft"
        aria-label="POI 关键词"
        placeholder="例如：学校"
        clearable
        :disabled="disabled"
        @keyup.enter="searchFirstPage"
      />
      <el-button
        type="primary"
        plain
        :loading="analysisStore.poiLoading"
        :disabled="disabled || analysisStore.poiLoading || !keywordDraft.trim()"
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
  </section>
</template>

<style scoped>
.poi-search {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.poi-search-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.poi-search-heading > strong {
  font-size: 13px;
}

.poi-search-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.poi-search-row :deep(.el-button) {
  flex: 0 0 auto;
}
</style>
