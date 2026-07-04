import { useState } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, navStr, pnlColor } from "@/lib/format"
import { ChevronDown, ChevronRight } from "lucide-react"

export default function Positions() {
  const [showClosed, setShowClosed] = useState(false)
  const { data: positions, loading, reload } = useApi(() => api.getPositions(true))

  if (loading) return <div className="py-20 text-center text-muted-foreground">加载中...</div>
  if (!positions) return <div className="py-20 text-center text-red-500">加载失败</div>

  const view = showClosed ? positions : positions.filter((p) => p.is_open)

  const merged: Record<string, { name: string; value: number; cost: number; pnl: number; channels: number }> = {}
  for (const p of view.filter((p) => p.is_open)) {
    const m = merged[p.fund_code] ?? { name: p.fund_name, value: 0, cost: 0, pnl: 0, channels: 0 }
    m.value += p.market_value
    m.cost += p.total_cost
    m.pnl += p.unrealized_pnl
    m.channels += 1
    merged[p.fund_code] = m
  }
  const mergedRows = Object.entries(merged).sort((a, b) => b[1].value - a[1].value)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">持仓明细</h1>
        <Button variant="outline" size="sm" onClick={() => setShowClosed(!showClosed)}>
          {showClosed ? "隐藏已清仓" : "显示已清仓"}
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">按基金 + 渠道拆分</CardTitle>
        </CardHeader>
        <CardContent>
          {view.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无持仓数据</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead>渠道</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead className="text-right">份额</TableHead>
                  <TableHead className="text-right">成本</TableHead>
                  <TableHead className="text-right">均价</TableHead>
                  <TableHead className="text-right">最新净值</TableHead>
                  <TableHead className="text-right">市值</TableHead>
                  <TableHead className="text-right">浮动盈亏</TableHead>
                  <TableHead className="text-right">收益率</TableHead>
                  <TableHead className="text-right">已实现</TableHead>
                  <TableHead className="text-right">占比</TableHead>
                  <TableHead>状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {view.map((p) => (
                  <TableRow key={`${p.fund_code}-${p.channel}`}>
                    <TableCell className="font-mono text-xs">{p.fund_code}</TableCell>
                    <TableCell className="font-medium">{p.fund_name}</TableCell>
                    <TableCell>{p.channel || "未标注"}</TableCell>
                    <TableCell>{p.fund_type}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.held_shares.toFixed(2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.total_cost)}</TableCell>
                    <TableCell className="text-right tabular-nums">{navStr(p.avg_cost_nav)}</TableCell>
                    <TableCell className="text-right tabular-nums">{navStr(p.latest_nav)}</TableCell>
                    <TableCell className="text-right tabular-nums">{money(p.market_value)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.unrealized_pnl)}`}>{money(p.unrealized_pnl)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.return_rate)}`}>{pct(p.return_rate)}</TableCell>
                    <TableCell className={`text-right tabular-nums ${pnlColor(p.realized_pnl)}`}>{money(p.realized_pnl)}</TableCell>
                    <TableCell className="text-right tabular-nums">{p.is_open ? pct(p.weight) : "—"}</TableCell>
                    <TableCell>
                      <Badge variant={p.is_open ? "success" : "secondary"}>
                        {p.is_open ? "持有" : "已清仓"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <p className="mt-3 text-sm text-muted-foreground">共 {view.length} 个持仓</p>
        </CardContent>
      </Card>

      {mergedRows.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">按基金合并（跨渠道）</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead className="text-right">市值</TableHead>
                  <TableHead className="text-right">成本</TableHead>
                  <TableHead className="text-right">浮动盈亏</TableHead>
                  <TableHead className="text-right">收益率</TableHead>
                  <TableHead className="text-right">渠道数</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mergedRows.map(([code, m]) => (
                  <TableRow key={code}>
                    <TableCell className="font-mono text-xs">{code}</TableCell>
                    <TableCell className="font-medium">{m.name}</TableCell>
                    <TableCell className="text-right">{money(m.value)}</TableCell>
                    <TableCell className="text-right">{money(m.cost)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(m.pnl)}`}>{money(m.pnl)}</TableCell>
                    <TableCell className={`text-right ${pnlColor(m.value / m.cost - 1)}`}>
                      {pct(m.cost ? m.value / m.cost - 1 : null)}
                    </TableCell>
                    <TableCell className="text-right">{m.channels}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
