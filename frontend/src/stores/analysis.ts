import { defineStore } from 'pinia'

import { createAnalysisAreaBuffer } from '@/api/analysisAreas'
import { getApiErrorMessage } from '@/api/errors'
import type { PoiExportData } from '@/export/poiCsv'
import {
  createRiskAnalysisJob,
  getRiskAnalysisJob,
  getRiskAnalysisResult,
  getRiskAnalysisSpatialResult,
  getRiskAnalysisSubmission,
} from '@/api/riskAnalysis'
import { searchAmapPois, searchAmapPoisInGeometry } from '@/map/amapPoi'
import type {
  AnalysisAreaBufferResponse,
  BufferGeometry,
  Coordinate,
  PolygonGeometry,
  SourceGeometry,
} from '@/types/analysisArea'
import type {
  RiskAnalysisJobStatus,
  RiskAnalysisResult,
  RiskAnalysisSpatialResult,
  RiskAnalysisSubmissionDetail,
  RiskIndicatorWeightInput,
} from '@/types/riskAnalysis'
import type { PoiDto, PoiGeometrySearchTruncatedReason } from '@/types/poi'
import { parseSourceGeometry } from '@/validation/sourceGeometry'

const MAX_CONSECUTIVE_POLL_FAILURES = 3
const DEFAULT_POLL_INTERVAL_MS = 2000
const WORKSPACE_TASK_ID_STORAGE_KEY = 'esr:risk-analysis:workspace-task-id'
const WORKSPACE_DRAFT_STORAGE_KEY = 'esr:risk-analysis:workspace-draft'
const WORKSPACE_WEIGHT_CODES = ['PM25', 'AQI', 'NDVI'] as const
const POI_EXPORT_PAGE_SIZE = 50
const POI_EXPORT_LIMIT = 5000

interface RiskAnalysisJobReference {
  task_id: string
}

interface WorkspaceDraft {
  source_geometry_wgs84: SourceGeometry
  buffer_distance_m: number
  weights: RiskIndicatorWeightInput[]
  buffer_ready: boolean
}

interface AnalysisState {
  sourceGeometryWgs84: SourceGeometry | null
  bufferDistanceMeters: number
  bufferResult: AnalysisAreaBufferResponse | null
  bufferLoading: boolean
  bufferError: string | null
  bufferRequestRevision: number
  poiKeyword: string
  poiPage: number
  poiPageSize: number
  poiItems: PoiDto[]
  poiTotal: number
  poiAggregatedItems: PoiDto[]
  poiReportedCandidateCount: number | null
  poiRetrievedUniqueCount: number | null
  poiRetrievalComplete: boolean | null
  poiHasMore: boolean | null
  poiTruncatedReason: PoiGeometrySearchTruncatedReason | null
  poiLoading: boolean
  poiError: string | null
  poiHasSearched: boolean
  poiRequestRevision: number
  poiCommittedKeyword: string | null
  poiExportLoading: boolean
  poiExportError: string | null
  poiExportProgress: {
    currentPage: number
    plannedPages: number | null
    totalReported: number | null
    retrievableLimit: number | null
  } | null
  poiExportRevision: number
  weights: RiskIndicatorWeightInput[]
  job: RiskAnalysisJobReference | null
  jobStatus: RiskAnalysisJobStatus | null
  result: RiskAnalysisResult | null
  spatialResult: RiskAnalysisSpatialResult | null
  spatialLoadingTaskId: string | null
  spatialWarning: string | null
  submissionContext: RiskAnalysisSubmissionDetail | null
  submissionLoading: boolean
  submissionError: string | null
  jobSubmitting: boolean
  polling: boolean
  taskError: string | null
  jobRevision: number
  pollIntervalMs: number
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function isSimplePoiGeometry(geometry: BufferGeometry): geometry is PolygonGeometry {
  return geometry.type === 'Polygon' && geometry.coordinates.length === 1
}

function readWorkspaceTaskId(): string | null {
  try {
    const taskId = window.sessionStorage.getItem(WORKSPACE_TASK_ID_STORAGE_KEY)?.trim()
    return taskId || null
  } catch {
    return null
  }
}

function saveWorkspaceTaskId(taskId: string): boolean {
  try {
    window.sessionStorage.setItem(WORKSPACE_TASK_ID_STORAGE_KEY, taskId)
    return window.sessionStorage.getItem(WORKSPACE_TASK_ID_STORAGE_KEY) === taskId
  } catch {
    // sessionStorage 不可用时仅失去同标签页 F5 恢复能力，不影响任务提交和轮询。
    return false
  }
}

function clearWorkspaceTaskId(): void {
  try {
    window.sessionStorage.removeItem(WORKSPACE_TASK_ID_STORAGE_KEY)
  } catch {
    // 与写入失败相同，存储不可用不应阻断正常分析流程。
  }
}

function clearWorkspaceDraft(): void {
  try {
    window.sessionStorage.removeItem(WORKSPACE_DRAFT_STORAGE_KEY)
  } catch {
    // Draft 只是同标签页恢复能力，清理失败不能阻断当前 Workspace。
  }
}

function readWorkspaceDraft(): WorkspaceDraft | null {
  try {
    const raw = window.sessionStorage.getItem(WORKSPACE_DRAFT_STORAGE_KEY)
    if (!raw) return null

    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error()

    const draft = value as Record<string, unknown>
    const sourceGeometry = Object.prototype.hasOwnProperty.call(draft, 'source_geometry_wgs84')
      ? parseSourceGeometry(draft.source_geometry_wgs84)
      : parseSourceGeometry({ type: 'Point', coordinates: draft.source_point_wgs84 })
    const distance = draft.buffer_distance_m
    const weights = draft.weights
    if (
      typeof distance !== 'number' ||
      !Number.isFinite(distance) ||
      distance <= 0 ||
      typeof draft.buffer_ready !== 'boolean' ||
      !Array.isArray(weights) ||
      weights.length !== WORKSPACE_WEIGHT_CODES.length
    ) {
      throw new Error()
    }

    const parsedWeights = weights.map((item) => {
      if (typeof item !== 'object' || item === null || Array.isArray(item)) throw new Error()
      const weight = item as Record<string, unknown>
      if (
        typeof weight.code !== 'string' ||
        !WORKSPACE_WEIGHT_CODES.includes(weight.code as (typeof WORKSPACE_WEIGHT_CODES)[number]) ||
        typeof weight.weight_percent !== 'number' ||
        !Number.isFinite(weight.weight_percent) ||
        weight.weight_percent < 0 ||
        weight.weight_percent > 100
      ) {
        throw new Error()
      }
      return { code: weight.code, weight_percent: weight.weight_percent }
    })
    if (new Set(parsedWeights.map((item) => item.code)).size !== WORKSPACE_WEIGHT_CODES.length) {
      throw new Error()
    }

    return {
      source_geometry_wgs84: sourceGeometry,
      buffer_distance_m: distance,
      weights: parsedWeights,
      buffer_ready: draft.buffer_ready,
    }
  } catch {
    clearWorkspaceDraft()
    return null
  }
}

function saveWorkspaceDraft(
  sourceGeometry: SourceGeometry | null,
  bufferDistanceMeters: number,
  weights: RiskIndicatorWeightInput[],
  bufferReady: boolean,
): void {
  if (!sourceGeometry) return
  const draft: WorkspaceDraft = {
    source_geometry_wgs84: parseSourceGeometry(sourceGeometry),
    buffer_distance_m: bufferDistanceMeters,
    weights: weights.map((item) => ({ ...item })),
    buffer_ready: bufferReady,
  }
  try {
    window.sessionStorage.setItem(WORKSPACE_DRAFT_STORAGE_KEY, JSON.stringify(draft))
  } catch {
    // 存储不可用时不影响当前内存中的编辑和提交。
  }
}

export const useAnalysisStore = defineStore('analysis', {
  state: (): AnalysisState => ({
    sourceGeometryWgs84: null,
    bufferDistanceMeters: 3000,
    bufferResult: null,
    bufferLoading: false,
    bufferError: null,
    bufferRequestRevision: 0,
    poiKeyword: '',
    poiPage: 1,
    poiPageSize: 10,
    poiItems: [],
    poiTotal: 0,
    poiAggregatedItems: [],
    poiReportedCandidateCount: null,
    poiRetrievedUniqueCount: null,
    poiRetrievalComplete: null,
    poiHasMore: null,
    poiTruncatedReason: null,
    poiLoading: false,
    poiError: null,
    poiHasSearched: false,
    poiRequestRevision: 0,
    poiCommittedKeyword: null,
    poiExportLoading: false,
    poiExportError: null,
    poiExportProgress: null,
    poiExportRevision: 0,
    weights: [
      { code: 'PM25', weight_percent: 30 },
      { code: 'AQI', weight_percent: 40 },
      { code: 'NDVI', weight_percent: 30 },
    ],
    job: null,
    jobStatus: null,
    result: null,
    spatialResult: null,
    spatialLoadingTaskId: null,
    spatialWarning: null,
    submissionContext: null,
    submissionLoading: false,
    submissionError: null,
    jobSubmitting: false,
    polling: false,
    taskError: null,
    jobRevision: 0,
    pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
  }),
  getters: {
    analysisLocked: (state): boolean => {
      if (state.jobSubmitting || state.polling) return true
      if (!state.job || state.result) return false

      const status = state.jobStatus?.status
      return status !== 'FAILED' && status !== 'CANCELED'
    },
    canResumePolling: (state): boolean => {
      if (!state.job || state.result || state.jobSubmitting || state.polling) return false

      const status = state.jobStatus?.status
      return status !== 'FAILED' && status !== 'CANCELED'
    },
    spatialLoading: (state): boolean => state.spatialLoadingTaskId !== null,
  },
  actions: {
    invalidatePoiExportContext() {
      const wasLoading = this.poiExportLoading
      this.poiExportRevision += 1
      this.poiExportLoading = false
      this.poiExportProgress = null
      this.poiExportError = wasLoading ? '查询条件已变化，导出已取消' : null
    },
    invalidatePoiSearch() {
      this.poiRequestRevision += 1
      this.poiPage = 1
      this.poiItems = []
      this.poiTotal = 0
      this.poiAggregatedItems = []
      this.poiReportedCandidateCount = null
      this.poiRetrievedUniqueCount = null
      this.poiRetrievalComplete = null
      this.poiHasMore = null
      this.poiTruncatedReason = null
      this.poiLoading = false
      this.poiError = null
      this.poiHasSearched = false
    },
    setPoiKeyword(keyword: string) {
      if (this.poiKeyword === keyword) return
      this.poiKeyword = keyword
      this.invalidatePoiSearch()
    },
    async searchPois(page = 1) {
      const keyword = this.poiKeyword.trim()
      if (!keyword) {
        this.poiError = '请输入 POI 关键词'
        return
      }
      if (!this.bufferResult) {
        this.poiError = '请先生成缓冲区'
        return
      }

      const geometry = this.bufferResult.buffer.geometry
      const simpleGeometry = isSimplePoiGeometry(geometry) ? geometry : null

      if (this.poiCommittedKeyword !== keyword) {
        this.poiCommittedKeyword = keyword
        this.invalidatePoiExportContext()
      }

      this.invalidatePoiSearch()
      const revision = this.poiRequestRevision
      const bufferRevision = this.bufferRequestRevision
      const pageSize = this.poiPageSize
      this.poiPage = page
      this.poiItems = []
      this.poiLoading = true
      this.poiError = null
      this.poiHasSearched = false

      try {
        const result = simpleGeometry
          ? await searchAmapPois({ geometry: simpleGeometry, keyword, page, pageSize })
          : await searchAmapPoisInGeometry({ geometry, keyword })
        if (
          revision !== this.poiRequestRevision ||
          bufferRevision !== this.bufferRequestRevision ||
          keyword !== this.poiKeyword.trim() ||
          page !== this.poiPage
        ) {
          return
        }
        if ('reportedCandidateCount' in result) {
          this.poiAggregatedItems = result.items
          this.poiReportedCandidateCount = result.reportedCandidateCount
          this.poiRetrievedUniqueCount = result.retrievedUniqueCount
          this.poiRetrievalComplete = result.retrievalComplete
          this.poiHasMore = result.hasMore
          this.poiTruncatedReason = result.truncatedReason
          const offset = (page - 1) * pageSize
          this.poiItems = result.items.slice(offset, offset + pageSize)
        } else {
          this.poiItems = result.items
          this.poiTotal = result.total
        }
        this.poiHasSearched = true
      } catch (error: unknown) {
        if (revision !== this.poiRequestRevision) return
        this.poiError = getApiErrorMessage(error, 'POI 查询失败')
      } finally {
        if (revision === this.poiRequestRevision) this.poiLoading = false
      }
    },
    async changePoiPage(page: number) {
      if (this.poiReportedCandidateCount === null) {
        await this.searchPois(page)
        return
      }

      this.poiPage = page
      const offset = (page - 1) * this.poiPageSize
      this.poiItems = this.poiAggregatedItems.slice(offset, offset + this.poiPageSize)
    },
    prepareCurrentPagePoiExport(): PoiExportData | null {
      if (this.poiExportLoading) return null
      this.poiExportError = null
      if (!this.poiCommittedKeyword || !this.poiHasSearched || this.poiItems.length === 0) {
        this.poiExportError = '当前页没有可导出的 POI 数据'
        return null
      }

      const items = this.poiItems.map((item) => ({
        ...item,
        locationWgs84: [...item.locationWgs84] as Coordinate,
      }))
      return {
        mode: 'current-page',
        keyword: this.poiCommittedKeyword,
        page: this.poiPage,
        items,
        totalReported: this.poiReportedCandidateCount ?? this.poiTotal,
        retrievableLimit:
          this.poiRetrievedUniqueCount ?? Math.min(this.poiTotal, POI_EXPORT_LIMIT),
        exportedCount: items.length,
      }
    },
    async collectRetrievablePoiExport(): Promise<PoiExportData | null> {
      if (this.poiExportLoading) return null
      this.poiExportError = null
      if (!this.poiCommittedKeyword || !this.poiHasSearched || !this.bufferResult) {
        this.poiExportError = '请先完成 POI 查询'
        return null
      }

      const geometry = this.bufferResult.buffer.geometry
      if (!isSimplePoiGeometry(geometry)) {
        if (this.poiAggregatedItems.length === 0) {
          this.poiExportError = '当前查询没有可导出的 POI 数据'
          return null
        }
        const items = this.poiAggregatedItems.map((item) => ({
          ...item,
          locationWgs84: [...item.locationWgs84] as Coordinate,
        }))
        return {
          mode: 'retrievable',
          keyword: this.poiCommittedKeyword,
          page: null,
          items,
          totalReported: this.poiReportedCandidateCount ?? 0,
          retrievableLimit: this.poiRetrievedUniqueCount ?? items.length,
          exportedCount: items.length,
        }
      }

      const keyword = this.poiCommittedKeyword
      const bufferRevision = this.bufferRequestRevision
      const revision = ++this.poiExportRevision
      const isCurrent = () =>
        revision === this.poiExportRevision &&
        bufferRevision === this.bufferRequestRevision &&
        keyword === this.poiCommittedKeyword

      this.poiExportLoading = true
      this.poiExportProgress = {
        currentPage: 1,
        plannedPages: null,
        totalReported: null,
        retrievableLimit: null,
      }

      try {
        const uniqueItems = new Map<string, PoiDto>()
        let totalReported = 0
        let retrievableLimit = 0
        let plannedPages: number | null = null
        let rawAcceptedCount = 0

        for (let page = 1; page <= (plannedPages ?? 1); page += 1) {
          if (!isCurrent()) return null
          if (page > 1) {
            this.poiExportProgress = {
              currentPage: page,
              plannedPages,
              totalReported,
              retrievableLimit,
            }
          }

          const result = await searchAmapPois({
            geometry,
            keyword,
            page,
            pageSize: POI_EXPORT_PAGE_SIZE,
          })
          if (!isCurrent()) return null

          if (page === 1) {
            totalReported = result.total
            retrievableLimit = Math.min(totalReported, POI_EXPORT_LIMIT)
            plannedPages = Math.ceil(retrievableLimit / POI_EXPORT_PAGE_SIZE)
            this.poiExportProgress = {
              currentPage: 1,
              plannedPages,
              totalReported,
              retrievableLimit,
            }
            if (plannedPages === 0) throw new Error('当前查询没有可导出的 POI 数据')
          }

          if (result.items.length === 0) {
            if (rawAcceptedCount === 0) throw new Error('当前查询没有可导出的 POI 数据')
            break
          }

          // 高德 count 是报告总数，不保证分页 rows 构成严格快照；仅用第一页固定请求计划和消费上限。
          const remaining = retrievableLimit - rawAcceptedCount
          const acceptedItems = result.items.slice(0, remaining)
          rawAcceptedCount += acceptedItems.length
          for (const item of acceptedItems) {
            if (!uniqueItems.has(item.id)) uniqueItems.set(item.id, item)
          }
          if (rawAcceptedCount >= retrievableLimit) break
        }

        if (!isCurrent()) return null
        const items = Array.from(uniqueItems.values(), (item) => ({
          ...item,
          locationWgs84: [...item.locationWgs84] as Coordinate,
        }))
        return {
          mode: 'retrievable',
          keyword,
          page: null,
          items,
          totalReported,
          retrievableLimit,
          exportedCount: items.length,
        }
      } catch (error: unknown) {
        if (isCurrent()) this.poiExportError = getApiErrorMessage(error, 'POI 可获取结果导出失败')
        return null
      } finally {
        if (revision === this.poiExportRevision) {
          this.poiExportLoading = false
          this.poiExportProgress = null
        }
      }
    },
    resetRiskAnalysis() {
      // 不把 Timer 放进 Pinia；递增版本号即可让旧轮询在下一次唤醒时自行退出。
      this.jobRevision += 1
      clearWorkspaceTaskId()
      this.job = null
      this.jobStatus = null
      this.result = null
      this.spatialResult = null
      this.spatialLoadingTaskId = null
      this.spatialWarning = null
      this.submissionContext = null
      this.submissionLoading = false
      this.submissionError = null
      this.jobSubmitting = false
      this.polling = false
      this.taskError = null
      this.pollIntervalMs = DEFAULT_POLL_INTERVAL_MS
    },
    setSourceGeometry(geometry: SourceGeometry) {
      if (this.analysisLocked) return
      const sourceGeometry = parseSourceGeometry(geometry)
      // 切换研究对象会使旧 Buffer 立即失效，同时递增版本号让尚未返回的旧请求无法覆盖新选择。
      this.bufferRequestRevision += 1
      this.poiCommittedKeyword = null
      this.invalidatePoiSearch()
      this.invalidatePoiExportContext()
      this.sourceGeometryWgs84 = sourceGeometry
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
      saveWorkspaceDraft(
        this.sourceGeometryWgs84,
        this.bufferDistanceMeters,
        this.weights,
        false,
      )
    },
    setSourcePoint(coordinates: Coordinate) {
      this.setSourceGeometry({ type: 'Point', coordinates })
    },
    setBufferDistance(distanceMeters: number) {
      if (this.analysisLocked || this.bufferDistanceMeters === distanceMeters) return
      this.bufferRequestRevision += 1
      this.poiCommittedKeyword = null
      this.invalidatePoiSearch()
      this.invalidatePoiExportContext()
      this.bufferDistanceMeters = distanceMeters
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
      saveWorkspaceDraft(
        this.sourceGeometryWgs84,
        this.bufferDistanceMeters,
        this.weights,
        false,
      )
    },
    setWeight(code: string, weightPercent: number) {
      if (this.analysisLocked) return
      const item = this.weights.find((weight) => weight.code === code)
      if (!item || item.weight_percent === weightPercent) return
      item.weight_percent = weightPercent
      this.resetRiskAnalysis()
      saveWorkspaceDraft(
        this.sourceGeometryWgs84,
        this.bufferDistanceMeters,
        this.weights,
        !!this.bufferResult,
      )
    },
    clearSelection() {
      if (this.analysisLocked) return
      this.bufferRequestRevision += 1
      this.poiCommittedKeyword = null
      this.invalidatePoiSearch()
      this.invalidatePoiExportContext()
      this.sourceGeometryWgs84 = null
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
      clearWorkspaceDraft()
    },
    resumeRiskAnalysisPolling() {
      if (!this.canResumePolling) return

      const revision = ++this.jobRevision
      this.polling = true
      this.taskError = null
      void this.pollRiskAnalysis(revision, this.pollIntervalMs)
    },
    async restoreRiskAnalysis() {
      // 路由重新挂载时只允许补取缺失的 Context，不能重复查询状态或启动第二个轮询。
      if (this.job) {
        if (!this.bufferResult) void this.restoreRiskAnalysisSubmission(this.job.task_id)
        return
      }
      if (this.jobSubmitting || this.polling) return

      const taskId = readWorkspaceTaskId()
      if (!taskId) {
        if (this.sourceGeometryWgs84) return
        const draft = readWorkspaceDraft()
        if (!draft) return

        this.sourceGeometryWgs84 = parseSourceGeometry(draft.source_geometry_wgs84)
        this.bufferDistanceMeters = draft.buffer_distance_m
        this.weights = draft.weights.map((item) => ({ ...item }))
        if (draft.buffer_ready) await this.createBuffer()
        return
      }

      const revision = ++this.jobRevision
      this.job = { task_id: taskId }
      this.jobStatus = null
      this.result = null
      this.spatialResult = null
      this.spatialLoadingTaskId = null
      this.spatialWarning = null
      this.submissionContext = null
      this.submissionLoading = false
      this.submissionError = null
      this.jobSubmitting = false
      this.polling = false
      this.taskError = null
      this.pollIntervalMs = DEFAULT_POLL_INTERVAL_MS
      // 提交上下文是补充信息；慢响应或失败不能延迟状态、轮询和 Result 恢复。
      void this.restoreRiskAnalysisSubmission(taskId)

      try {
        const status = await getRiskAnalysisJob(taskId)
        if (revision !== this.jobRevision) return

        // 服务端已确认正式 Task 可接管后，才能清理可能因崩溃残留的 Draft。
        clearWorkspaceDraft()
        this.jobStatus = status
        if (status.status === 'FAILED' || status.status === 'CANCELED') {
          this.taskError =
            status.error?.message || `风险分析任务${status.status === 'FAILED' ? '失败' : '已取消'}`
          return
        }

        if (status.status === 'SUCCEEDED' && status.result_available) {
          const result = await getRiskAnalysisResult(taskId)
          if (revision !== this.jobRevision) return
          this.result = result
          void this.loadRiskAnalysisSpatialResult(taskId, revision)
          return
        }

        this.polling = true
        void this.pollRiskAnalysis(revision, this.pollIntervalMs)
      } catch (error: unknown) {
        if (revision !== this.jobRevision) return
        this.polling = false
        this.taskError = getApiErrorMessage(error, '恢复当前风险分析任务失败')
      }
    },
    async restoreRiskAnalysisSubmission(taskId: string) {
      if (
        this.job?.task_id !== taskId ||
        this.bufferResult ||
        this.submissionContext ||
        this.submissionLoading
      ) {
        return
      }

      this.submissionLoading = true
      this.submissionError = null
      try {
        const submission = await getRiskAnalysisSubmission(taskId)
        if (this.job?.task_id !== taskId) return

        this.submissionContext = submission
        // 当前可编辑 weights 必须复制；只读提交事实始终保留服务端原值。
        this.weights = submission.request.weights.map((item) => ({ ...item }))
      } catch {
        if (this.job?.task_id !== taskId) return
        this.submissionError = '提交上下文恢复失败，但任务状态和分析结果不受影响'
      } finally {
        if (this.job?.task_id === taskId) {
          this.submissionLoading = false
        }
      }
    },
    async loadRiskAnalysisSpatialResult(taskId: string, revision: number) {
      if (
        revision !== this.jobRevision ||
        this.job?.task_id !== taskId ||
        this.result?.task_id !== taskId ||
        this.spatialResult?.task_id === taskId ||
        this.spatialLoadingTaskId === taskId
      ) {
        return
      }

      this.spatialLoadingTaskId = taskId
      this.spatialWarning = null
      try {
        const spatialResult = await getRiskAnalysisSpatialResult(taskId)
        if (
          revision !== this.jobRevision ||
          this.job?.task_id !== taskId ||
          this.result?.task_id !== taskId
        ) {
          return
        }
        this.spatialResult = spatialResult
      } catch (error: unknown) {
        if (
          revision !== this.jobRevision ||
          this.job?.task_id !== taskId ||
          this.result?.task_id !== taskId
        ) {
          return
        }
        this.spatialWarning = getApiErrorMessage(error, '空间风险结果加载失败')
      } finally {
        if (
          revision === this.jobRevision &&
          this.job?.task_id === taskId &&
          this.spatialLoadingTaskId === taskId
        ) {
          this.spatialLoadingTaskId = null
        }
      }
    },
    async createBuffer() {
      if (this.analysisLocked) {
        this.bufferError = '当前风险分析任务尚未结束，暂不能修改研究区'
        return
      }
      if (!this.sourceGeometryWgs84) {
        this.bufferError = '请先在地图上选择研究点'
        return
      }

      const revision = ++this.bufferRequestRevision
      this.poiCommittedKeyword = null
      this.invalidatePoiSearch()
      this.invalidatePoiExportContext()
      const geometry = parseSourceGeometry(this.sourceGeometryWgs84)
      const distanceM = this.bufferDistanceMeters

      this.resetRiskAnalysis()
      this.bufferLoading = true
      this.bufferError = null
      this.bufferResult = null

      try {
        const result = await createAnalysisAreaBuffer({ geometry, distance_m: distanceM })
        // 用户可能在请求期间重新选点或修改距离；旧响应必须丢弃，否则地图会显示与当前参数不一致的 Polygon。
        if (revision !== this.bufferRequestRevision) return
        this.bufferResult = result
        saveWorkspaceDraft(
          this.sourceGeometryWgs84,
          this.bufferDistanceMeters,
          this.weights,
          true,
        )
      } catch (error: unknown) {
        if (revision !== this.bufferRequestRevision) return
        this.bufferError = getApiErrorMessage(error, '生成缓冲区失败')
      } finally {
        if (revision === this.bufferRequestRevision) {
          this.bufferLoading = false
        }
      }
    },
    async submitRiskAnalysis() {
      if (this.analysisLocked) {
        this.taskError = '当前风险分析任务尚未结束，请等待任务完成后再重新提交'
        return
      }
      if (!this.bufferResult) {
        this.taskError = '请先生成缓冲区'
        return
      }

      const totalWeight = this.weights.reduce((sum, item) => sum + item.weight_percent, 0)
      const hasPositiveWeight = this.weights.some((item) => item.weight_percent > 0)
      if (Math.abs(totalWeight - 100) > 1e-6 || !hasPositiveWeight) {
        this.taskError = `指标权重总和必须为 100，当前为 ${totalWeight}`
        return
      }

      const revision = ++this.jobRevision
      clearWorkspaceTaskId()
      this.job = null
      this.jobStatus = null
      this.result = null
      this.spatialResult = null
      this.spatialLoadingTaskId = null
      this.spatialWarning = null
      this.submissionContext = null
      this.submissionLoading = false
      this.submissionError = null
      this.jobSubmitting = true
      this.polling = false
      this.taskError = null

      try {
        const created = await createRiskAnalysisJob({
          geometry: this.bufferResult.buffer.geometry,
          weights: this.weights.map((item) => ({ ...item })),
        })
        if (revision !== this.jobRevision) return

        this.job = created.job
        const taskPointerSaved = saveWorkspaceTaskId(created.job.task_id)
        if (taskPointerSaved) clearWorkspaceDraft()
        this.jobStatus = {
          task_id: created.job.task_id,
          status: created.job.status,
          stage: 'QUEUED',
          progress: 0,
          result_available: false,
          submitted_at: created.job.submitted_at,
        }
        this.jobSubmitting = false
        this.pollIntervalMs = created.retryAfterMs
        this.polling = true
        void this.pollRiskAnalysis(revision, this.pollIntervalMs)
      } catch (error: unknown) {
        if (revision !== this.jobRevision) return
        this.jobSubmitting = false
        this.taskError = getApiErrorMessage(error, '提交风险分析任务失败')
      }
    },
    async pollRiskAnalysis(revision: number, intervalMs: number) {
      const taskId = this.job?.task_id
      if (!taskId) return

      let consecutiveFailures = 0
      while (revision === this.jobRevision) {
        await wait(intervalMs)
        if (revision !== this.jobRevision) return

        try {
          const status = await getRiskAnalysisJob(taskId)
          if (revision !== this.jobRevision) return

          consecutiveFailures = 0
          this.jobStatus = status

          if (status.status === 'FAILED' || status.status === 'CANCELED') {
            this.polling = false
            this.taskError =
              status.error?.message || `风险分析任务${status.status === 'FAILED' ? '失败' : '已取消'}`
            return
          }

          if (status.status === 'SUCCEEDED' && status.result_available) {
            const result = await getRiskAnalysisResult(taskId)
            if (revision !== this.jobRevision) return
            this.result = result
            this.polling = false
            this.taskError = null
            void this.loadRiskAnalysisSpatialResult(taskId, revision)
            return
          }
          // Celery 极端情况下可能已 SUCCESS，但 result.json 尚未可见。
          // result_available=false 时继续轮询，而不是抢跑 result API。
        } catch (error: unknown) {
          if (revision !== this.jobRevision) return
          consecutiveFailures += 1
          if (consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES) {
            this.polling = false
            this.taskError = getApiErrorMessage(error, '查询风险分析任务状态失败')
            return
          }
        }
      }
    },
  },
})
