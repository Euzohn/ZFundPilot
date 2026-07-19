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
  GitCompare,
  Settings as SettingsIcon,
  ChevronLeft,
  ChevronRight,
  Menu,
  X,
  House,
  Github,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getColorTheme, getColorThemeAsync, applyColorTheme } from "@/lib/colorTheme"

const STORAGE_KEY = "zfundpilot_sidebar_collapsed"

const navGroups = [
  {
    label: "概览",
    items: [
      { to: "/", label: "首页", icon: House },
      { to: "/overview", label: "组合总览", icon: LayoutDashboard },
    ],
  },
  {
    label: "交易与持仓",
    items: [
      { to: "/transactions", label: "交易管理", icon: ArrowLeftRight },
      { to: "/positions", label: "持仓明细", icon: Briefcase },
      { to: "/nav", label: "净值更新", icon: RefreshCw },
    ],
  },
  {
    label: "分析与工具",
    items: [
      { to: "/returns", label: "收益分析", icon: TrendingUp },
      { to: "/risk", label: "风险与建议", icon: ShieldCheck },
      { to: "/compare", label: "基金对比", icon: GitCompare },
      { to: "/ai", label: "AI 助手", icon: Bot },
    ],
  },
]

const bottomNav = { to: "/settings", label: "设置", icon: SettingsIcon }

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const linkClass = (isActive: boolean) =>
    cn(
      "flex items-center rounded-lg text-sm font-medium transition-colors duration-200",
      collapsed ? "justify-center px-0 py-2" : "gap-3 px-3 py-2",
      isActive
        ? "bg-blue-600/15 text-blue-300"
        : "text-slate-400 hover:bg-slate-800/50 hover:text-slate-200",
    )

  return (
    <nav className={cn("flex-1 overflow-y-auto py-2", collapsed ? "px-2" : "px-3")}>
      {navGroups.map((group) => (
        <div key={group.label} className="mb-1">
          {!collapsed && (
            <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-slate-600">{group.label}</p>
          )}
          {group.items.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={onNavigate}
              className={({ isActive }) => linkClass(isActive)}
              title={collapsed ? label : undefined}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              {!collapsed && <span className="whitespace-nowrap">{label}</span>}
            </NavLink>
          ))}
        </div>
      ))}
      <div className="mt-2 border-t border-slate-800/50 pt-2">
        <NavLink
          to={bottomNav.to}
          onClick={onNavigate}
          className={({ isActive }) => linkClass(isActive)}
          title={collapsed ? bottomNav.label : undefined}
        >
          <bottomNav.icon className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && <span className="whitespace-nowrap">{bottomNav.label}</span>}
        </NavLink>
      </div>
    </nav>
  )
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "true" } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  useEffect(() => {
    applyColorTheme(getColorTheme())
    getColorThemeAsync().then(applyColorTheme).catch(() => {})
  }, [])

  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(STORAGE_KEY, next ? "true" : "false") } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* 噪点叠加层 */}
      <div className="grain-overlay" aria-hidden="true" />

      {/* Mobile top bar */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white px-4 md:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 transition-colors hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
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
            <h1 className="text-base font-bold text-white tracking-tight whitespace-nowrap">ZFundPilot</h1>
          )}
        </div>

        <NavLinks collapsed={collapsed} />

        <div className={cn("border-t border-slate-800/60", collapsed ? "px-2 py-3" : "px-3 py-3")}>
          <a
            href="https://github.com/Euzohn/ZFundPilot"
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "flex items-center rounded-lg text-slate-500 transition-colors hover:bg-slate-800 hover:text-white",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
            )}
            title={collapsed ? "GitHub" : undefined}
          >
            <Github className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="whitespace-nowrap">GitHub</span>}
          </a>
          <button
            onClick={toggle}
            className={cn(
              "flex items-center rounded-lg text-slate-500 transition-colors hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
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
        <div className="flex items-center justify-between py-5 px-5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600/20">
              <Logo className="h-6 w-6" />
            </div>
            <h1 className="text-base font-bold text-white tracking-tight whitespace-nowrap">ZFundPilot</h1>
          </div>
          <button
            onClick={() => setMobileOpen(false)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-slate-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
            aria-label="关闭菜单"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <NavLinks collapsed={false} onNavigate={() => setMobileOpen(false)} />
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
