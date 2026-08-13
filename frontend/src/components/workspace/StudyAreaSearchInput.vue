<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { searchAmapStudyPoints } from '@/map/amapStudyPoint'
import type { Coordinate, SourceGeometry } from '@/types/analysisArea'
import type { StudyPointCandidate } from '@/types/poi'

const props = defineProps<{
  disabled: boolean
  sourceGeometry: SourceGeometry | null
}>()
const emit = defineEmits<{ confirm: [geometry: SourceGeometry] }>()

const keyword = ref('')
const candidates = ref<StudyPointCandidate[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const hasSearched = ref(false)
const selectedCandidate = ref<{ name: string; locationWgs84: Coordinate } | null>(null)
let requestRevision = 0

const selectedName = computed(() => {
  const selected = selectedCandidate.value
  const geometry = props.sourceGeometry
  if (
    !selected ||
    geometry?.type !== 'Point' ||
    geometry.coordinates[0] !== selected.locationWgs84[0] ||
    geometry.coordinates[1] !== selected.locationWgs84[1]
  ) {
    return null
  }
  return selected.name
})

function invalidateRequest() {
  requestRevision += 1
  loading.value = false
}

watch(keyword, () => {
  invalidateRequest()
  candidates.value = []
  error.value = null
  hasSearched.value = false
})

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) invalidateRequest()
  },
)

async function search() {
  if (props.disabled || loading.value) return

  const submittedKeyword = keyword.value.trim()
  if (!submittedKeyword) {
    error.value = '请输入地址或 POI 关键词'
    hasSearched.value = false
    return
  }

  const revision = ++requestRevision
  candidates.value = []
  loading.value = true
  error.value = null
  hasSearched.value = false

  try {
    const result = await searchAmapStudyPoints(submittedKeyword)
    if (revision !== requestRevision || keyword.value.trim() !== submittedKeyword || props.disabled) {
      return
    }
    candidates.value = result
    hasSearched.value = true
  } catch (caught: unknown) {
    if (revision !== requestRevision || keyword.value.trim() !== submittedKeyword || props.disabled) {
      return
    }
    error.value = caught instanceof Error ? caught.message : '地址或 POI 搜索失败'
  } finally {
    if (revision === requestRevision && keyword.value.trim() === submittedKeyword) {
      loading.value = false
    }
  }
}

function confirmCandidate(candidate: StudyPointCandidate) {
  if (props.disabled) return
  selectedCandidate.value = {
    name: candidate.name,
    locationWgs84: [...candidate.locationWgs84] as Coordinate,
  }
  emit('confirm', { type: 'Point', coordinates: candidate.locationWgs84 })
}

onBeforeUnmount(invalidateRequest)
</script>

<template>
  <div class="study-area-search-input">
    <div class="study-area-input-heading">
      <strong>搜索地址 / POI</strong>
      <small>高德地点搜索</small>
    </div>
    <div class="study-point-search-row">
      <el-input
        v-model="keyword"
        aria-label="地址或 POI 关键词"
        placeholder="如：南京大学、中关村"
        :disabled="disabled"
        @keyup.enter="search"
      />
      <el-button
        type="primary"
        plain
        :loading="loading"
        :disabled="disabled || loading"
        @click="search"
      >
        搜索
      </el-button>
    </div>

    <el-alert
      v-if="error"
      class="study-point-search-error"
      :title="error"
      type="error"
      :closable="false"
      show-icon
    />
    <small
      v-else-if="hasSearched && candidates.length === 0"
      class="study-area-input-hint study-point-search-empty"
    >
      未找到匹配地点
    </small>
    <small v-if="selectedName" class="study-point-selected">已选择：{{ selectedName }}</small>

    <div v-if="candidates.length" class="study-point-results">
      <button
        v-for="candidate in candidates"
        :key="candidate.id"
        type="button"
        class="study-point-result"
        :disabled="disabled"
        @click="confirmCandidate(candidate)"
      >
        <strong>{{ candidate.name }}</strong>
        <small>{{ candidate.district }}{{ candidate.address }}</small>
      </button>
    </div>
  </div>
</template>

<style scoped>
.study-area-search-input,
.study-point-results {
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
.study-area-input-hint,
.study-point-selected {
  color: var(--muted);
  font-size: 11px;
}

.study-point-search-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.study-point-result {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.study-point-result:hover:not(:disabled) {
  border-color: var(--primary);
}

.study-point-result:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
</style>
