<script setup lang="ts">
import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import RiskAnalysisPanel from '@/components/workspace/RiskAnalysisPanel.vue'
import type { RiskIndicatorWeightInput } from '@/types/riskAnalysis'

type AnalysisTab = 'poi' | 'risk'

defineProps<{
  activeTab: AnalysisTab
  disabled: boolean
  committedWeights: RiskIndicatorWeightInput[]
  riskSubmitting: boolean
  riskPolling: boolean
}>()

defineEmits<{
  'update:activeTab': [tab: AnalysisTab]
  'submit-risk': [weights: RiskIndicatorWeightInput[]]
}>()
</script>

<template>
  <section class="analysis-panel">
    <div class="analysis-panel-heading">
      <strong>分析</strong>
    </div>
    <div class="analysis-tabs" role="tablist" aria-label="分析输入方式">
      <button
        type="button"
        class="analysis-tab"
        :class="{ active: activeTab === 'poi' }"
        role="tab"
        :aria-selected="activeTab === 'poi'"
        @click="$emit('update:activeTab', 'poi')"
      >
        POI
      </button>
      <button
        type="button"
        class="analysis-tab"
        :class="{ active: activeTab === 'risk' }"
        role="tab"
        :aria-selected="activeTab === 'risk'"
        @click="$emit('update:activeTab', 'risk')"
      >
        风险
      </button>
    </div>

    <div v-show="activeTab === 'poi'" class="analysis-tab-content" role="tabpanel">
      <PoiSearchPanel :disabled="disabled" />
    </div>
    <div v-show="activeTab === 'risk'" class="analysis-tab-content" role="tabpanel">
      <RiskAnalysisPanel
        :committed-weights="committedWeights"
        :disabled="disabled"
        :submitting="riskSubmitting"
        :polling="riskPolling"
        @submit="$emit('submit-risk', $event)"
      />
    </div>
  </section>
</template>

<style scoped>
.analysis-panel,
.analysis-tab-content {
  display: grid;
  gap: 10px;
}

.analysis-panel-heading > strong {
  font-size: 13px;
}

.analysis-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
}

.analysis-tab {
  padding: 8px;
  border: 0;
  border-right: 1px solid var(--border);
  background: #fff;
  color: var(--muted);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.analysis-tab:last-child {
  border-right: 0;
}

.analysis-tab.active {
  background: #edf3ff;
  color: var(--primary);
  font-weight: 700;
}

.analysis-tab:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}

.analysis-tab-content {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fbfcff;
}
</style>
