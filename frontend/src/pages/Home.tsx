import { useEffect, useMemo, useRef, useState, useCallback } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary } from "@/api/types"
import { money, pct, signedMoney, localDateStr } from "@/lib/format"
import { getColorTheme, getColorThemeAsync, applyColorTheme } from "@/lib/colorTheme"
import { isMarketOpen } from "@/lib/market"
import { useLang } from "@/i18n/LanguageContext"

const GITHUB_URL = "https://github.com/Euzohn/ZFundPilot"

function greeting(greetings: string[]) {
  const h = new Date().getHours()
  if (h < 6) return greetings[0]
  if (h < 12) return greetings[1]
  if (h < 14) return greetings[2]
  if (h < 18) return greetings[3]
  return greetings[4]
}

function formatDateTime(d: Date) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, "0")
  const day = String(d.getDate()).padStart(2, "0")
  const weekdays = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
  const w = weekdays[d.getDay()]
  const h = String(d.getHours()).padStart(2, "0")
  const min = String(d.getMinutes()).padStart(2, "0")
  const s = String(d.getSeconds()).padStart(2, "0")
  return `${y}.${m}.${day} / ${w} / ${h}:${min}:${s}`
}

function concentrationLabel(w: number | undefined, conc: { concHigh: string; concModerate: string; concLow: string }): string {
  if (w == null) return "---"
  if (w > 0.5) return conc.concHigh
  if (w > 0.3) return conc.concModerate
  return conc.concLow
}

function concentrationColor(w: number | undefined): string {
  if (w == null) return "text-white/80"
  if (w > 0.5) return "text-loss-400"
  if (w > 0.3) return "text-brand-accent"
  return "text-gain-400"
}

function pnlColorDark(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-white/60"
  if (v > 0) return "text-gain-400"
  return "text-loss-400"
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    const update = () => setReduced(mq.matches)
    update()
    mq.addEventListener("change", update)
    return () => mq.removeEventListener("change", update)
  }, [])
  return reduced
}

export default function Home() {
  const navigate = useNavigate()
  const { data: summary, loading, reload } = useApi<PortfolioSummary>(() => api.getSummary())
  const { data: authStatus } = useApi(() => api.getAuthStatus(), [])
  const { lang, t } = useLang()
  const [now, setNow] = useState(new Date())
  const reducedMotion = usePrefersReducedMotion()

  const clockRef = useRef<HTMLSpanElement>(null)

  const tr = t.home
  const labelFont = lang === "zh" ? "font-sans" : "font-mono uppercase"
  const descFont = lang === "zh" ? "font-sans" : "font-mono uppercase tracking-wider"

  useEffect(() => {
    applyColorTheme(getColorTheme())
    getColorThemeAsync().then(applyColorTheme).catch(() => {})
  }, [])

  useEffect(() => {
    if (reducedMotion) return
    let lastMin = -1
    const tick = () => {
      const d = new Date()
      if (clockRef.current) clockRef.current.textContent = formatDateTime(d)
      const min = d.getHours() * 60 + d.getMinutes()
      if (min !== lastMin) {
        lastMin = min
        setNow(d)
      }
    }
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [reducedMotion])

  const handleVisibility = useCallback(() => {
    if (document.visibilityState === "visible") reload()
  }, [reload])
  useEffect(() => {
    document.addEventListener("visibilitychange", handleVisibility)
    return () => document.removeEventListener("visibilitychange", handleVisibility)
  }, [handleVisibility])

  const mkt = useMemo(() => isMarketOpen(now), [now])
  const todayStr = useMemo(() => localDateStr(), [])
  const yesterdayStr = useMemo(() => localDateStr(new Date(Date.now() - 86400000)), [])
  const navStatus = summary?.as_of_date
    ? summary.as_of_date === todayStr
      ? tr.navLatest
      : summary.as_of_date
    : "---"

  const showScanlines = !reducedMotion

  return (
    <div className="flex min-h-[100dvh] flex-col bg-brand-bg-dark text-brand-text-light">
      {/* CRT scanlines */}
      {showScanlines && (
        <div
          aria-hidden="true"
          className="fixed inset-0 pointer-events-none z-10"
          style={{
            background:
              "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.1) 2px, rgba(0,0,0,0.1) 4px)",
          }}
        />
      )}

      {/* Main content */}
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-6 py-16 md:py-20">
        {/* Hero — logo inline with title */}
        <section className="fade-in-up mb-12 flex items-start gap-5">
          <svg
            viewBox="0 0 64 64"
            className="mt-1 h-12 w-12 shrink-0 md:h-14 md:w-14 lg:h-16 lg:w-16"
            fill="none"
            role="img"
            aria-label="ZFundPilot logo"
          >
            <title>ZFundPilot</title>
            <path d="M2 10 L2 2 L10 2" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <path d="M54 2 L62 2 L62 10" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <path d="M62 54 L62 62 L54 62" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <path d="M10 62 L2 62 L2 54" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <line x1="32" y1="6" x2="32" y2="20" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <line x1="32" y1="44" x2="32" y2="58" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <line x1="6" y1="32" x2="20" y2="32" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <line x1="44" y1="32" x2="58" y2="32" stroke="hsl(var(--brand-accent))" strokeWidth="1" />
            <circle cx="32" cy="32" r="10" stroke="hsl(var(--brand-text-light))" strokeWidth="1" />
            <path
              d="M27 28 L37 28 L27 36 L37 36"
              stroke="hsl(var(--brand-accent))"
              strokeWidth="2"
              strokeLinecap="square"
              strokeLinejoin="miter"
              fill="none"
            />
          </svg>
          <div>
            <h1
              className="text-5xl font-bold tracking-tighter leading-none md:text-6xl lg:text-7xl"
              style={{ textShadow: "0 0 30px rgba(234,234,234,0.08)" }}
            >
              ZFUNDPILOT
            </h1>
            <p className={`mt-3 text-sm tracking-wider text-white/40 ${labelFont}`}>
              {tr.tagline}
            </p>
            <p className="mt-4 font-mono text-xs tracking-wider text-white/40">
              <span ref={clockRef}>{formatDateTime(now)}</span>
              <span aria-hidden="true"> · </span>
              <span>{greeting(tr.greetings)}</span>
            </p>
          </div>
        </section>

        {/* Metrics */}
        <section className="fade-in-up mb-6 min-h-[120px]" style={{ animationDelay: "100ms" }} aria-busy={loading}>
          {loading ? (
            <div className="grid grid-cols-1 gap-px border border-white/10 bg-white/10 sm:grid-cols-2 lg:grid-cols-4" aria-hidden="true">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="bg-brand-bg-dark p-6">
                  <div className={`h-3 w-20 bg-white/10 ${reducedMotion ? "" : "animate-pulse"}`} />
                  <div className={`mt-3 h-7 w-28 bg-white/10 ${reducedMotion ? "" : "animate-pulse"}`} />
                </div>
              ))}
            </div>
          ) : summary && summary.holding_count === 0 ? (
            <div>
              <p className={`text-lg tracking-wider text-white/60 ${labelFont}`}>{tr.noData}</p>
              <button
                type="button"
                onClick={() => navigate("/transactions")}
                className="mt-2 font-mono text-sm tracking-wider text-brand-accent transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-brand-bg-dark active:scale-[0.98]"
              >
                {tr.initiateTx}
              </button>
            </div>
          ) : summary ? (
            <div className="grid grid-cols-1 gap-px border border-white/10 bg-white/10 sm:grid-cols-2 lg:grid-cols-4">
              <div className="bg-brand-bg-dark p-6">
                <p className={`text-sm tracking-wider text-white/40 ${labelFont}`}>{summary.as_of_date === todayStr ? tr.dailyPnl : summary.as_of_date === yesterdayStr ? tr.yesterdayPnl : summary.as_of_date}</p>
                <output className={`mt-2 block font-mono text-2xl font-bold tabular-nums ${pnlColorDark(summary.daily_pnl)}`}>
                  {signedMoney(summary.daily_pnl)}{" "}
                  <span className="text-sm font-normal text-white/40">({pct(summary.daily_return)})</span>
                </output>
              </div>
              <div className="bg-brand-bg-dark p-6">
                <p className={`text-sm tracking-wider text-white/40 ${labelFont}`}>{tr.currentValue}</p>
                <output className="mt-2 block font-mono text-2xl font-bold tabular-nums text-brand-text-light">
                  {money(summary.total_value)}
                </output>
              </div>
              <div className="bg-brand-bg-dark p-6">
                <p className={`text-sm tracking-wider text-white/40 ${labelFont}`}>{tr.totalPnl}</p>
                <output className={`mt-2 block font-mono text-2xl font-bold tabular-nums ${pnlColorDark(summary.total_pnl)}`}>
                  {signedMoney(summary.total_pnl)}{" "}
                  <span className="text-sm font-normal text-white/40">({pct(summary.total_return)})</span>
                </output>
              </div>
              <div className="bg-brand-bg-dark p-6">
                <p className={`text-sm tracking-wider text-white/40 ${labelFont}`}>{tr.holdings}</p>
                <output className="mt-2 block font-mono text-2xl font-bold tabular-nums text-brand-text-light">
                  {summary.holding_count} {tr.units}
                </output>
              </div>
            </div>
          ) : (
            <div>
              <p className={`text-lg tracking-wider text-brand-accent ${labelFont}`}>{tr.error}</p>
              <button
                type="button"
                onClick={reload}
                className="mt-2 font-mono text-sm tracking-wider text-brand-accent transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-brand-bg-dark active:scale-[0.98]"
              >
                {tr.retry}
              </button>
            </div>
          )}
        </section>

        {/* System status */}
        {summary && summary.holding_count > 0 && (
          <section className="fade-in-up mb-12" style={{ animationDelay: "200ms" }}>
            <div className="border border-white/10 bg-brand-bg-dark p-4">
              <p className={`text-sm tracking-wider text-white/40 ${labelFont}`}>{tr.systemStatus}</p>
              <p className="mt-2 font-mono text-xs tracking-wider">
                <span className="text-white/60">{tr.market}:</span>{" "}
                <span className={mkt ? "text-gain-400" : "text-brand-accent"}>
                  {mkt ? tr.marketOpen : tr.marketClosed}
                </span>
                <span aria-hidden="true" className="mx-3 text-white/30">///</span>
                <span className="text-white/60">{tr.nav}:</span>{" "}
                <span className={summary.as_of_date === todayStr ? "text-gain-400" : "text-white/80"}>
                  {navStatus}
                </span>
                <span aria-hidden="true" className="mx-3 text-white/30">///</span>
                <span className="text-white/60">{tr.concentration}:</span>{" "}
                <span className={concentrationColor(summary.max_single_weight)}>
                  {concentrationLabel(summary.max_single_weight, tr)}
                  {summary.max_single_weight ? ` ${(summary.max_single_weight * 100).toFixed(1)}%` : ""}
                </span>
              </p>
            </div>
          </section>
        )}

        {/* Navigation — asymmetric bento (TX + AI span 2 cols on desktop) */}
        <section className="fade-in-up" style={{ animationDelay: "300ms" }}>
          <p className={`mb-4 text-sm tracking-wider text-white/40 ${labelFont}`}>{tr.navigation}</p>
          <div className="grid grid-cols-2 gap-px border border-white/10 bg-white/10 sm:grid-cols-4">
            {t.quickActions.map(({ label, desc }, i) => {
              const codes = ["TX", "NV", "PS", "RT", "RK", "AI"]
              const routes = ["/transactions", "/nav", "/positions", "/returns", "/risk", "/ai"]
              const isWide = i === 0 || i === 5
              return (
                <button
                  key={routes[i]}
                  type="button"
                  onClick={() => navigate(routes[i])}
                  className={`group relative bg-brand-bg-dark p-5 text-left transition-colors duration-200 hover:bg-brand-text-light hover:text-brand-bg-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-brand-bg-dark active:scale-[0.98] sm:p-6 ${isWide ? "sm:col-span-2" : ""}`}
                >
                  <span
                    aria-hidden="true"
                    className="pointer-events-none absolute left-1 top-1 h-2 w-2 border-l border-t border-brand-accent opacity-0 transition-opacity group-hover:opacity-100"
                  />
                  <span
                    aria-hidden="true"
                    className="pointer-events-none absolute right-1 bottom-1 h-2 w-2 border-r border-b border-brand-accent opacity-0 transition-opacity group-hover:opacity-100"
                  />
                  <div className={`flex items-center gap-3 ${isWide ? "sm:flex-row sm:items-center" : "flex-col"}`}>
                    <p className="font-mono text-2xl font-bold">{codes[i]}</p>
                    <div className={isWide ? "sm:border-l sm:border-white/10 sm:pl-3" : ""}>
                      <p className={`text-sm ${labelFont}`}>{label}</p>
                      <p className={`mt-0.5 text-xs text-white/30 group-hover:text-black/50 ${descFont}`}>
                        {desc}
                      </p>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-white/10">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <span aria-hidden="true" className="font-mono text-sm text-brand-accent">+</span>
              <span className="font-mono text-xs uppercase tracking-wider text-white/60">ZFUNDPILOT ®</span>
              <span className="font-mono text-xs uppercase tracking-wider text-white/30">v{authStatus?.version ?? "..."}</span>
            </div>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-wider text-white/60 transition-colors hover:text-brand-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-accent focus-visible:ring-offset-2 focus-visible:ring-offset-brand-bg-dark active:scale-[0.98]"
            >
              <span>[ GITHUB ]</span>
              <span
                aria-hidden="true"
                className="inline-block translate-x-0 text-white/40 transition-transform group-hover:translate-x-0.5 group-hover:text-brand-accent"
              >
                ↗
              </span>
            </a>
          </div>
          <p className={`mt-2 text-[10px] tracking-wider text-white/30 ${lang === "zh" ? "font-sans" : "font-mono uppercase"}`}>
            {tr.disclaimer}
          </p>
        </div>
      </footer>
    </div>
  )
}
