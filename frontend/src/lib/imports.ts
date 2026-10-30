import { api } from "@/lib/api/client";
import type { components, operations } from "@/lib/api/schema";
import { apiErrorMessage } from "@/lib/auth";

export type ImportBatchOut = components["schemas"]["ImportBatchOut"];
export type ImportPreviewOut = components["schemas"]["ImportPreviewOut"];
export type ImportErrorOut = components["schemas"]["ImportErrorOut"];

export type SourceName = "orders" | "payments" | "refunds" | "settlements" | "fees";

export const SOURCE_NAMES: SourceName[] = ["orders", "payments", "refunds", "settlements", "fees"];

export const REQUIRED_HEADERS: Record<SourceName, string[]> = {
  orders: ["external_id", "amount", "currency", "occurred_at"],
  payments: ["external_id", "amount", "currency", "occurred_at"],
  refunds: ["external_id", "amount", "currency", "occurred_at", "original_external_id"],
  settlements: ["external_id", "amount", "currency", "occurred_at"],
  fees: ["external_id", "amount", "currency", "occurred_at"],
};

export const MAX_FILE_SIZE = 10 * 1024 * 1024;
export const ERROR_PAGE_SIZE = 20;
export const POLL_INTERVAL_MS = 1000;

type ImportForm =
  operations["upload_import_api_v1_workspaces__workspace_id__imports_post"]["requestBody"]["content"]["multipart/form-data"];

export class ImportRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function validateFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith(".csv")) return "Choose a CSV file.";
  if (file.size > MAX_FILE_SIZE) return "The file is larger than 10 MB.";
  if (file.size === 0) return "The file is empty.";
  return null;
}

export function buildImportFormData(sourceName: SourceName, file: File): FormData {
  const formData = new FormData();
  formData.append("source_name", sourceName);
  formData.append("file", file);
  return formData;
}

export function idempotencyKeyFor(existing: string | null): string {
  return existing ?? crypto.randomUUID();
}

export function mapImportError(status: number, body: unknown): string {
  if (status === 0) return "Network error. Check your connection and try again.";
  if (status === 413) return "The file is larger than 10 MB.";
  if (status === 409 || status === 422) return apiErrorMessage(body);
  if (status >= 500) return "The server could not finish the request. Try again.";
  return apiErrorMessage(body);
}

export function isRetryableError(status: number): boolean {
  return status === 0 || status === 409 || status >= 500;
}

export function describeImportError(err: unknown): { message: string; retryable: boolean } {
  if (err instanceof ImportRequestError) {
    return { message: err.message, retryable: isRetryableError(err.status) };
  }
  return { message: "Something went wrong. Please try again.", retryable: true };
}

export function matchPollingBatch(
  batches: ImportBatchOut[],
  filename: string,
  uploadStartedAt: Date,
): ImportBatchOut | null {
  const candidates = batches
    .filter((batch) => batch.filename === filename)
    .filter((batch) => new Date(batch.created_at) >= uploadStartedAt)
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  return candidates[0] ?? null;
}

export function calculateProgress(batch: ImportBatchOut): number {
  if (batch.rows_total === 0) return 0;
  return Math.min(100, Math.round((batch.rows_processed / batch.rows_total) * 100));
}

async function send<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result;
  try {
    result = await request;
  } catch {
    throw new ImportRequestError(0, mapImportError(0, undefined));
  }
  const { data, error, response } = result;
  if (!response.ok || !data) {
    throw new ImportRequestError(response.status, mapImportError(response.status, error));
  }
  return data;
}

export function previewImport(
  workspaceId: string,
  sourceName: SourceName,
  file: File,
): Promise<ImportPreviewOut> {
  return send(
    api.POST("/api/v1/workspaces/{workspace_id}/imports/preview", {
      params: { path: { workspace_id: workspaceId } },
      // The generated type describes the file as a string; the body is a FormData with the File.
      body: buildImportFormData(sourceName, file) as unknown as ImportForm,
    }),
  );
}

export function uploadImport(
  workspaceId: string,
  sourceName: SourceName,
  file: File,
  idempotencyKey: string,
): Promise<ImportBatchOut> {
  return send(
    api.POST("/api/v1/workspaces/{workspace_id}/imports", {
      params: { path: { workspace_id: workspaceId } },
      headers: { "Idempotency-Key": idempotencyKey },
      body: buildImportFormData(sourceName, file) as unknown as ImportForm,
    }),
  );
}

export function listImports(workspaceId: string, limit = 50): Promise<ImportBatchOut[]> {
  return send(
    api.GET("/api/v1/workspaces/{workspace_id}/imports", {
      params: { path: { workspace_id: workspaceId }, query: { limit } },
    }),
  );
}

export function listImportErrors(importId: string, offset = 0): Promise<ImportErrorOut[]> {
  return send(
    api.GET("/api/v1/imports/{import_id}/errors", {
      params: { path: { import_id: importId }, query: { limit: ERROR_PAGE_SIZE, offset } },
    }),
  );
}
