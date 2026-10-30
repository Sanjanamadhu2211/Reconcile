import {
  EXCEPTION_CATEGORIES,
  EXCEPTION_STATUSES,
  CATEGORY_LABELS,
  STATUS_LABELS,
  buildQueryString,
  parseFilters,
  type ExceptionCategory,
  type ExceptionFilters,
  type ExceptionStatus,
} from "@/lib/exceptions";
import type { WorkspaceSummary } from "@/lib/workspaces";

export const BATCH_STATUSES = ["pending", "processing", "completed", "failed"] as const;
export type BatchStatus = (typeof BATCH_STATUSES)[number];

const BATCH_STATUS_LABELS: Record<BatchStatus, string> = {
  pending: "Pending",
  processing: "Processing",
  completed: "Completed",
  failed: "Failed",
};

const NO_FILTERS = parseFilters(new URLSearchParams());

export function formatMatchRate(rate: string | null): string {
  const percent = matchRatePercent(rate);
  return percent === null ? "—" : `${percent}%`;
}

// Moves the decimal point by hand so the stored string is never converted to a float.
export function matchRatePercent(rate: string | null): string | null {
  if (rate === null || !/^\d+(\.\d+)?$/.test(rate)) return null;
  const [whole, fraction = ""] = rate.split(".");
  const rest = fraction.slice(2).replace(/0+$/, "");
  const wholePercent = Number(whole + fraction.slice(0, 2).padEnd(2, "0"));
  return rest ? `${wholePercent}.${rest}` : String(wholePercent);
}

export function isEmptyDashboard(summary: WorkspaceSummary): boolean {
  const { batches_by_status: counts } = summary.imports;
  const batchCount = BATCH_STATUSES.reduce((total, status) => total + counts[status], 0);
  return batchCount === 0 && summary.latest_run === null;
}

export function batchTiles(counts: Partial<Record<BatchStatus, number>>) {
  return BATCH_STATUSES.map((status) => ({
    key: status,
    label: BATCH_STATUS_LABELS[status],
    value: counts[status] ?? 0,
  }));
}

export function exceptionQueueHref(
  workspaceId: string,
  filter: Partial<Pick<ExceptionFilters, "status" | "category">>,
): string {
  return `/workspaces/${workspaceId}/exceptions?${buildQueryString({ ...NO_FILTERS, ...filter })}`;
}

export function exceptionTiles(
  workspaceId: string,
  counts: {
    by_status: Partial<Record<ExceptionStatus, number>>;
    by_category: Partial<Record<ExceptionCategory, number>>;
  },
) {
  return {
    statuses: EXCEPTION_STATUSES.map((status) => ({
      key: status,
      label: STATUS_LABELS[status],
      value: counts.by_status[status] ?? 0,
      href: exceptionQueueHref(workspaceId, { status }),
    })),
    categories: EXCEPTION_CATEGORIES.map((category) => ({
      key: category,
      label: CATEGORY_LABELS[category],
      value: counts.by_category[category] ?? 0,
      href: exceptionQueueHref(workspaceId, { category }),
    })),
  };
}
