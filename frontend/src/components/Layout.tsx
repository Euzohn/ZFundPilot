import { useState, useEffect } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { api } from "@/api/client"
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
  FlaskConical,
  Star,
  Search as SearchIcon,
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
import ThemeToggle from "./ThemeToggle"
import LanguageToggle from "./LanguageToggle"
import { useLang } from "@/i18n/LanguageContext"

const STORAGE_KEY = "zfundpilot_sidebar_collapsed"

const navGroups = [
  {
    labelKey: "groupOverview" as const,
    items: [
      { to: "/", labelKey: "home" as const, icon: House },
      { to: "/overview", labelKey: "overview" as const, icon: LayoutDashboard },
    ],
  },
  {
    labelKey: "groupTrading" as const,
    items: [
      { to: "/positions", labelKey: "positions" as const, icon: Briefcase },
      { to: "/transactions", labelKey: "transactions" as const, icon: ArrowLeftRight },
      { to: "/nav", labelKey: "navUpdate" as const, icon: RefreshCw },
    ],
  },
  {
    labelKey: "groupAnalysis" as const,
    items: [
      { to: "/returns", labelKey: "returns" as const, icon: TrendingUp },
      { to: "/risk", labelKey: "risk" as const, icon: ShieldCheck },
      { to: "/compare", labelKey: "compare" as const, icon: GitCompare },
      { to: "/screener", labelKey: "screener" as const, icon: SearchIcon },
      { to: "/watchlist", labelKey: "watchlist" as const, icon: Star },
      { to: "/backtest", labelKey: "backtest" as const, icon: FlaskConical },
      { to: "/ai", labelKey: "aiChat" as const, icon: Bot },
    ],
  },
]

const bottomNav = { to: "/settings", labelKey: "settings" as const, icon: SettingsIcon }

function NavLinks({ collapsed, onNavigate, pendingCount }: { collapsed: boolean; onNavigate?: () => void; pendingCount: number }) {
  const { t } = useLang()

  const linkClass = (isActive: boolean) =>
    cn(
      "flex items-center rounded-lg text-sm font-medium transition-colors duration-200",
      collapsed ? "justify-center px-0 py-2" : "gap-3 px-3 py-2",
      isActive
        ? "bg-blue-600/15 text-blue-300"
        : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
    )

  return (
    <nav className={cn("flex-1 overflow-y-auto py-2", collapsed ? "px-2" : "px-3")}>
      {navGroups.map((group) => (
        <div key={group.labelKey} className="mb-1">
          {!collapsed && (
            <p className="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-zinc-600">{t.nav[group.labelKey]}</p>
          )}
          {group.items.map(({ to, labelKey, icon: Icon }) => {
            const showBadge = to === "/transactions" && pendingCount > 0
            return (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              onClick={onNavigate}
              className={({ isActive }) => linkClass(isActive)}
              title={collapsed ? t.nav[labelKey] : undefined}
            >
              <span className="relative shrink-0">
                <Icon className="h-[18px] w-[18px]" />
                {collapsed && showBadge && (
                  <span className="absolute -top-1 -right-1.5 h-2 w-2 rounded-full bg-red-500 ring-1 ring-zinc-900" />
                )}
              </span>
              {!collapsed && <span className="whitespace-nowrap">{t.nav[labelKey]}</span>}
              {!collapsed && showBadge && (
                <span className="ml-auto inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold">
                  {pendingCount > 99 ? "99+" : pendingCount}
                </span>
              )}
            </NavLink>
            )
          })}
        </div>
      ))}
      <div className="mt-2 border-t border-zinc-800/50 pt-2">
        <NavLink
          to={bottomNav.to}
          onClick={onNavigate}
          className={({ isActive }) => linkClass(isActive)}
          title={collapsed ? t.nav[bottomNav.labelKey] : undefined}
        >
          <bottomNav.icon className="h-[18px] w-[18px] shrink-0" />
          {!collapsed && <span className="whitespace-nowrap">{t.nav[bottomNav.labelKey]}</span>}
        </NavLink>
      </div>
    </nav>
  )
}

export default function Layout() {
  const { t } = useLang()
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(STORAGE_KEY) === "true" } catch { return false }
  })
  const [mobileOpen, setMobileOpen] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)
  const location = useLocation()

  useEffect(() => { setMobileOpen(false) }, [location.pathname])

  useEffect(() => {
    applyColorTheme(getColorTheme())
    getColorThemeAsync().then(applyColorTheme).catch(() => {})
  }, [])

  useEffect(() => {
    let active = true
    const fetchCount = () => {
      api.getPendingAlertCount().then(r => { if (active) setPendingCount(r.count) }).catch(() => {})
    }
    fetchCount()
    const timer = setInterval(fetchCount, 60000)
    return () => { active = false; clearInterval(timer) }
  }, [])

  const toggle = () => {
    const next = !collapsed
    setCollapsed(next)
    try { localStorage.setItem(STORAGE_KEY, next ? "true" : "false") } catch {}
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* 噪点叠加层 */}
      <div className="grain-overlay" aria-hidden="true" />

      {/* Mobile top bar */}
      <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background px-4 md:hidden">
        <button
          onClick={() => setMobileOpen(true)}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
          aria-label={t.nav.openMenu}
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
          "hidden md:flex flex-col bg-gradient-to-b from-zinc-900 to-zinc-950 text-zinc-300 transition-all duration-300",
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

        <NavLinks collapsed={collapsed} pendingCount={pendingCount} />

        <div className={cn("border-t border-zinc-800/60", collapsed ? "px-2 py-3" : "px-3 py-3")}>
          <a
            href="https://github.com/Euzohn/ZFundPilot"
            target="_blank"
            rel="noopener noreferrer"
            className={cn(
              "flex items-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-white",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
            )}
            title={collapsed ? "GitHub" : undefined}
          >
            <Github className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="whitespace-nowrap">GitHub</span>}
          </a>
          <ThemeToggle
            variant="icon"
            label={collapsed ? undefined : t.nav.theme}
            className={cn(
              "mt-1 text-zinc-500 hover:bg-zinc-800 hover:text-white",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
            )}
          />
          <LanguageToggle
            variant="icon"
            label={collapsed ? undefined : t.nav.language}
            className={cn(
              "mt-1 text-zinc-500 hover:bg-zinc-800 hover:text-white",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
            )}
          />
          <button
            onClick={toggle}
            className={cn(
              "mt-1 flex items-center rounded-lg text-zinc-500 transition-colors hover:bg-zinc-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
              collapsed ? "justify-center w-full py-2" : "justify-start w-full gap-2 px-3 py-2 text-xs",
            )}
            title={collapsed ? t.nav.expandSidebar : t.nav.collapseSidebar}
          >
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <><ChevronLeft className="h-4 w-4" /> {t.nav.collapseSidebar}</>}
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
          "fixed inset-y-0 left-0 z-50 flex w-64 flex-col bg-gradient-to-b from-zinc-900 to-zinc-950 text-zinc-300 transition-transform duration-300 md:hidden",
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
            className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
            aria-label={t.nav.closeMenu}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <NavLinks collapsed={false} onNavigate={() => setMobileOpen(false)} pendingCount={pendingCount} />
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
