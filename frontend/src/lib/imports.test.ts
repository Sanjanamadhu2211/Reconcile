import { describe, expect, test } from "bun:test";
import {
  MAX_FILE_SIZE,
  calculateProgress,
  describeImportError,
  idempotencyKeyFor,
  ImportRequestError,
  isRetryableError,
  mapImportError,
  matchPollingBatch,
  validateFile,
  type ImportBatchOut,
} from "./imports";

function batch(overrides: Partial<ImportBatchOut> = {}): ImportBatchOut {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    workspace_id: "00000000-0000-0000-0000-000000000000",
    source_name: "orders",
    filename: "orders.csv",
    status: "processing",
    rows_total: 100,
    rows_processed: 50,
    rows_failed: 0,
    error_summary: null,
    started_at: null,
    updated_at: "2024-01-01T00:00:00Z",
    created_at: "2024-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("validateFile", () => {
  test("accepts a CSV extension in any case", () => {
    expect(validateFile(new File(["a"], "orders.csv"))).toBeNull();
    expect(validateFile(new File(["a"], "ORDERS.CSV"))).toBeNull();
  });

  test("rejects other extensions", () => {
    expect(validateFile(new File(["a"], "orders.txt"))).toBe("Choose a CSV file.");
    expect(validateFile(new File(["a"], "orders.csv.zip"))).toBe("Choose a CSV file.");
  });

  test("accepts a file of exactly 10 MB", () => {
    const file = new File([new Uint8Array(MAX_FILE_SIZE)], "orders.csv");
    expect(validateFile(file)).toBeNull();
  });

  test("rejects a file one byte over 10 MB", () => {
    const file = new File([new Uint8Array(MAX_FILE_SIZE + 1)], "orders.csv");
    expect(validateFile(file)).toBe("The file is larger than 10 MB.");
  });

  test("rejects an empty file", () => {
    expect(validateFile(new File([], "orders.csv"))).toBe("The file is empty.");
  });
});

describe("matchPollingBatch", () => {
  const uploadStartedAt = new Date("2024-01-01T00:00:30Z");

  test("picks the newest batch with the same filename created after the upload started", () => {
    const batches = [
      batch({ id: "new", created_at: "2024-01-01T00:01:00Z" }),
      batch({ id: "mid", created_at: "2024-01-01T00:00:45Z" }),
    ];
    expect(matchPollingBatch(batches, "orders.csv", uploadStartedAt)?.id).toBe("new");
  });

  test("ignores batches created before the upload started", () => {
    const batches = [batch({ created_at: "2024-01-01T00:00:20Z" })];
    expect(matchPollingBatch(batches, "orders.csv", uploadStartedAt)).toBeNull();
  });

  test("ignores batches with another filename", () => {
    const batches = [
      batch({ id: "other", filename: "payments.csv", created_at: "2024-01-01T00:01:00Z" }),
      batch({ id: "match", created_at: "2024-01-01T00:00:45Z" }),
    ];
    expect(matchPollingBatch(batches, "orders.csv", uploadStartedAt)?.id).toBe("match");
  });

  test("returns null when nothing matches", () => {
    expect(matchPollingBatch([], "orders.csv", uploadStartedAt)).toBeNull();
    expect(
      matchPollingBatch([batch({ filename: null })], "orders.csv", uploadStartedAt),
    ).toBeNull();
  });
});

describe("calculateProgress", () => {
  test("is the share of processed rows, capped at 100", () => {
    expect(calculateProgress(batch({ rows_total: 200, rows_processed: 50 }))).toBe(25);
    expect(calculateProgress(batch({ rows_total: 100, rows_processed: 150 }))).toBe(100);
  });

  test("is 0 when the total is 0", () => {
    expect(calculateProgress(batch({ rows_total: 0, rows_processed: 0 }))).toBe(0);
  });
});

describe("mapImportError", () => {
  test("maps 413 to the size message", () => {
    expect(mapImportError(413, {})).toBe("The file is larger than 10 MB.");
  });

  test("reads the server message for 409 and 422", () => {
    expect(mapImportError(409, { detail: "Idempotency key reused" })).toBe(
      "Idempotency key reused",
    );
    expect(mapImportError(422, { detail: "Missing header: amount" })).toBe(
      "Missing header: amount",
    );
    expect(mapImportError(422, { detail: [{ loc: ["body", "file"], msg: "Required" }] })).toBe(
      "file: Required",
    );
  });

  test("maps a network failure and server errors to plain messages", () => {
    expect(mapImportError(0, undefined)).toBe(
      "Network error. Check your connection and try again.",
    );
    expect(mapImportError(503, {})).toBe("The server could not finish the request. Try again.");
  });

  test("only conflicts, network failures and server errors are retryable", () => {
    expect([0, 409, 500, 503].every(isRetryableError)).toBe(true);
    expect([413, 422, 401, 404].some(isRetryableError)).toBe(false);
  });

  test("describes a thrown error with its status-based retry flag", () => {
    const conflict = new ImportRequestError(409, "Try again");
    expect(describeImportError(conflict)).toEqual({ message: "Try again", retryable: true });
    expect(describeImportError(new Error("boom")).retryable).toBe(true);
  });
});

describe("idempotencyKeyFor", () => {
  test("keeps the key of an earlier attempt so a retry resumes the same batch", () => {
    const key = idempotencyKeyFor(null);
    expect(key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(idempotencyKeyFor(key)).toBe(key);
  });
});
