import axios from 'axios'

const TOKEN_KEY = 'voxdoc_token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

// Vite proxies /api to the FastAPI server on :8000 (see vite.config.js).
const api = axios.create({ baseURL: '/api' })

// Attach the bearer token to every request.
api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// A 401 means the token is missing, invalid or expired — drop it and bounce to
// the login page rather than letting the UI sit there failing silently.
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/')) {
      clearToken()
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

/** Pull a readable message out of a FastAPI error response. */
export function errorMessage(err, fallback = 'Something went wrong') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg
  return err?.message || fallback
}

// ── Auth ─────────────────────────────────────────────────────────────────────
export const register = (username, password) =>
  api.post('/auth/register', { username, password }).then((r) => r.data)

export const login = (username, password) =>
  api.post('/auth/login', { username, password }).then((r) => r.data)

export const fetchMe = () => api.get('/auth/me').then((r) => r.data)

// ── Workspaces ───────────────────────────────────────────────────────────────
export const listWorkspaces = () => api.get('/chat/workspaces').then((r) => r.data)

export const createWorkspace = (name) =>
  api.post('/chat/workspace', { name }).then((r) => r.data)

export const deleteWorkspace = (id) =>
  api.delete(`/chat/workspace/${id}`).then((r) => r.data)

// ── Chat ─────────────────────────────────────────────────────────────────────
export const fetchHistory = (workspaceId) =>
  api.get(`/chat/history/${workspaceId}`).then((r) => r.data)

export const sendMessage = (workspaceId, message) =>
  api.post('/chat/message', { workspace_id: workspaceId, message }).then((r) => r.data)

// ── Documents ────────────────────────────────────────────────────────────────
export const listDocuments = (workspaceId) =>
  api.get(`/documents/${workspaceId}`).then((r) => r.data)

export const uploadDocument = (workspaceId, file, onProgress) => {
  const form = new FormData()
  form.append('file', file)
  form.append('workspace_id', workspaceId)
  return api
    .post('/documents/upload', form, {
      onUploadProgress: (e) =>
        onProgress?.(e.total ? Math.round((e.loaded * 100) / e.total) : 0),
    })
    .then((r) => r.data)
}

export const ingestUrl = (workspaceId, url) => {
  const form = new FormData()
  form.append('url', url)
  form.append('workspace_id', workspaceId)
  return api.post('/documents/url', form).then((r) => r.data)
}

export const deleteDocument = (docId) =>
  api.delete(`/documents/${docId}`).then((r) => r.data)

// ── Voice ────────────────────────────────────────────────────────────────────
export const transcribeAudio = (blob) => {
  const form = new FormData()
  form.append('audio', blob, 'clip.webm')
  return api.post('/voice/transcribe', form).then((r) => r.data)
}

export default api
