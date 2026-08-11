<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import StatusCard from '@/components/common/StatusCard.vue'
import MapCanvas from '@/components/map/MapCanvas.vue'
import PoiSearchPanel from '@/components/poi/PoiSearchPanel.vue'
import RiskAnalysisResultDownloads from '@/components/risk-analysis/RiskAnalysisResultDownloads.vue'
import { searchAmapStudyPoints } from '@/map/amapStudyPoint'
import { useAnalysisStore } from '@/stores/analysis'
import { useSystemStore } from '@/stores/system'
import type { Coordinate, SourceGeometry } from '@/types/analysisArea'
import type { StudyPointCandidate } from '@/types/poi'
import type { RiskJobStatus } from '@/types/riskAnalysis'

const systemStore = useSystemStore()
const analysisStore = useAnalysisStore()
const decimalDegreesPattern = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/
const longitudeInput = ref('')
const latitudeInput = ref('')
const coordinateInputError = ref<string | null>(null)
const studyPointKeyword = ref('')
const studyPointCandidates = ref<StudyPointCandidate[]>([])
const studyPointLoading = ref(false)
const studyPointError = ref<string | null>(null)
const studyPointHasSearched = ref(false)
const selectedStudyPointName = ref<string | null>(null)
let studyPointRequestRevision = 0
type DrawingMode = 'point' | 'polyline' | 'rectangle' | 'polygon'
interface MapCanvasDrawingApi {
  startDrawing: (mode: DrawingMode) => void
  cancelDrawing: () => void
}
const mapCanvasRef = ref<MapCanvasDrawingApi | null>(null)
const activeDrawingMode = ref<DrawingMode | null>(null)
const drawingError = ref<string | null>(null)
const drawingModes: Array<{ mode: DrawingMode; label: string }> = [
  { mode: 'point', label: '点' },
  { mode: 'polyline', label: '线' },
  { mode: 'rectangle', label: '矩形' },
  { mode: 'polygon', label: '多边形' },
]

const backendText = computed(() => {
  if (systemStore.loading) return '检查中'
  return systemStore.backendOnline ? '在线' : '未连接'
})

const resultRetentionText = computed(() => {
  const hours = systemStore.capabilities?.result_ttl_hours
  return hours ? `${hours} 小时` : '读取中'
})

const maxBufferMeters = computed(() => systemStore.capabilities?.limits.max_buffer_meters)
const bufferDistance = computed({
  get: () => analysisStore.bufferDistanceMeters,
  set: (value: number | undefined) => {
    if (typeof value === 'number' && Number.isFinite(value)) {
      analysisStore.setBufferDistance(value)
    }
  },
})
const bufferDistanceValid = computed(() => {
  const distance = analysisStore.bufferDistanceMeters
  if (!Number.isFinite(distance) || distance <= 0) return false
  return maxBufferMeters.value === undefined || distance <= maxBufferMeters.value
})
const bufferLimitText = computed(() => {
  if (maxBufferMeters.value === undefined) return '上限以服务端校验为准'
  return `服务端当前上限 ${maxBufferMeters.value.toLocaleString()} 米`
})
const sourceGeometrySummary = computed(() => {
  const geometry = analysisStore.sourceGeometryWgs84
  if (!geometry) return null
  if (geometry.type === 'Point') {
    return `${geometry.coordinates[0].toFixed(6)}, ${geometry.coordinates[1].toFixed(6)}`
  }
  if (geometry.type === 'LineString') {
    return `LineString · ${geometry.coordinates.length} 个顶点`
  }
  return `Polygon · ${Math.max(0, geometry.coordinates[0]?.length ?? 1) - 1} 个顶点`
})
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
const weightTotal = computed(() =>
  analysisStore.weights.reduce((sum, item) => sum + item.weight_percent, 0),
)
const weightsValid = computed(
  () =>
    Math.abs(weightTotal.value - 100) <= 1e-6 &&
    analysisStore.weights.some((item) => item.weight_percent > 0),
)
const canSubmitRiskAnalysis = computed(
  () => !!analysisStore.bufferResult && weightsValid.value && !analysisStore.analysisLocked,
)
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
const activeWorkflowStep = computed(() => {
  if (analysisStore.result) return 5
  if (analysisStore.job) return 4
  if (!analysisStore.sourceGeometryWgs84) return 1
  if (!analysisStore.bufferResult) return 2
  return 3
})

function handlePointSelected(coordinates: Coordinate) {
  mapCanvasRef.value?.cancelDrawing()
  analysisStore.setSourcePoint(coordinates)
  selectedStudyPointName.value = null
  drawingError.value = null
}

function handleGeometrySelected(geometry: SourceGeometry) {
  if (analysisStore.analysisLocked) return
  analysisStore.setSourceGeometry(geometry)
  selectedStudyPointName.value = null
  drawingError.value = null
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
  if (analysisStore.analysisLocked) return
  drawingError.value = null
  mapCanvasRef.value?.cancelDrawing()
}

function clearStudyArea() {
  if (analysisStore.analysisLocked) return
  mapCanvasRef.value?.cancelDrawing()
  analysisStore.clearSelection()
  selectedStudyPointName.value = null
  drawingError.value = null
}

watch(studyPointKeyword, () => {
  studyPointRequestRevision += 1
  studyPointCandidates.value = []
  studyPointLoading.value = false
  studyPointError.value = null
  studyPointHasSearched.value = false
})

async function searchStudyPoints() {
  if (analysisStore.analysisLocked || studyPointLoading.value) return

  const submittedKeyword = studyPointKeyword.value.trim()
  if (!submittedKeyword) {
    studyPointError.value = '请输入地址或 POI 关键词'
    studyPointHasSearched.value = false
    return
  }

  const revision = ++studyPointRequestRevision
  studyPointCandidates.value = []
  studyPointLoading.value = true
  studyPointError.value = null
  studyPointHasSearched.value = false

  try {
    const candidates = await searchAmapStudyPoints(submittedKeyword)
    if (
      revision !== studyPointRequestRevision ||
      studyPointKeyword.value.trim() !== submittedKeyword
    ) {
      return
    }
    studyPointCandidates.value = candidates
    studyPointHasSearched.value = true
  } catch (error: unknown) {
    if (
      revision !== studyPointRequestRevision ||
      studyPointKeyword.value.trim() !== submittedKeyword
    ) {
      return
    }
    studyPointError.value = error instanceof Error ? error.message : '地址或 POI 搜索失败'
  } finally {
    if (
      revision === studyPointRequestRevision &&
      studyPointKeyword.value.trim() === submittedKeyword
    ) {
      studyPointLoading.value = false
    }
  }
}

function selectStudyPoint(candidate: StudyPointCandidate) {
  if (analysisStore.analysisLocked) return
  handlePointSelected(candidate.locationWgs84)
  selectedStudyPointName.value = candidate.name
}

function applyCoordinateInput() {
  if (analysisStore.analysisLocked) return

  const longitudeText = longitudeInput.value.trim()
  const latitudeText = latitudeInput.value.trim()
  if (!longitudeText || !latitudeText) {
    coordinateInputError.value = '请输入经度和纬度'
    return
  }
  if (!decimalDegreesPattern.test(longitudeText) || !decimalDegreesPattern.test(latitudeText)) {
    coordinateInputError.value = '经纬度只接受普通十进制度文本'
    return
  }

  const longitude = Number(longitudeText)
  const latitude = Number(latitudeText)
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
    coordinateInputError.value = '经纬度必须是有限数值'
    return
  }
  if (longitude < -180 || longitude > 180) {
    coordinateInputError.value = '经度必须在 -180 至 180 之间'
    return
  }
  if (latitude < -90 || latitude > 90) {
    coordinateInputError.value = '纬度必须在 -90 至 90 之间'
    return
  }

  coordinateInputError.value = null
  handlePointSelected([longitude, latitude])
}

function createBuffer() {
  if (!bufferDistanceValid.value || analysisStore.analysisLocked) return
  void analysisStore.createBuffer()
}

function updateWeight(code: string, value: number | undefined) {
  if (analysisStore.analysisLocked || typeof value !== 'number' || !Number.isFinite(value)) return
  analysisStore.setWeight(code, value)
}

function submitRiskAnalysis() {
  if (!canSubmitRiskAnalysis.value) return
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
    <section class="page-heading">
      <div>
        <p class="eyebrow">ANALYSIS WORKSPACE</p>
        <h1>环境社会风险分析工作台</h1>
        <p>选择研究点、生成米制缓冲区，并提交真实栅格风险分析任务。</p>
      </div>
      <el-button type="primary" :loading="systemStore.loading" @click="systemStore.load">
        检查服务
      </el-button>
    </section>

    <section class="status-grid">
      <StatusCard label="后端服务" :value="backendText" hint="Flask / API v1" />
      <StatusCard label="内部坐标系" value="EPSG:4326" hint="地图展示适配 GCJ-02" />
      <StatusCard label="结果保留" :value="resultRetentionText" hint="以后端 capabilities 为准" />
      <StatusCard label="项目阶段" value="Phase 2C" hint="前端风险分析最小闭环" />
    </section>

    <section class="workspace-grid phase2c-workspace-grid">
      <aside class="workflow-panel panel-card">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">WORKFLOW</p>
            <h2>分析流程</h2>
          </div>
        </div>
        <ol class="workflow-list">
          <li :class="{ active: activeWorkflowStep === 1 }">
            <span>01</span>
            <div>
              <strong>选择研究区</strong>
              <small>支持地图点击或 WGS84 坐标输入</small>
            </div>
          </li>
          <li :class="{ active: activeWorkflowStep === 2 }">
            <span>02</span>
            <div>
              <strong>设置缓冲区</strong>
              <small>{{ bufferLimitText }}</small>
            </div>
          </li>
          <li :class="{ active: activeWorkflowStep === 3 }">
            <span>03</span>
            <div>
              <strong>配置风险指标</strong>
              <small>PM25 / AQI / NDVI 权重合计 100%</small>
            </div>
          </li>
          <li :class="{ active: activeWorkflowStep === 4 }">
            <span>04</span>
            <div>
              <strong>提交异步任务</strong>
              <small>轮询 Celery Job，终态自动停止</small>
            </div>
          </li>
          <li :class="{ active: activeWorkflowStep === 5 }">
            <span>05</span>
            <div>
              <strong>查看分析结果</strong>
              <small>展示有效像元和真实风险统计</small>
            </div>
          </li>
        </ol>
      </aside>

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

      <aside class="result-panel panel-card phase2c-result-panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">ANALYSIS CONTROL</p>
            <h2>当前分析</h2>
          </div>
        </div>

        <section class="control-section">
          <div class="section-title-row">
            <strong>在线绘制</strong>
            <el-tag v-if="activeDrawingMode" type="primary" effect="plain" size="small">
              {{ drawingModes.find((item) => item.mode === activeDrawingMode)?.label }}绘制中
            </el-tag>
          </div>
          <div class="drawing-tool-grid">
            <el-button
              v-for="item in drawingModes"
              :key="item.mode"
              :type="activeDrawingMode === item.mode ? 'primary' : 'default'"
              :disabled="analysisStore.analysisLocked"
              :aria-label="`绘制${item.label}`"
              @click="startDrawing(item.mode)"
            >
              {{ item.label }}
            </el-button>
          </div>
          <div class="drawing-actions">
            <el-button
              :disabled="analysisStore.analysisLocked || !activeDrawingMode"
              @click="cancelDrawing"
            >
              取消绘制
            </el-button>
            <el-button
              type="danger"
              plain
              :disabled="
                analysisStore.analysisLocked ||
                  (!analysisStore.sourceGeometryWgs84 && !activeDrawingMode)
              "
              @click="clearStudyArea"
            >
              清除研究区
            </el-button>
          </div>
          <el-alert
            v-if="drawingError"
            :title="drawingError"
            type="error"
            :closable="false"
            show-icon
          />

          <div class="section-title-row">
            <strong>输入研究点</strong>
            <small>WGS84 / EPSG:4326</small>
          </div>
          <div class="coordinate-input-grid">
            <el-input
              v-model="longitudeInput"
              aria-label="研究点经度"
              placeholder="经度 [-180, 180]"
              :disabled="analysisStore.analysisLocked"
            />
            <el-input
              v-model="latitudeInput"
              aria-label="研究点纬度"
              placeholder="纬度 [-90, 90]"
              :disabled="analysisStore.analysisLocked"
            />
          </div>
          <small class="section-hint">仅支持普通十进制度，不支持科学计数法等格式。</small>
          <el-button
            type="primary"
            plain
            :disabled="analysisStore.analysisLocked"
            @click="applyCoordinateInput"
          >
            使用该坐标
          </el-button>
          <el-alert
            v-if="coordinateInputError"
            :title="coordinateInputError"
            type="error"
            :closable="false"
            show-icon
          />

          <div class="study-point-search">
            <div class="section-title-row">
              <strong>搜索地址 / POI</strong>
              <small>高德地点搜索</small>
            </div>
            <div class="study-point-search-row">
              <el-input
                v-model="studyPointKeyword"
                aria-label="地址或 POI 关键词"
                placeholder="如：南京大学、中关村"
                :disabled="analysisStore.analysisLocked"
                @keyup.enter="searchStudyPoints"
              />
              <el-button
                type="primary"
                plain
                :loading="studyPointLoading"
                :disabled="analysisStore.analysisLocked || studyPointLoading"
                @click="searchStudyPoints"
              >
                搜索
              </el-button>
            </div>

            <el-alert
              v-if="studyPointError"
              class="study-point-search-error"
              :title="studyPointError"
              type="error"
              :closable="false"
              show-icon
            />
            <small
              v-else-if="studyPointHasSearched && studyPointCandidates.length === 0"
              class="section-hint study-point-search-empty"
            >
              未找到匹配地点
            </small>
            <small v-if="selectedStudyPointName" class="study-point-selected">
              已选择：{{ selectedStudyPointName }}
            </small>

            <div v-if="studyPointCandidates.length" class="study-point-results">
              <button
                v-for="candidate in studyPointCandidates"
                :key="candidate.id"
                type="button"
                class="study-point-result"
                :disabled="analysisStore.analysisLocked"
                @click="selectStudyPoint(candidate)"
              >
                <strong>{{ candidate.name }}</strong>
                <small>{{ candidate.district }}{{ candidate.address }}</small>
              </button>
            </div>
          </div>
        </section>

        <el-empty
          v-if="!analysisStore.sourceGeometryWgs84 && !analysisStore.job"
          description="点击地图或输入坐标选择研究点"
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
            analysisStore.job &&
              !analysisStore.sourceGeometryWgs84 &&
              analysisStore.submissionError
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
          <div class="selection-summary">
            <span class="selection-label">研究对象（WGS84）</span>
            <strong>{{ sourceGeometrySummary }}</strong>
            <small>地图 GCJ-02 已在适配层转换为 EPSG:4326</small>
          </div>

          <section class="control-section">
            <div class="section-title-row">
              <strong>缓冲区</strong>
              <small>{{ bufferLimitText }}</small>
            </div>
            <el-input-number
              v-model="bufferDistance"
              aria-label="缓冲距离"
              :min="1"
              :max="maxBufferMeters"
              :step="100"
              :precision="0"
              :disabled="analysisStore.analysisLocked"
              controls-position="right"
            />
            <el-button
              type="primary"
              plain
              :loading="analysisStore.bufferLoading"
              :disabled="!bufferDistanceValid || analysisStore.analysisLocked"
              @click="createBuffer"
            >
              生成缓冲区
            </el-button>

            <el-alert
              v-if="analysisStore.bufferError"
              :title="analysisStore.bufferError"
              type="error"
              :closable="false"
              show-icon
            />

            <div v-if="analysisStore.bufferResult" class="compact-result-grid">
              <div>
                <span>面积</span>
                <strong>{{ analysisStore.bufferResult.buffer.area_km2.toFixed(3) }} km²</strong>
              </div>
              <div>
                <span>实际距离</span>
                <strong>
                  {{ analysisStore.bufferResult.buffer.distance_m.toLocaleString() }} m
                </strong>
              </div>
              <div>
                <span>米制工作 CRS</span>
                <strong>{{ analysisStore.bufferResult.buffer.working_crs }}</strong>
              </div>
            </div>
          </section>

          <section v-if="analysisStore.bufferResult" class="control-section">
            <PoiSearchPanel />
          </section>

          <section v-if="analysisStore.bufferResult" class="control-section">
            <div class="section-title-row">
              <strong>风险指标</strong>
              <el-tag :type="weightsValid ? 'success' : 'danger'" effect="plain" size="small">
                合计 {{ weightTotal }}%
              </el-tag>
            </div>
            <div class="weight-list">
              <div v-for="item in analysisStore.weights" :key="item.code" class="weight-row">
                <span>{{ item.code }}</span>
                <el-input-number
                  :model-value="item.weight_percent"
                  :min="0"
                  :max="100"
                  :step="5"
                  :precision="0"
                  :disabled="analysisStore.analysisLocked"
                  size="small"
                  controls-position="right"
                  @update:model-value="updateWeight(item.code, $event)"
                />
              </div>
            </div>
            <small class="section-hint">
              前端只做即时提示；指标合法性和权重规则仍以后端 RiskAnalysisPipeline 为最终校验。
            </small>
            <small v-if="analysisStore.analysisLocked" class="section-hint">
              当前任务仍在服务端执行，研究点、缓冲距离和权重暂时锁定，避免丢失正在运行的任务。
            </small>
            <el-button
              type="primary"
              :loading="analysisStore.jobSubmitting"
              :disabled="!canSubmitRiskAnalysis"
              @click="submitRiskAnalysis"
            >
              {{ analysisStore.polling ? '分析进行中' : '开始风险分析' }}
            </el-button>
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
          <el-button
            v-if="analysisStore.canResumePolling"
            plain
            @click="resumeRiskAnalysisPolling"
          >
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
              {{ analysisStore.result.grid.shape[0] }} ×
              {{ analysisStore.result.grid.shape[1] }} · {{ analysisStore.result.grid.crs }}
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
.phase2c-workspace-grid {
  grid-template-columns: 250px minmax(500px, 1fr) 340px;
}

.phase2c-result-panel {
  overflow-y: auto;
}

.selection-summary,
.control-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.selection-summary {
  margin-top: 22px;
  padding: 12px;
  border-radius: 10px;
  background: #f6f8fc;
}

.selection-label,
.selection-summary small,
.section-title-row small,
.section-hint,
.compact-result-grid span,
.statistics-grid span,
.task-meta span,
.indicator-results small,
.indicator-results > div > span {
  color: var(--muted);
  font-size: 11px;
}

.selection-summary strong {
  font-size: 13px;
  word-break: break-all;
}

.control-section {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}

.control-section :deep(.el-input-number) {
  width: 100%;
}

.coordinate-input-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.drawing-tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.drawing-tool-grid :deep(.el-button),
.drawing-actions :deep(.el-button) {
  margin-left: 0;
}

.drawing-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.study-point-search {
  display: grid;
  gap: 10px;
  margin-top: 8px;
  padding-top: 14px;
  border-top: 1px dashed var(--border);
}

.study-point-search-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.study-point-results {
  display: grid;
  gap: 7px;
}

.study-point-result {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.study-point-result:hover:not(:disabled) {
  border-color: var(--primary);
}

.study-point-result:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.study-point-result strong {
  font-size: 12px;
}

.study-point-result small,
.study-point-selected {
  color: var(--muted);
  font-size: 11px;
}

.study-point-selected {
  color: var(--primary);
}

.section-title-row,
.weight-row,
.compact-result-grid > div,
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
.compact-result-grid,
.indicator-results {
  display: grid;
  gap: 9px;
}

.weight-row > span {
  font-size: 12px;
  font-weight: 700;
}

.weight-row :deep(.el-input-number) {
  width: 126px;
}

.compact-result-grid {
  padding: 11px;
  border-radius: 9px;
  background: #f6f8fc;
}

.compact-result-grid strong,
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
  .phase2c-workspace-grid {
    grid-template-columns: 220px minmax(440px, 1fr) 310px;
  }
}
</style>
