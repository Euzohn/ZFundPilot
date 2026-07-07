import { api } from "@/api/client"

const STORAGE_KEY = "zfundpilot_channels"

const DEFAULT_CHANNELS = [
  "支付宝", "理财通", "天天基金", "基金公司直销", "银行", "券商", "其它",
]

let serverChannels: string[] | null = null
let loaded = false

async function loadFromServer(): Promise<string[] | null> {
  try {
    const prefs = await api.getPreferences()
    if (prefs.channels) {
      const parsed = JSON.parse(prefs.channels)
      if (Array.isArray(parsed) && parsed.length > 0) {
        serverChannels = parsed
        return parsed
      }
    }
  } catch { /* server unavailable, fall back */ }
  return null
}

export async function getChannelsAsync(): Promise<string[]> {
  if (!loaded) {
    loaded = true
    const server = await loadFromServer()
    if (server) {
      // 同步到 localStorage 作为缓存
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(server)) } catch {}
      return server
    }
  }
  if (serverChannels) return serverChannels
  return getChannels()
}

export function getChannels(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch { /* ignore */ }
  return [...DEFAULT_CHANNELS]
}

export async function saveChannels(channels: string[]): Promise<void> {
  serverChannels = channels
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(channels)) } catch {}
  // 同步到服务端（静默降级）
  try {
    await api.savePreferences(JSON.stringify(channels))
  } catch { /* server unavailable */ }
}

export function getDefaultChannels(): string[] {
  return [...DEFAULT_CHANNELS]
}