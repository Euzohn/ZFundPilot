import { useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money, pct, pnlColor } from "@/lib/format"
import { cn } from "@/lib/utils"
import { TrendingUp, TrendingDown, ChevronRight, ChevronUp, ChevronDown } from "lucide-react"

export default function Positions() {
  const navigate = useNavigate()
  const [showClosed, setShowClosed] = useState(false)
  const [sortField, setSortField] = useState("value")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [closedSortField, setClosedSortField] = useState("realized")
  const [closedSortDir, setClosedSortDir] = useState<"asc" | "desc">("desc")
  const { data: positions, loading } = useApi(() => api.getPositions(true))

  const view = positions ? (showClosed ? positions : positions.filter((p) => p.is_open)) : []

  // 按基金合并（跨渠道）
  const merged: Record<string, { name: string; type: string; sector: string; value: number; cost: number; pnl: number; channels: number }> = {}
  for (const p of view.filter((p) => p.is_open)) {
    const m = merged[p.fund_code] ?? { name: p.fund_name, type: p.fund_type, sector: p.sector, value: 0, cost: 0, pnl: 0, channels: 0 }
    m.value += p.market_value
    m.cost += p.total_cost
    m.pnl += p.unrealized_pnl
    m.channels += 1
    merged[p.fund_code] = m
  }
  const mergedRows = Object.entries(merged).sort((a, b) => b[1].value - a[1].value)

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      setSortDir("desc")
    }
  }

  const sortedRows = useMemo(() => {
    return [...mergedRows].sort(([, a], [, b]) => {
      const getVal = (m: typeof a): number | string => {
        switch (sortField) {
          case "name": return m.name
          case "type": return m.type
          case "sector": return m.sector
          case "value": return m.value
          case "pnl": return m.pnl
          case "return": return m.cost ? m.value / m.cost - 1 : -999
          case "channels": return m.channels
          default: return m.value
        }
      }
      const va = getVal(a)
      const vb = getVal(b)
      const cmp = typeof va === "string" && typeof vb === "string"
        ? va.localeCompare(vb)
        : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [mergedRows, sortField, sortDir])

  function SortHeader({ field, children, className }: { field: string; children: React.ReactNode; className?: string }) {
    const active = sortField === field
    return (
      <TableHead
        className={cn("cursor-pointer select-none", active ? "text-foreground" : "", className)}
        onClick={() => toggleSort(field)}
      >
        <span className="inline-flex items-center gap-1">
          {children}
          {active && (sortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
        </span>
      </TableHead>
    )
  }

  return (
    <div className="space-y-6">
      {loading ? (
        <div className="py-20 text-center text-muted-foreground">加载中...</div>
      ) : !positions ? (
        <div className="py-20 text-center text-red-500">加载失败</div>
      ) : (
      <>
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-xl md:text-2xl font-bold">持仓明细</h1>
        <Button variant="outline" size="sm" onClick={() => setShowClosed(!showClosed)}>
          {showClosed ? "隐藏已清仓" : "显示已清仓"}
        </Button>
      </div>

      {/* 按基金合并视图（主视图，简洁） */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">持仓列表</CardTitle>
        </CardHeader>
        <CardContent>
            {sortedRows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无持仓数据</p>
          ) : (
            <Table>
              <TableHeader>
                  <TableRow>
                    <SortHeader field="name">名称</SortHeader>
                    <SortHeader field="type">类型</SortHeader>
                    <SortHeader field="sector">板块</SortHeader>
                    <SortHeader field="value" className="text-right">市值</SortHeader>
                    <SortHeader field="pnl" className="text-right">浮动盈亏</SortHeader>
                    <SortHeader field="return" className="text-right">收益率</SortHeader>
                    <SortHeader field="channels" className="text-right">渠道</SortHeader>
                    <TableHead className="w-20">操作</TableHead>
                    <TableHead className="w-8"></TableHead>
                  </TableRow>
              </TableHeader>
              <TableBody>
                {sortedRows.map(([code, m]) => {
                  const ret = m.cost ? m.value / m.cost - 1 : null
                  return (
                    <TableRow
                      key={code}
                      className="cursor-pointer"
                      onClick={() => navigate(`/fund/${code}`)}
                    >
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium max-w-[160px] truncate" title={m.name}>{m.name}</span>
                          <span className="font-mono text-xs text-muted-foreground">{code}</span>
                        </div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{m.type}</Badge></TableCell>
                      <TableCell>{m.sector ? <Badge variant="secondary" className="font-normal">{m.sector}</Badge> : <span className="text-xs text-muted-foreground">—</span>}</TableCell>
                      <TableCell className="text-right tabular-nums font-medium">{money(m.value)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(m.pnl)}`}>{money(m.pnl)}</TableCell>
                      <TableCell className={`text-right tabular-nums ${pnlColor(ret)}`}>{pct(ret)}</TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">{m.channels}</TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <div className="flex gap-1">
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs text-gain border-gain/30 hover:bg-gain/5"
                            onClick={() => navigate(`/transactions?code=${code}&action=buy`)}
                          >
                            <TrendingUp className="h-3 w-3" />
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs text-loss border-loss/30 hover:bg-loss/5"
                            onClick={() => navigate(`/transactions?code=${code}&action=sell`)}
                          >
                            <TrendingDown className="h-3 w-3" />
                          </Button>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <ChevronRight className="h-4 w-4" />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
          <p className="mt-3 text-sm text-muted-foreground">共 {sortedRows.length} 只基金 · 点击行查看详情</p>
        </CardContent>
      </Card>

      {/* 已清仓记录（仅在 showClosed 时显示） */}
      {showClosed && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">已清仓记录</CardTitle>
          </CardHeader>
          <CardContent>
            {(() => {
              const openCodes = new Set(positions.filter(p => p.is_open).map(p => p.fund_code))
              const closed = positions.filter((p) => !p.is_open && !openCodes.has(p.fund_code))
              const closedMerged: Record<string, { name: string; realized: number; channels: number }> = {}
              for (const p of closed) {
                const m = closedMerged[p.fund_code] ?? { name: p.fund_name, realized: 0, channels: 0 }
                m.realized += p.realized_pnl
                m.channels += 1
                closedMerged[p.fund_code] = m
              }
              const closedEntries = Object.entries(closedMerged)
              const toggleClosedSort = (field: string) => {
                if (closedSortField === field) setClosedSortDir((d) => (d === "asc" ? "desc" : "asc"))
                else { setClosedSortField(field); setClosedSortDir("desc") }
              }
              const closedSorted = [...closedEntries].sort(([, a], [, b]) => {
                const va = closedSortField === "name" ? a.name : closedSortField === "channels" ? a.channels : a.realized
                const vb = closedSortField === "name" ? b.name : closedSortField === "channels" ? b.channels : b.realized
                const cmp = typeof va === "string" && typeof vb === "string" ? va.localeCompare(vb) : (va as number) - (vb as number)
                return closedSortDir === "asc" ? cmp : -cmp
              })
              function ClosedSortHeader({ field, children, className }: { field: string; children: React.ReactNode; className?: string }) {
                const active = closedSortField === field
                return (
                  <TableHead className={cn("cursor-pointer select-none", active ? "text-foreground" : "", className)} onClick={() => toggleClosedSort(field)}>
                    <span className="inline-flex items-center gap-1">
                      {children}
                      {active && (closedSortDir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
                    </span>
                  </TableHead>
                )
              }
              if (closedSorted.length === 0) return <p className="py-4 text-center text-muted-foreground">无已清仓记录</p>
              return (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <ClosedSortHeader field="name">名称</ClosedSortHeader>
                      <ClosedSortHeader field="realized" className="text-right">已实现盈亏</ClosedSortHeader>
                      <ClosedSortHeader field="channels" className="text-right">渠道数</ClosedSortHeader>
                      <TableHead className="w-8"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {closedSorted.map(([code, m]) => (
                      <TableRow
                        key={code}
                        className="cursor-pointer"
                        onClick={() => navigate(`/fund/${code}`)}
                      >
                        <TableCell>
                          <div className="flex flex-col">
                            <span className="font-medium max-w-[160px] truncate" title={m.name}>{m.name}</span>
                            <span className="font-mono text-xs text-muted-foreground">{code}</span>
                          </div>
                        </TableCell>
                        <TableCell className={`text-right tabular-nums ${pnlColor(m.realized)}`}>{money(m.realized)}</TableCell>
                        <TableCell className="text-right tabular-nums text-muted-foreground">{m.channels}</TableCell>
                        <TableCell className="text-muted-foreground"><ChevronRight className="h-4 w-4" /></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )
            })()}
          </CardContent>
        </Card>
      )}
      </>
      )}
    </div>
  )
}