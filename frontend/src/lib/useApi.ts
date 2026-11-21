import { useState, useEffect, useCallback, useRef } from "react"

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 请求代际计数：deps 变化/手动 reload/卸载时递增，过期响应不再写入状态
  const generation = useRef(0)

  const reload = useCallback(async () => {
    const gen = ++generation.current
    setLoading(true)
    try {
      const result = await fetcher()
      if (gen !== generation.current) return
      setData(result)
      setError(null)
    } catch (e) {
      if (gen !== generation.current) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      if (gen === generation.current) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    reload()
    // deps 变化或卸载时使在途请求失效，避免过期响应覆盖新数据/卸载后 setState
    return () => {
      generation.current += 1
    }
  }, [reload])

  return { data, loading, error, reload, setData }
}
