import { useEffect, useState } from 'react'

export default function useAds(request, query) {
  const [result, setResult] = useState({ query, data: null, loading: true, error: '' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let timer
    setResult({ query, data: null, loading: true, error: '' })
    async function refresh() {
      try {
        const data = await request(`/api/ads/page?${query}`, { signal: controller.signal })
        if (!controller.signal.aborted) setResult({ query, data, loading: false, error: '' })
      } catch (err) {
        if (!controller.signal.aborted) setResult((previous) => ({ ...previous, loading: false, error: err.message }))
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 10000)
      }
    }
    refresh()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [request, query, attempt])

  // Hide the previous query's rows immediately, before the effect runs.
  const current = result.query === query ? result : { data: null, loading: true, error: '' }
  return { ...current, retry: () => setAttempt((n) => n + 1) }
}
