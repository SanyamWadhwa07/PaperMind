/**
 * The single HTTP client for the app.
 *
 * Every request goes through here. Previously a dozen call sites hardcoded
 * `http://localhost:5000`, which broke the moment the backend moved to :8000
 * and could never have worked in a deployment.
 *
 * - Base URL is relative by default, so requests hit the same origin. In dev
 *   Vite proxies /api to the backend; in Docker nginx does. Set VITE_API_URL
 *   only when the API genuinely lives on another origin.
 * - The bearer token is attached automatically.
 * - Errors are normalised to a single `ApiError` shape, so callers never have
 *   to dig through `err.response.data.error.message`.
 */
import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL ?? ''
const TOKEN_KEY = 'token'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export class ApiError extends Error {
  constructor(message, { status, code, details, cause } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.cause = cause
  }

  /** True when retrying could plausibly succeed. */
  get isRetryable() {
    return this.status === 0 || this.status === 429 || this.status >= 500
  }
}

/**
 * Ceiling for anything that runs the extraction + summarisation pipeline.
 *
 * Kept in step with nginx's `proxy_read_timeout` on `/api` (600s, see
 * `frontend/nginx.conf`). A client timeout shorter than the proxy's is worse
 * than useless: the request keeps running server-side and the paper is saved,
 * but the UI has already reported it as failed.
 */
const PIPELINE_TIMEOUT = 600_000

/**
 * For routes that call an LLM or a third-party API once, rather than running
 * the whole pipeline: peer review, slide generation, relation mapping, SOTA
 * lookup, cluster recomputation.
 *
 * These are the reason the client default cannot simply be raised to cover
 * everything. A 30s default is what makes a genuinely hung ordinary request
 * fail fast; the handful of endpoints that are legitimately slow name their own
 * budget here instead.
 */
const ANALYSIS_TIMEOUT = 180_000

const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  // Ordinary reads. Pipeline routes raise this per-request — see PIPELINE_TIMEOUT.
  timeout: 30_000,
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/** Pull a human-readable message out of whatever shape the server returned. */
function extractMessage(data, fallback) {
  if (!data) return fallback
  if (typeof data === 'string') return data
  if (typeof data.error === 'string') return data.error
  if (data.error?.message) return data.error.message
  if (data.detail) {
    return typeof data.detail === 'string' ? data.detail : fallback
  }
  if (data.message) return data.message
  return fallback
}

/** Session expiry is handled once, here, rather than in every page. */
function handleUnauthorized() {
  tokenStore.clear()
  // The cache holds responses fetched under the session that just ended.
  // Imported lazily because `query.js` has no dependency on this module and
  // importing it at the top would make the pair circular.
  import('./query').then(({ invalidate }) => invalidate()).catch(() => {})
  const path = window.location.pathname
  const isAuthPage = ['/login', '/signup', '/forgot-password', '/reset-password'].some(
    (p) => path.startsWith(p),
  )
  if (!isAuthPage) {
    // Preserve where the user was so login can return them to it.
    const next = encodeURIComponent(path + window.location.search)
    window.location.assign(`/login?next=${next}`)
  }
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (axios.isCancel(error)) {
      return Promise.reject(new ApiError('Request cancelled', { status: 0, code: 'cancelled' }))
    }

    const status = error.response?.status ?? 0
    const data = error.response?.data

    if (status === 401) {
      handleUnauthorized()
    }

    // A client timeout has no error.response, so it looked identical to the
    // server being unreachable — "Cannot reach the server" on a pipeline route
    // that was, in fact, reachable and still running server-side (it saves the
    // paper regardless; only the UI had given up). Now much less load-bearing
    // since /api/process/jobs* return in well under a second, but still six
    // lines for the endpoints that legitimately run long (ANALYSIS_TIMEOUT).
    const isTimeout = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    const message =
      status === 0
        ? isTimeout
          ? 'The request took too long. It may still be running on the server.'
          : 'Cannot reach the server. Check that the API is running.'
        : extractMessage(data, 'Request failed')

    return Promise.reject(
      new ApiError(message, {
        status,
        code: data?.error?.code ?? (isTimeout ? 'timeout' : undefined),
        details: data?.error?.details,
        cause: error,
      }),
    )
  },
)

/** Unwrap the axios envelope so callers work with the payload directly. */
const unwrap = (promise) => promise.then((res) => res.data)

export const http = {
  get: (url, config) => unwrap(api.get(url, config)),
  post: (url, body, config) => unwrap(api.post(url, body, config)),
  put: (url, body, config) => unwrap(api.put(url, body, config)),
  patch: (url, body, config) => unwrap(api.patch(url, body, config)),
  delete: (url, config) => unwrap(api.delete(url, config)),
}

/* ── Endpoint map ─────────────────────────────────────────────────────────
   Named functions instead of URL strings scattered through components, so a
   route change is a one-line edit here.
   ──────────────────────────────────────────────────────────────────────── */

export const auth = {
  login: (email, password) => http.post('/api/auth/login', { email, password }),
  signup: (email, password, fullName) =>
    http.post('/api/auth/signup', { email, password, full_name: fullName }),
  logout: () => http.post('/api/auth/logout'),
  me: () => http.get('/api/auth/me'),
  updateProfile: (fields) => http.put('/api/auth/me', fields),
  changePassword: (currentPassword, newPassword) =>
    http.post('/api/auth/change-password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
  forgotPassword: (email) => http.post('/api/auth/forgot-password', { email }),
  resetPassword: (token, newPassword) =>
    http.post('/api/auth/reset-password', { token, new_password: newPassword }),
}

export const papers = {
  search: (query, maxResults = 10) =>
    http.post('/api/search', { query, max_results: maxResults }),

  // Deprecated: these call the synchronous /api/process/* routes, which block
  // for the full pipeline (backend/routes/process_paper.py, kept for evals/ and
  // scripts). The app itself uses `jobs.enqueueUpload`/`enqueueArxiv` below,
  // which return immediately and let the notification tray show progress.
  //
  // Same budget as an upload. This ran on the 120s default, but the server
  // downloads the PDF from arXiv and then runs the identical pipeline, so it is
  // strictly the slower of the two. The client gave up at two minutes on work
  // that routinely takes longer — and because the server carries on regardless,
  // the paper was saved anyway. A batch would report failures for papers that
  // were, at that moment, being written to the database.
  processArxiv: (arxivId, { signal } = {}) =>
    http.post(
      '/api/process/arxiv',
      { arxiv_id: arxivId },
      { timeout: PIPELINE_TIMEOUT, signal },
    ),

  processUpload: (file, { onProgress, signal } = {}) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/api/process/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: PIPELINE_TIMEOUT, // Upload plus full pipeline.
      signal,
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    })
  },

  list: (params) => http.get('/api/summaries', { params }),
  get: (id) => http.get(`/api/summaries/${id}`),
  remove: (id) => http.delete(`/api/summaries/${id}`),
  dashboardStats: () => http.get('/api/dashboard/stats'),

  exportUrl: (id, format) => `${BASE_URL}/api/export/${id}?format=${format}`,
  exportBlob: (id, format) =>
    api.get(`/api/export/${id}`, { params: { format }, responseType: 'blob' })
      .then((res) => res.data),
}

export const jobs = {
  // Enqueue endpoints return in well under a second — the pipeline runs in the
  // background (see backend/services/job_queue.py) — so these deliberately use
  // the default 30s timeout, not PIPELINE_TIMEOUT. That's the whole point of
  // this API existing alongside the deprecated `papers.processArxiv`/
  // `processUpload` below.
  enqueueUpload: (file, { onProgress } = {}) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/api/process/jobs', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    })
  },
  enqueueArxiv: (arxivId, priority) =>
    http.post('/api/process/jobs/arxiv', { arxiv_id: arxivId, ...(priority != null ? { priority } : {}) }),
  enqueueBatch: (arxivIds) => http.post('/api/process/jobs/batch', { arxiv_ids: arxivIds }),
  // Only works for arXiv-sourced papers — see the route's docstring.
  reprocess: (summaryId) => http.post(`/api/process/jobs/reprocess/${summaryId}`),
  list: (params) => http.get('/api/process/jobs', { params }),
  get: (id) => http.get(`/api/process/jobs/${id}`),
  remove: (id) => http.delete(`/api/process/jobs/${id}`),
}

export const graph = {
  forPaper: (id) => http.get(`/api/graph/paper/${id}`),
  recommendations: (id) => http.get(`/api/graph/recommendations/${id}`),
  semanticSearch: (query, topK = 10) =>
    http.post('/api/graph/search', { query, top_k: topK }),
  timeline: () => http.get('/api/graph/timeline'),
  ancestry: (id) => http.get(`/api/graph/ancestry/${id}`),
  // Hits Semantic Scholar, which rate-limits unauthenticated callers hard
  // enough that the fallback to arXiv is the common path, not the rare one.
  discover: (query, limit = 12) =>
    http.get('/api/graph/discover', {
      params: { q: query, limit },
      timeout: ANALYSIS_TIMEOUT,
    }),
}

export const corpus = {
  citationNetwork: () => http.get('/api/corpus/citation-network'),
  authorGraph: () => http.get('/api/corpus/author-graph'),
  topicClusters: () => http.get('/api/corpus/topic-clusters'),
  contradictions: () => http.get('/api/corpus/contradiction-map'),
  // Both re-read the corpus and run a model over it.
  recomputeClusters: () =>
    http.post('/api/corpus/recompute-clusters', {}, { timeout: ANALYSIS_TIMEOUT }),
  relatePapers: () =>
    http.post('/api/corpus/relate-papers', {}, { timeout: ANALYSIS_TIMEOUT }),
}

export const collections = {
  list: () => http.get('/api/collections'),
  create: (name, description, color) =>
    http.post('/api/collections', { name, description, color }),
  remove: (id) => http.delete(`/api/collections/${id}`),
  papers: (id) => http.get(`/api/collections/${id}/papers`),
  addPaper: (id, summaryId) =>
    http.post(`/api/collections/${id}/papers`, { summary_id: summaryId }),
  removePaper: (id, summaryId) =>
    http.delete(`/api/collections/${id}/papers/${summaryId}`),
}

export const intelligence = {
  // Reads whatever analysis is already stored — fast.
  forPaper: (id) => http.get(`/api/intelligence/paper/${id}`),
  gaps: (id) => http.get(`/api/intelligence/gaps/${id}`),
  reproducibility: (id) => http.get(`/api/intelligence/reproducibility/${id}`),

  // These generate. Each is one LLM round trip over the whole paper, so they
  // need a budget well past the default for an ordinary read.
  peerReview: (id, { force = false } = {}) =>
    http.post(`/api/intelligence/peer-review/${id}`, {}, {
      timeout: ANALYSIS_TIMEOUT,
      params: force ? { force: true } : undefined,
    }),
  sota: (id) => http.get(`/api/intelligence/sota/${id}`, { timeout: ANALYSIS_TIMEOUT }),
  slides: (id) =>
    api
      .post(`/api/export/slides/${id}`, {}, {
        responseType: 'blob',
        timeout: ANALYSIS_TIMEOUT,
      })
      .then((res) => res.data),
}

export const queue = {
  list: () => http.get('/api/queue'),
  add: (summaryId, priority) => http.post('/api/queue', { summary_id: summaryId, priority }),
  update: (itemId, fields) => http.put(`/api/queue/${itemId}`, fields),
  remove: (itemId) => http.delete(`/api/queue/${itemId}`),
  autoPopulate: () => http.post('/api/queue/auto-populate'),
}

export const feedback = {
  submit: (summaryId, rating, comment) =>
    http.post(`/api/feedback/summary/${summaryId}`, { rating, comment }),
  get: (summaryId) => http.get(`/api/feedback/summary/${summaryId}`),
}

export const batch = {
  compare: (summaryIds) => http.post('/api/batch/compare', { summary_ids: summaryIds }),
}

export const profile = {
  get: () => http.get('/api/profile'),
  update: (fields) => http.put('/api/profile', fields),
  uploadAvatar: (file) => {
    const form = new FormData()
    // Field name must be `avatar` — that is what the endpoint declares.
    form.append('avatar', file)
    return http.post('/api/profile/avatar', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  removeAvatar: () => http.delete('/api/profile/avatar'),
}

export default api
