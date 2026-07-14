import { useEffect } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary } from "@/api/types"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import Logo from "@/components/Logo"
import LogoSpinner from "@/components/LogoSpinner"
import { Card, CardContent } from "@/components/ui/card"
import { getColorTheme, getColorThemeAsync, applyColorTheme } from "@/lib/colorTheme"
import {
  ArrowLeftRight, RefreshCw, Briefcase, TrendingUp,
  ShieldCheck, Bot, Github, ExternalLink,
} from "lucide-react"

const GITHUB_URL = "https://github.com/Euzohn/ZFundPilot"

const quickActions = [
  { to: "/transactions", label: "录入交易", desc: "添加买入/卖出/分红流水", icon: ArrowLeftRight },
  { to: "/nav", label: "更新净值", desc: "拉取基金最新净值数据", icon: RefreshCw },
  { to: "/positions", label: "持仓明细", desc: "查看当前持仓与成本", icon: Briefcase },
  { to: "/returns", label: "收益分析", desc: "组合收益曲线与排名", icon: TrendingUp },
  { to: "/risk", label: "风险评估", desc: "回撤/波动率/集中度分析", icon: ShieldCheck },
  { to: "/ai", label: "AI 投顾", desc: "AI 结合持仓给出建议", icon: Bot },
]

function greeting() {
  const h = new Date().getHours()
  if (h < 6) return "夜深了"
  if (h < 12) return "上午好"
  if (h < 14) return "中午好"
  if (h < 18) return "下午好"
  return "晚上好"
}

function formatDate() {
  const d = new Date()
  const y = d.getFullYear()
  const m = d.getMonth() + 1
  const day = d.getDate()
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"]
  const w = weekdays[d.getDay()]
  return `${y}年${m}月${day}日 星期${w}`
}

export default function Home() {
  const navigate = useNavigate()
  const { data: summary, loading } = useApi<PortfolioSummary>(() => api.getSummary())

  useEffect(() => {
    applyColorTheme(getColorTheme())
    getColorThemeAsync().then(applyColorTheme).catch(() => {})
  }, [])

  return (
    <div className="min-h-[100dvh] bg-slate-50">
      {/* Top bar */}
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2.5">
            <Logo className="h-8 w-8" />
            <span className="text-lg font-bold tracking-tight text-slate-900">ZFundPilot</span>
          </div>
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700"
          >
            <Github className="h-3.5 w-3.5" />
            开源项目
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>
      </header>

      {/* Main content */}
      <main className="mx-auto max-w-5xl px-6 py-12 md:py-16">
        {/* Hero */}
        <div className="mb-12">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 md:text-4xl">
            个人基金分析与风险管理系统
          </h1>
          <p className="mt-2 text-sm text-slate-500">{formatDate()} · {greeting()}</p>

          {/* Metrics */}
          <div className="mt-8">
            {loading ? (
              <div className="flex items-center gap-2 text-slate-400">
                <LogoSpinner className="h-5 w-5" />
                <span className="text-sm">加载中...</span>
              </div>
            ) : summary && summary.holding_count === 0 ? (
              <div className="flex items-center gap-3">
                <p className="text-sm text-slate-500">还没有交易记录</p>
                <button
                  onClick={() => navigate("/transactions")}
                  className="text-sm font-medium text-blue-600 hover:text-blue-700"
                >
                  开始录入第一笔交易 →
                </button>
              </div>
            ) : summary ? (
              <div className="flex flex-col gap-6 sm:flex-row sm:items-end">
                <div className="sm:pr-8">
                  <p className="text-xs text-slate-400">当前市值</p>
                  <p className="text-2xl font-bold tabular-nums text-slate-900">{money(summary.total_value)}</p>
                </div>
                <div className="sm:border-l sm:border-slate-200 sm:px-8">
                  <p className="text-xs text-slate-400">总盈亏</p>
                  <p className={`text-2xl font-bold tabular-nums ${pnlColor(summary.total_pnl)}`}>
                    {signedMoney(summary.total_pnl)}
                    <span className="ml-1.5 text-sm font-normal text-slate-400">({pct(summary.total_return)})</span>
                  </p>
                </div>
                <div className="sm:border-l sm:border-slate-200 sm:pl-8">
                  <p className="text-xs text-slate-400">持仓基金</p>
                  <p className="text-2xl font-bold tabular-nums text-slate-900">{summary.holding_count} 只</p>
                </div>
              </div>
            ) : null}
          </div>
        </div>

        {/* Quick actions */}
        <div>
          <h2 className="mb-4 text-sm font-medium text-slate-500">快捷入口</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {quickActions.map(({ to, label, desc, icon: Icon }) => (
              <Card
                key={to}
                className="cursor-pointer rounded-xl transition-all hover:-translate-y-0.5 hover:shadow-md"
                onClick={() => navigate(to)}
              >
                <CardContent className="flex items-center gap-3 p-5">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900">{label}</p>
                    <p className="truncate text-xs text-slate-400">{desc}</p>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </main>
    </div>
  )
}
