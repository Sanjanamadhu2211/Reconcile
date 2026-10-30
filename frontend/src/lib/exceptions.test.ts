import { describe, expect, test } from "bun:test";
import {
  CATEGORY_LABELS,
  STATUS_LABELS,
  PAGE_SIZE,
  buildMatchQueryString,
  buildQueryString,
  chooseLatestCompletedRun,
  debounce,
  formatRangeText,
  getCandidateIds,
  getCategoryLabel,
  getRuleLabel,
  getStatusLabel,
  parseFilters,
  parseMatchFilters,
  type ExceptionFilters,
  type ReconciliationRunSummary,
} from "./exceptions";

const BACKEND_CATEGORIES = ["unmatched", "ambiguous", "amount_mismatch", "duplicate"];
const BACKEND_STATUSES = ["open", "proposed", "resolved"];

const roundTrip = (filters: ExceptionFilters) =>
  parseFilters(new URLSearchParams(buildQueryString(filters)));

describe("exception filters", () => {
  test("round trip keeps every filter and page", () => {
    const filters: ExceptionFilters = {
      category: "amount_mismatch",
      status: "proposed",
      source: "settlements",
      search: "refund 42 & more",
      page: 3,
    };
    expect(roundTrip(filters)).toEqual(filters);
  });

  test("empty filters round trip to the defaults and an empty query", () => {
    const filters: ExceptionFilters = { category: "", status: "", source: "", search: "", page: 1 };
    expect(buildQueryString(filters)).toBe("");
    expect(roundTrip(filters)).toEqual(filters);
  });

  test("invalid values fall back to defaults", () => {
    const params = new URLSearchParams(
      "category=missing&status=closed&source=bank&page=abc&q=" + "x".repeat(300),
    );
    const filters = parseFilters(params);
    expect(filters.category).toBe("");
    expect(filters.status).toBe("");
    expect(filters.source).toBe("");
    expect(filters.page).toBe(1);
    expect(filters.search).toHaveLength(200);
  });

  test("zero, negative and fractional pages fall back to the first page", () => {
    for (const page of ["0", "-2", "1.5"]) {
      expect(parseFilters(new URLSearchParams({ page })).page).toBe(1);
    }
  });

  test("match filters round trip and ignore unknown rules", () => {
    const filters = { rule: "exact_id" as const, page: 2 };
    expect(parseMatchFilters(new URLSearchParams(buildMatchQueryString(filters)))).toEqual(filters);
    expect(parseMatchFilters(new URLSearchParams("rule=fuzzy")).rule).toBe("");
  });
});

describe("formatRangeText", () => {
  test("first, middle and last page", () => {
    expect(formatRangeText(1, PAGE_SIZE)).toBe("Showing 1–20");
    expect(formatRangeText(2, PAGE_SIZE)).toBe("Showing 21–40");
    expect(formatRangeText(3, 5)).toBe("Showing 41–45");
  });

  test("zero results", () => {
    expect(formatRangeText(1, 0)).toBe("No results");
  });
});

describe("label mapping", () => {
  test("covers every backend category", () => {
    for (const category of BACKEND_CATEGORIES) {
      expect(CATEGORY_LABELS).toHaveProperty(category);
      expect(getCategoryLabel(category)).not.toBe(category);
    }
  });

  test("covers every backend status", () => {
    for (const status of BACKEND_STATUSES) {
      expect(STATUS_LABELS).toHaveProperty(status);
      expect(getStatusLabel(status)).not.toBe(status);
    }
  });

  test("covers both match rules", () => {
    expect(getRuleLabel("exact_id")).toBe("Exact ID");
    expect(getRuleLabel("amount_currency_time")).toBe("Amount, currency and time");
  });

  test("unknown codes are shown as received", () => {
    expect(getCategoryLabel("new_kind")).toBe("new_kind");
    expect(getStatusLabel("new_status")).toBe("new_status");
  });
});

describe("chooseLatestCompletedRun", () => {
  const run = (
    id: string,
    status: string,
    completedAt: string | null,
  ): ReconciliationRunSummary => ({
    id,
    status,
    rule_version: "1",
    tolerance_hours: 24,
    matches_count: 0,
    exceptions_count: 0,
    started_at: null,
    completed_at: completedAt,
  });

  test("returns null when there are no completed runs", () => {
    expect(chooseLatestCompletedRun([])).toBeNull();
    expect(
      chooseLatestCompletedRun([run("a", "running", null), run("b", "failed", null)]),
    ).toBeNull();
  });

  test("ignores failed and running runs even when they are newer", () => {
    const runs = [
      run("running", "running", null),
      run("failed", "failed", "2026-03-03T00:00:00Z"),
      run("older", "completed", "2026-03-01T00:00:00Z"),
      run("newer", "completed", "2026-03-02T00:00:00Z"),
    ];
    expect(chooseLatestCompletedRun(runs)?.id).toBe("newer");
  });
});

describe("getCandidateIds", () => {
  test("returns only string candidates from details", () => {
    expect(getCandidateIds({ candidates: ["a", 3, "b"] })).toEqual(["a", "b"]);
    expect(getCandidateIds({ other: true })).toEqual([]);
    expect(getCandidateIds(null)).toEqual([]);
  });
});

describe("debounce", () => {
  test("calls once with the last arguments after the quiet period", async () => {
    const calls: string[] = [];
    const push = debounce((value: string) => calls.push(value), 20);
    push("a");
    push("ab");
    push("abc");
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(calls).toEqual(["abc"]);
  });

  test("cancel drops the pending call", async () => {
    const calls: string[] = [];
    const push = debounce((value: string) => calls.push(value), 20);
    push("a");
    push.cancel();
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(calls).toEqual([]);
  });
});
