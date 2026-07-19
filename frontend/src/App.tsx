import { useState, useEffect } from "react"
import { Routes, Route } from "react-router-dom"
import Layout from "@/components/Layout"
import LogoSplash from "@/components/LogoSplash"
import Overview from "@/pages/Overview"
import Home from "@/pages/Home"
import Transactions from "@/pages/Transactions"
import Positions from "@/pages/Positions"
import FundDetail from "@/pages/FundDetail"
import NavUpdate from "@/pages/NavUpdate"
import Returns from "@/pages/Returns"
import Risk from "@/pages/Risk"
import AIChat from "@/pages/AIChat"
import Settings from "@/pages/Settings"
import FundCompare from "@/pages/FundCompare"
import Login from "@/pages/Login"
import { api } from "@/api/client"
import { getToken } from "@/lib/auth"

export default function App() {
  const [authRequired, setAuthRequired] = useState<boolean | null>(null)

  useEffect(() => {
    api.getAuthStatus().then((s) => setAuthRequired(s.required)).catch(() => setAuthRequired(false))
  }, [])

  if (authRequired === null) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3">
        <LogoSplash className="h-20 w-20" />
        <p className="text-sm font-bold tracking-tight text-slate-700">ZFundPilot</p>
      </div>
    )
  }

  // 需要登录但本地无 token → 展示登录页
  if (authRequired && !getToken()) {
    return <Login onSuccess={() => window.location.reload()} />
  }

  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route element={<Layout />}>
        <Route path="overview" element={<Overview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="positions" element={<Positions />} />
        <Route path="fund/:code" element={<FundDetail />} />
        <Route path="nav" element={<NavUpdate />} />
        <Route path="returns" element={<Returns />} />
        <Route path="risk" element={<Risk />} />
        <Route path="ai" element={<AIChat />} />
        <Route path="compare" element={<FundCompare />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
