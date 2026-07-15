import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary } from "@/api/types"
import { money, pct, signedMoney } from "@/lib/format"
import { getColorTheme, getColorThemeAsync, applyColorTheme } from "@/lib/colorTheme"

const GITHUB_URL = "https://github.com/Euzohn/ZFundPilot"

const quickActions = [
  { to: "/transactions", code: "TX", label: "TRANSACTIONS", desc: "BUY / SELL / DIVIDEND FLOW" },
  { to: "/nav", code: "NV", label: "NAV UPDATE", desc: "FETCH NET VALUE DATA" },
  { to: "/positions", code: "PS", label: "POSITIONS", desc: "HOLDINGS AND COST BASIS" },
  { to: "/returns", code: "RT", label: "RETURNS", desc: "CURVE AND RANKING" },
  { to: "/risk", code: "RK", label: "RISK ASSESS", desc: "DRAWDOWN / VOLATILITY / HHI" },
  { to: "/ai", code: "AI", label: "AI ADVISOR", desc: "LLM POWERED ANALYSIS" },
]

function greeting() {
  const h = new Date().getHours()
  if (h < 6) return "深夜"
  if (h < 12) return "上午好"
  if (h < 14) return "中午好"
  if (h < 18) return "下午好"
  return "晚上好"
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

function marketStatus(d: Date): string {
  const day = d.getDay()
  if (day === 0 || day === 6) return "CLOSED"
  const t = d.getHours() * 60 + d.getMinutes()
  if ((t >= 570 && t <= 690) || (t >= 780 && t <= 900)) return "OPEN"
  return "CLOSED"
}

function concentrationLevel(w: number | undefined): string {
  if (w == null) return "---"
  if (w > 0.5) return "HIGH"
  if (w > 0.3) return "MODERATE"
  return "LOW"
}

function pnlColorDark(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-white/60"
  if (v > 0) return "text-gain-400"
  return "text-loss-400"
}

export default function Home() {
  const navigate = useNavigate()
  const { data: summary, loading } = useApi<PortfolioSummary>(() => api.getSummary())
  const [now, setNow] = useState(new Date())

  useEffect(() => {
    applyColorTheme(getColorTheme())
    getColorThemeAsync().then(applyColorTheme).catch(() => {})
  }, [])

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const mkt = marketStatus(now)
  const todayStr = new Date().toISOString().slice(0, 10)
  const navStatus = summary?.as_of_date
    ? summary.as_of_date === todayStr
      ? "CURRENT"
      : summary.as_of_date
    : "---"

  return (
    <div className="flex min-h-[100dvh] flex-col bg-[#0A0A0A] text-[#EAEAEA]">
      {/* CRT scanlines */}
      <div
        className="fixed inset-0 pointer-events-none z-50"
        style={{
          background:
            "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.1) 2px, rgba(0,0,0,0.1) 4px)",
        }}
      />

      {/* Main content — no header, content-first */}
      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center px-6 py-16 md:py-20">
        {/* Hero */}
        <section className="mb-12">
          <h1
            className="text-5xl font-bold uppercase tracking-tighter leading-none md:text-6xl lg:text-7xl"
            style={{ textShadow: "0 0 30px rgba(234,234,234,0.08)" }}
          >
            PORTFOLIO<br />
            TERMINAL
          </h1>
          <p className="mt-4 font-mono text-xs uppercase tracking-wider text-white/40">
            {formatDateTime(now)} · {greeting()}
          </p>
        </section>

        {/* Metrics */}
        <section className="mb-6">
          {loading ? (
            <p className="font-mono text-sm uppercase tracking-wider text-white/40 animate-pulse">
              [ FETCHING DATA... ]
            </p>
          ) : summary && summary.holding_count === 0 ? (
            <div className="font-mono">
              <p className="text-lg uppercase tracking-wider text-white/60">[ NO DATA ]</p>
              <button
                onClick={() => navigate("/transactions")}
                className="mt-2 text-sm uppercase tracking-wider text-[#FF2A2A] transition-colors hover:text-white"
              >
                {">>> INITIATE FIRST TRANSACTION"}
              </button>
            </div>
          ) : summary ? (
            <div className="grid grid-cols-1 gap-px border border-white/10 bg-white/10 sm:grid-cols-3">
              <div className="bg-[#0A0A0A] p-6">
                <p className="font-mono text-xs uppercase tracking-wider text-white/40">[ CURRENT VALUE ]</p>
                <output
                  className="mt-2 block font-mono text-2xl font-bold tabular-nums"
                  style={{ textShadow: "0 0 15px rgba(234,234,234,0.1)" }}
                >
                  {money(summary.total_value)}
                </output>
              </div>
              <div className="bg-[#0A0A0A] p-6">
                <p className="font-mono text-xs uppercase tracking-wider text-white/40">[ TOTAL P&L ]</p>
                <output
                  className={`mt-2 block font-mono text-2xl font-bold tabular-nums ${pnlColorDark(summary.total_pnl)}`}
                  style={{ textShadow: "0 0 15px rgba(234,234,234,0.1)" }}
                >
                  {signedMoney(summary.total_pnl)}{" "}
                  <span className="text-sm font-normal text-white/40">({pct(summary.total_return)})</span>
                </output>
              </div>
              <div className="bg-[#0A0A0A] p-6">
                <p className="font-mono text-xs uppercase tracking-wider text-white/40">[ HOLDINGS ]</p>
                <output
                  className="mt-2 block font-mono text-2xl font-bold tabular-nums"
                  style={{ textShadow: "0 0 15px rgba(234,234,234,0.1)" }}
                >
                  {summary.holding_count} UNITS
                </output>
              </div>
            </div>
          ) : null}
        </section>

        {/* System status */}
        {summary && summary.holding_count > 0 && (
          <section className="mb-12">
            <div className="border border-white/10 bg-[#0A0A0A] p-4">
              <p className="font-mono text-xs uppercase tracking-wider text-white/40">[ SYSTEM STATUS ]</p>
              <p className="mt-2 font-mono text-xs uppercase tracking-wider">
                <span className="text-white/60">MARKET:</span>{" "}
                <span className={mkt === "OPEN" ? "text-gain-400" : "text-[#FF2A2A]"}>{mkt}</span>
                <span className="mx-3 text-white/20">///</span>
                <span className="text-white/60">NAV:</span>{" "}
                <span className="text-white/80">{navStatus}</span>
                <span className="mx-3 text-white/20">///</span>
                <span className="text-white/60">CONCENTRATION:</span>{" "}
                <span className="text-white/80">
                  {concentrationLevel(summary.max_single_weight)}
                  {summary.max_single_weight ? ` ${(summary.max_single_weight * 100).toFixed(1)}%` : ""}
                </span>
              </p>
            </div>
          </section>
        )}

        {/* Navigation */}
        <section>
          <p className="mb-4 font-mono text-xs uppercase tracking-wider text-white/40">[ NAVIGATION ]</p>
          <div className="grid grid-cols-2 gap-px border border-white/10 bg-white/10 sm:grid-cols-3">
            {quickActions.map(({ to, code, label, desc }) => (
              <button
                key={to}
                onClick={() => navigate(to)}
                className="group bg-[#0A0A0A] p-6 text-left transition-colors hover:bg-[#EAEAEA] hover:text-[#0A0A0A] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[#FF2A2A] active:opacity-80"
              >
                <p className="font-mono text-2xl font-bold">{code}</p>
                <p className="mt-1 font-mono text-xs uppercase tracking-wider">{label}</p>
                <p className="mt-1 font-mono text-[10px] uppercase tracking-wider text-white/40 group-hover:text-black/60">
                  {desc}
                </p>
              </button>
            ))}
          </div>
        </section>
      </main>

      {/* Footer — branding at the bottom, no header at top */}
      <footer className="border-t border-white/10">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="font-mono text-sm text-[#FF2A2A]">+</span>
              <span className="font-mono text-xs uppercase tracking-wider text-white/60">ZFUNDPILOT ®</span>
              <span className="font-mono text-xs uppercase tracking-wider text-white/30">v0.5.0</span>
            </div>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xs uppercase tracking-wider text-white/60 transition-colors hover:text-[#FF2A2A]"
            >
              [ GITHUB ]
            </a>
          </div>
          <p className="mt-2 font-mono text-[10px] uppercase tracking-wider text-white/30">
            /// NO TRADE SIGNALS / NOT FINANCIAL ADVICE / DATA ONLY ///
          </p>
        </div>
      </footer>
    </div>
  )
}
