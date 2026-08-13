<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import WorkspaceWorkflowNavigator from '@/components/workspace/WorkspaceWorkflowNavigator.vue'
import MapCanvas from '@/components/map/MapCanvas.vue'
import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'
import AnalysisPanel from '@/components/workspace/AnalysisPanel.vue'
import BufferPanel from '@/components/workspace/BufferPanel.vue'
import StudyAreaPanel from '@/components/workspace/StudyAreaPanel.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useSystemStore } from '@/stores/system'
import type { Coordinate, SourceGeometry } from '@/types/analysisArea'
import type { RiskIndicatorWeightInput, RiskJobStatus } from '@/types/riskAnalysis'

const systemStore = useSystemStore()
const analysisStore = useAnalysisStore()
type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'
interface MapCanvasDrawingApi {
  startDrawing: (mode: DrawingMode) => void
  cancelDrawing: () => void
}
const mapCanvasRef = ref<MapCanvasDrawingApi | null>(null)
const activeDrawingMode = ref<DrawingMode | null>(null)
const drawingError = ref<string | null>(null)
const activeAnalysisTab = ref<'poi' | 'risk'>('poi')

const maxBufferMeters = computed(() => systemStore.capabilities?.limits.max_buffer_meters)
const bufferGeometry = computed(
  () =>
    analysisStore.bufferResult?.buffer.geometry ??
    analysisStore.submissionContext?.request.geometry ??
    null,
)
const recoveryNoticeText = computed(() => {
  if (analysisStore.submissionContext) {
    return '已从服务端恢复实际分析范围和指标权重；原始研究点、缓冲距离及 Buffer 元数据未保存。'
  }
  if (analysisStore.submissionLoading) return '已恢复当前任务状态，正在读取服务端提交上下文。'
  return '已恢复当前任务状态；原始研究点和缓冲区输入尚未恢复。'
})
const jobStatusText = computed(() => {
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
  if (status === 'RUNNING') return 'primary'
  return 'info'
})
const progressPercentage = computed(() => {
  const progress = analysisStore.jobStatus?.progress
  if (progress === null || progress === undefined) return 0
  return Math.max(0, Math.min(100, progress))
})
const activeWorkflowStep = computed<1 | 2 | 3 | 4>(() => {
  if (analysisStore.result) return 4
  if (analysisStore.job) return 3
  if (!analysisStore.sourceGeometryWgs84) return 1
  if (!analysisStore.bufferResult) return 2
  return 3
})

function handlePointSelected(coordinates: Coordinate) {
  mapCanvasRef.value?.cancelDrawing()
  analysisStore.setSourcePoint(coordinates)
  drawingError.value = null
}

function handleGeometrySelected(geometry: SourceGeometry) {
  if (analysisStore.analysisLocked) return
  analysisStore.setSourceGeometry(geometry)
  drawingError.value = null
}

function handleConfirmedGeometrySelected(geometry: SourceGeometry) {
  if (analysisStore.analysisLocked) return
  mapCanvasRef.value?.cancelDrawing()
  handleGeometrySelected(geometry)
}

function handleDrawingModeChange(mode: DrawingMode | null) {
  activeDrawingMode.value = mode
}

function handleDrawingError(message: string) {
  drawingError.value = message
}

function startDrawing(mode: DrawingMode) {
  if (analysisStore.analysisLocked) return
  drawingError.value = null
  mapCanvasRef.value?.startDrawing(mode)
}

function cancelDrawing() {
  drawingError.value = null
  mapCanvasRef.value?.cancelDrawing()
}

function clearStudyArea() {
  if (analysisStore.analysisLocked) return
  mapCanvasRef.value?.cancelDrawing()
  analysisStore.clearSelection()
  drawingError.value = null
}

function createBuffer(distance: number) {
  if (analysisStore.analysisLocked) return
  analysisStore.setBufferDistance(distance)
  void analysisStore.createBuffer()
}

function submitRiskAnalysis(weights: RiskIndicatorWeightInput[]) {
  if (analysisStore.analysisLocked || !analysisStore.bufferResult) return
  weights.forEach((item) => analysisStore.setWeight(item.code, item.weight_percent))
  void analysisStore.submitRiskAnalysis()
}

function resumeRiskAnalysisPolling() {
  analysisStore.resumeRiskAnalysisPolling()
}

onMounted(() => {
  void systemStore.load()
  void analysisStore.restoreRiskAnalysis()
})
</script>

<template>
  <div class="workspace-page">
    <section class="workspace-header panel-card">
      <div class="workspace-title">
        <div>
          <p class="eyebrow">ANALYSIS WORKSPACE</p>
          <h1>环境社会风险分析工作台</h1>
        </div>
        <div class="workspace-status">
          <span class="service-indicator">
            <span class="status-dot" :class="{ online: systemStore.backendOnline }" />
            {{
              systemStore.loading ? '检查中' : systemStore.backendOnline ? '服务在线' : '服务未连接'
            }}
          </span>
          <span class="crs-chip">EPSG:4326</span>
          <el-button size="small" :loading="systemStore.loading" @click="systemStore.load">
            检查服务
          </el-button>
        </div>
      </div>
    </section>

    <WorkspaceWorkflowNavigator :active-step="activeWorkflowStep" />

    <section class="workspace-main">
      <MapCanvas
        ref="mapCanvasRef"
        :source-geometry="analysisStore.sourceGeometryWgs84"
        :buffer-geometry="bufferGeometry"
        :risk-spatial-result="analysisStore.spatialResult"
        :poi-items="analysisStore.poiItems"
        :selection-disabled="analysisStore.analysisLocked"
        @select-point="handlePointSelected"
        @select-geometry="handleGeometrySelected"
        @drawing-mode-change="handleDrawingModeChange"
        @drawing-error="handleDrawingError"
      />

      <aside class="result-panel panel-card phase2c-result-panel workspace-context-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">ANALYSIS CONTROL</p>
            <h2>当前分析</h2>
          </div>
        </div>

        <section class="control-section">
          <StudyAreaPanel
            :disabled="analysisStore.analysisLocked"
            :source-geometry="analysisStore.sourceGeometryWgs84"
            :active-drawing-mode="activeDrawingMode"
            :drawing-error="drawingError"
            @confirm="handleConfirmedGeometrySelected"
            @start-drawing="startDrawing"
            @cancel-drawing="cancelDrawing"
            @clear="clearStudyArea"
          />
        </section>

        <el-empty
          v-if="!analysisStore.sourceGeometryWgs84 && !analysisStore.job"
          description="绘制或输入研究区"
          :image-size="86"
        />

        <el-alert
          v-if="analysisStore.job && !analysisStore.sourceGeometryWgs84"
          :title="recoveryNoticeText"
          type="info"
          :closable="false"
          show-icon
        />

        <el-alert
          v-if="
            analysisStore.job && !analysisStore.sourceGeometryWgs84 && analysisStore.submissionError
          "
          :title="analysisStore.submissionError"
          type="warning"
          :closable="false"
          show-icon
        />

        <section
          v-if="!analysisStore.sourceGeometryWgs84 && analysisStore.submissionContext"
          class="control-section"
        >
          <div class="section-title-row">
            <strong>服务端提交上下文</strong>
            <el-tag type="info" effect="plain" size="small">WGS84</el-tag>
          </div>
          <div class="task-meta">
            <span>分析范围</span>
            <strong>{{ analysisStore.submissionContext.request.geometry.type }}</strong>
          </div>
          <div class="weight-list">
            <div
              v-for="item in analysisStore.submissionContext.request.weights"
              :key="item.code"
              class="weight-row"
            >
              <span>{{ item.code }}</span>
              <strong>{{ item.weight_percent }}%</strong>
            </div>
          </div>
        </section>

        <template v-if="analysisStore.sourceGeometryWgs84">
          <section class="control-section">
            <BufferPanel
              :committed-distance="analysisStore.bufferDistanceMeters"
              :max-distance="maxBufferMeters"
              :disabled="analysisStore.analysisLocked"
              :loading="analysisStore.bufferLoading"
              :error="analysisStore.bufferError"
              :result="analysisStore.bufferResult"
              @generate="createBuffer"
            />
          </section>

          <section v-if="analysisStore.bufferResult" class="control-section">
            <AnalysisPanel
              v-model:active-tab="activeAnalysisTab"
              :disabled="analysisStore.analysisLocked"
              :committed-weights="analysisStore.weights"
              :risk-submitting="analysisStore.jobSubmitting"
              :risk-polling="analysisStore.polling"
              @submit-risk="submitRiskAnalysis"
            />
          </section>
        </template>

        <section v-if="analysisStore.job || analysisStore.taskError" class="control-section">
          <div class="section-title-row">
            <strong>异步任务</strong>
            <el-tag :type="jobStatusType" effect="plain" size="small">
              {{ jobStatusText }}
            </el-tag>
          </div>

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
          <el-button v-if="analysisStore.canResumePolling" plain @click="resumeRiskAnalysisPolling">
            重新查询当前任务
          </el-button>
        </section>

        <section v-if="analysisStore.result" class="control-section result-section">
          <div class="section-title-row">
            <strong>分析结果</strong>
            <el-tag type="success" effect="dark" size="small">SUCCEEDED</el-tag>
          </div>

          <RiskAnalysisResultDownloads :task-id="analysisStore.result.task_id" />

          <small v-if="analysisStore.spatialLoading" class="section-hint">
            正在加载空间风险分布…
          </small>
          <el-alert
            v-if="analysisStore.spatialWarning"
            :title="analysisStore.spatialWarning"
            type="warning"
            :closable="false"
            show-icon
          />

          <div class="statistics-grid">
            <div>
              <span>有效像元</span>
              <strong>{{ analysisStore.result.statistics.valid_pixel_count }}</strong>
            </div>
            <div>
              <span>最小值</span>
              <strong>{{ analysisStore.result.statistics.minimum.toFixed(6) }}</strong>
            </div>
            <div>
              <span>平均值</span>
              <strong>{{ analysisStore.result.statistics.mean.toFixed(6) }}</strong>
            </div>
            <div>
              <span>最大值</span>
              <strong>{{ analysisStore.result.statistics.maximum.toFixed(6) }}</strong>
            </div>
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
      </aside>
    </section>

    <el-alert
      v-if="systemStore.error"
      class="service-error"
      :title="`后端连接失败：${systemStore.error}`"
      type="warning"
      :closable="false"
      show-icon
    />
  </div>
</template>

<style scoped>
.workspace-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.workspace-header {
  flex: none;
  padding: 10px 14px;
  box-shadow: 0 6px 20px rgba(43, 73, 121, 0.05);
}

.workspace-title,
.workspace-status {
  display: flex;
  align-items: center;
}

.workspace-title {
  justify-content: space-between;
  gap: 16px;
}

.workspace-title h1 {
  margin: 3px 0 0;
  font-size: 18px;
  letter-spacing: -0.01em;
}

.workspace-status {
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}

.service-indicator,
.crs-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 28px;
  padding: 0 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #f8faff;
  color: #60708d;
  font-size: 11px;
  white-space: nowrap;
}

.workspace-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
}

.workspace-main :deep(.map-card) {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.workspace-context-panel {
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.phase2c-result-panel {
  overflow-y: auto;
}

.control-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.section-title-row small,
.section-hint,
.statistics-grid span,
.task-meta span,
.indicator-results small,
.indicator-results > div > span {
  color: var(--muted);
  font-size: 11px;
}

.control-section {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}

.control-section :deep(.el-input-number) {
  width: 100%;
}

.section-title-row,
.weight-row,
.task-meta,
.indicator-results > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row > strong {
  font-size: 13px;
}

.weight-list,
.indicator-results {
  display: grid;
  gap: 9px;
}

.weight-row > span {
  font-size: 12px;
  font-weight: 700;
}

.task-meta strong,
.indicator-results > div > span {
  font-size: 12px;
  text-align: right;
}

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

.statistics-grid strong {
  font-size: 13px;
}

.indicator-results > div {
  padding: 9px 0;
  border-bottom: 1px dashed var(--border);
}

.indicator-results > div:last-child {
  border-bottom: 0;
}

.indicator-results > div > div {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

@media (max-width: 1200px) {
  .workspace-page {
    gap: 10px;
  }

  .workspace-header {
    padding: 9px 12px;
  }

  .workspace-main {
    grid-template-columns: minmax(0, 1fr) 330px;
    gap: 12px;
  }
}
</style>
