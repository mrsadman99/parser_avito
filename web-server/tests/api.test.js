import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError } from '../src/api.js'

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test('validation details become readable field messages', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [
    { loc: ['body', 'url'], msg: 'Value error, Укажите ссылку Avito' },
    { loc: ['body', 'min_price'], msg: 'Цена должна быть положительной' },
  ] }), { status: 422 })
  await assert.rejects(api('/api/links'), (err) => {
    assert.equal(err.status, 422)
    assert.equal(err.message, 'Ссылка: Укажите ссылку Avito; Минимальная цена: Цена должна быть положительной')
    return true
  })
})

test('401 retains status for session invalidation', async () => {
  globalThis.fetch = async () => new Response('{"detail":"Требуется авторизация"}', { status: 401 })
  await assert.rejects(api('/api/me'), (err) => err instanceof ApiError && err.status === 401)
})

test('non-JSON server error retains HTTP status', async () => {
  globalThis.fetch = async () => new Response('<html>Bad gateway</html>', { status: 502 })
  await assert.rejects(api('/api/me'), (err) => err.status === 502 && !err.message.includes('html'))
})

test('requests carry credentials and JSON body', async () => {
  globalThis.fetch = async (path, options) => {
    assert.equal(path, '/api/links')
    assert.equal(options.headers.Authorization, 'Bearer test-token')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), { url: 'https://avito.ru' })
    return new Response('{"id":1}', { status: 201 })
  }
  assert.deepEqual(await api('/api/links', { token: 'test-token', method: 'POST', body: { url: 'https://avito.ru' } }), { id: 1 })
})

function pendingFetch(_path, { signal }) {
  return new Promise((resolve, reject) => {
    const abort = () => reject(new DOMException('Aborted', 'AbortError'))
    if (signal.aborted) abort()
    else signal.addEventListener('abort', abort, { once: true })
  })
}

test('caller cancellation is preserved as AbortError', async () => {
  globalThis.fetch = pendingFetch
  const controller = new AbortController()
  const result = api('/api/ads/page', { signal: controller.signal })
  controller.abort()
  await assert.rejects(result, (err) => err.name === 'AbortError')
})

test('timeout returns a retryable message', async () => {
  globalThis.fetch = pendingFetch
  await assert.rejects(api('/api/ads/page', { timeout: 5 }), (err) => err instanceof ApiError && err.message.includes('вовремя'))
})

test('network failure has a readable message', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(api('/api/links'), (err) => err.status === 0 && err.message.includes('соединение'))
})
