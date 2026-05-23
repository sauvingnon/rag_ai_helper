const BASE = '/admin'

export const filesApi = {
  list: () => fetch(`${BASE}/files`).then(r => r.json()),

  upload: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(`${BASE}/files`, { method: 'POST', body: fd }).then(r => {
      if (!r.ok) return r.json().then(e => Promise.reject(e.detail))
      return r.json()
    })
  },

  download: (fileId, filename) =>
    fetch(`${BASE}/files/${fileId}/download`)
      .then(r => r.blob())
      .then(blob => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = filename
        a.click()
        URL.revokeObjectURL(a.href)
      }),

  delete: (fileId) =>
    fetch(`${BASE}/files/${fileId}`, { method: 'DELETE' }).then(r => {
      if (!r.ok && r.status !== 204) return r.json().then(e => Promise.reject(e.detail))
    }),

  index: (fileId) =>
    fetch(`${BASE}/files/${fileId}/index`, { method: 'POST' }).then(r => {
      if (!r.ok) return r.json().then(e => Promise.reject(e.detail))
      return r.json()
    }),
}

export const chunksApi = {
  list: (params = {}) => {
    const q = new URLSearchParams()
    if (params.source_file_id) q.set('source_file_id', params.source_file_id)
    if (params.offset !== undefined) q.set('offset', params.offset)
    if (params.limit !== undefined) q.set('limit', params.limit)
    return fetch(`${BASE}/chunks?${q}`).then(r => r.json())
  },

  update: (id, body) =>
    fetch(`${BASE}/chunks/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => {
      if (!r.ok) return r.json().then(e => Promise.reject(e.detail))
      return r.json()
    }),

  delete: (id) =>
    fetch(`${BASE}/chunks/${encodeURIComponent(id)}`, { method: 'DELETE' }).then(r => {
      if (!r.ok && r.status !== 204) return r.json().then(e => Promise.reject(e.detail))
    }),
}

export const tasksApi = {
  list: () => fetch(`${BASE}/tasks`).then(r => r.json()),
}

export const aiApi = {
  reloadDb: () =>
    fetch(`${BASE}/ai/reload-db`, { method: 'POST' }).then(r => {
      if (!r.ok) return r.json().then(e => Promise.reject(e.error || 'Ошибка'))
      return r.json()
    }),
}

export const systemApi = {
  sessionsStats: () => fetch(`${BASE}/sessions/stats`).then(r => r.json()),

  clearSessions: () =>
    fetch(`${BASE}/sessions/all`, { method: 'DELETE' }).then(r => {
      if (!r.ok) return r.json().then(e => Promise.reject(e.detail || 'Ошибка'))
      return r.json()
    }),
}
