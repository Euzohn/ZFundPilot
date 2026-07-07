import { useState, useEffect } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import Logo from "./Logo"
import {
  LayoutDashboard,
  ArrowLeftRight,
  Briefcase,
  RefreshCw,
  TrendingUp,
  ShieldCheck,
  Bot,
  LogOut,
  Settings as SettingsIcon,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
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
  { to: "/ai", label: "AI 助手", icon: Bot },
  { to: "/settings", label: "设置", icon: SettingsIcon },
]

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  return (
    <nav className={cn("flex-1 space-y-0.5 py-2", collapsed ? "px-2" : "px-3")}>
      {navItems.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onNavigate}
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
  )
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "true" } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  // Route change closes mobile drawer
  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(STORAGE_KEY, next ? "true" : "false") } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Mobile top bar */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4 md:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100"
          aria-label="打开菜单"
        >
          <Menu className="h-5 w-5" />
        </button>
        <div className="flex items-center gap-2">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-blue-600/15">
            <Logo className="h-5 w-5" />
          </div>
          <span className="text-base font-bold tracking-tight">ZFundPilot</span>
        </div>
      </header>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "hidden md:flex flex-col bg-gradient-to-b from-slate-900 to-slate-950 text-slate-300 transition-all duration-300",
          collapsed ? "w-16" : "w-60",
        )}
      >
        <div className={cn("flex py-5", collapsed ? "justify-center" : "items-center gap-2.5 px-5")}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-600/20">
            <Logo className="h-6 w-6" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <h1 className="text-base font-bold text-white tracking-tight whitespace-nowrap">ZFundPilot</h1>
              <p className="text-[11px] text-slate-500 whitespace-nowrap">个人基金分析</p>
            </div>
          )}
        </div>

        <NavLinks collapsed={collapsed} />

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
              className="flex w-full items-center gap-2 rounded-lg py-2 text-xs text-slate-500 transition-colors hover:bg-slate-800 hover:text-red-400"
            >
              <LogOut className="h-4 w-4" />
              退出登录
            </button>
          )}
          <button
            onClick={toggle}
            className={cn(
              "flex items-center rounded-lg text-slate-500 transition-colors hover:bg-slate-800 hover:text-white",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 py-2 text-xs",
            )}
            title={collapsed ? "展开侧边栏" : "收起侧边栏"}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <><ChevronLeft className="h-4 w-4" /> 收起侧边栏</>}
          </button>
        </div>
      </aside>

      {/* Mobile drawer backdrop */}
      <div
        className={cn(
          "fixed inset-0 z-40 bg-black/50 transition-opacity duration-300 md:hidden",
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0",
        )}
        onClick={() => setMobileOpen(false)}
      />

      {/* Mobile drawer sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-gradient-to-b from-slate-900 to-slate-950 text-slate-300 transition-transform duration-300 md:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {/* Logo + close */}
        <div className="flex items-center justify-between py-5 px-5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600/20">
              <Logo className="h-6 w-6" />
            </div>
            <div className="overflow-hidden">
              <h1 className="text-base font-bold text-white tracking-tight whitespace-nowrap">ZFundPilot</h1>
              <p className="text-[11px] text-slate-500 whitespace-nowrap">个人基金分析</p>
            </div>
          </div>
          <button
            onClick={() => setMobileOpen(false)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-800 hover:text-white"
            aria-label="关闭菜单"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <NavLinks collapsed={false} onNavigate={() => setMobileOpen(false)} />

        <div className="border-t border-slate-800/60 px-5 py-4 space-y-3">
          <p className="text-[11px] leading-relaxed text-slate-600">
            仅用于数据分析与风险管理，
            不构成任何投资建议或交易指令。
          </p>
          <button
            onClick={() => { clearToken(); window.location.reload() }}
            className="flex w-full items-center gap-2 rounded-lg py-2 text-xs text-slate-500 transition-colors hover:bg-slate-800 hover:text-red-400"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto pt-14 md:pt-0">
        <div className="mx-auto max-w-7xl px-4 py-4 md:px-8 md:py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
