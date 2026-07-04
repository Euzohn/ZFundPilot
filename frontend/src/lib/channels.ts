const STORAGE_KEY = "zfundpilot_channels"

const DEFAULT_CHANNELS = [
  "支付宝", "理财通", "天天基金", "基金公司直销", "银行", "券商", "其它",
]

export function getChannels(): string[] {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      if (Array.isArray(parsed) && parsed.length > 0) return parsed
    }
  } catch {
    // ignore
  }
  return [...DEFAULT_CHANNELS]
}

export function saveChannels(channels: string[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(channels))
}

export function getDefaultChannels(): string[] {
  return [...DEFAULT_CHANNELS]
}
