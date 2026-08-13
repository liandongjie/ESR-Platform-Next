<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { RiskIndicatorWeightInput } from '@/types/riskAnalysis'

const props = defineProps<{
  committedWeights: RiskIndicatorWeightInput[]
  disabled: boolean
  submitting: boolean
  polling: boolean
}>()

const emit = defineEmits<{ submit: [weights: RiskIndicatorWeightInput[]] }>()

const weightsDraft = ref(props.committedWeights.map((item) => ({ ...item })))

const weightTotal = computed(() =>
  weightsDraft.value.reduce((sum, item) => sum + item.weight_percent, 0),
)
const weightsValid = computed(
  () =>
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

function submit() {
  if (props.disabled || props.submitting || !weightsValid.value) return
  emit('submit', weightsDraft.value.map((item) => ({ ...item })))
}
</script>

<template>
  <section class="risk-analysis-panel">
    <div class="risk-analysis-heading">
      <strong>风险指标</strong>
      <el-tag :type="weightsValid ? 'success' : 'danger'" effect="plain" size="small">
        合计 {{ weightTotal }}%
      </el-tag>
    </div>

    <div class="risk-weight-list">
      <div v-for="item in weightsDraft" :key="item.code" class="risk-weight-row">
        <span>{{ item.code }}</span>
        <el-input-number
          :model-value="item.weight_percent"
          :min="0"
          :max="100"
          :step="5"
          :precision="0"
          :disabled="disabled"
          size="small"
          controls-position="right"
          @update:model-value="updateWeight(item.code, $event)"
        />
      </div>
    </div>
    <small class="risk-analysis-hint">
      前端只做即时提示；指标合法性和权重规则仍以后端 RiskAnalysisPipeline 为最终校验。
    </small>
    <small v-if="disabled" class="risk-analysis-hint">
      当前任务仍在服务端执行，权重暂时锁定，避免丢失正在运行的任务。
    </small>
    <el-button
      type="primary"
      :loading="submitting"
      :disabled="disabled || submitting || !weightsValid"
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

.risk-weight-row > span {
  font-size: 12px;
  font-weight: 700;
}

.risk-weight-row :deep(.el-input-number) {
  width: 126px;
}

.risk-analysis-hint {
  color: var(--muted);
  font-size: 11px;
}
</style>
