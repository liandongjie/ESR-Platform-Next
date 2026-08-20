<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'

import MapCanvas from '@/components/map/MapCanvas.vue'
import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'
import { useTaskHistoryStore } from '@/stores/taskHistory'
import type { RiskAnalysisJobHistoryItem, RiskJobStatus } from '@/types/riskAnalysis'

const taskHistoryStore = useTaskHistoryStore()

const statusLabels: Record<RiskJobStatus, string> = {
  QUEUED: '排队中',
  RUNNING: '分析中',
  RETRYING: '重试中',
  SUCCEEDED: '已完成',
  FAILED: '失败',
  CANCELED: '已取消',
}

const dateFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

const drawerVisible = computed({
  get: () => taskHistoryStore.selectedTaskId !== null,
  set: (visible: boolean) => {
    if (!visible) taskHistoryStore.closeDetail()
  },
})

function statusText(status: RiskJobStatus): string {
  return statusLabels[status]
}

function statusType(
  status: RiskJobStatus,
): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (status === 'SUCCEEDED') return 'success'
  if (status === 'FAILED' || status === 'CANCELED') return 'danger'
  if (status === 'RETRYING') return 'warning'
  if (status === 'RUNNING') return 'primary'
  return 'info'
}

function submittedAtText(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date)
}

function weightText(item: RiskAnalysisJobHistoryItem): string {
  if (!item.request_summary.weights.length) return '-'
  return item.request_summary.weights
    .map((weight) => `${weight.code} ${weight.weight_percent}%`)
    .join(' · ')
}

function progressText(item: RiskAnalysisJobHistoryItem): string {
  return item.progress === null ? '-' : `${item.progress}%`
}

function openTask(item: RiskAnalysisJobHistoryItem) {
  void taskHistoryStore.openTask(item)
}

function changePage(page: number) {
  void taskHistoryStore.changePage(page)
}

onMounted(() => {
  // 页面每次进入都从服务端重新读取任务；浏览器 F5 后不会依赖旧 Pinia 内存恢复历史。
  void taskHistoryStore.initialize()
})

onBeforeUnmount(() => {
  // 历史列表轮询只服务于当前页面，离开页面后停止，避免后台产生无意义请求。
  taskHistoryStore.stopAutoRefresh()
  taskHistoryStore.closeDetail()
})
</script>

<template>
  <div class="tasks-page">
    <section class="page-heading">
      <div>
        <h1>历史任务</h1>
        <p>任务记录来自服务端持久化元数据，页面刷新后仍可重新发现正在运行和已完成的任务。</p>
      </div>
      <el-button
        type="primary"
        plain
        :loading="taskHistoryStore.refreshing"
        @click="taskHistoryStore.refreshNow"
      >
        刷新任务
      </el-button>
    </section>

    <section class="history-summary-bar" aria-label="任务概览">
      <div>
        <span>任务总数</span>
        <strong>{{ taskHistoryStore.total }}</strong>
      </div>
      <div>
        <span>当前加载</span>
        <strong>{{ taskHistoryStore.items.length }}</strong>
      </div>
      <div>
        <span>状态刷新</span>
        <strong>{{ taskHistoryStore.polling ? '自动刷新中' : '按需刷新' }}</strong>
      </div>
    </section>

    <el-alert
      v-if="taskHistoryStore.error"
      :title="taskHistoryStore.error"
      type="error"
      :closable="false"
      show-icon
    />

    <section class="history-panel">
      <el-skeleton v-if="taskHistoryStore.loading" :rows="6" animated />

      <el-empty
        v-else-if="taskHistoryStore.items.length === 0"
        description="暂无风险分析任务"
      />

      <el-table v-else :data="taskHistoryStore.items" stripe>
        <el-table-column label="提交时间" min-width="180">
          <template #default="{ row }">
            {{ submittedAtText(row.submitted_at) }}
          </template>
        </el-table-column>

        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="进度" width="90">
          <template #default="{ row }">
            {{ progressText(row) }}
          </template>
        </el-table-column>

        <el-table-column prop="stage" label="阶段" min-width="130" />

        <el-table-column label="研究区" width="100">
          <template #default="{ row }">
            {{ row.request_summary.geometry_type || '-' }}
          </template>
        </el-table-column>

        <el-table-column label="指标权重" min-width="260">
          <template #default="{ row }">
            {{ weightText(row) }}
          </template>
        </el-table-column>

        <el-table-column label="任务 ID" min-width="210">
          <template #default="{ row }">
            <code class="task-id">{{ row.task_id }}</code>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openTask(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div
        v-if="taskHistoryStore.total > taskHistoryStore.limit"
        class="pagination-row"
      >
        <el-pagination
          background
          layout="prev, pager, next, total"
          :current-page="taskHistoryStore.page"
          :page-size="taskHistoryStore.limit"
          :total="taskHistoryStore.total"
          @current-change="changePage"
        />
      </div>
    </section>

    <el-drawer v-model="drawerVisible" title="任务详情" size="420px">
      <template v-if="taskHistoryStore.selectedTask">
        <div class="detail-block">
          <span>任务 ID</span>
          <code>{{ taskHistoryStore.selectedTask.task_id }}</code>
        </div>
        <div class="detail-grid">
          <div>
            <span>状态</span>
            <strong>{{ statusText(taskHistoryStore.selectedTask.status) }}</strong>
          </div>
          <div>
            <span>阶段</span>
            <strong>{{ taskHistoryStore.selectedTask.stage }}</strong>
          </div>
          <div>
            <span>进度</span>
            <strong>{{ progressText(taskHistoryStore.selectedTask) }}</strong>
          </div>
          <div>
            <span>提交时间</span>
            <strong>{{ submittedAtText(taskHistoryStore.selectedTask.submitted_at) }}</strong>
          </div>
        </div>

        <el-alert
          v-if="taskHistoryStore.selectedTask.error?.message"
          :title="taskHistoryStore.selectedTask.error.message"
          type="error"
          :closable="false"
          show-icon
        />

        <el-alert
          v-if="taskHistoryStore.detailError"
          :title="taskHistoryStore.detailError"
          type="error"
          :closable="false"
          show-icon
        />

        <el-skeleton v-if="taskHistoryStore.detailLoading" :rows="5" animated />

        <template v-else-if="taskHistoryStore.selectedResult">
          <h3>分析结果</h3>
          <RiskAnalysisResultDownloads :task-id="taskHistoryStore.selectedResult.task_id" />
          <div class="detail-grid">
            <div>
              <span>有效像元</span>
              <strong>{{ taskHistoryStore.selectedResult.statistics.valid_pixel_count }}</strong>
            </div>
            <div>
              <span>最小值</span>
              <strong>{{ taskHistoryStore.selectedResult.statistics.minimum.toFixed(6) }}</strong>
            </div>
            <div>
              <span>平均值</span>
              <strong>{{ taskHistoryStore.selectedResult.statistics.mean.toFixed(6) }}</strong>
            </div>
            <div>
              <span>最大值</span>
              <strong>{{ taskHistoryStore.selectedResult.statistics.maximum.toFixed(6) }}</strong>
            </div>
          </div>

          <div class="indicator-list">
            <div
              v-for="indicator in taskHistoryStore.selectedResult.indicators"
              :key="indicator.code"
            >
              <strong>{{ indicator.code }}</strong>
              <span>{{ indicator.weight_percent }}% · mean {{ indicator.statistics.mean.toFixed(6) }}</span>
            </div>
          </div>
        </template>

        <el-empty
          v-else
          description="任务尚未产生可读取的最终结果"
          :image-size="80"
        />

        <template
          v-if="
            taskHistoryStore.selectedTask.status === 'SUCCEEDED' &&
              taskHistoryStore.selectedTask.result_available
          "
        >
          <h3>空间风险分布</h3>
          <el-alert
            v-if="taskHistoryStore.spatialError"
            :title="taskHistoryStore.spatialError"
            type="warning"
            :closable="false"
            show-icon
          />
          <el-skeleton v-if="taskHistoryStore.spatialLoading" :rows="4" animated />
          <MapCanvas
            v-else-if="taskHistoryStore.selectedRiskPreview || taskHistoryStore.selectedSpatialResult"
            :key="
              taskHistoryStore.selectedRiskPreview?.task_id ??
                taskHistoryStore.selectedSpatialResult?.task_id
            "
            class="task-spatial-map"
            :risk-preview="taskHistoryStore.selectedRiskPreview"
            :risk-spatial-result="taskHistoryStore.selectedSpatialResult"
            read-only
          />
        </template>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.tasks-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.page-heading,
.detail-grid,
.indicator-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.task-spatial-map {
  min-height: 360px;
}

.page-heading h1 {
  margin: 0 0 6px;
  font-size: 24px;
}

.page-heading {
  margin-bottom: 0;
}

.page-heading p:last-child {
  margin: 0;
  color: var(--muted);
}

.history-summary-bar {
  display: flex;
  min-height: 40px;
  align-items: center;
  flex-wrap: wrap;
  gap: 0;
  border: 1px solid var(--border);
  background: #fff;
}

.history-summary-bar > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 7px 14px;
  border-right: 1px solid var(--border);
}

.history-summary-bar span,
.detail-block span,
.detail-grid span,
.indicator-list span {
  display: block;
  color: var(--muted);
  font-size: 12px;
}

.history-summary-bar strong {
  font-size: 14px;
}

.history-panel {
  padding: 10px;
  border: 1px solid var(--border);
  background: #fff;
}

.task-id {
  font-size: 11px;
  word-break: break-all;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  padding-top: 16px;
}

.detail-block,
.detail-grid > div {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: 2px;
  background: var(--surface-subtle);
}

.detail-block code {
  display: block;
  margin-top: 6px;
  word-break: break-all;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}

.detail-grid > div {
  min-width: 0;
}

.detail-grid strong {
  display: block;
  margin-top: 4px;
  font-size: 13px;
  word-break: break-word;
}

h3 {
  margin: 22px 0 10px;
}

.indicator-list {
  display: grid;
  gap: 8px;
  margin-top: 14px;
}

.indicator-list > div {
  padding: 10px 0;
  border-bottom: 1px dashed var(--border);
}

@media (max-width: 900px) {
  .page-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .history-summary-bar > div {
    flex: 1 1 160px;
  }
}
</style>
