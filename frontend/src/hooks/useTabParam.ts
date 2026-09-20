import { useSearchParams } from "react-router-dom"

export function useTabParam(key: string, defaultValue: string, allowed?: string[]) {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get(key)
  const value = raw && (!allowed || allowed.includes(raw)) ? raw : defaultValue
  const setValue = (next: string) => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        if (next === defaultValue) p.delete(key)
        else p.set(key, next)
        return p
      },
      { replace: true },
    )
  }
  return [value, setValue] as const
}
