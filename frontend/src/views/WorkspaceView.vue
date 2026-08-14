<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, ref, watch } from 'vue'

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
const serviceCheckComplete = ref(false)
let sourceMutationRevision = 0
let bufferMutationRevision = 0
let initialStepDerived = false
let workflowTakenOver = false
let riskNotificationsArmed = false
const activeRiskStatuses = new Set(['QUEUED', 'RUNNING', 'RETRYING'])

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
const showServiceError = computed(
  () => serviceCheckComplete.value && !systemStore.loading && !systemStore.backendOnline,
)

async function loadSystemStatus() {
  await systemStore.load()
  serviceCheckComplete.value = true
}

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
  workflowTakenOver = true
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
  workflowTakenOver = true
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
  if (!analysisStore.setRiskWeights(weights)) return
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
  workflowTakenOver = true
  if (activeWorkflowStep.value === 1 && step !== 1 && activeStudyAreaMethod.value === 'draw') {
    cancelDrawing()
  }
  activeWorkflowStep.value = step
  if (step === 4) openAvailableResult()
  else resultDrawerOpen.value = false
}

function handleStudyAreaMethodChange(method: StudyAreaMethod) {
  if (activeStudyAreaMethod.value === method) return
  workflowTakenOver = true
  if (activeStudyAreaMethod.value === 'draw' && method !== 'draw') cancelDrawing()
  activeStudyAreaMethod.value = method
}

function deriveInitialWorkflowStep() {
  if (initialStepDerived) return
  initialStepDerived = true
  if (workflowTakenOver) return

  if (analysisStore.bufferResult) activeWorkflowStep.value = 3
  else if (analysisStore.sourceGeometryWgs84) activeWorkflowStep.value = 2
  else activeWorkflowStep.value = 1
}

watch(
  () => [analysisStore.job?.task_id ?? null, analysisStore.jobStatus?.status ?? null] as const,
  ([taskId, status], [previousTaskId, previousStatus]) => {
    if (
      !riskNotificationsArmed ||
      !taskId ||
      taskId !== previousTaskId ||
      !previousStatus ||
      !status ||
      !activeRiskStatuses.has(previousStatus) ||
      (status !== 'SUCCEEDED' && status !== 'FAILED')
    ) {
      return
    }
    if (resultDrawerOpen.value && resultDrawerType.value === 'risk') return

    if (status === 'SUCCEEDED') ElMessage.success('风险分析已完成，可在结果中查看')
    else ElMessage.error('风险分析失败，可查看任务详情')
  },
)

onMounted(async () => {
  void loadSystemStatus()
  const catalogLoading = analysisStore.loadRiskIndicatorCatalog()
  const riskRecovery = analysisStore.restoreRiskAnalysis()
  await Promise.allSettled([catalogLoading, riskRecovery])
  analysisStore.initializeLegacyRiskWeights()
  deriveInitialWorkflowStep()
  riskNotificationsArmed = true
})
</script>

<template>
  <div class="workspace-page">
    <section class="workspace-toolbar">
      <WorkspaceWorkflowNavigator
        :active-step="activeWorkflowStep"
        :available-steps="availableWorkflowSteps"
        :completed-steps="completedWorkflowSteps"
        @select-step="selectWorkflowStep"
      />
      <div v-if="showServiceError" class="workspace-service-error" role="status">
        <span>服务暂不可用</span>
        <el-button size="small" text @click="loadSystemStatus">重试</el-button>
      </div>
    </section>

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
            :risk-indicator-catalog="analysisStore.riskIndicatorCatalog"
            :risk-indicator-catalog-loading="analysisStore.riskIndicatorCatalogLoading"
            :risk-indicator-catalog-error="analysisStore.riskIndicatorCatalogError"
            @poi-query-success="openPoiResult"
            @poi-open-result="openPoiResult"
            @risk-open-result="openRiskResult"
            @retry-risk-catalog="analysisStore.loadRiskIndicatorCatalog"
            @submit-risk="submitRiskAnalysis"
          />
        </section>
      </aside>
    </section>
  </div>
</template>

<style scoped>
.workspace-page {
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow: hidden;
}

.workspace-toolbar {
  flex: none;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  min-height: 36px;
  border: 1px solid var(--border);
  border-bottom: 0;
  background: #fff;
}

.workspace-service-error {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  color: #a33e36;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.workspace-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 380px;
  gap: 0;
  border: 1px solid var(--border);
  overflow: hidden;
  background: #fff;
}

.workspace-main.is-result-step {
  grid-template-columns: minmax(0, 1fr);
}

.workspace-main :deep(.map-card) {
  width: 100%;
  height: 100%;
  min-height: 0;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

.workspace-map-region {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.workspace-context-panel {
  min-width: 0;
  height: 100%;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 12px;
  border: 0;
  border-left: 1px solid var(--border);
  border-radius: 0;
  box-shadow: none;
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

.workspace-context-panel > .control-section:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: 0;
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
  .workspace-main {
    grid-template-columns: minmax(0, 1fr) 340px;
  }
}

@media (max-width: 900px) {
  .workspace-toolbar {
    grid-template-columns: minmax(0, 1fr);
  }

  .workspace-service-error {
    min-height: 36px;
    border-top: 1px solid var(--border);
  }

  .workspace-main {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(240px, 3fr) minmax(220px, 2fr);
  }

  .workspace-main.is-result-step {
    grid-template-rows: minmax(0, 1fr);
  }

  .workspace-context-panel {
    border-left: 0;
    border-top: 1px solid var(--border);
  }
}
</style>
