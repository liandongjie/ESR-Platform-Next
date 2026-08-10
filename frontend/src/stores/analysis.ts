import { defineStore } from 'pinia'

import { createAnalysisAreaBuffer } from '@/api/analysisAreas'
import { getApiErrorMessage } from '@/api/errors'
import {
  createRiskAnalysisJob,
  getRiskAnalysisJob,
  getRiskAnalysisResult,
  getRiskAnalysisSubmission,
} from '@/api/riskAnalysis'
import type {
  AnalysisAreaBufferResponse,
  Coordinate,
  PointGeometry,
} from '@/types/analysisArea'
import type {
  RiskAnalysisJobStatus,
  RiskAnalysisResult,
  RiskAnalysisSubmissionDetail,
  RiskIndicatorWeightInput,
} from '@/types/riskAnalysis'

const MAX_CONSECUTIVE_POLL_FAILURES = 3
const DEFAULT_POLL_INTERVAL_MS = 2000
const WORKSPACE_TASK_ID_STORAGE_KEY = 'esr:risk-analysis:workspace-task-id'

interface RiskAnalysisJobReference {
  task_id: string
}

interface AnalysisState {
  sourceGeometryWgs84: PointGeometry | null
  bufferDistanceMeters: number
  bufferResult: AnalysisAreaBufferResponse | null
  bufferLoading: boolean
  bufferError: string | null
  bufferRequestRevision: number
  weights: RiskIndicatorWeightInput[]
  job: RiskAnalysisJobReference | null
  jobStatus: RiskAnalysisJobStatus | null
  result: RiskAnalysisResult | null
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

function readWorkspaceTaskId(): string | null {
  try {
    const taskId = window.sessionStorage.getItem(WORKSPACE_TASK_ID_STORAGE_KEY)?.trim()
    return taskId || null
  } catch {
    return null
  }
}

function saveWorkspaceTaskId(taskId: string): void {
  try {
    window.sessionStorage.setItem(WORKSPACE_TASK_ID_STORAGE_KEY, taskId)
  } catch {
    // sessionStorage 不可用时仅失去同标签页 F5 恢复能力，不影响任务提交和轮询。
  }
}

function clearWorkspaceTaskId(): void {
  try {
    window.sessionStorage.removeItem(WORKSPACE_TASK_ID_STORAGE_KEY)
  } catch {
    // 与写入失败相同，存储不可用不应阻断正常分析流程。
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
    weights: [
      { code: 'PM25', weight_percent: 30 },
      { code: 'AQI', weight_percent: 40 },
      { code: 'NDVI', weight_percent: 30 },
    ],
    job: null,
    jobStatus: null,
    result: null,
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
  },
  actions: {
    resetRiskAnalysis() {
      // 不把 Timer 放进 Pinia；递增版本号即可让旧轮询在下一次唤醒时自行退出。
      this.jobRevision += 1
      clearWorkspaceTaskId()
      this.job = null
      this.jobStatus = null
      this.result = null
      this.submissionContext = null
      this.submissionLoading = false
      this.submissionError = null
      this.jobSubmitting = false
      this.polling = false
      this.taskError = null
      this.pollIntervalMs = DEFAULT_POLL_INTERVAL_MS
    },
    setSourcePoint(coordinates: Coordinate) {
      if (this.analysisLocked) return
      // 切换研究点会使旧 Buffer 立即失效，同时递增版本号让尚未返回的旧请求无法覆盖新选择。
      this.bufferRequestRevision += 1
      this.sourceGeometryWgs84 = {
        type: 'Point',
        coordinates: [...coordinates],
      }
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
    },
    setBufferDistance(distanceMeters: number) {
      if (this.analysisLocked || this.bufferDistanceMeters === distanceMeters) return
      this.bufferRequestRevision += 1
      this.bufferDistanceMeters = distanceMeters
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
    },
    setWeight(code: string, weightPercent: number) {
      if (this.analysisLocked) return
      const item = this.weights.find((weight) => weight.code === code)
      if (!item || item.weight_percent === weightPercent) return
      item.weight_percent = weightPercent
      this.resetRiskAnalysis()
    },
    clearSelection() {
      if (this.analysisLocked) return
      this.bufferRequestRevision += 1
      this.sourceGeometryWgs84 = null
      this.bufferResult = null
      this.bufferLoading = false
      this.bufferError = null
      this.resetRiskAnalysis()
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
      if (!taskId) return

      const revision = ++this.jobRevision
      this.job = { task_id: taskId }
      this.jobStatus = null
      this.result = null
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
      const geometry: PointGeometry = {
        type: 'Point',
        coordinates: [...this.sourceGeometryWgs84.coordinates],
      }
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
        saveWorkspaceTaskId(created.job.task_id)
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
