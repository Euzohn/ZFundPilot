import { api } from "@/api/client"

const STORAGE_KEY = "zfundpilot_color_theme"

export type ColorTheme = "international" | "china"

const DEFAULT_THEME: ColorTheme = "international"

export function getColorTheme(): ColorTheme {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    return (v as ColorTheme) || DEFAULT_THEME
  } catch {
    return DEFAULT_THEME
  }
}

export async function getColorThemeAsync(): Promise<ColorTheme> {
  try {
    const prefs = await api.getPreferences()
    const theme = prefs["color_theme"] as ColorTheme | undefined
    if (theme === "international" || theme === "china") {
      localStorage.setItem(STORAGE_KEY, theme)
      return theme
    }
  } catch {
    // server unavailable — fall through to local
  }
  return getColorTheme()
}

export async function saveColorTheme(theme: ColorTheme): Promise<void> {
  localStorage.setItem(STORAGE_KEY, theme)
  try {
    await api.savePreferences({ color_theme: theme })
  } catch {
    // server unavailable — local only
  }
}

export function applyColorTheme(theme: ColorTheme): void {
  const root = document.documentElement
  if (theme === "china") {
    root.classList.add("color-theme-cn")
  } else {
    root.classList.remove("color-theme-cn")
  }
}
