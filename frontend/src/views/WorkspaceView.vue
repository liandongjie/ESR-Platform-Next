<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
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
type WorkflowStep = 1 | 2 | 3 | 4
type StudyAreaMethod = 'draw' | 'coordinate' | 'search' | 'administrative' | 'file'
interface MapCanvasDrawingApi {
  startDrawing: (mode: DrawingMode) => void
  cancelDrawing: () => void
}
const mapCanvasRef = ref<MapCanvasDrawingApi | null>(null)
const activeDrawingMode = ref<DrawingMode | null>(null)
const drawingError = ref<string | null>(null)
const activeWorkflowStep = ref<WorkflowStep>(1)
const activeStudyAreaMethod = ref<StudyAreaMethod>('draw')
const activeAnalysisTab = ref<'poi' | 'risk'>('poi')
type ResultDrawerType = 'poi' | 'risk'
const resultDrawerOpen = ref(false)
const resultDrawerType = ref<ResultDrawerType | null>(null)
let sourceMutationRevision = 0
let bufferMutationRevision = 0

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
const poiHasResult = computed(() => analysisStore.poiHasSearched)
const resultAvailable = computed(() => poiHasResult.value || riskHasTaskOrResult.value)
const hasSourceDownstream = computed(
  () => !!analysisStore.bufferResult || resultAvailable.value,
)
const availableWorkflowSteps = computed<WorkflowStep[]>(() => {
  const available: WorkflowStep[] = [1]
  if (analysisStore.sourceGeometryWgs84) available.push(2)
  if (analysisStore.bufferResult) available.push(3)
  if (resultAvailable.value) available.push(4)
  return available
})
const completedWorkflowSteps = computed<WorkflowStep[]>(() => {
  const completed: WorkflowStep[] = []
  if (analysisStore.sourceGeometryWgs84) completed.push(1)
  if (analysisStore.bufferResult) completed.push(2)
  if (resultAvailable.value) completed.push(3)
  if (poiHasResult.value || analysisStore.result) completed.push(4)
  return completed
})
const mapSelectionDisabled = computed(
  () =>
    analysisStore.analysisLocked ||
    activeWorkflowStep.value !== 1 ||
    activeStudyAreaMethod.value !== 'draw',
)

async function confirmDestructiveMutation(message: string, title: string): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, title, {
      type: 'warning',
      confirmButtonText: '继续',
      cancelButtonText: '取消',
    })
    return true
  } catch {
    return false
  }
}

async function commitSourceMutation(
  mutate: () => void,
  kind: 'replace' | 'clear',
  cancelDrawCandidateOnCancel = false,
) {
  if (activeWorkflowStep.value !== 1 || analysisStore.analysisLocked) return
  const revision = ++sourceMutationRevision

  if (hasSourceDownstream.value) {
    const confirmed = await confirmDestructiveMutation(
      kind === 'clear'
        ? '清除研究区将同时清除已有缓冲区及后续分析状态。'
        : '修改研究区将同时清除已有缓冲区及后续分析状态。',
      kind === 'clear' ? '确认清除研究区' : '确认修改研究区',
    )
    if (
      revision !== sourceMutationRevision ||
      activeWorkflowStep.value !== 1 ||
      analysisStore.analysisLocked
    ) {
      return
    }
    if (!confirmed) {
      if (cancelDrawCandidateOnCancel) mapCanvasRef.value?.cancelDrawing()
      return
    }
  }

  mutate()
  drawingError.value = null
  if (kind === 'clear') {
    mapCanvasRef.value?.cancelDrawing()
    return
  }
  if (activeStudyAreaMethod.value !== 'draw') mapCanvasRef.value?.cancelDrawing()
  selectWorkflowStep(2)
}

function handlePointSelected(coordinates: Coordinate) {
  if (mapSelectionDisabled.value) return
  void commitSourceMutation(() => analysisStore.setSourcePoint(coordinates), 'replace', true)
}

function handleGeometrySelected(geometry: SourceGeometry) {
  if (mapSelectionDisabled.value) return
  void commitSourceMutation(() => analysisStore.setSourceGeometry(geometry), 'replace', true)
}

function handleConfirmedGeometrySelected(geometry: SourceGeometry) {
  if (activeWorkflowStep.value !== 1 || analysisStore.analysisLocked) return
  void commitSourceMutation(() => analysisStore.setSourceGeometry(geometry), 'replace')
}

function handleDrawingModeChange(mode: DrawingMode | null) {
  activeDrawingMode.value = mode
}

function handleDrawingError(message: string) {
  drawingError.value = message
}

function startDrawing(mode: DrawingMode) {
  if (mapSelectionDisabled.value) return
  drawingError.value = null
  mapCanvasRef.value?.startDrawing(mode)
}

function cancelDrawing() {
  drawingError.value = null
  mapCanvasRef.value?.cancelDrawing()
}

function clearStudyArea() {
  if (analysisStore.analysisLocked) return
  void commitSourceMutation(() => analysisStore.clearSelection(), 'clear')
}

async function createBuffer(distance: number) {
  if (analysisStore.analysisLocked || activeWorkflowStep.value !== 2) return
  const intentRevision = ++bufferMutationRevision
  if (resultAvailable.value) {
    const confirmed = await confirmDestructiveMutation(
      '重新生成缓冲区将清除已有 POI 查询和风险分析状态。',
      '确认重新生成缓冲区',
    )
    if (
      !confirmed ||
      intentRevision !== bufferMutationRevision ||
      activeWorkflowStep.value !== 2 ||
      analysisStore.analysisLocked
    ) {
      return
    }
  }

  analysisStore.setBufferDistance(distance)
  const request = analysisStore.createBuffer()
  const storeRequestRevision = analysisStore.bufferRequestRevision
  await request
  if (
    intentRevision === bufferMutationRevision &&
    activeWorkflowStep.value === 2 &&
    analysisStore.bufferRequestRevision === storeRequestRevision &&
    !analysisStore.bufferLoading &&
    !analysisStore.bufferError &&
    analysisStore.bufferResult
  ) {
    selectWorkflowStep(3)
  }
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

function resultTypeAvailable(type: ResultDrawerType) {
  return type === 'risk' ? riskHasTaskOrResult.value : poiHasResult.value
}

function openAvailableResult() {
  if (resultDrawerType.value && resultTypeAvailable(resultDrawerType.value)) {
    resultDrawerOpen.value = true
    return
  }
  if (riskHasTaskOrResult.value) openRiskResult()
  else if (poiHasResult.value) openPoiResult()
}

function selectWorkflowStep(step: WorkflowStep) {
  if (!availableWorkflowSteps.value.includes(step)) return
  if (activeWorkflowStep.value === 1 && step !== 1 && activeStudyAreaMethod.value === 'draw') {
    cancelDrawing()
  }
  activeWorkflowStep.value = step
  if (step === 4) openAvailableResult()
  else resultDrawerOpen.value = false
}

function handleStudyAreaMethodChange(method: StudyAreaMethod) {
  if (activeStudyAreaMethod.value === 'draw' && method !== 'draw') cancelDrawing()
  activeStudyAreaMethod.value = method
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

    <WorkspaceWorkflowNavigator
      :active-step="activeWorkflowStep"
      :available-steps="availableWorkflowSteps"
      :completed-steps="completedWorkflowSteps"
      @select-step="selectWorkflowStep"
    />

    <section class="workspace-main" :class="{ 'is-result-step': activeWorkflowStep === 4 }">
      <div class="workspace-map-region">
        <MapCanvas
          ref="mapCanvasRef"
          :source-geometry="analysisStore.sourceGeometryWgs84"
          :buffer-geometry="bufferGeometry"
          :risk-spatial-result="analysisStore.spatialResult"
          :poi-items="analysisStore.poiItems"
          :selection-disabled="mapSelectionDisabled"
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

      <aside
        v-show="activeWorkflowStep !== 4"
        class="result-panel panel-card phase2c-result-panel workspace-context-panel"
      >
        <div class="panel-heading">
          <div>
            <p class="eyebrow">ANALYSIS CONTROL</p>
            <h2>当前分析</h2>
          </div>
        </div>

        <section v-if="activeWorkflowStep === 1" class="control-section study-area-context">
          <StudyAreaPanel
            :disabled="analysisStore.analysisLocked"
            :source-geometry="analysisStore.sourceGeometryWgs84"
            :active-drawing-mode="activeDrawingMode"
            :drawing-error="drawingError"
            :active-method="activeStudyAreaMethod"
            @confirm="handleConfirmedGeometrySelected"
            @start-drawing="startDrawing"
            @cancel-drawing="cancelDrawing"
            @update:active-method="handleStudyAreaMethodChange"
            @clear="clearStudyArea"
          />
        </section>

        <el-empty
          v-if="activeWorkflowStep === 1 && !analysisStore.sourceGeometryWgs84 && !analysisStore.job"
          description="绘制或输入研究区"
          :image-size="86"
        />

        <el-alert
          v-if="activeWorkflowStep === 1 && analysisStore.job && !analysisStore.sourceGeometryWgs84"
          :title="recoveryNoticeText"
          type="info"
          :closable="false"
          show-icon
        />

        <el-button
          v-if="activeWorkflowStep === 1 && analysisStore.job && !analysisStore.sourceGeometryWgs84"
          type="primary"
          plain
          @click="openRiskResult"
        >
          查看任务/结果
        </el-button>

        <el-alert
          v-if="
            analysisStore.job &&
              !analysisStore.sourceGeometryWgs84 &&
              analysisStore.submissionError &&
              activeWorkflowStep === 1
          "
          :title="analysisStore.submissionError"
          type="warning"
          :closable="false"
          show-icon
        />

        <section
          v-if="activeWorkflowStep === 1 && !analysisStore.sourceGeometryWgs84 && analysisStore.submissionContext"
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

        <section v-show="activeWorkflowStep === 2" class="control-section buffer-context">
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

        <section v-show="activeWorkflowStep === 3" class="control-section analysis-context">
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

.workspace-main.is-result-step {
  grid-template-columns: minmax(0, 1fr);
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
