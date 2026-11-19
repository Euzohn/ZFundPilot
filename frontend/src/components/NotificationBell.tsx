import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  Bell,
  CalendarClock,
  CheckCheck,
  Cog,
  Gift,
  HeartPulse,
  RefreshCw,
  TrendingUp,
  X,
} from "lucide-react"
import { api } from "@/api/client"
import type { NotificationItem, NotificationSourceType } from "@/api/types"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { useLang } from "@/i18n/LanguageContext"
import { formatRelativeTimeTz } from "@/lib/format"
import {
  notificationTarget,
  notificationTitle,
  sourceLabel,
} from "@/lib/notificationLabels"
import { cn } from "@/lib/utils"

/** 关键操作（记为分红/忽略提醒/提案审批等）后派发，徽章即时刷新。 */
export const NOTIFICATIONS_CHANGED_EVENT = "zfund:notifications-changed"

export function dispatchNotificationsChanged(): void {
  window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED_EVENT))
}

const SOURCE_ICONS: Record<NotificationSourceType, typeof Gift> = {
  dividend: Gift,
  tpsl: TrendingUp,
  auto_invest: CalendarClock,
  job: Cog,
  nav_update: RefreshCw,
  data_health: HeartPulse,
}

const SOURCE_ORDER: NotificationSourceType[] = [
  "dividend", "tpsl", "auto_invest", "job", "nav_update", "data_health",
]

export default function NotificationBell({
  className,
  popoverSide = "bottom",
  popoverAlign = "end",
}: {
  className?: string
  popoverSide?: "top" | "right" | "bottom" | "left"
  popoverAlign?: "start" | "center" | "end"
}) {
  const { t } = useLang()
  const navigate = useNavigate()
  const [count, setCount] = useState(0)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<NotificationItem[]>([])
  const [invalidIds, setInvalidIds] = useState<Set<number>>(new Set())
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const refreshCount = useCallback(() => {
    api.getNotificationCount().then((r) => setCount(r.count)).catch(() => {})
  }, [])

  useEffect(() => {
    refreshCount()
    const timer = setInterval(refreshCount, 60000)
    const onChange = () => refreshCount()
    window.addEventListener(NOTIFICATIONS_CHANGED_EVENT, onChange)
    window.addEventListener("zfund:proposals-changed", onChange)
    return () => {
      clearInterval(timer)
      window.removeEventListener(NOTIFICATIONS_CHANGED_EVENT, onChange)
      window.removeEventListener("zfund:proposals-changed", onChange)
    }
  }, [refreshCount])

  const loadItems = useCallback(async () => {
    setLoading(true)
    setFailed(false)
    try {
      const resp = await api.getNotifications({ limit: 100 })
      const visible = resp.items.filter((n) => n.status !== "dismissed")
      setItems(visible)
      // 悬空引用校验：分红/止盈止损源可能已被幽灵清理或用户删除
      const alertItems = visible.filter(
        (n) => n.source_type === "dividend" || n.source_type === "tpsl")
      if (alertItems.length > 0) {
        const [dividends, tpSl] = await Promise.all([
          api.getDividendAlerts().catch(() => null),
          api.getTpSlAlerts().catch(() => null),
        ])
        // 只对成功拉取的来源做失效判定，请求失败不误判「已失效」
        const live = new Set<string>()
        const checked = new Set<string>()
        if (dividends) {
          dividends.forEach((a) => live.add(`dividend:${a.id}`))
          checked.add("dividend")
        }
        if (tpSl) {
          tpSl.forEach((a) => live.add(`tpsl:${a.id}`))
          checked.add("tpsl")
        }
        setInvalidIds(new Set(
          alertItems
            .filter((n) => checked.has(n.source_type)
              && !live.has(`${n.source_type}:${n.source_id}`))
            .map((n) => n.id)))
      } else {
        setInvalidIds(new Set())
      }
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleOpenChange = (next: boolean) => {
    setOpen(next)
    if (next) void loadItems()
  }

  const handleItemClick = (n: NotificationItem) => {
    if (invalidIds.has(n.id)) return
    if (n.status === "unread") {
      api.markNotificationsRead([n.id]).catch(() => {})
      setItems((prev) => prev.map((x) => x.id === n.id ? { ...x, status: "read" } : x))
      setCount((c) => Math.max(0, c - 1))
      dispatchNotificationsChanged()
    }
    setOpen(false)
    navigate(notificationTarget(n))
  }

  const handleDismiss = (n: NotificationItem) => {
    api.dismissNotifications([n.id]).catch(() => {})
    setItems((prev) => prev.filter((x) => x.id !== n.id))
    if (n.status === "unread") setCount((c) => Math.max(0, c - 1))
    dispatchNotificationsChanged()
  }

  const handleMarkAllRead = () => {
    api.markNotificationsRead().catch(() => {})
    setItems((prev) => prev.map((x) => ({ ...x, status: "read" as const })))
    setCount(0)
    dispatchNotificationsChanged()
  }

  const groups = SOURCE_ORDER
    .map((source) => ({
      source,
      items: items.filter((n) => n.source_type === source),
    }))
    .filter((g) => g.items.length > 0)

  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          className={cn(
            "relative flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            className,
          )}
          aria-label={t.notifications.open}
        >
          <Bell className="h-[18px] w-[18px]" />
          {count > 0 && (
            <span className="absolute -top-0.5 -right-0.5 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full bg-destructive text-destructive-foreground text-[9px] font-semibold ring-1 ring-card">
              {count > 99 ? "99+" : count}
            </span>
          )}
        </button>
      </PopoverTrigger>
      <PopoverContent
        side={popoverSide}
        align={popoverAlign}
        sideOffset={8}
        className="w-80 sm:w-96 p-0"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">{t.notifications.title}</h2>
          {count > 0 && (
            <button
              onClick={handleMarkAllRead}
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <CheckCheck className="h-3.5 w-3.5" />
              {t.notifications.markAllRead}
            </button>
          )}
        </div>
        <div className="max-h-[60vh] overflow-y-auto">
          {loading && (
            <p className="px-4 py-6 text-center text-xs text-muted-foreground">…</p>
          )}
          {!loading && failed && (
            <p className="px-4 py-6 text-center text-xs text-destructive">
              {t.notifications.loadFailed}
            </p>
          )}
          {!loading && !failed && groups.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-muted-foreground">
              {t.notifications.empty}
            </p>
          )}
          {!loading && !failed && groups.map(({ source, items: groupItems }) => {
            const Icon = SOURCE_ICONS[source]
            return (
              <div key={source}>
                <p className="flex items-center gap-1.5 bg-muted/50 px-4 py-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  <Icon className="h-3 w-3" />
                  {sourceLabel(source)}
                </p>
                {groupItems.map((n) => {
                  const invalid = invalidIds.has(n.id)
                  return (
                    <div
                      key={n.id}
                      className="group flex items-start gap-2 border-b border-border/50 px-4 py-2.5 last:border-b-0"
                    >
                      <button
                        onClick={() => handleItemClick(n)}
                        className={cn(
                          "flex-1 text-left",
                          invalid ? "cursor-default opacity-60" : "cursor-pointer",
                        )}
                      >
                        <span className="flex items-start gap-1.5">
                          {n.status === "unread" && !invalid && (
                            <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-destructive" />
                          )}
                          <span className="text-xs leading-relaxed">
                            {notificationTitle(n.title_code, n.title_params)}
                            {invalid && (
                              <span className="ml-1.5 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                                {t.notifications.invalid}
                              </span>
                            )}
                          </span>
                        </span>
                        <span className="mt-0.5 block text-[10px] text-muted-foreground">
                          {formatRelativeTimeTz(n.created_at)}
                        </span>
                      </button>
                      <button
                        onClick={() => handleDismiss(n)}
                        className="mt-0.5 rounded p-0.5 text-muted-foreground/50 transition-colors hover:bg-accent hover:text-foreground"
                        aria-label={t.notifications.dismiss}
                        title={t.notifications.dismiss}
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      </PopoverContent>
    </Popover>
  )
}