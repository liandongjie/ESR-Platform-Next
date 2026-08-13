<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import WorkspaceWorkflowNavigator from '@/components/workspace/WorkspaceWorkflowNavigator.vue'
import MapCanvas from '@/components/map/MapCanvas.vue'
import PoiResultPanel from '@/components/poi/PoiResultPanel.vue'
import RiskResultPanel from '@/components/risk-analysis/RiskResultPanel.vue'
import AnalysisPanel from '@/components/workspace/AnalysisPanel.vue'
import BufferPanel from '@/components/workspace/BufferPanel.vue'
import StudyAreaPanel from '@/components/workspace/StudyAreaPanel.vue'
import WorkspaceResultDrawer from '@/components/workspace/WorkspaceResultDrawer.vue'
import { useAnalysisStore } from '@/stores/analysis'
import { useSystemStore } from '@/stores/system'
import type { Coordinate, SourceGeometry } from '@/types/analysisArea'
import type { RiskIndicatorWeightInput } from '@/types/riskAnalysis'

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
type ResultDrawerType = 'poi' | 'risk'
const resultDrawerOpen = ref(false)
const resultDrawerType = ref<ResultDrawerType | null>(null)

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
const resultDrawerTitle = computed(() =>
  resultDrawerType.value === 'risk' ? '风险任务 / 结果' : 'POI 结果',
)
const riskHasTaskOrResult = computed(
  () =>
    analysisStore.jobSubmitting ||
    analysisStore.polling ||
    !!analysisStore.job ||
    !!analysisStore.result ||
    !!analysisStore.taskError,
)
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
  openRiskResult()
}

function openPoiResult() {
  resultDrawerType.value = 'poi'
  resultDrawerOpen.value = true
}

function openRiskResult() {
  resultDrawerType.value = 'risk'
  resultDrawerOpen.value = true
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
      <div class="workspace-map-region">
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

        <WorkspaceResultDrawer
          :open="resultDrawerOpen"
          :title="resultDrawerTitle"
          @close="resultDrawerOpen = false"
        >
          <PoiResultPanel v-if="resultDrawerType === 'poi'" />
          <RiskResultPanel v-else-if="resultDrawerType === 'risk'" />
        </WorkspaceResultDrawer>
      </div>

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

        <el-button
          v-if="analysisStore.job && !analysisStore.sourceGeometryWgs84"
          type="primary"
          plain
          @click="openRiskResult"
        >
          查看任务/结果
        </el-button>

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
              :risk-has-task-or-result="riskHasTaskOrResult"
              @poi-query-success="openPoiResult"
              @poi-open-result="openPoiResult"
              @risk-open-result="openRiskResult"
              @submit-risk="submitRiskAnalysis"
            />
          </section>
        </template>
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

.workspace-map-region {
  position: relative;
  min-width: 0;
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
.task-meta span {
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
.task-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.section-title-row > strong {
  font-size: 13px;
}

.weight-list {
  display: grid;
  gap: 9px;
}

.weight-row > span {
  font-size: 12px;
  font-weight: 700;
}

.task-meta strong {
  font-size: 12px;
  text-align: right;
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
