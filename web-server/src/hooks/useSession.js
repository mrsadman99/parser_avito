import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'

export default function useSession() {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '')
  const [actor, setActor] = useState(null)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(Boolean(token))
  const [loggingOut, setLoggingOut] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const tokenRef = useRef(token)
  const logoutLock = useRef(false)

  const clearSession = useCallback(() => {
    tokenRef.current = ''
    localStorage.removeItem('token')
    localStorage.removeItem('is_admin')
    setToken('')
    setActor(null)
    setChecking(false)
  }, [])

  const request = useCallback(async (path, options = {}) => {
    try {
      return await api(path, { ...options, token })
    } catch (err) {
      if (err.status === 401 && tokenRef.current === token && !options.signal?.aborted) {
        clearSession()
        setError('Сессия завершена. Войдите снова.')
      }
      throw err
    }
  }, [token, clearSession])

  useEffect(() => {
    if (!token) return
    const controller = new AbortController()
    setChecking(true)
    setError('')
    request('/api/me', { signal: controller.signal })
      .then((user) => { if (!controller.signal.aborted) setActor(user) })
      .catch((err) => { if (!controller.signal.aborted) setError(err.status === 401 ? 'Сессия завершена. Войдите снова.' : err.message) })
      .finally(() => { if (!controller.signal.aborted) setChecking(false) })
    return () => controller.abort()
  }, [token, attempt, request])

  async function authenticate(mode, credentials) {
    const result = await api(`/api/${mode}`, { method: 'POST', body: credentials })
    localStorage.setItem('token', result.token)
    localStorage.removeItem('is_admin')
    tokenRef.current = result.token
    setError('')
    setChecking(true)
    setToken(result.token)
  }

  async function logout() {
    if (logoutLock.current) return
    logoutLock.current = true
    setLoggingOut(true)
    setError('')
    try {
      await request('/api/logout', { method: 'POST' })
      clearSession()
    } catch (err) {
      setError(err.message)
    } finally {
      logoutLock.current = false
      setLoggingOut(false)
    }
  }

  return { token, actor, checking, error, loggingOut, request, authenticate, logout,
    retry: () => setAttempt((value) => value + 1) }
}
