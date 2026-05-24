import { useEffect, useState } from 'react'

export function useAsyncData<T>(loader: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)

    loader()
      .then((result) => {
        if (active) {
          setData(result)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (active) {
          setError(err instanceof Error ? err.message : '数据加载失败')
          setLoading(false)
        }
      })

    return () => {
      active = false
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error }
}
