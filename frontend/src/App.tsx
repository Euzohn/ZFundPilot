import { Routes, Route } from "react-router-dom"
import Layout from "@/components/Layout"
import Overview from "@/pages/Overview"
import Transactions from "@/pages/Transactions"
import Positions from "@/pages/Positions"
import NavUpdate from "@/pages/NavUpdate"
import Returns from "@/pages/Returns"
import Risk from "@/pages/Risk"

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="transactions" element={<Transactions />} />
        <Route path="positions" element={<Positions />} />
        <Route path="nav" element={<NavUpdate />} />
        <Route path="returns" element={<Returns />} />
        <Route path="risk" element={<Risk />} />
      </Route>
    </Routes>
  )
}
