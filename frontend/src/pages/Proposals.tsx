import { useCallback, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type {
  OperationProposal,
  ProposalActionResult,
  ProposalStatus,
} from "@/api/types"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge, type BadgeProps } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import ErrorState from "@/components/ErrorState"
import ConfirmDialog from "@/components/ConfirmDialog"
import { AlertTriangle, Check, Inbox, RefreshCw, X } from "lucide-react"
import { useLang } from "@/i18n/LanguageContext"
import { money, navStr } from "@/lib/format"
import { toast } from "sonner"
import { cn } from "@/lib/utils"

const STATUS_FILTERS: Array<ProposalStatus | ""> = [
  "",
  "pending",
  "succeeded",
  "failed",
  "conflict",
  "rejected",
  "cancelled",
  "expired",
]

function formatDateTime(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}

function statusVariant(status: ProposalStatus): BadgeProps["variant"] {
  switch (status) {
    case "pending":
      return "warning"
    case "succeeded":
      return "success"
    case "rejected":
    case "cancelled":
      return "secondary"
    case "expired":
      return "outline"
    default:
      return "destructive"
  }
}

export default function Proposals() {
  const { t } = useLang()
  const [status, setStatus] = useState<ProposalStatus | "">("")
  const [detail, setDetail] = useState<OperationProposal | null>(null)
  const [approveTarget, setApproveTarget] = useState<OperationProposal | null>(null)
  const [rejectTarget, setRejectTarget] = useState<OperationProposal | null>(null)
  const [rejectReason, setRejectReason] = useState("")
  const [busy, setBusy] = useState(false)

  const fetcher = useCallback(
    () => api.getProposals(status || undefined),
    [status],
  )
  const { data, loading, error, reload } = useApi(fetcher)

  const statusLabels = useMemo<Record<ProposalStatus, string>>(
    () => ({
      pending: t.proposals.statusPending,
      succeeded: t.proposals.statusSucceeded,
      failed: t.proposals.statusFailed,
      conflict: t.proposals.statusConflict,
      rejected: t.proposals.statusRejected,
      cancelled: t.proposals.statusCancelled,
      expired: t.proposals.statusExpired,
    }),
    [t],
  )

  const filterLabels = useMemo<Record<string, string>>(
    () => ({ "": t.proposals.filterAll, ...statusLabels }),
    [statusLabels, t],
  )

  const finish = (result: ProposalActionResult, message: string) => {
    if (detail?.proposal_id === result.proposal_id) setDetail(result)
    toast.success(message)
    reload()
  }

  const doApprove = async () => {
    if (!approveTarget) return
    setBusy(true)
    try {
      const result = await api.approveProposal(approveTarget.proposal_id)
      finish(result, t.proposals.approveDone)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.proposals.actionFailed)
    } finally {
      setBusy(false)
      setApproveTarget(null)
    }
  }

  const doReject = async () => {
    if (!rejectTarget) return
    setBusy(true)
    try {
      const result = await api.rejectProposal(
        rejectTarget.proposal_id,
        rejectReason.trim(),
      )
      finish(result, t.proposals.rejectDone)
      setRejectTarget(null)
      setRejectReason("")
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.proposals.actionFailed)
    } finally {
      setBusy(false)
    }
  }

  const items = data?.items ?? []
  const pendingCount = data?.pending_count ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        title={t.proposals.title}
        subtitle={t.proposals.subtitle}
        icon={<Inbox className="h-6 w-6" />}
        actions={
          <Button variant="outline" size="sm" onClick={() => reload()} disabled={loading}>
            <RefreshCw className={cn("mr-1.5 h-4 w-4", loading && "animate-spin")} />
            {t.common.refresh}
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardContent className="flex items-center justify-between p-4">
            <span className="text-sm text-muted-foreground">{t.proposals.pendingCount}</span>
            <span className="text-2xl font-semibold tabular-nums">{pendingCount}</span>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between p-4">
            <span className="text-sm text-muted-foreground">{t.proposals.totalCount}</span>
            <span className="text-2xl font-semibold tabular-nums">{data?.total ?? 0}</span>
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((value) => (
          <Button
            key={value || "all"}
            size="sm"
            variant={status === value ? "default" : "outline"}
            onClick={() => setStatus(value)}
          >
            {filterLabels[value]}
          </Button>
        ))}
      </div>

      <Card>
        <CardContent className="p-0">
          {loading && !data ? (
            <LoadingState size="md" />
          ) : error ? (
            <ErrorState message={error} onRetry={reload} size="md" />
          ) : items.length === 0 ? (
            <EmptyState
              title={t.proposals.empty}
              description={t.proposals.emptyHint}
              icon={Inbox}
            />
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t.proposals.colId}</TableHead>
                    <TableHead>{t.proposals.colOperation}</TableHead>
                    <TableHead>{t.proposals.colFund}</TableHead>
                    <TableHead className="hidden md:table-cell">{t.proposals.colAction}</TableHead>
                    <TableHead className="hidden md:table-cell">{t.proposals.colDate}</TableHead>
                    <TableHead className="text-right">{t.proposals.colAmount}</TableHead>
                    <TableHead>{t.proposals.colStatus}</TableHead>
                    <TableHead className="hidden lg:table-cell">{t.proposals.colCreated}</TableHead>
                    <TableHead className="text-right">{t.proposals.colActions}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.proposal_id}>
                      <TableCell className="tabular-nums text-muted-foreground">
                        #{item.proposal_id}
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        {item.operation_label}
                      </TableCell>
                      <TableCell>
                        <div className="font-medium">{item.summary.fund_name}</div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {item.summary.fund_code}
                        </div>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {item.summary.action_label}
                      </TableCell>
                      <TableCell className="hidden md:table-cell tabular-nums">
                        {item.summary.date}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {money(item.summary.amount)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(item.status)}>
                          {statusLabels[item.status]}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                        {formatDateTime(item.created_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setDetail(item)}
                          >
                            {t.proposals.view}
                          </Button>
                          {item.can_approve && (
                            <>
                              <Button
                                size="sm"
                                onClick={() => setApproveTarget(item)}
                              >
                                <Check className="mr-1 h-3.5 w-3.5" />
                                {t.proposals.approve}
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => {
                                  setRejectReason("")
                                  setRejectTarget(item)
                                }}
                              >
                                <X className="mr-1 h-3.5 w-3.5" />
                                {t.proposals.reject}
                              </Button>
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 详情 */}
      <Dialog open={detail !== null} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {t.proposals.detailTitle} #{detail.proposal_id}
                </DialogTitle>
                <DialogDescription>{detail.summary.title}</DialogDescription>
              </DialogHeader>

              <div className="space-y-4 text-sm">
                <div className="flex items-center gap-2">
                  <Badge variant={statusVariant(detail.status)}>
                    {statusLabels[detail.status]}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {detail.operation_label}
                  </span>
                </div>

                {detail.summary.warnings.length > 0 && (
                  <div className="rounded-md border border-warning/40 bg-warning/10 p-3">
                    <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
                      <AlertTriangle className="h-3.5 w-3.5" />
                      {t.proposals.detailWarnings}
                    </p>
                    <ul className="mt-1.5 space-y-1 text-xs text-muted-foreground">
                      {detail.summary.warnings.map((warning) => (
                        <li key={warning}>· {warning}</li>
                      ))}
                    </ul>
                  </div>
                )}

                <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                  <DetailRow label={t.proposals.colFund}>
                    {detail.summary.fund_name}
                    <span className="ml-1 font-mono text-xs text-muted-foreground">
                      {detail.summary.fund_code}
                    </span>
                  </DetailRow>
                  <DetailRow label={t.proposals.colAction}>
                    {detail.summary.action_label}
                  </DetailRow>
                  <DetailRow label={t.proposals.colDate}>{detail.summary.date}</DetailRow>
                  <DetailRow label={t.proposals.colAmount}>
                    {money(detail.summary.amount)}
                  </DetailRow>
                  <DetailRow label={t.proposals.shares}>
                    {detail.summary.shares ?? "—"}
                  </DetailRow>
                  <DetailRow label={t.proposals.nav}>
                    {navStr(detail.summary.nav)}
                  </DetailRow>
                  <DetailRow label={t.proposals.fee}>{money(detail.summary.fee)}</DetailRow>
                  <DetailRow label={t.proposals.channel}>
                    {detail.summary.channel || "—"}
                  </DetailRow>
                  <DetailRow label={t.proposals.isT1}>
                    {detail.summary.is_t1 ? t.proposals.t1Yes : t.proposals.t1No}
                  </DetailRow>
                  <DetailRow label={t.proposals.expiresAt}>
                    {formatDateTime(detail.expires_at)}
                  </DetailRow>
                  {detail.summary.note && (
                    <DetailRow label={t.proposals.note} className="col-span-2">
                      {detail.summary.note}
                    </DetailRow>
                  )}
                  <DetailRow label={t.proposals.colCreated} className="col-span-2">
                    {formatDateTime(detail.created_at)}
                  </DetailRow>
                </dl>

                {(detail.reviewed_by || detail.reviewed_at) && (
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                      {t.proposals.detailReview}
                    </p>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                      <DetailRow label={t.proposals.reviewedBy}>
                        {detail.reviewed_by || "—"}
                      </DetailRow>
                      <DetailRow label={t.proposals.reviewedAt}>
                        {formatDateTime(detail.reviewed_at)}
                      </DetailRow>
                      {detail.rejection_reason && (
                        <DetailRow label={t.proposals.rejectionReason} className="col-span-2">
                          {detail.rejection_reason}
                        </DetailRow>
                      )}
                    </dl>
                  </div>
                )}

                {detail.execution_result && (
                  <div>
                    <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                      {t.proposals.detailExecution}
                    </p>
                    {detail.execution_result.ok ? (
                      <p className="text-xs">
                        {t.proposals.txId}: {detail.execution_result.tx_id}
                      </p>
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {detail.execution_result.message || detail.execution_result.reason}
                      </p>
                    )}
                  </div>
                )}

                <details className="rounded-md border p-3">
                  <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
                    {t.proposals.detailParams}
                  </summary>
                  <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all text-[11px] text-muted-foreground">
                    {JSON.stringify(detail.params, null, 2)}
                  </pre>
                </details>
              </div>

              {detail.can_approve && (
                <DialogFooter>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setRejectReason("")
                      setRejectTarget(detail)
                    }}
                  >
                    {t.proposals.reject}
                  </Button>
                  <Button onClick={() => setApproveTarget(detail)}>
                    {t.proposals.approve}
                  </Button>
                </DialogFooter>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* 批准确认 */}
      <ConfirmDialog
        open={approveTarget !== null}
        onOpenChange={(open) => !open && setApproveTarget(null)}
        title={t.proposals.approveTitle}
        description={
          approveTarget ? (
            <div className="space-y-1">
              <p>
                {approveTarget.summary.title} · {money(approveTarget.summary.amount)} ·{" "}
                {approveTarget.summary.date}
              </p>
              <p>{t.proposals.approveDesc}</p>
            </div>
          ) : undefined
        }
        confirmText={t.proposals.approve}
        onConfirm={doApprove}
        loading={busy}
      />

      {/* 拒绝 */}
      <Dialog
        open={rejectTarget !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRejectTarget(null)
            setRejectReason("")
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.proposals.rejectTitle}</DialogTitle>
            <DialogDescription>{t.proposals.rejectDesc}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">
              {t.proposals.rejectReason}
            </label>
            <textarea
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              placeholder={t.proposals.rejectReasonPlaceholder}
              maxLength={500}
              rows={3}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRejectTarget(null)}
              disabled={busy}
            >
              {t.common.cancel}
            </Button>
            <Button variant="destructive" onClick={doReject} disabled={busy}>
              {busy ? t.common.processing : t.proposals.reject}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function DetailRow({
  label,
  className,
  children,
}: {
  label: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={className}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  )
}