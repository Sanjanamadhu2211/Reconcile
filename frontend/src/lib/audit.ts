import type { components } from "@/lib/api/schema";
import { pageWindow, parsePage, pick } from "@/lib/exceptions";

export type AuditEvent = components["schemas"]["AuditEventOut"];
type OrganizationOut = components["schemas"]["OrganizationOut"];

export type AuditAction =
  | "import.created"
  | "import.completed"
  | "import.failed"
  | "exception.proposed"
  | "exception.approved"
  | "exception.rejected"
  | "exception.reopened";
export type AuditTargetType = "import_batch" | "exception";

export const AUDIT_ACTION_LABELS: Record<AuditAction, string> = {
  "import.created": "Import created",
  "import.completed": "Import completed",
  "import.failed": "Import failed",
  "exception.proposed": "Exception proposed",
  "exception.approved": "Exception approved",
  "exception.rejected": "Exception rejected",
  "exception.reopened": "Exception reopened",
};

export const AUDIT_ACTIONS = Object.keys(AUDIT_ACTION_LABELS) as AuditAction[];

export const TARGET_TYPE_LABELS: Record<AuditTargetType, string> = {
  import_batch: "Import batch",
  exception: "Exception",
};

export const AUDIT_TARGET_TYPES = Object.keys(TARGET_TYPE_LABELS) as AuditTargetType[];

export interface AuditFilters {
  organizationId: string;
  action: AuditAction | "";
  targetType: AuditTargetType | "";
  page: number;
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function getAuditActionLabel(action: string): string {
  return AUDIT_ACTION_LABELS[action as AuditAction] ?? action;
}

export function getTargetTypeLabel(targetType: string): string {
  return TARGET_TYPE_LABELS[targetType as AuditTargetType] ?? targetType;
}

export function parseAuditFilters(params: URLSearchParams): AuditFilters {
  const organization = params.get("organization") ?? "";
  return {
    organizationId: UUID_PATTERN.test(organization) ? organization : "",
    action: pick(AUDIT_ACTIONS, params.get("action")),
    targetType: pick(AUDIT_TARGET_TYPES, params.get("target_type")),
    page: parsePage(params.get("page")),
  };
}

export function buildAuditQueryString(filters: AuditFilters): string {
  const params = new URLSearchParams();
  if (filters.organizationId) params.set("organization", filters.organizationId);
  if (filters.action) params.set("action", filters.action);
  if (filters.targetType) params.set("target_type", filters.targetType);
  if (filters.page > 1) params.set("page", String(filters.page));
  return params.toString();
}

export function auditRequestQuery(filters: AuditFilters, organizationId: string) {
  return {
    organization_id: organizationId,
    action: filters.action || undefined,
    target_type: filters.targetType || undefined,
    ...pageWindow(filters.page),
  };
}

// Falls back to the first organization when the URL names one the user does not belong to.
export function pickOrganization(
  organizations: OrganizationOut[],
  organizationId: string,
): OrganizationOut | undefined {
  return (
    organizations.find((organization) => organization.id === organizationId) ?? organizations[0]
  );
}
