// В production фронт раздаётся тем же сервером, что и API (relative /api).
// Для dev через Vite — proxy в vite.config.js. Переопределить можно VITE_API_URL.
const API_BASE = (import.meta.env && import.meta.env.VITE_API_URL) || ''

export async function api(path, { method = 'GET', body, token } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Ошибка ${res.status}`)
  return data
}

export const API_BASE_URL = API_BASE
