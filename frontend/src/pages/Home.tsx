import { useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { PortfolioSummary } from "@/api/types"
import { money, pct, signedMoney, pnlColor } from "@/lib/format"
import Logo from "@/components/Logo"
import LogoSpinner from "@/components/LogoSpinner"
import { Card, CardContent } from "@/components/ui/card"
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

  const noData = summary && summary.holding_count === 0

  return (
    <div className="space-y-8">
      {/* Hero */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 px-6 py-10 md:px-10 md:py-14">
        <div className="absolute inset-0 bg-[url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNjAiIGhlaWdodD0iNjAiIHZpZXdCb3g9IjAgMCA2MCA2MCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48ZyBmaWxsPSJub25lIiBmaWxsLXJ1bGU9ImV2ZW5vZGQiPjxnIGZpbGw9IiNmZmYiIGZpbGwtb3BhY2l0eT0iMC4wMyI+PHBhdGggZD0iTTM2IDM0djItSDI0di0yaDEyek0zNiAyNHYtMkgyNHYyaDEyeiIvPjwvZz48L2c+PC9zdmc+')] opacity-30" />
        <div className="relative flex flex-col gap-6">
          <div className="flex items-center gap-4">
            <Logo className="h-12 w-12 drop-shadow-lg" />
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">ZFundPilot</h1>
              <p className="text-sm text-blue-200">个人基金分析与风险管理系统</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm text-blue-100">
            <span>{formatDate()} · {greeting()}</span>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-3 py-1 text-xs text-blue-100 transition-colors hover:bg-white/20 hover:text-white"
            >
              <Github className="h-3.5 w-3.5" />
              开源项目
              <ExternalLink className="h-3 w-3" />
            </a>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-blue-200">
              <LogoSpinner className="h-5 w-5" />
              <span className="text-sm">加载中...</span>
            </div>
          ) : noData ? (
            <div className="rounded-xl bg-white/10 px-4 py-3 text-sm text-blue-100">
              还没有交易记录，{' '}
              <button onClick={() => navigate("/transactions")} className="font-medium text-white underline underline-offset-2 hover:text-blue-50">
                开始录入第一笔交易
              </button>
            </div>
          ) : summary ? (
            <div className="flex flex-wrap gap-4">
              <div className="rounded-xl bg-white/10 px-5 py-3">
                <p className="text-xs text-blue-200">当前市值</p>
                <p className="text-xl font-bold text-white tabular-nums">{money(summary.total_value)}</p>
              </div>
              <div className="rounded-xl bg-white/10 px-5 py-3">
                <p className="text-xs text-blue-200">总盈亏</p>
                <p className={`text-xl font-bold tabular-nums ${summary.total_pnl >= 0 ? "text-gain" : "text-loss"}`}>
                  {signedMoney(summary.total_pnl)}
                  <span className="ml-1.5 text-sm font-normal opacity-80">({pct(summary.total_return)})</span>
                </p>
              </div>
              <div className="rounded-xl bg-white/10 px-5 py-3">
                <p className="text-xs text-blue-200">持仓基金</p>
                <p className="text-xl font-bold text-white tabular-nums">{summary.holding_count} 只</p>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="mb-3 text-sm font-medium text-muted-foreground">快捷入口</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:gap-4">
          {quickActions.map(({ to, label, desc, icon: Icon }) => (
            <Card
              key={to}
              className="cursor-pointer transition-all hover:shadow-md hover:-translate-y-0.5"
              onClick={() => navigate(to)}
            >
              <CardContent className="flex items-center gap-3 p-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                  <Icon className="h-4.5 w-4.5" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium">{label}</p>
                  <p className="truncate text-xs text-muted-foreground">{desc}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  )
}