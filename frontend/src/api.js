/**
 * The backend contract, in one place.
 *
 * Every function here maps to exactly one route in backend/app/api/routes.py.
 * Responses are returned as plain JSON - no client-side model duplication, so a
 * field added on the server shows up in the editor without a frontend change.
 */

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

function url(path) {
  return `${API_BASE}${path}`
}

async function request(path, { method = 'GET', body, headers, raw } = {}) {
  const options = { method, headers: { ...(headers || {}) } }

  if (body instanceof FormData) {
    options.body = body // let the browser set the multipart boundary
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json'
    options.body = JSON.stringify(body)
  }

  const response = await fetch(url(path), options)

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch {
      /* the body was not JSON; the status line is the best we have */
    }
    throw new Error(detail)
  }

  if (raw) return response
  if (response.status === 204) return null
  return response.json()
}

/** Turn a storage-relative path or image_url into something <img src> can load. */
export function assetUrl(path) {
  if (!path) return null
  if (/^https?:\/\//.test(path) || path.startsWith('data:')) return path
  if (path.startsWith('/static/')) return url(path)
  return url(`/static/${path.replace(/^\/+/, '')}`)
}

export const api = {
  // --- metadata -----------------------------------------------------------
  health: () => request('/api/health'),
  styles: () => request('/api/styles'),
  pipelineNodes: () => request('/api/pipeline/nodes'),
  demoStory: () => request('/api/seed/demo'),

  // --- voice + reference images ------------------------------------------
  transcribe: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/api/transcribe', { method: 'POST', body: form })
  },

  uploadReferences: (name, description, files) => {
    const form = new FormData()
    form.append('name', name)
    form.append('description', description || '')
    Array.from(files).slice(0, 2).forEach((file) => form.append('files', file))
    return request('/api/characters/refs', { method: 'POST', body: form })
  },

  // --- projects -----------------------------------------------------------
  createProject: (payload) => request('/api/projects', { method: 'POST', body: payload }),
  listProjects: () => request('/api/projects'),
  getProject: (projectId) => request(`/api/projects/${projectId}`),
  deleteProject: (projectId) => request(`/api/projects/${projectId}`, { method: 'DELETE' }),
  generate: (projectId, payload) =>
    request(`/api/projects/${projectId}/generate`, { method: 'POST', body: payload }),

  // --- jobs ---------------------------------------------------------------
  job: (jobId, since = 0) => request(`/api/jobs/${jobId}?since=${since}`),
  jobEventsUrl: (jobId, since = 0) => url(`/api/jobs/${jobId}/events?since=${since}`),

  // --- editor -------------------------------------------------------------
  updatePanel: (projectId, panelId, payload) =>
    request(`/api/projects/${projectId}/panels/${panelId}`, { method: 'PATCH', body: payload }),
  regeneratePanel: (projectId, panelId, payload = {}) =>
    request(`/api/projects/${projectId}/panels/${panelId}/regenerate`, {
      method: 'POST',
      body: payload,
    }),
  updateLayout: (projectId, payload) =>
    request(`/api/projects/${projectId}/layout`, { method: 'PATCH', body: payload }),

  // --- export -------------------------------------------------------------
  exportProject: (projectId, formats) =>
    request(`/api/projects/${projectId}/export`, { method: 'POST', body: { formats } }),
  downloadUrl: (projectId, format) => url(`/api/projects/${projectId}/download/${format}`),
}

export const EXPORT_FORMATS = [
  { id: 'pdf', label: 'PDF', hint: 'Print-ready pages, lettering baked in', icon: '📄' },
  { id: 'png_zip', label: 'PNG zip', hint: 'Composed pages plus every panel as a PNG', icon: '🖼️' },
  { id: 'web', label: 'Web comic', hint: 'One self-contained HTML file', icon: '🌐' },
  { id: 'epub', label: 'EPUB', hint: 'For e-readers, with the source story', icon: '📚' },
]

export default api
