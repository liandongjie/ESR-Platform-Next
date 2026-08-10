import { defineStore } from 'pinia'

import { getApiErrorMessage } from '@/api/errors'
import {
  getRiskAnalysisResult,
  getRiskAnalysisSpatialResult,
  listRiskAnalysisJobs,
} from '@/api/riskAnalysis'
import type {
  RiskAnalysisJobHistoryItem,
  RiskAnalysisResult,
  RiskAnalysisSpatialResult,
  RiskJobStatus,
} from '@/types/riskAnalysis'

const HISTORY_REFRESH_INTERVAL_MS = 2000
const MAX_CONSECUTIVE_REFRESH_FAILURES = 3

interface TaskHistoryState {
  items: RiskAnalysisJobHistoryItem[]
  total: number
  limit: number
  page: number
  loading: boolean
  refreshing: boolean
  error: string | null
  polling: boolean
  refreshRevision: number
  selectedTaskId: string | null
  detailRevision: number
  selectedResult: RiskAnalysisResult | null
  detailLoading: boolean
  detailError: string | null
  selectedSpatialResult: RiskAnalysisSpatialResult | null
  spatialLoadingTaskId: string | null
  spatialError: string | null
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

function needsRefresh(status: RiskJobStatus, resultAvailable: boolean): boolean {
  if (status === 'QUEUED' || status === 'RUNNING' || status === 'RETRYING') return true
  // Celery 可能已经 SUCCESS，但 result.json 仍处于最终发布窗口，此时继续刷新列表。
  return status === 'SUCCEEDED' && !resultAvailable
}

export const useTaskHistoryStore = defineStore('taskHistory', {
  state: (): TaskHistoryState => ({
    items: [],
    total: 0,
    limit: 20,
    page: 1,
    loading: false,
    refreshing: false,
    error: null,
    polling: false,
    refreshRevision: 0,
    selectedTaskId: null,
    detailRevision: 0,
    selectedResult: null,
    detailLoading: false,
    detailError: null,
    selectedSpatialResult: null,
    spatialLoadingTaskId: null,
    spatialError: null,
  }),
  getters: {
    offset: (state): number => (state.page - 1) * state.limit,
    hasRefreshableTasks: (state): boolean =>
      state.items.some((item) => needsRefresh(item.status, item.result_available)),
    selectedTask: (state): RiskAnalysisJobHistoryItem | null =>
      state.items.find((item) => item.task_id === state.selectedTaskId) ?? null,
    spatialLoading: (state): boolean => state.spatialLoadingTaskId !== null,
  },
  actions: {
    async loadJobs(initial = false): Promise<boolean> {
      if (initial) {
        this.loading = true
      } else {
        this.refreshing = true
      }
      this.error = null

      try {
        const history = await listRiskAnalysisJobs(this.limit, this.offset)
        this.items = history.items
        this.total = history.total
        return true
      } catch (error: unknown) {
        this.error = getApiErrorMessage(error, '查询历史任务失败')
        return false
      } finally {
        this.loading = false
        this.refreshing = false
      }
    },
    async initialize() {
      const loaded = await this.loadJobs(true)
      if (loaded && this.hasRefreshableTasks) {
        this.startAutoRefresh()
      }
    },
    async refreshNow() {
      const loaded = await this.loadJobs(false)
      if (loaded && this.hasRefreshableTasks) {
        this.startAutoRefresh()
      }
    },
    async changePage(page: number) {
      const lastPage = Math.max(1, Math.ceil(this.total / this.limit))
      const nextPage = Math.min(Math.max(1, page), lastPage)
      if (nextPage === this.page) return

      // 切页前让旧轮询版本失效，避免上一页的迟到响应覆盖新页数据。
      this.stopAutoRefresh()
      this.page = nextPage

      const loaded = await this.loadJobs(false)
      if (loaded && this.hasRefreshableTasks) {
        this.startAutoRefresh()
      }
    },
    startAutoRefresh() {
      if (this.polling || !this.hasRefreshableTasks) return

      const revision = ++this.refreshRevision
      this.polling = true
      void this.pollHistory(revision)
    },
    stopAutoRefresh() {
      // 不在 Pinia 保存 Timer 实例；版本号失效即可让旧循环安全退出。
      this.refreshRevision += 1
      this.polling = false
    },
    async pollHistory(revision: number) {
      let consecutiveFailures = 0

      while (revision === this.refreshRevision) {
        await wait(HISTORY_REFRESH_INTERVAL_MS)
        if (revision !== this.refreshRevision) return

        const loaded = await this.loadJobs(false)
        if (revision !== this.refreshRevision) return

        if (!loaded) {
          consecutiveFailures += 1
          if (consecutiveFailures >= MAX_CONSECUTIVE_REFRESH_FAILURES) {
            this.polling = false
            return
          }
          continue
        }

        consecutiveFailures = 0
        if (!this.hasRefreshableTasks) {
          this.polling = false
          return
        }
      }
    },
    async openTask(task: RiskAnalysisJobHistoryItem) {
      const resultAvailable = task.status === 'SUCCEEDED' && task.result_available
      const sameDetailSession = this.selectedTaskId === task.task_id
      if (sameDetailSession) {
        if (
          !resultAvailable ||
          this.detailLoading ||
          this.selectedResult ||
          this.spatialLoadingTaskId === task.task_id ||
          this.selectedSpatialResult
        ) {
          return
        }
      } else {
        this.detailRevision += 1
        this.selectedTaskId = task.task_id
        this.selectedResult = null
        this.detailLoading = false
        this.detailError = null
        this.selectedSpatialResult = null
        this.spatialLoadingTaskId = null
        this.spatialError = null
      }

      if (!resultAvailable) return

      const revision = this.detailRevision
      this.detailError = null
      this.detailLoading = true
      void this.loadSpatialResult(task.task_id, revision)
      try {
        const result = await getRiskAnalysisResult(task.task_id)
        if (this.selectedTaskId !== task.task_id || this.detailRevision !== revision) return
        this.selectedResult = result
      } catch (error: unknown) {
        if (this.selectedTaskId !== task.task_id || this.detailRevision !== revision) return
        this.detailError = getApiErrorMessage(error, '读取任务结果失败')
      } finally {
        if (this.selectedTaskId === task.task_id && this.detailRevision === revision) {
          this.detailLoading = false
        }
      }
    },
    async loadSpatialResult(taskId: string, revision: number) {
      if (
        this.selectedTaskId !== taskId ||
        this.detailRevision !== revision ||
        this.selectedSpatialResult?.task_id === taskId ||
        this.spatialLoadingTaskId === taskId
      ) {
        return
      }

      this.spatialLoadingTaskId = taskId
      this.spatialError = null
      try {
        const spatialResult = await getRiskAnalysisSpatialResult(taskId)
        if (this.selectedTaskId !== taskId || this.detailRevision !== revision) return
        this.selectedSpatialResult = spatialResult
      } catch (error: unknown) {
        if (this.selectedTaskId !== taskId || this.detailRevision !== revision) return
        this.spatialError = getApiErrorMessage(error, '读取空间风险结果失败')
      } finally {
        if (
          this.selectedTaskId === taskId &&
          this.detailRevision === revision &&
          this.spatialLoadingTaskId === taskId
        ) {
          this.spatialLoadingTaskId = null
        }
      }
    },
    closeDetail() {
      this.detailRevision += 1
      this.selectedTaskId = null
      this.selectedResult = null
      this.detailLoading = false
      this.detailError = null
      this.selectedSpatialResult = null
      this.spatialLoadingTaskId = null
      this.spatialError = null
    },
  },
})
