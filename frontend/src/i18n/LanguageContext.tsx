import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react"
import zh, { type default as _zhType } from "./zh"
import en from "./en"

export type Lang = "zh" | "en"
export type Translation = typeof _zhType

const translations: Record<Lang, Translation> = { zh, en }

let currentLang: Lang = "zh"

export function getCurrentLang(): Lang {
  return currentLang
}

interface LanguageContextValue {
  lang: Lang
  setLang: (lang: Lang) => void
  toggleLang: () => void
  t: Translation
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

const STORAGE_KEY = "zfundpilot_lang"

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY) as Lang | null
      return saved === "en" || saved === "zh" ? saved : "zh"
    } catch {
      return "zh"
    }
  })

  useEffect(() => {
    currentLang = lang
    try {
      localStorage.setItem(STORAGE_KEY, lang)
    } catch {}
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next: Lang) => setLangState(next), [])
  const toggleLang = useCallback(() => setLangState((prev) => (prev === "zh" ? "en" : "zh")), [])

  const value: LanguageContextValue = {
    lang,
    setLang,
    toggleLang,
    t: translations[lang],
  }

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLang(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error("useLang must be used within LanguageProvider")
  return ctx
}

export { translations }
