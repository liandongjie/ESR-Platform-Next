import http from 'k6/http'
import { check, fail, sleep } from 'k6'
import { SharedArray } from 'k6/data'
import { Counter, Rate, Trend } from 'k6/metrics'

const SCENARIO = (__ENV.SCENARIO || 'A').toUpperCase()
const VUS = Number.parseInt(__ENV.VUS || '50', 10)
const BASE_URL = (__ENV.BASE_URL || '').replace(/\/$/, '')
const PAGE_LIMIT = Number.parseInt(__ENV.PAGE_LIMIT || '20', 10)
const PAGE_OFFSET = Number.parseInt(__ENV.PAGE_OFFSET || '0', 10)
const POLL_INTERVAL_SECONDS = Number.parseFloat(__ENV.POLL_INTERVAL_SECONDS || '2')
const POLL_TIMEOUT_SECONDS = Number.parseFloat(__ENV.POLL_TIMEOUT_SECONDS || '180')
const ARTIFACT_KIND = (__ENV.ARTIFACT_KIND || '').trim()
const RUN_ID = (__ENV.RUN_ID || `${Date.now()}`).replace(/[^A-Za-z0-9_.-]/g, '-')

const scenarioData = JSON.parse(
  open(__ENV.SCENARIO_DATA_FILE || './scenario.example.json'),
)

const users = new SharedArray('load-test-users', () => {
  if (__ENV.ESR_USERNAME && __ENV.ESR_PASSWORD) {
    return [{ username: __ENV.ESR_USERNAME, password: __ENV.ESR_PASSWORD }]
  }
  return JSON.parse(open(__ENV.USERS_FILE || './users.example.json'))
})

const enqueueRequestDuration = new Trend('esr_enqueue_request_duration_ms', true)
const queueWaitDuration = new Trend('esr_server_queue_wait_ms', true)
const executionDuration = new Trend('esr_server_execution_ms', true)
const missingServerTiming = new Counter('esr_missing_server_timing_fields')
const terminalJobs = new Counter('esr_terminal_jobs')
const enqueuedJobsTerminal = new Rate('esr_enqueued_jobs_terminal')
const artifactCandidateAvailable = new Rate('esr_artifact_candidate_available')

const thresholds = {
  http_req_failed: ['rate<0.01'],
  checks: ['rate>0.99'],
  'http_req_duration{endpoint:status}': ['p(95)<500'],
}
if (SCENARIO === 'A') {
  thresholds['http_req_duration{endpoint:list}'] = ['p(95)<500']
  if (ARTIFACT_KIND) thresholds.esr_artifact_candidate_available = ['rate==1']
}
if (SCENARIO === 'B') {
  thresholds.esr_enqueued_jobs_terminal = ['rate==1']
}

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['min', 'p(50)', 'p(95)', 'p(99)', 'max'],
  thresholds,
  scenarios:
    SCENARIO === 'A'
      ? {
          api_read_path: {
            executor: 'constant-vus',
            exec: 'scenarioA',
            vus: VUS,
            duration: __ENV.DURATION || '1m',
            gracefulStop: '10s',
          },
        }
      : SCENARIO === 'B'
        ? {
            submit_and_poll: {
              executor: 'per-vu-iterations',
              exec: 'scenarioB',
              vus: VUS,
              iterations: 1,
              maxDuration: __ENV.MAX_DURATION || '5m',
            },
          }
        : {
            idempotency_probe: {
              executor: 'shared-iterations',
              exec: 'idempotencyProbe',
              vus: 1,
              iterations: 1,
              maxDuration: __ENV.MAX_DURATION || '5m',
            },
          },
}

function api(path) {
  return `${BASE_URL}/api/v1${path}`
}

function requestParams(accessToken, endpoint, responseType = 'text', headers = {}) {
  return {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...headers,
    },
    tags: { endpoint },
    responseType,
  }
}

function responseJson(response, label) {
  try {
    return response.json()
  } catch {
    check(null, { [`${label} returns JSON`]: () => false })
    return null
  }
}

function login(user) {
  const response = http.post(
    api('/auth/login'),
    JSON.stringify(user),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { endpoint: 'login' },
      responseType: 'text',
    },
  )
  if (!check(response, { 'login status is 200': (item) => item.status === 200 })) return null

  const payload = responseJson(response, 'login')
  const accessToken = payload?.access_token
  check(accessToken, { 'login returns access token': (value) => typeof value === 'string' })
  return typeof accessToken === 'string' ? accessToken : null
}

function selectedUser() {
  return users[(__VU - 1) % users.length]
}

function submissionPayload() {
  const geometry = __ENV.GEOMETRY_JSON
    ? JSON.parse(__ENV.GEOMETRY_JSON)
    : scenarioData.geometry
  if (__ENV.INDICATOR_CODES) {
    const codes = __ENV.INDICATOR_CODES.split(',').map((item) => item.trim()).filter(Boolean)
    const percentages = [34, 33, 33]
    return {
      geometry,
      weights: codes.map((code, index) => ({ code, weight_percent: percentages[index] })),
    }
  }
  return { geometry, weights: scenarioData.weights }
}

function validTimestamp(value) {
  const milliseconds = Date.parse(value)
  return Number.isFinite(milliseconds) ? milliseconds : null
}

function recordServerTimings(status) {
  const queuedAt = validTimestamp(status.queued_at || status.submitted_at)
  const startedAt = validTimestamp(status.started_at)
  const completedAt = validTimestamp(status.completed_at)

  if (queuedAt !== null && startedAt !== null) {
    queueWaitDuration.add(startedAt - queuedAt)
  } else {
    missingServerTiming.add(1, { timing: 'queue_wait' })
  }
  if (startedAt !== null && completedAt !== null) {
    executionDuration.add(completedAt - startedAt)
  } else {
    missingServerTiming.add(1, { timing: 'execution' })
  }
}

export function setup() {
  if (!['A', 'B', 'IDEMPOTENCY_PROBE'].includes(SCENARIO)) {
    fail('SCENARIO must be A, B, or IDEMPOTENCY_PROBE')
  }
  if (!BASE_URL) fail('BASE_URL is required and must be the origin without /api/v1')
  if (!Number.isInteger(VUS) || VUS < 1) fail('VUS must be a positive integer')
  if (users.length === 0) fail('credential source must contain users')
  if (
    users.some(
      (user) =>
        typeof user?.username !== 'string' ||
        !user.username ||
        typeof user?.password !== 'string' ||
        !user.password ||
        user.password.startsWith('REPLACE_'),
    )
  ) {
    fail('every load-test user needs a non-empty username and password')
  }
  if (users.length < VUS && __ENV.ALLOW_USER_REUSE !== 'true') {
    fail(`credential source has ${users.length} users for ${VUS} VUs; set ALLOW_USER_REUSE=true only for dry-runs`)
  }
  if (SCENARIO === 'B' || SCENARIO === 'IDEMPOTENCY_PROBE') {
    const payload = submissionPayload()
    if (!payload.geometry || !Array.isArray(payload.weights) || payload.weights.length !== 3) {
      fail('Scenario B requires one geometry and exactly three indicator weights')
    }
    const total = payload.weights.reduce((sum, item) => sum + item.weight_percent, 0)
    if (Math.abs(total - 100) > 1e-6) fail('Scenario B indicator weights must total 100')
  }
  if (ARTIFACT_KIND && !['manifest', 'preview', 'raster'].includes(ARTIFACT_KIND)) {
    fail('ARTIFACT_KIND must be empty, manifest, preview, or raster')
  }
}

export function scenarioA() {
  const accessToken = login(selectedUser())
  if (!accessToken) return

  const listResponse = http.get(
    api(`/risk-analysis/jobs?limit=${PAGE_LIMIT}&offset=${PAGE_OFFSET}`),
    requestParams(accessToken, 'list'),
  )
  if (!check(listResponse, { 'list status is 200': (item) => item.status === 200 })) return

  const list = responseJson(listResponse, 'list')
  const items = Array.isArray(list?.items) ? list.items : []
  const explicitTaskId = (__ENV.TASK_ID || '').trim()
  if (items.length === 0 && !explicitTaskId) {
    sleep(Number.parseFloat(__ENV.ITERATION_SLEEP_SECONDS || '1'))
    return
  }

  const job = explicitTaskId
    ? { task_id: explicitTaskId }
    : ARTIFACT_KIND
      ? items.find((item) => item?.status === 'SUCCEEDED' && item?.result_available === true)
      : items[(__VU - 1) % items.length]
  const taskId = job?.task_id
  if (typeof taskId !== 'string') {
    if (ARTIFACT_KIND) artifactCandidateAvailable.add(false)
    sleep(Number.parseFloat(__ENV.ITERATION_SLEEP_SECONDS || '1'))
    return
  }
  const statusResponse = http.get(
    api(`/risk-analysis/jobs/${encodeURIComponent(taskId)}`),
    requestParams(accessToken, 'status'),
  )
  const statusOk = check(statusResponse, { 'status response is 200': (item) => item.status === 200 })
  if (ARTIFACT_KIND) {
    if (!statusOk) {
      artifactCandidateAvailable.add(false)
      sleep(Number.parseFloat(__ENV.ITERATION_SLEEP_SECONDS || '1'))
      return
    }
    const status = responseJson(statusResponse, 'status')
    const downloadable = status?.status === 'SUCCEEDED' && status?.result_available === true
    artifactCandidateAvailable.add(downloadable)
    if (downloadable) {
      const artifactResponse = http.get(
        api(`/risk-analysis/jobs/${encodeURIComponent(taskId)}/result/artifacts/${ARTIFACT_KIND}`),
        requestParams(accessToken, 'artifact', 'none'),
      )
      check(artifactResponse, { 'artifact status is 200': (item) => item.status === 200 })
    }
  }
  sleep(Number.parseFloat(__ENV.ITERATION_SLEEP_SECONDS || '1'))
}

export function scenarioB() {
  const user = selectedUser()
  const accessToken = login(user)
  if (!accessToken) return

  const response = http.post(
    api('/risk-analysis/jobs'),
    JSON.stringify(submissionPayload()),
    requestParams(accessToken, 'enqueue', 'text', {
      'Content-Type': 'application/json',
      'Idempotency-Key': `k6-${RUN_ID}-${user.username}`,
    }),
  )
  enqueueRequestDuration.add(response.timings.duration)
  if (!check(response, { 'enqueue status is 200 or 202': (item) => [200, 202].includes(item.status) })) {
    return
  }

  const created = responseJson(response, 'enqueue')
  const taskId = created?.task_id
  if (!check(taskId, { 'enqueue returns task id': (value) => typeof value === 'string' })) {
    enqueuedJobsTerminal.add(false)
    return
  }

  const terminalStatuses = new Set(['SUCCEEDED', 'FAILED', 'CANCELED', 'EXPIRED'])
  const deadline = Date.now() + POLL_TIMEOUT_SECONDS * 1000
  while (Date.now() < deadline) {
    sleep(POLL_INTERVAL_SECONDS)
    const statusResponse = http.get(
      api(`/risk-analysis/jobs/${encodeURIComponent(taskId)}`),
      requestParams(accessToken, 'status'),
    )
    if (!check(statusResponse, { 'poll status is 200': (item) => item.status === 200 })) continue

    const status = responseJson(statusResponse, 'status')
    if (terminalStatuses.has(status?.status)) {
      terminalJobs.add(1, { status: status.status })
      enqueuedJobsTerminal.add(true)
      recordServerTimings(status)
      check(status, { 'job reaches a terminal status': () => true })
      return
    }
  }
  enqueuedJobsTerminal.add(false)
  check(null, { 'job reaches a terminal status': () => false })
}

export function idempotencyProbe() {
  const user = selectedUser()
  const accessToken = login(user)
  if (!accessToken) return

  const idempotencyKey = __ENV.IDEMPOTENCY_KEY || `k6-probe-${RUN_ID}-${user.username}`
  const params = requestParams(accessToken, 'idempotency_probe', 'text', {
    'Content-Type': 'application/json',
    'Idempotency-Key': idempotencyKey,
  })
  const body = JSON.stringify(submissionPayload())
  const first = http.post(api('/risk-analysis/jobs'), body, params)
  const second = http.post(api('/risk-analysis/jobs'), body, params)
  const accepted = check(null, {
    'idempotency probe submissions are accepted': () =>
      [200, 202].includes(first.status) && [200, 202].includes(second.status),
  })
  if (!accepted) return

  const firstTaskId = responseJson(first, 'first idempotency probe')?.task_id
  const secondTaskId = responseJson(second, 'second idempotency probe')?.task_id
  check(null, {
    'same idempotency key returns the same task id': () =>
      typeof firstTaskId === 'string' && firstTaskId === secondTaskId,
  })
}
