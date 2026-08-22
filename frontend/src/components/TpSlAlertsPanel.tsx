import { useState } from "react"
import { api } from "@/api/client"
import type { DividendAlert } from "@/api/types"
import { useApi } from "@/lib/useApi"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { useLang } from "@/i18n/LanguageContext"
import { pct } from "@/lib/format"
import { Bell, CheckCircle2, XCircle } from "lucide-react"
import { toast } from "sonner"

export default function TpSlAlertsPanel() {
  const { t } = useLang()
  const { data: alerts, loading, error, reload } = useApi<DividendAlert[]>(() => api.getTpSlAlerts(), [])
  const [updating, setUpdating] = useState<number | null>(null)

  const handleUpdate = async (id: number, status: string) => {
    setUpdating(id)
    try {
      await api.updateAlert(id, status)
      toast.success(t.common.saved)
      reload()
    } catch (e) {
      toast.error(`${t.common.operationFailed}: ${e}`)
    } finally {
      setUpdating(null)
    }
  }

  if (loading) return <LoadingState size="sm" />
  if (error) return <EmptyState title={t.common.loadFailed} size="sm" />

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2 text-base">
          <Bell className="h-5 w-5 text-primary" />
          {t.returns.tpSlAlerts}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {!alerts || alerts.length === 0 ? (
          <EmptyState title={t.returns.noTpSlAlerts} size="sm" />
        ) : (
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
              {alerts.map((alert) => (
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
                    <Badge variant={alert.status === "pending" ? "secondary" : "outline"} className="text-[10px]">
                      {alert.status === "pending" ? t.common.pending : alert.status === "confirmed" ? t.common.confirmed : t.common.ignored}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {alert.status === "pending" && (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0"
                          onClick={() => handleUpdate(alert.id, "confirmed")}
                          disabled={updating === alert.id}
                        >
                          <CheckCircle2 className="h-4 w-4 text-gain" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 w-7 p-0"
                          onClick={() => handleUpdate(alert.id, "ignored")}
                          disabled={updating === alert.id}
                        >
                          <XCircle className="h-4 w-4 text-loss" />
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
