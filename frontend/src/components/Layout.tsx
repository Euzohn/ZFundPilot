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
} from "lucide-react"
import { cn } from "@/lib/utils"
import { clearToken } from "@/lib/auth"

const navItems = [
  { to: "/", label: "组合总览", icon: LayoutDashboard },
  { to: "/transactions", label: "交易管理", icon: ArrowLeftRight },
  { to: "/positions", label: "持仓明细", icon: Briefcase },
  { to: "/nav", label: "净值更新", icon: RefreshCw },
  { to: "/returns", label: "收益分析", icon: TrendingUp },
  { to: "/risk", label: "风险与建议", icon: ShieldCheck },
]

export default function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      {/* Sidebar */}
      <aside className="flex w-60 flex-col bg-slate-900 text-slate-300">
        <div className="flex items-center gap-2 px-6 py-5">
          <Package className="h-7 w-7 text-blue-400" />
          <div>
            <h1 className="text-lg font-bold text-white">ZFundPilot</h1>
            <p className="text-xs text-slate-500">个人基金分析</p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3 py-2">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-white",
                )
              }
            >
              <Icon className="h-5 w-5 shrink-0" />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-800 px-6 py-4 space-y-3">
          <p className="text-xs leading-relaxed text-slate-600">
            仅用于数据分析与风险管理，
            不构成任何投资建议或交易指令。
          </p>
          <button
            onClick={() => { clearToken(); window.location.reload() }}
            className="flex items-center gap-2 text-xs text-slate-500 transition-colors hover:text-red-400"
          >
            <LogOut className="h-3.5 w-3.5" />
            退出登录
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
