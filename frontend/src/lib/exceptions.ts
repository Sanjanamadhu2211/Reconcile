import type { Dispatch } from "react";
import type { components } from "@/lib/api/schema";

export type ReconciliationRunSummary = components["schemas"]["ReconciliationRunSummary"];
export type ExceptionItem = components["schemas"]["ExceptionItem"];

export type ExceptionCategory = "unmatched" | "ambiguous" | "amount_mismatch" | "duplicate";
export type ExceptionStatus = "open" | "proposed" | "resolved";
export type MatchRule = "exact_id" | "amount_currency_time";

export const PAGE_SIZE = 20;
const MAX_SEARCH_LENGTH = 200;

export const CATEGORY_LABELS: Record<ExceptionCategory, string> = {
  unmatched: "Unmatched",
  ambiguous: "Ambiguous",
  amount_mismatch: "Amount mismatch",
  duplicate: "Duplicate",
};

export const STATUS_LABELS: Record<ExceptionStatus, string> = {
  open: "Open",
  proposed: "Proposed",
  resolved: "Resolved",
};

export const MATCH_RULE_LABELS: Record<MatchRule, string> = {
  exact_id: "Exact ID",
  amount_currency_time: "Amount, currency and time",
};

export const EXCEPTION_CATEGORIES = Object.keys(CATEGORY_LABELS) as ExceptionCategory[];
export const EXCEPTION_STATUSES = Object.keys(STATUS_LABELS) as ExceptionStatus[];
export const MATCH_RULES = Object.keys(MATCH_RULE_LABELS) as MatchRule[];
export const SOURCE_NAMES = ["orders", "payments", "refunds", "settlements", "fees"] as const;
export type SourceName = (typeof SOURCE_NAMES)[number];

export interface ExceptionFilters {
  category: ExceptionCategory | "";
  status: ExceptionStatus | "";
  source: SourceName | "";
  search: string;
  page: number;
}

export interface MatchFilters {
  rule: MatchRule | "";
  page: number;
}

export function getCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category as ExceptionCategory] ?? category;
}

export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status as ExceptionStatus] ?? status;
}

export function getRuleLabel(rule: string): string {
  return MATCH_RULE_LABELS[rule as MatchRule] ?? rule;
}

export function parseFilters(params: URLSearchParams): ExceptionFilters {
  return {
    category: pick(EXCEPTION_CATEGORIES, params.get("category")),
    status: pick(EXCEPTION_STATUSES, params.get("status")),
    source: pick(SOURCE_NAMES, params.get("source")),
    search: (params.get("q") ?? "").slice(0, MAX_SEARCH_LENGTH),
    page: parsePage(params.get("page")),
  };
}

export function buildQueryString(filters: ExceptionFilters): string {
  const params = new URLSearchParams();
  if (filters.category) params.set("category", filters.category);
  if (filters.status) params.set("status", filters.status);
  if (filters.source) params.set("source", filters.source);
  if (filters.search) params.set("q", filters.search);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

export function parseMatchFilters(params: URLSearchParams): MatchFilters {
  return { rule: pick(MATCH_RULES, params.get("rule")), page: parsePage(params.get("page")) };
}

export function buildMatchQueryString(filters: MatchFilters): string {
  const params = new URLSearchParams();
  if (filters.rule) params.set("rule", filters.rule);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

export function exceptionsRequestQuery(filters: ExceptionFilters) {
  return {
    category: filters.category || undefined,
    status: filters.status || undefined,
    source_name: filters.source || undefined,
    q: filters.search || undefined,
    ...pageWindow(filters.page),
  };
}

export function matchesRequestQuery(filters: MatchFilters) {
  return { rule: filters.rule || undefined, ...pageWindow(filters.page) };
}

// One extra row tells the page whether a next page exists; the counts are not returned by the API.
export function pageWindow(page: number) {
  return { limit: PAGE_SIZE + 1, offset: (page - 1) * PAGE_SIZE };
}

export function formatRangeText(page: number, rowCount: number): string {
  if (rowCount === 0) return "No results";
  const start = (page - 1) * PAGE_SIZE + 1;
  return `Showing ${start}–${start + rowCount - 1}`;
}

export function chooseLatestCompletedRun(
  runs: ReconciliationRunSummary[],
): ReconciliationRunSummary | null {
  const [latest] = runs
    .filter((run) => run.status === "completed")
    .sort((a, b) => completedAt(b) - completedAt(a));
  return latest ?? null;
}

export function getCandidateIds(details: ExceptionItem["details"]): string[] {
  const candidates = details?.candidates;
  return Array.isArray(candidates)
    ? candidates.filter((candidate): candidate is string => typeof candidate === "string")
    : [];
}

export function debounce(fn: Dispatch<string>, delayMs: number) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const debounced = (value: string) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(value), delayMs);
  };
  debounced.cancel = () => clearTimeout(timer);
  return debounced;
}

function completedAt(run: ReconciliationRunSummary): number {
  return Date.parse(run.completed_at ?? "") || 0;
}

export function parsePage(value: string | null): number {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

export function pick<T extends string>(allowed: readonly T[], value: string | null): T | "" {
  return allowed.find((item) => item === value) ?? "";
}
