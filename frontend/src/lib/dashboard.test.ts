import { describe, expect, test } from "bun:test";
import { EXCEPTION_CATEGORIES, EXCEPTION_STATUSES } from "./exceptions";
import {
  batchTiles,
  exceptionQueueHref,
  exceptionTiles,
  formatMatchRate,
  isEmptyDashboard,
} from "./dashboard";
import type { WorkspaceSummary } from "./workspaces";

const summaryWith = (
  batches: Partial<WorkspaceSummary["imports"]["batches_by_status"]>,
  latestRun: WorkspaceSummary["latest_run"] = null,
): WorkspaceSummary => ({
  imports: {
    batches_by_status: { pending: 0, processing: 0, completed: 0, failed: 0, ...batches },
    rows_imported: 0,
    rows_invalid: 0,
    recent_batches: [],
  },
  latest_run: latestRun,
  exceptions: {
    by_status: { open: 0, proposed: 0, resolved: 0 },
    by_category: { unmatched: 0, ambiguous: 0, amount_mismatch: 0, duplicate: 0 },
  },
});

const run = {
  id: "run-1",
  completed_at: "2026-10-30T10:00:00Z",
  matches_count: 8,
  exceptions_count: 2,
  match_rate: "0.8000",
};

describe("formatMatchRate", () => {
  test("moves the decimal point without rounding", () => {
    expect(formatMatchRate("0.8123")).toBe("81.23%");
    expect(formatMatchRate("0.1234")).toBe("12.34%");
    expect(formatMatchRate("0.012345")).toBe("1.2345%");
  });

  test("drops trailing zeros and keeps whole percentages clean", () => {
    expect(formatMatchRate("1.0000")).toBe("100%");
    expect(formatMatchRate("0.0000")).toBe("0%");
    expect(formatMatchRate("0.8000")).toBe("80%");
    expect(formatMatchRate("0.5")).toBe("50%");
  });

  test("shows a dash when there is no rate", () => {
    expect(formatMatchRate(null)).toBe("—");
  });
});

describe("isEmptyDashboard", () => {
  test("is empty when there are no imports and no run", () => {
    expect(isEmptyDashboard(summaryWith({}))).toBe(true);
  });

  test("is not empty once a batch exists, even without a run", () => {
    expect(isEmptyDashboard(summaryWith({ pending: 1 }))).toBe(false);
  });

  test("is not empty once a run exists", () => {
    expect(isEmptyDashboard(summaryWith({}, run))).toBe(false);
  });
});

describe("batchTiles", () => {
  test("zero-fills every status in order", () => {
    expect(batchTiles({ completed: 3 })).toEqual([
      { key: "pending", label: "Pending", value: 0 },
      { key: "processing", label: "Processing", value: 0 },
      { key: "completed", label: "Completed", value: 3 },
      { key: "failed", label: "Failed", value: 0 },
    ]);
  });
});

describe("exceptionQueueHref", () => {
  test("links every status to the queue filtered by that status", () => {
    for (const status of EXCEPTION_STATUSES) {
      expect(exceptionQueueHref("ws-1", { status })).toBe(
        `/workspaces/ws-1/exceptions?status=${status}`,
      );
    }
  });

  test("links every category to the queue filtered by that category", () => {
    for (const category of EXCEPTION_CATEGORIES) {
      expect(exceptionQueueHref("ws-1", { category })).toBe(
        `/workspaces/ws-1/exceptions?category=${category}`,
      );
    }
  });
});

describe("exceptionTiles", () => {
  test("zero-fills statuses and categories with links to the queue", () => {
    const tiles = exceptionTiles("ws-1", {
      by_status: { open: 4 },
      by_category: { duplicate: 1 },
    });

    expect(tiles.statuses.map(({ key, value }) => [key, value])).toEqual([
      ["open", 4],
      ["proposed", 0],
      ["resolved", 0],
    ]);
    expect(tiles.statuses[0].href).toBe("/workspaces/ws-1/exceptions?status=open");
    expect(tiles.categories.map(({ key, value }) => [key, value])).toEqual([
      ["unmatched", 0],
      ["ambiguous", 0],
      ["amount_mismatch", 0],
      ["duplicate", 1],
    ]);
    expect(tiles.categories[3].href).toBe("/workspaces/ws-1/exceptions?category=duplicate");
  });
});
