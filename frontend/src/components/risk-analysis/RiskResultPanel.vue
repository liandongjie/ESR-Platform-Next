<script setup lang="ts">
import { computed } from 'vue'

import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'
import { useAnalysisStore } from '@/stores/analysis'
import type { RiskJobStatus } from '@/types/riskAnalysis'

const analysisStore = useAnalysisStore()

const jobStatusText = computed(() => {
  if (analysisStore.jobSubmitting) return '提交中'
  const status = analysisStore.jobStatus?.status
  if (!status) return '未提交'
  const labels: Record<RiskJobStatus, string> = {
    QUEUED: '排队中',
    RUNNING: '分析中',
    RETRYING: '重试中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELED: '已取消',
  }
  return labels[status]
})
const jobStatusType = computed<'success' | 'warning' | 'danger' | 'info' | 'primary'>(() => {
  const status = analysisStore.jobStatus?.status
  if (status === 'SUCCEEDED') return 'success'
  if (status === 'FAILED' || status === 'CANCELED') return 'danger'
  if (status === 'RETRYING') return 'warning'
  if (status === 'RUNNING' || analysisStore.jobSubmitting) return 'primary'
  return 'info'
})
const progressPercentage = computed(() => {
  const progress = analysisStore.jobStatus?.progress
  if (progress === null || progress === undefined) return 0
  return Math.max(0, Math.min(100, progress))
})
</script>

<template>
  <section class="risk-result-panel">
    <section class="risk-result-section">
      <div class="section-title-row">
        <strong>异步任务</strong>
        <el-tag :type="jobStatusType" effect="plain" size="small">
          {{ jobStatusText }}
        </el-tag>
      </div>

      <small v-if="analysisStore.jobSubmitting" class="section-hint">正在提交风险分析任务…</small>
      <div v-if="analysisStore.job" class="task-meta">
        <span>Task ID</span>
        <code>{{ analysisStore.job.task_id }}</code>
      </div>
      <div v-if="analysisStore.jobStatus" class="task-meta">
        <span>Stage</span>
        <strong>{{ analysisStore.jobStatus.stage }}</strong>
      </div>
      <el-progress
        v-if="analysisStore.jobStatus"
        :percentage="progressPercentage"
        :status="analysisStore.result ? 'success' : undefined"
      />
      <small v-if="analysisStore.polling" class="section-hint">
        正在按服务端建议间隔查询状态，任务进入终态后会自动停止。
      </small>
      <el-alert
        v-if="analysisStore.taskError"
        :title="analysisStore.taskError"
        type="error"
        :closable="false"
        show-icon
      />
      <el-button
        v-if="analysisStore.canResumePolling"
        plain
        @click="analysisStore.resumeRiskAnalysisPolling"
      >
        重新查询当前任务
      </el-button>
    </section>

    <section v-if="analysisStore.result" class="risk-result-section">
      <div class="section-title-row">
        <strong>分析结果</strong>
        <el-tag type="success" effect="dark" size="small">SUCCEEDED</el-tag>
      </div>

      <RiskAnalysisResultDownloads :task-id="analysisStore.result.task_id" />
      <small v-if="analysisStore.spatialLoading" class="section-hint">正在加载空间风险分布…</small>
      <el-alert
        v-if="analysisStore.spatialWarning"
        :title="analysisStore.spatialWarning"
        type="warning"
        :closable="false"
        show-icon
      />

      <div class="statistics-grid">
        <div><span>有效像元</span><strong>{{ analysisStore.result.statistics.valid_pixel_count }}</strong></div>
        <div><span>最小值</span><strong>{{ analysisStore.result.statistics.minimum.toFixed(6) }}</strong></div>
        <div><span>平均值</span><strong>{{ analysisStore.result.statistics.mean.toFixed(6) }}</strong></div>
        <div><span>最大值</span><strong>{{ analysisStore.result.statistics.maximum.toFixed(6) }}</strong></div>
      </div>

      <div class="task-meta">
        <span>Grid</span>
        <strong>
          {{ analysisStore.result.grid.shape[0] }} × {{ analysisStore.result.grid.shape[1] }} ·
          {{ analysisStore.result.grid.crs }}
        </strong>
      </div>

      <div class="indicator-results">
        <div v-for="indicator in analysisStore.result.indicators" :key="indicator.code">
          <div>
            <strong>{{ indicator.code }}</strong>
            <small>{{ indicator.name }} · {{ indicator.weight_percent }}%</small>
          </div>
          <span>mean {{ indicator.statistics.mean.toFixed(6) }}</span>
        </div>
      </div>
    </section>
  </section>
</template>

<style scoped>
.risk-result-panel,
.risk-result-section,
.indicator-results {
  display: grid;
  gap: 10px;
}

.risk-result-section + .risk-result-section {
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.section-title-row,
.task-meta,
.indicator-results > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row > strong { font-size: 13px; }
.section-hint,
.statistics-grid span,
.task-meta span,
.indicator-results small,
.indicator-results > div > span {
  color: var(--muted);
  font-size: 11px;
}

.task-meta strong,
.indicator-results > div > span { font-size: 12px; text-align: right; }
.task-meta code {
  max-width: 205px;
  overflow: hidden;
  color: #334b72;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.statistics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}
.statistics-grid > div {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border-radius: 9px;
  background: #f6f8fc;
}
.statistics-grid strong { font-size: 13px; }
.indicator-results > div { padding-bottom: 8px; border-bottom: 1px solid #edf0f6; }
.indicator-results > div:last-child { border-bottom: 0; }
.indicator-results > div > div { display: grid; gap: 2px; }
</style>
