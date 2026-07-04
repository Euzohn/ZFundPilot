import { useState } from "react"
import { NavLink, Outlet } from "react-router-dom"
import {
  LayoutDashboard,
  ArrowLeftRight,
  Briefcase,
  RefreshCw,
  TrendingUp,
  ShieldCheck,
  Package,
  LogOut,
  Settings as SettingsIcon,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { clearToken } from "@/lib/auth"

const STORAGE_KEY = "zfundpilot_sidebar_collapsed"
const navItems = [
  { to: "/", label: "组合总览", icon: LayoutDashboard },
  { to: "/transactions", label: "交易管理", icon: ArrowLeftRight },
  { to: "/positions", label: "持仓明细", icon: Briefcase },
  { to: "/nav", label: "净值更新", icon: RefreshCw },
  { to: "/returns", label: "收益分析", icon: TrendingUp },
  { to: "/risk", label: "风险与建议", icon: ShieldCheck },
  { to: "/settings", label: "设置", icon: SettingsIcon },
]

export default function Layout() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "true" } catch { return false }
  })

  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(STORAGE_KEY, next ? "true" : "false") } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <aside
        className={cn(
          "flex flex-col bg-gradient-to-b from-slate-900 to-slate-950 text-slate-300 transition-all duration-300",
          collapsed ? "w-16" : "w-60",
        )}
      >
        {/* Logo */}
        <div className={cn("flex py-5", collapsed ? "justify-center" : "items-center gap-2.5 px-5")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600/20">
            <Package className="h-5 w-5 text-blue-400" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <h1 className="text-base font-bold text-white tracking-tight whitespace-nowrap">ZFundPilot</h1>
              <p className="text-[11px] text-slate-500 whitespace-nowrap">个人基金分析</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className={cn("flex-1 space-y-0.5 py-2", collapsed ? "px-2" : "px-3")}>
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center rounded-lg text-sm font-medium transition-all duration-200",
                  collapsed ? "justify-center px-0 py-2" : "gap-3 px-3 py-2",
                  isActive
                    ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200",
                )
              }
              title={collapsed ? label : undefined}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Bottom */}
        <div className={cn("border-t border-slate-800/60 space-y-3", collapsed ? "px-2 py-4" : "px-5 py-4")}>
          {!collapsed && (
            <p className="text-[11px] leading-relaxed text-slate-600">
              仅用于数据分析与风险管理，
              不构成任何投资建议或交易指令。
            </p>
          )}
          {!collapsed && (
            <button
              onClick={() => { clearToken(); window.location.reload() }}
              className="flex items-center gap-2 text-xs text-slate-500 transition-colors hover:text-red-400"
            >
              <LogOut className="h-3.5 w-3.5" />
              退出登录
            </button>
          )}
          <button
            onClick={toggle}
            className={cn(
              "flex items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-800 hover:text-white",
              collapsed ? "w-full py-2" : "w-full gap-2 py-2 text-xs",
            )}
            title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <><ChevronLeft className="h-4 w-4" /> 收起侧边栏</>}
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}