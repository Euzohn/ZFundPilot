import { Fragment, useCallback, useMemo, useState } from "react"
import type { ReactNode } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type {
  OperationProposal,
  PlanSnapshot,
  ProposalActionResult,
  ProposalStatus,
  ProposalSummary,
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
import { actionLabel } from "@/lib/actionLabels"
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

function isBatchSummary(summary: ProposalSummary): boolean {
  return summary.operation_type === "batch_import"
}

const PLAN_OPERATIONS = new Set([
  "create_plan",
  "update_plan",
  "toggle_plan",
  "delete_plan",
])

function isPlanSummary(summary: ProposalSummary): boolean {
  return PLAN_OPERATIONS.has(summary.operation_type)
}

function isAlertSummary(summary: ProposalSummary): boolean {
  return summary.operation_type === "resolve_alert"
}

function batchActionsText(summary: ProposalSummary): string {
  const entries = Object.entries(summary.actions ?? {})
  if (entries.length === 0) return "—"
  return entries.map(([action, count]) => `${actionLabel(action)}×${count}`).join(" ")
}

function batchDateRange(summary: ProposalSummary): string {
  const range = summary.date_range
  if (!range?.from && !range?.to) return "—"
  if (!range?.from || range.from === range.to) return range.from || range.to
  return `${range.from} ~ ${range.to}`
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
  const { data, loading, error, reload } = useApi(fetcher, [status])

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

  const notifyChanged = () => {
    window.dispatchEvent(new Event("zfund:proposals-changed"))
  }

  const finish = (result: ProposalActionResult, message: string) => {
    if (detail?.proposal_id === result.proposal_id) setDetail(result)
    toast.success(message)
    reload()
    notifyChanged()
  }

  const doApprove = async () => {
    if (!approveTarget) return
    setBusy(true)
    try {
      const result = await api.approveProposal(approveTarget.proposal_id)
      finish(
        result,
        isAlertSummary(approveTarget.summary)
          ? t.proposals.approveDoneAlert
          : t.proposals.approveDone,
      )
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.proposals.actionFailed)
      reload()
      notifyChanged()
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
      reload()
      notifyChanged()
    } finally {
      setBusy(false)
    }
  }

  const openDetail = async (proposalId: number) => {
    try {
      setDetail(await api.getProposal(proposalId))
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t.proposals.loadFailed)
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
                        {isBatchSummary(item.summary) ? (
                          <>
                            <div className="font-medium">
                              {item.summary.count ?? 0} {t.proposals.batchItems}
                            </div>
                            <div className="font-mono text-xs text-muted-foreground">
                              {batchDateRange(item.summary)}
                            </div>
                          </>
                        ) : (
                          <>
                            <div className="font-medium">{item.summary.fund_name}</div>
                            <div className="font-mono text-xs text-muted-foreground">
                              {item.summary.fund_code}
                            </div>
                          </>
                        )}
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {isBatchSummary(item.summary)
                          ? batchActionsText(item.summary)
                          : isPlanSummary(item.summary)
                            ? item.summary.schedule ?? item.summary.cadence_label ?? "—"
                            : isAlertSummary(item.summary)
                              ? item.summary.alert_type_label ?? "—"
                              : item.summary.action_label}
                      </TableCell>
                      <TableCell className="hidden md:table-cell tabular-nums">
                        {isBatchSummary(item.summary)
                          ? batchDateRange(item.summary)
                          : isPlanSummary(item.summary)
                            ? item.summary.next_run ?? "—"
                            : isAlertSummary(item.summary)
                              ? item.summary.record_date ?? item.summary.ex_date ?? "—"
                              : item.summary.date}
                      </TableCell>
                      <TableCell className="text-right tabular-nums">
                        {money(
                          isBatchSummary(item.summary)
                            ? item.summary.amount_total
                            : isAlertSummary(item.summary)
                              ? item.summary.estimated_amount ?? null
                              : item.summary.amount,
                        )}
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
                            onClick={() => openDetail(item.proposal_id)}
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

                {(detail.summary.warnings?.length ?? 0) > 0 && (
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

                {isBatchSummary(detail.summary) ? (
                  <BatchSection summary={detail.summary} />
                ) : isPlanSummary(detail.summary) ? (
                  <PlanSection summary={detail.summary} />
                ) : isAlertSummary(detail.summary) ? (
                  <AlertSection summary={detail.summary} />
                ) : (
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
                )}

                {/* F1：update/delete 的前后差异展示 */}
                <DiffSection summary={detail.summary} />

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
                      detail.execution_result.tx_ids ? (
                        <p className="text-xs">
                          {t.proposals.batchWritten.replace(
                            "{count}",
                            String(detail.execution_result.count ?? detail.execution_result.tx_ids.length),
                          )}
                          {" · "}
                          {t.proposals.txId}: {detail.execution_result.tx_ids.join(", ")}
                        </p>
                      ) : detail.execution_result.plan_id !== undefined ? (
                        <div className="space-y-1">
                          <p className="text-xs">
                            {t.proposals.planId}: #{detail.execution_result.plan_id}
                            {detail.execution_result.enabled !== undefined && (
                              <>
                                {" · "}
                                {detail.execution_result.enabled
                                  ? t.proposals.planStateEnabled
                                  : t.proposals.planStateDisabled}
                              </>
                            )}
                          </p>
                          {(detail.execution_result.warnings ?? []).map((w) => (
                            <p key={w} className="text-xs text-warning">
                              {w}
                            </p>
                          ))}
                        </div>
                      ) : (
                        <p className="text-xs">
                          {t.proposals.txId}: {detail.execution_result.tx_id}
                        </p>
                      )
                    ) : (
                      <p className="text-xs text-muted-foreground">
                        {detail.execution_result.message || detail.execution_result.reason}
                        {detail.execution_result.executed_before_failure !== undefined && (
                          <> · {t.proposals.batchRolledBack}</>
                        )}
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
              {isBatchSummary(approveTarget.summary) ? (
                <>
                  <p>
                    {approveTarget.summary.title} ·{" "}
                    {money(approveTarget.summary.amount_total)} ·{" "}
                    {batchDateRange(approveTarget.summary)}
                  </p>
                  <p>{t.proposals.batchApproveHint}</p>
                </>
              ) : isPlanSummary(approveTarget.summary) ? (
                <>
                  <p>
                    {approveTarget.summary.title} ·{" "}
                    {money(approveTarget.summary.amount)} ·{" "}
                    {approveTarget.summary.schedule ?? approveTarget.summary.cadence_label ?? "—"}
                  </p>
                  {approveTarget.summary.scheduler_hint && (
                    <p className="text-xs text-muted-foreground">
                      {approveTarget.summary.scheduler_hint}
                    </p>
                  )}
                </>
              ) : isAlertSummary(approveTarget.summary) ? (
                <>
                  <p>
                    {approveTarget.summary.title} ·{" "}
                    {approveTarget.summary.fund_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {approveTarget.summary.alert_type_label} ·{" "}
                    {approveTarget.summary.before_status} →{" "}
                    {approveTarget.summary.after_status}
                  </p>
                </>
              ) : (
                <p>
                  {approveTarget.summary.title} · {money(approveTarget.summary.amount)} ·{" "}
                  {approveTarget.summary.date}
                </p>
              )}
              <p>
                {isAlertSummary(approveTarget.summary)
                  ? t.proposals.approveDescAlert
                  : t.proposals.approveDesc}
              </p>
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

const DIFF_FIELD_LABELS: Record<string, (t: { proposals: Record<string, string> }) => string> = {
  fund_code: (t) => t.proposals.colFund,
  action: (t) => t.proposals.colAction,
  date: (t) => t.proposals.colDate,
  amount: (t) => t.proposals.colAmount,
  shares: (t) => t.proposals.shares,
  nav: (t) => t.proposals.nav,
  fee: (t) => t.proposals.fee,
  channel: (t) => t.proposals.channel,
  is_t1: (t) => t.proposals.isT1,
  note: (t) => t.proposals.note,
}

function formatField(field: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—"
  if (field === "is_t1") return value ? "是/Yes" : "否/No"
  if (typeof value === "number") {
    if (field === "amount" || field === "fee") return money(value)
    if (field === "nav" || field === "shares") return navStr(value)
    return String(value)
  }
  return String(value)
}

function DiffSection({ summary }: { summary: ProposalSummary }) {
  const { t } = useLang()
  if (summary.operation_type === "update_transaction") {
    const before = summary.before
    const after = summary.after
    const changed = summary.changed_fields ?? []
    if (!before || !after || changed.length === 0) return null
    return (
      <div className="rounded-md border border-border p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {t.proposals.changedFields}：{changed.join("、")}
        </p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <span className="font-medium text-muted-foreground">{t.proposals.diffBefore}</span>
          <span className="font-medium text-muted-foreground">{t.proposals.diffAfter}</span>
          {changed.map((field) => {
            const beforeVal = (before as unknown as Record<string, unknown>)[field]
            const afterVal = (after as unknown as Record<string, unknown>)[field]
            const label = DIFF_FIELD_LABELS[field]?.(t) ?? field
            return (
              <Fragment key={field}>
                <div>
                  <span className="text-muted-foreground">{label}：</span>
                  <span className="line-through text-muted-foreground">{formatField(field, beforeVal)}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">{label}：</span>
                  <span className="font-medium">{formatField(field, afterVal)}</span>
                </div>
              </Fragment>
            )
          })}
        </div>
      </div>
    )
  }
  if (summary.operation_type === "delete_transaction" && summary.before) {
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3">
        <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
          <AlertTriangle className="h-3.5 w-3.5" />
          {t.proposals.diffWillDelete} · {t.proposals.txId} #{summary.tx_id}
        </p>
        {summary.reason && (
          <p className="mt-1 text-xs text-muted-foreground">
            {t.proposals.deleteReason}：{summary.reason}
          </p>
        )}
      </div>
    )
  }
  if (summary.operation_type === "add_conversion" && summary.conversion) {
    const from = summary.conversion.from
    const to = summary.conversion.to
    return (
      <div className="rounded-md border border-border p-3">
        <p className="mb-2 text-xs font-medium text-muted-foreground">
          {t.proposals.conversionFrom} → {t.proposals.conversionTo}
        </p>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <div>
            <span className="font-medium text-muted-foreground">{t.proposals.conversionLegFrom}：</span>
            <span>{from.fund_code}{from.action_label ? ` (${from.action_label})` : ""}</span>
          </div>
          <div>
            <span className="font-medium text-muted-foreground">{t.proposals.conversionLegTo}：</span>
            <span>{to.fund_code}{to.action_label ? ` (${to.action_label})` : ""}</span>
          </div>
          <div><span className="text-muted-foreground">{t.proposals.shares}：</span>{formatField("shares", from.shares)}</div>
          <div><span className="text-muted-foreground">{t.proposals.colAmount}：</span>{formatField("amount", to.amount)}</div>
          <div><span className="text-muted-foreground">{t.proposals.nav}：</span>{formatField("nav", from.nav)}</div>
          <div><span className="text-muted-foreground">{t.proposals.nav}：</span>{formatField("nav", to.nav)}</div>
        </div>
      </div>
    )
  }
  if (summary.operation_type === "delete_conversion" && summary.conversion) {
    const from = summary.conversion.from
    const to = summary.conversion.to
    return (
      <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3">
        <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
          <AlertTriangle className="h-3.5 w-3.5" />
          {t.proposals.deleteConversion}
        </p>
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
          <div><span className="text-muted-foreground">{t.proposals.conversionLegFrom}：</span>{from.fund_code}</div>
          <div><span className="text-muted-foreground">{t.proposals.conversionLegTo}：</span>{to.fund_code}</div>
          <div><span className="text-muted-foreground">{t.proposals.shares}：</span>{formatField("shares", from.shares)}</div>
          <div><span className="text-muted-foreground">{t.proposals.colAmount}：</span>{formatField("amount", to.amount)}</div>
        </div>
        {summary.reason && (
          <p className="mt-1 text-xs text-muted-foreground">
            {t.proposals.deleteReason}：{summary.reason}
          </p>
        )}
      </div>
    )
  }
  return null
}

function BatchSection({ summary }: { summary: ProposalSummary }) {
  const { t } = useLang()
  const items = summary.items ?? []
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        <DetailRow label={t.proposals.batchItems}>
          {summary.count ?? items.length}
        </DetailRow>
        <DetailRow label={t.proposals.colAmount}>
          {money(summary.amount_total)}
        </DetailRow>
        <DetailRow label={t.proposals.batchActions}>
          {batchActionsText(summary)}
        </DetailRow>
        <DetailRow label={t.proposals.colDate}>
          {batchDateRange(summary)}
        </DetailRow>
        <DetailRow label={t.proposals.batchFunds} className="col-span-2">
          {(summary.funds ?? []).length > 0
            ? (summary.funds ?? [])
                .map((f) => `${f.fund_name || f.fund_code}(${f.fund_code})`)
                .join("、")
            : "—"}
        </DetailRow>
        {summary.note && (
          <DetailRow label={t.proposals.note} className="col-span-2">
            {summary.note}
          </DetailRow>
        )}
      </dl>
      <div className="rounded-md border border-border">
        <div className="max-h-72 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>#</TableHead>
                <TableHead>{t.proposals.colFund}</TableHead>
                <TableHead>{t.proposals.colAction}</TableHead>
                <TableHead className="hidden sm:table-cell">{t.proposals.colDate}</TableHead>
                <TableHead className="text-right">{t.proposals.colAmount}</TableHead>
                <TableHead className="text-right">{t.proposals.shares}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item, idx) => (
                <TableRow key={`${item.fund_code}-${idx}`}>
                  <TableCell className="tabular-nums text-muted-foreground">
                    {idx + 1}
                  </TableCell>
                  <TableCell>
                    <div className="text-xs font-medium">{item.fund_name || item.fund_code}</div>
                    <div className="font-mono text-[11px] text-muted-foreground">
                      {item.fund_code}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">{item.action_label || actionLabel(item.action)}</TableCell>
                  <TableCell className="hidden sm:table-cell text-xs tabular-nums">
                    {item.date}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {money(item.amount)}
                  </TableCell>
                  <TableCell className="text-right text-xs tabular-nums">
                    {item.shares ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  )
}

const PLAN_CADENCE_LABELS: Record<string, (t: {
  transactions: { daily: string; weekly: string; biweekly: string; monthly: string }
}) => string> = {
  daily: (t) => t.transactions.daily,
  week: (t) => t.transactions.weekly,
  biweek: (t) => t.transactions.biweekly,
  month: (t) => t.transactions.monthly,
}

function planFieldLabel(field: string, t: {
  proposals: { colFund: string; colAmount: string; channel: string; note: string; planCadence: string; planDayOfWeek: string; planDayOfMonth: string }
  transactions: { daily: string; weekly: string; biweekly: string; monthly: string }
}): string {
  switch (field) {
    case "fund_code": return t.proposals.colFund
    case "amount": return t.proposals.colAmount
    case "cadence": return t.proposals.planCadence
    case "day_of_week": return t.proposals.planDayOfWeek
    case "day_of_month": return t.proposals.planDayOfMonth
    case "channel": return t.proposals.channel
    case "note": return t.proposals.note
    default: return field
  }
}

function formatPlanField(field: string, value: unknown, t: {
  transactions: { daily: string; weekly: string; biweekly: string; monthly: string; weekdays: string[] }
}): string {
  if (value === null || value === undefined || value === "") return "—"
  if (field === "amount" && typeof value === "number") return money(value)
  if (field === "cadence" && typeof value === "string") {
    return PLAN_CADENCE_LABELS[value]?.(t) ?? value
  }
  if (field === "day_of_week" && typeof value === "number") {
    const weekdays = t.transactions.weekdays
    return weekdays ? weekdays[value] ?? String(value) : String(value)
  }
  return String(value)
}

function AlertSection({ summary }: { summary: ProposalSummary }) {
  const { t } = useLang()
  const statusLabel = (value: string | null | undefined) => {
    if (value === "confirmed") return t.proposals.alertStatusConfirmed
    if (value === "ignored") return t.proposals.alertStatusIgnored
    if (value === "pending") return t.proposals.alertStatusPending
    return value || "—"
  }
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        <DetailRow label={t.proposals.colFund}>
          {summary.fund_name}
          <span className="ml-1 font-mono text-xs text-muted-foreground">
            {summary.fund_code}
          </span>
        </DetailRow>
        <DetailRow label={t.proposals.alertType}>
          {summary.alert_type_label || "—"}
        </DetailRow>
        <DetailRow label={t.proposals.alertStatus}>
          <span className="line-through text-muted-foreground">
            {statusLabel(summary.before_status)}
          </span>
          {" → "}
          <span className="font-medium">{statusLabel(summary.after_status)}</span>
        </DetailRow>
        <DetailRow label={t.proposals.alertLinkedTx}>
          {summary.linked_tx_id ? `#${summary.linked_tx_id}` : "—"}
        </DetailRow>
        <DetailRow label={t.proposals.alertRecordDate}>
          {summary.record_date || "—"}
        </DetailRow>
        <DetailRow label={t.proposals.alertExDate}>
          {summary.ex_date || "—"}
        </DetailRow>
        {summary.alert_type === "dividend" ? (
          <>
            <DetailRow label={t.proposals.alertPayDate}>
              {summary.pay_date || "—"}
            </DetailRow>
            <DetailRow label={t.proposals.alertPerShare}>
              {summary.per_share ?? "—"}
            </DetailRow>
            <DetailRow label={t.proposals.alertHeldShares}>
              {summary.held_shares ?? "—"}
            </DetailRow>
            <DetailRow label={t.proposals.alertEstimatedAmount}>
              {money(summary.estimated_amount)}
            </DetailRow>
          </>
        ) : (
          <>
            <DetailRow label={t.proposals.alertTriggeredReturn}>
              {summary.triggered_return ?? "—"}
            </DetailRow>
            <DetailRow label={t.proposals.alertThreshold}>
              {summary.threshold ?? "—"}
            </DetailRow>
          </>
        )}
      </dl>
      <p className="rounded-md border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
        {t.proposals.alertNoLedgerHint}
      </p>
    </div>
  )
}

function PlanSection({ summary }: { summary: ProposalSummary }) {
  const { t } = useLang()
  const op = summary.operation_type
  const enabledText = (v: boolean | undefined) =>
    v ? t.proposals.planStateEnabled : t.proposals.planStateDisabled
  const before = summary.before as PlanSnapshot | undefined
  const after = summary.after as PlanSnapshot | undefined
  const changed = summary.changed_fields ?? []
  return (
    <div className="space-y-3">
      {op === "delete_plan" && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
            <AlertTriangle className="h-3.5 w-3.5" />
            {t.proposals.planDeleteWarn}
          </p>
        </div>
      )}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        <DetailRow label={t.proposals.colFund}>
          {summary.fund_name}
          <span className="ml-1 font-mono text-xs text-muted-foreground">
            {summary.fund_code}
          </span>
        </DetailRow>
        {summary.plan_id !== undefined && (
          <DetailRow label={t.proposals.planId}>#{summary.plan_id}</DetailRow>
        )}
        <DetailRow label={t.proposals.colAmount}>{money(summary.amount)}</DetailRow>
        <DetailRow label={t.proposals.planSchedule}>
          {summary.schedule || summary.cadence_label || "—"}
        </DetailRow>
        {op === "toggle_plan" ? (
          <DetailRow label={t.proposals.planState}>
            <span className="line-through text-muted-foreground">
              {enabledText(summary.enabled_before)}
            </span>
            {" → "}
            <span className="font-medium">{enabledText(summary.enabled_after)}</span>
          </DetailRow>
        ) : op === "create_plan" ? (
          <DetailRow label={t.proposals.planState}>{enabledText(false)}</DetailRow>
        ) : (
          <DetailRow label={t.proposals.planState}>
            {enabledText(summary.enabled)}
          </DetailRow>
        )}
        <DetailRow label={t.proposals.planNextRun}>
          {summary.next_run || "—"}
        </DetailRow>
        {op === "delete_plan" && (
          <DetailRow label={t.proposals.planLastRun}>
            {before?.last_run || "—"}
          </DetailRow>
        )}
        <DetailRow label={t.proposals.channel}>
          {summary.channel || "—"}
        </DetailRow>
        {summary.note && (
          <DetailRow label={t.proposals.note} className="col-span-2">
            {summary.note}
          </DetailRow>
        )}
      </dl>
      {op === "update_plan" && before && after && changed.length > 0 && (
        <div className="rounded-md border border-border p-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">
            {t.proposals.changedFields}：{changed.map((f) => planFieldLabel(f, t)).join("、")}
          </p>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs">
            <span className="font-medium text-muted-foreground">{t.proposals.diffBefore}</span>
            <span className="font-medium text-muted-foreground">{t.proposals.diffAfter}</span>
            {changed.map((field) => {
              const beforeVal = (before as unknown as Record<string, unknown>)[field]
              const afterVal = (after as unknown as Record<string, unknown>)[field]
              const label = planFieldLabel(field, t)
              return (
                <Fragment key={field}>
                  <div>
                    <span className="text-muted-foreground">{label}：</span>
                    <span className="line-through text-muted-foreground">
                      {formatPlanField(field, beforeVal, t)}
                    </span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">{label}：</span>
                    <span className="font-medium">
                      {formatPlanField(field, afterVal, t)}
                    </span>
                  </div>
                </Fragment>
              )
            })}
          </div>
        </div>
      )}
      {summary.scheduler_hint && (
        <p className="rounded-md border border-border bg-muted/40 p-2.5 text-xs text-muted-foreground">
          {summary.scheduler_hint}
        </p>
      )}
    </div>
  )
}