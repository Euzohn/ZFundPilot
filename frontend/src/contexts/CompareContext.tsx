import { useState, useEffect, useCallback, createContext, useContext, type ReactNode } from "react"

const STORAGE_KEY = "zfund_compare_codes"
const MAX_CODES = 20

interface CompareContextValue {
  codes: string[]
  addCode: (code: string) => void
  addCodes: (codes: string[]) => void
  removeCode: (code: string) => void
  clear: () => void
  hasCode: (code: string) => boolean
  count: number
}

const CompareContext = createContext<CompareContextValue | null>(null)

function loadCodes(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((c: unknown) => typeof c === "string" && /^\d{6}$/.test(c)) : []
  } catch {
    return []
  }
}

function saveCodes(codes: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(codes))
  } catch { /* ignore */ }
}

export function CompareProvider({ children }: { children: ReactNode }) {
  const [codes, setCodes] = useState<string[]>(loadCodes)

  useEffect(() => {
    saveCodes(codes)
  }, [codes])

  const addCode = useCallback((code: string) => {
    const c = code.trim()
    if (!c || !/^\d{6}$/.test(c)) return
    setCodes((prev) => {
      if (prev.includes(c)) return prev
      if (prev.length >= MAX_CODES) return prev
      return [...prev, c]
    })
  }, [])

  const addCodes = useCallback((newCodes: string[]) => {
    const valid = newCodes.map((s) => s.trim()).filter((c) => /^\d{6}$/.test(c))
    if (valid.length === 0) return
    setCodes((prev) => {
      const set = new Set(prev)
      for (const c of valid) {
        if (set.size >= MAX_CODES) break
        set.add(c)
      }
      return Array.from(set)
    })
  }, [])

  const removeCode = useCallback((code: string) => {
    setCodes((prev) => prev.filter((c) => c !== code))
  }, [])

  const clear = useCallback(() => {
    setCodes([])
  }, [])

  const hasCode = useCallback((code: string) => {
    return codes.includes(code)
  }, [codes])

  return (
    <CompareContext.Provider value={{ codes, addCode, addCodes, removeCode, clear, hasCode, count: codes.length }}>
      {children}
    </CompareContext.Provider>
  )
}

export function useCompare() {
  const ctx = useContext(CompareContext)
  if (!ctx) throw new Error("useCompare must be used within CompareProvider")
  return ctx
}