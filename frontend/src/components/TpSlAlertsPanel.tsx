import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { api } from "@/api/client"
import type { DividendAlert } from "@/api/types"
import { useApi } from "@/lib/useApi"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import { useLang } from "@/i18n/LanguageContext"
import { pct } from "@/lib/format"
import { Bell, CheckCircle2, XCircle, RotateCcw, ChevronDown, ChevronRight } from "lucide-react"
import { toast } from "sonner"

export default function TpSlAlertsPanel() {
  const { t } = useLang()
  const navigate = useNavigate()
  const { data: alerts, loading, error, reload, setData } = useApi<DividendAlert[]>(() => api.getTpSlAlerts(), [])
  const [updating, setUpdating] = useState<number | null>(null)
  const [showProcessed, setShowProcessed] = useState(false)

  const handleConfirm = (alert: DividendAlert) => {
    navigate(`/transactions?code=${alert.fund_code}&action=sell&tp_sl_alert_id=${alert.id}`)
  }

  const handleIgnore = async (id: number) => {
    setUpdating(id)
    const snapshot = alerts
    setData(prev => prev?.map(a => a.id === id ? { ...a, status: "ignored" } as DividendAlert : a) ?? null)
    try {
      await api.updateAlert(id, "ignored")
      toast.success(t.common.saved)
    } catch (e) {
      setData(snapshot)
      toast.error(`${t.common.operationFailed}: ${e}`)
    } finally {
      setUpdating(null)
    }
  }

  const handleReopen = async (id: number) => {
    setUpdating(id)
    const snapshot = alerts
    setData(prev => prev?.map(a => a.id === id ? { ...a, status: "pending" } as DividendAlert : a) ?? null)
    try {
      await api.updateAlert(id, "pending")
      toast.success(t.common.saved)
    } catch (e) {
      setData(snapshot)
      toast.error(`${t.common.operationFailed}: ${e}`)
    } finally {
      setUpdating(null)
    }
  }

  if (loading && !alerts) return <LoadingState size="sm" />
  if (error) return <ErrorState message={error} onRetry={reload} size="sm" />

  const pendingAlerts = alerts?.filter(a => a.status === "pending") ?? []
  const processedAlerts = alerts?.filter(a => a.status !== "pending") ?? []

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="h-5 w-5 text-primary" />
          {t.returns.tpSlAlerts}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {pendingAlerts.length === 0 && processedAlerts.length === 0 ? (
          <EmptyState title={t.returns.noTpSlAlerts} size="sm" />
        ) : (
          <>
            {pendingAlerts.length > 0 && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t.common.name}</TableHead>
                    <TableHead>{t.returns.alertType}</TableHead>
                    <TableHead className="text-right">{t.returns.triggeredReturn}</TableHead>
                    <TableHead className="text-right">{t.returns.threshold}</TableHead>
                    <TableHead className="text-right">{t.common.status}</TableHead>
                    <TableHead className="text-right">{t.common.actions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pendingAlerts.map((alert) => (
                    <TableRow key={alert.id}>
                      <TableCell className="font-medium">{alert.fund_name || alert.fund_code}</TableCell>
                      <TableCell>
                        <Badge variant={alert.alert_type === "take_profit" ? "default" : "destructive"} className="text-[10px]">
                          {alert.alert_type === "take_profit" ? t.returns.takeProfit : t.returns.stopLoss}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{pct(alert.triggered_return)}</TableCell>
                      <TableCell className="text-right tabular-nums">{pct(alert.threshold)}</TableCell>
                      <TableCell className="text-right">
                        <Badge variant="secondary" className="text-[10px]">
                          {t.common.pending}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={() => handleConfirm(alert)}
                            disabled={updating === alert.id}
                          >
                            <CheckCircle2 className="h-4 w-4 text-gain" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0"
                            onClick={() => handleIgnore(alert.id)}
                            disabled={updating === alert.id}
                          >
                            <XCircle className="h-4 w-4 text-loss" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {processedAlerts.length > 0 && (
              <div className="mt-3">
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-between text-xs text-muted-foreground hover:text-foreground"
                  onClick={() => setShowProcessed(!showProcessed)}
                >
                  <span>{t.returns.processedAlerts.replace("{n}", String(processedAlerts.length))}</span>
                  {showProcessed ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                </Button>
                {showProcessed && (
                  <div className="mt-1 space-y-1">
                    {processedAlerts.map((alert) => (
                      <div
                        key={alert.id}
                        className="flex items-center justify-between rounded-md px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent/50"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="truncate max-w-[120px]">{alert.fund_name || alert.fund_code}</span>
                          <Badge variant={alert.alert_type === "take_profit" ? "default" : "destructive"} className="text-[9px]">
                            {alert.alert_type === "take_profit" ? t.returns.takeProfit : t.returns.stopLoss}
                          </Badge>
                          <span>{pct(alert.triggered_return)}</span>
                          <Badge variant="outline" className="text-[9px]">
                            {alert.status === "confirmed" ? t.common.confirmed : t.common.ignored}
                          </Badge>
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-6 px-2 text-[10px] gap-1"
                          onClick={() => handleReopen(alert.id)}
                          disabled={updating === alert.id}
                        >
                          <RotateCcw className="h-3 w-3" />
                          {t.returns.reopen}
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}