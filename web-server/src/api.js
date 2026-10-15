const API_BASE = import.meta.env?.VITE_API_URL || ''

export class ApiError extends Error {
  constructor(message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const FIELD_LABELS = {
  url: 'Ссылка', min_price: 'Минимальная цена', max_price: 'Максимальная цена',
  start_date: 'Дата', username: 'Логин', password: 'Пароль',
  white_list: 'Ключевые слова', black_list: 'Стоп-слова',
}

function errorMessage(detail, status) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((issue) => {
      const field = issue.loc?.find((part) => FIELD_LABELS[part])
      const message = typeof issue.msg === 'string'
        ? issue.msg.replace(/^Value error, /, '') : 'Некорректное значение'
      return field ? `${FIELD_LABELS[field]}: ${message}` : message
    }).join('; ')
  }
  return `Ошибка сервера (${status})`
}

export async function api(path, { method = 'GET', body, token, signal, timeout = 20000 } = {}) {
  const controller = new AbortController()
  const cancel = () => controller.abort()
  let timedOut = false
  if (signal?.aborted) cancel()
  signal?.addEventListener('abort', cancel, { once: true })
  const timer = setTimeout(() => { timedOut = true; cancel() }, timeout)
  try {
    const headers = { Accept: 'application/json' }
    if (body !== undefined) headers['Content-Type'] = 'application/json'
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch(`${API_BASE}${path}`, {
      method, headers, body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    if (res.status === 204) return null
    const data = await res.json().catch(() => null)
    if (!res.ok) throw new ApiError(errorMessage(data?.detail, res.status), res.status)
    if (data === null) throw new ApiError('Сервер вернул некорректный ответ', res.status)
    return data
  } catch (error) {
    if (signal?.aborted) throw new DOMException('Запрос отменён', 'AbortError')
    if (timedOut) throw new ApiError('Сервер не ответил вовремя. Повторите запрос.')
    if (error instanceof ApiError) throw error
    throw new ApiError('Не удалось связаться с сервером. Проверьте соединение.')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', cancel)
  }
}

export const API_BASE_URL = API_BASE
