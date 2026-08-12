<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { normalizeAdministrativeBoundaries } from '@/api/analysisAreas'
import { getApiErrorMessage } from '@/api/errors'
import {
  getAmapAdministrativeBoundaries,
  listAmapAdministrativeRegions,
  type AdministrativeRegion,
} from '@/map/amapDistrict'
import type { BufferGeometry } from '@/types/analysisArea'

interface SelectionLevel {
  parent: AdministrativeRegion | null
  options: AdministrativeRegion[]
  selectedAdcode: string
  loading: boolean
}

const props = defineProps<{ disabled: boolean }>()
const emit = defineEmits<{ confirm: [geometry: BufferGeometry] }>()

const municipalityAdcodes = new Set(['110000', '120000', '310000', '500000'])
const levels = ref<SelectionLevel[]>([])
const error = ref<string | null>(null)
const confirming = ref(false)
let requestRevision = 0

const selectedRegion = computed(() => {
  for (let index = levels.value.length - 1; index >= 0; index -= 1) {
    const level = levels.value[index]!
    const selected = level.options.find((item) => item.adcode === level.selectedAdcode)
    if (selected) return selected
  }
  return null
})
const canConfirmSelected = computed(() => {
  const region = selectedRegion.value
  return Boolean(
    region &&
      (region.level === 'city' ||
        region.level === 'district' ||
        municipalityAdcodes.has(region.adcode)),
  )
})
const selectionLoading = computed(() => levels.value.some((item) => item.loading))

function invalidateRequests() {
  requestRevision += 1
  confirming.value = false
  levels.value.forEach((item) => {
    item.loading = false
  })
}

async function loadRoot() {
  if (props.disabled) return
  const revision = ++requestRevision
  error.value = null
  levels.value = [{ parent: null, options: [], selectedAdcode: '', loading: true }]
  try {
    const options = await listAmapAdministrativeRegions()
    if (revision !== requestRevision || props.disabled) return
    levels.value[0]!.options = options
    if (options.length === 0) error.value = '未找到可用行政区'
  } catch (caught: unknown) {
    if (revision !== requestRevision || props.disabled) return
    error.value = caught instanceof Error ? caught.message : '行政区列表加载失败'
  } finally {
    if (revision === requestRevision && levels.value[0]) levels.value[0].loading = false
  }
}

async function selectRegion(levelIndex: number, value: unknown) {
  if (props.disabled || typeof value !== 'string') return
  const level = levels.value[levelIndex]
  if (!level) return

  const revision = ++requestRevision
  error.value = null
  confirming.value = false
  level.selectedAdcode = value
  levels.value.splice(levelIndex + 1)
  const selected = level.options.find((item) => item.adcode === value)
  if (!selected) return

  const nextLevel: SelectionLevel = {
    parent: selected,
    options: [],
    selectedAdcode: '',
    loading: true,
  }
  levels.value.push(nextLevel)
  try {
    const options = await listAmapAdministrativeRegions(selected)
    if (revision !== requestRevision || props.disabled) return
    if (options.length === 0) {
      levels.value.splice(levelIndex + 1, 1)
      return
    }
    const currentLevel = levels.value[levelIndex + 1]
    if (currentLevel?.parent?.adcode === selected.adcode) currentLevel.options = options
  } catch (caught: unknown) {
    if (revision !== requestRevision || props.disabled) return
    levels.value.splice(levelIndex + 1, 1)
    error.value = caught instanceof Error ? caught.message : '下级行政区加载失败'
  } finally {
    const currentLevel = levels.value[levelIndex + 1]
    if (revision === requestRevision && currentLevel?.parent?.adcode === selected.adcode) {
      currentLevel.loading = false
    }
  }
}

async function confirmSelection() {
  const region = selectedRegion.value
  if (
    props.disabled ||
    confirming.value ||
    selectionLoading.value ||
    !region ||
    !canConfirmSelected.value
  ) {
    return
  }

  const revision = ++requestRevision
  const selectedAdcode = region.adcode
  confirming.value = true
  error.value = null
  try {
    const boundaries = await getAmapAdministrativeBoundaries(region)
    if (revision !== requestRevision || props.disabled || selectedRegion.value?.adcode !== selectedAdcode) return
    const normalized = await normalizeAdministrativeBoundaries({ boundaries })
    if (revision !== requestRevision || props.disabled || selectedRegion.value?.adcode !== selectedAdcode) return
    emit('confirm', normalized.geometry)
  } catch (caught: unknown) {
    if (revision !== requestRevision || props.disabled) return
    error.value = getApiErrorMessage(caught, '行政区边界确认失败')
  } finally {
    if (revision === requestRevision) confirming.value = false
  }
}

watch(
  () => props.disabled,
  (disabled) => {
    if (disabled) {
      const listWasLoading = selectionLoading.value
      invalidateRequests()
      // 锁定期间返回的列表必须丢弃；解锁后从根重新加载，避免留下无法重试的空层级。
      if (listWasLoading) levels.value = []
    } else if (levels.value.length === 0) {
      void loadRoot()
    }
  },
)

onMounted(loadRoot)
onBeforeUnmount(invalidateRequests)
</script>

<template>
  <div class="administrative-region-input">
    <div class="section-title-row">
      <strong>选择行政区</strong>
      <small>高德行政区查询</small>
    </div>

    <div v-if="levels.length" class="administrative-region-levels">
      <el-select
        v-for="(level, index) in levels"
        :key="`${index}-${level.parent?.adcode ?? 'root'}`"
        :model-value="level.selectedAdcode"
        :aria-label="level.parent ? `${level.parent.name}下级行政区` : '省级行政区'"
        :placeholder="level.parent ? `选择${level.parent.name}下级行政区` : '选择省级行政区'"
        :loading="level.loading"
        :disabled="disabled || level.loading"
        clearable
        @update:model-value="selectRegion(index, $event)"
      >
        <el-option
          v-for="option in level.options"
          :key="option.adcode"
          :label="option.name"
          :value="option.adcode"
        />
      </el-select>
    </div>

    <small v-if="selectedRegion && !canConfirmSelected" class="section-hint">
      当前省级节点首版仅支持浏览，请继续选择下级行政区。
    </small>

    <div class="administrative-region-actions">
      <el-button
        v-if="levels.length === 0 || (error && levels[0]?.options.length === 0)"
        plain
        :disabled="disabled"
        @click="loadRoot"
      >
        重新加载
      </el-button>
      <el-button
        type="primary"
        plain
        :loading="confirming"
        :disabled="disabled || confirming || selectionLoading || !canConfirmSelected"
        @click="confirmSelection"
      >
        确认行政区
      </el-button>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
  </div>
</template>

<style scoped>
.administrative-region-input,
.administrative-region-levels {
  display: grid;
  gap: 0.75rem;
}

.administrative-region-actions {
  display: flex;
  gap: 0.75rem;
}
</style>
