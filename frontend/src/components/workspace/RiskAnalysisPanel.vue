<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type {
  RiskIndicatorCatalog,
  RiskIndicatorCategoryCode,
  RiskIndicatorWeightInput,
} from '@/types/riskAnalysis'

const props = defineProps<{
  committedWeights: RiskIndicatorWeightInput[]
  disabled: boolean
  submitting: boolean
  polling: boolean
  hasTaskOrResult: boolean
  catalog?: RiskIndicatorCatalog | null
  catalogLoading?: boolean
  catalogError?: string | null
}>()

const emit = defineEmits<{
  submit: [weights: RiskIndicatorWeightInput[]]
  'open-result': []
  'retry-catalog': []
}>()

const weightsDraft = ref(props.committedWeights.map((item) => ({ ...item })))
const activeCategory = ref<RiskIndicatorCategoryCode>('environment')

const categories = computed(() =>
  [...(props.catalog?.categories ?? [])].sort((left, right) => left.order - right.order),
)
const visibleIndicators = computed(() =>
  (props.catalog?.indicators ?? []).filter((item) => item.category === activeCategory.value),
)
const draftMatchesCatalog = computed(() => {
  if (!props.catalog) return false
  const codes = new Set(props.catalog.indicators.map((item) => item.code))
  return (
    new Set(weightsDraft.value.map((item) => item.code)).size === weightsDraft.value.length &&
    weightsDraft.value.every((item) => codes.has(item.code))
  )
})

const weightTotal = computed(() =>
  weightsDraft.value.reduce((sum, item) => sum + item.weight_percent, 0),
)
const weightsValid = computed(
  () =>
    props.catalog !== null &&
    draftMatchesCatalog.value &&
    weightsDraft.value.every(
      (item) =>
        Number.isFinite(item.weight_percent) &&
        item.weight_percent >= 0 &&
        item.weight_percent <= 100,
    ) &&
    Math.abs(weightTotal.value - 100) <= 1e-6 &&
    weightsDraft.value.some((item) => item.weight_percent > 0),
)

watch(
  () => props.committedWeights,
  (weights) => {
    weightsDraft.value = weights.map((item) => ({ ...item }))
  },
  { deep: true },
)

function updateWeight(code: string, value: number | undefined) {
  if (props.disabled || typeof value !== 'number' || !Number.isFinite(value)) return
  const item = weightsDraft.value.find((weight) => weight.code === code)
  if (item) item.weight_percent = value
}

function isSelected(code: string) {
  return weightsDraft.value.some((item) => item.code === code)
}

function toggleIndicator(code: string, selected: boolean) {
  if (props.disabled) return
  if (selected && !isSelected(code)) {
    weightsDraft.value.push({ code, weight_percent: 0 })
  } else if (!selected) {
    weightsDraft.value = weightsDraft.value.filter((item) => item.code !== code)
  }
}

function weightFor(code: string) {
  return weightsDraft.value.find((item) => item.code === code)?.weight_percent ?? 0
}

function removeUnknownIndicators() {
  if (!props.catalog || props.disabled) return
  const codes = new Set(props.catalog.indicators.map((item) => item.code))
  weightsDraft.value = weightsDraft.value.filter((item) => codes.has(item.code))
}

function submit() {
  if (props.disabled || props.submitting || !weightsValid.value) return
  emit(
    'submit',
    weightsDraft.value.map((item) => ({ ...item })),
  )
}
</script>

<template>
  <section class="risk-analysis-panel">
    <div class="risk-analysis-heading">
      <strong>风险指标</strong>
      <div class="risk-analysis-heading-actions">
        <el-button v-if="hasTaskOrResult" type="primary" link @click="$emit('open-result')">
          查看任务/结果
        </el-button>
        <el-tag :type="weightsValid ? 'success' : 'danger'" effect="plain" size="small">
          合计 {{ weightTotal }}%
        </el-tag>
      </div>
    </div>

    <div v-if="catalog" class="risk-category-tabs" role="tablist" aria-label="风险指标分类">
      <button
        v-for="category in categories"
        :key="category.code"
        type="button"
        class="risk-category-tab"
        :class="{ active: activeCategory === category.code }"
        role="tab"
        :aria-selected="activeCategory === category.code"
        @click="activeCategory = category.code"
      >
        {{ category.name }}
      </button>
    </div>

    <div v-if="catalog" class="risk-weight-list">
      <div
        v-for="indicator in visibleIndicators"
        :key="indicator.code"
        class="risk-weight-row"
        :title="indicator.risk_semantics"
      >
        <el-checkbox
          :model-value="isSelected(indicator.code)"
          :disabled="disabled"
          @update:model-value="toggleIndicator(indicator.code, $event)"
        >
          {{ indicator.name }}（{{ indicator.code }}）
        </el-checkbox>
        <el-input-number
          :model-value="weightFor(indicator.code)"
          :min="0"
          :max="100"
          :step="5"
          :precision="0"
          :disabled="disabled || !isSelected(indicator.code)"
          size="small"
          controls-position="right"
          @update:model-value="updateWeight(indicator.code, $event)"
        />
      </div>
    </div>
    <small v-if="catalogLoading" class="risk-analysis-hint">正在加载风险指标目录…</small>
    <el-alert v-else-if="catalogError" :title="catalogError" type="error" :closable="false">
      <el-button type="primary" link @click="$emit('retry-catalog')">重试加载</el-button>
    </el-alert>
    <el-alert
      v-else-if="catalog && !draftMatchesCatalog"
      title="已恢复的指标配置不属于当前目录，请重新选择指标或重试加载。"
      type="warning"
      :closable="false"
    >
      <el-button type="primary" link @click="removeUnknownIndicators">按当前目录重新配置</el-button>
      <el-button type="primary" link @click="$emit('retry-catalog')">重试加载</el-button>
    </el-alert>
    <!-- <small class="risk-analysis-hint">
      前端只做即时提示；指标合法性和权重规则仍以后端 RiskAnalysisPipeline 为最终校验。
    </small> -->
    <small v-if="disabled" class="risk-analysis-hint">
      当前任务仍在服务端执行，权重暂时锁定，避免丢失正在运行的任务。
    </small>
    <el-button
      type="primary"
      :loading="submitting"
      :disabled="disabled || submitting || catalogLoading || !weightsValid"
      @click="submit"
    >
      {{ polling ? '分析进行中' : '开始风险分析' }}
    </el-button>
  </section>
</template>

<style scoped>
.risk-analysis-panel,
.risk-weight-list {
  display: grid;
  gap: 10px;
}

.risk-analysis-heading,
.risk-weight-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.risk-analysis-heading > strong {
  font-size: 13px;
}

.risk-analysis-heading-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.risk-category-tabs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 5px;
}

.risk-category-tab {
  padding: 7px 4px;
  border: 0;
  border-right: 1px solid var(--border);
  background: #fff;
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.risk-category-tab:last-child {
  border-right: 0;
}

.risk-category-tab.active {
  background: var(--primary-soft);
  color: var(--primary);
  font-weight: 700;
}

.risk-weight-row :deep(.el-checkbox) {
  min-width: 0;
  margin-right: 0;
}

.risk-weight-row :deep(.el-checkbox__label) {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.risk-weight-row :deep(.el-input-number) {
  width: 126px;
}

.risk-analysis-hint {
  color: var(--muted);
  font-size: 11px;
}
</style>
