import { api } from "@/api/client"

const STORAGE_KEY = "zfundpilot_channel_colors"

const PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#06b6d4", "#f43f5e", "#84cc16"]

const DEFAULT_CHANNEL_COLORS: Record<string, string> = {
  "支付宝": "#3b82f6",
  "理财通": "#10b981",
  "天天基金": "#f59e0b",
  "基金公司直销": "#8b5cf6",
  "银行": "#ec4899",
  "券商": "#06b6d4",
  "其它": "#f43f5e",
}

let serverColors: Record<string, string> | null = null
let loaded = false

async function loadFromServer(): Promise<Record<string, string> | null> {
  try {
    const prefs = await api.getPreferences()
    if (prefs.channel_colors) {
      const parsed = JSON.parse(prefs.channel_colors)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        serverColors = parsed
        return parsed
      }
    }
  } catch { /* server unavailable, fall back */ }
  return null
}

export async function getChannelColorsAsync(): Promise<Record<string, string>> {
  if (!loaded) {
    loaded = true
    const server = await loadFromServer()
    if (server) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(server)) } catch {}
      return server
    }
  }
  if (serverColors) return serverColors
  return getChannelColors()
}

export function getChannelColors(): Record<string, string> {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed
    }
  } catch { /* ignore */ }
  return { ...DEFAULT_CHANNEL_COLORS }
}

export async function saveChannelColors(colors: Record<string, string>): Promise<void> {
  serverColors = colors
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(colors)) } catch {}
  try {
    await api.savePreferences({ channel_colors: JSON.stringify(colors) })
  } catch { /* server unavailable */ }
}

export function getDefaultChannelColors(): Record<string, string> {
  return { ...DEFAULT_CHANNEL_COLORS }
}

export function getPalette(): string[] {
  return [...PALETTE]
}

export function getColorForChannel(channel: string, colors?: Record<string, string>, index?: number): string {
  const map = colors ?? getChannelColors()
  if (map[channel]) return map[channel]
  return PALETTE[(index ?? 0) % PALETTE.length]
}
