import { useEffect, useRef, useState } from 'react'

export default function useLinks(request) {
  const [links, setLinks] = useState([])
  const [loading, setLoading] = useState(true)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState('')
  const [attempt, setAttempt] = useState(0)
  const lock = useRef(false)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    request('/api/links', { signal: controller.signal })
      .then((rows) => { if (!controller.signal.aborted) { setLinks(rows); setLoaded(true) } })
      .catch((err) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [request, attempt])

  async function mutate(key, action) {
    if (lock.current) return false
    lock.current = true
    setPending(key)
    setError('')
    try {
      await action()
      return true
    } catch (err) {
      setError(err.message)
      return false
    } finally {
      lock.current = false
      setPending('')
    }
  }

  function save(id, body) {
    return mutate('save', async () => {
      const link = await request(id == null ? '/api/links' : `/api/links/${id}`, {
        method: id == null ? 'POST' : 'PUT', body,
      })
      setLinks((rows) => id == null ? [...rows, link] : rows.map((row) => row.id === id ? link : row))
    })
  }

  function remove(id) {
    return mutate(`delete:${id}`, async () => {
      await request(`/api/links/${id}`, { method: 'DELETE' })
      setLinks((rows) => rows.filter((row) => row.id !== id))
    })
  }

  return { links, loading, loaded, error, pending, save, remove, retry: () => setAttempt((n) => n + 1) }
}
