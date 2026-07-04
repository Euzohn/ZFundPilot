import { useState } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { FetchResult, LatestNav } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { RefreshCw, CheckCircle2, XCircle } from "lucide-react"
import { navStr } from "@/lib/format"

export default function NavUpdate() {
  const { data: navs, loading, reload } = useApi<LatestNav[]>(() => api.getLatestNavs())
  const [updating, setUpdating] = useState(false)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<FetchResult[] | null>(null)

  const handleUpdate = async () => {
    setUpdating(true)
    setProgress(0)
    setResults(null)
    try {
      // 简单方案：一次性请求，完成后显示结果
      const res = await api.updateNav()
      setResults(res)
      setProgress(100)
      reload()
    } catch (e) {
      alert(`更新失败: ${e}`)
    } finally {
      setUpdating(false)
    }
  }

  const okCount = results?.filter((r) => r.ok).length ?? 0
  const failCount = results?.filter((r) => !r.ok).length ?? 0

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">净值更新</h1>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardContent className="flex items-center justify-between p-6">
            <div>
              <p className="text-sm text-muted-foreground">待更新基金数</p>
              <p className="text-2xl font-bold">{navs?.length ?? 0} 只</p>
            </div>
            <RefreshCw className="h-8 w-8 text-blue-500" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6">
            <p className="text-sm text-muted-foreground">净值最近更新</p>
            <p className="text-2xl font-bold">
              {navs?.length ? navs[0].date : "未更新"}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">批量更新</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            数据源：AkShare 优先，失败自动切换天天基金。首次抓取较慢。
          </p>
          <Button onClick={handleUpdate} disabled={updating} className="w-full">
            <RefreshCw className={`mr-2 h-4 w-4 ${updating ? "animate-spin" : ""}`} />
            {updating ? "更新中..." : "更新全部基金净值"}
          </Button>

          {updating && (
            <div className="space-y-2">
              <Progress value={progress} />
              <p className="text-center text-sm text-muted-foreground">正在拉取净值数据...</p>
            </div>
          )}

          {results && (
            <div className="space-y-2">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 className="h-4 w-4" /> 成功 {okCount} 只
                </span>
                {failCount > 0 && (
                  <span className="flex items-center gap-1 text-red-600">
                    <XCircle className="h-4 w-4" /> 失败 {failCount} 只
                  </span>
                )}
              </div>
              {failCount > 0 && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3">
                  {results.filter((r) => !r.ok).map((r) => (
                    <p key={r.fund_code} className="text-sm text-red-700">
                      {r.fund_code}：{r.message}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">各基金最新净值</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">加载中...</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>代码</TableHead>
                  <TableHead>最新日期</TableHead>
                  <TableHead className="text-right">最新净值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {navs?.map((n) => (
                  <TableRow key={n.fund_code}>
                    <TableCell className="font-mono text-xs">{n.fund_code}</TableCell>
                    <TableCell>{n.date}</TableCell>
                    <TableCell className="text-right font-mono">{navStr(n.nav)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
