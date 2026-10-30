import { describe, expect, test } from "bun:test";
import { PAGE_SIZE } from "./exceptions";
import {
  AUDIT_ACTIONS,
  AUDIT_ACTION_LABELS,
  TARGET_TYPE_LABELS,
  auditRequestQuery,
  buildAuditQueryString,
  getAuditActionLabel,
  getTargetTypeLabel,
  parseAuditFilters,
  pickOrganization,
  type AuditAction,
  type AuditFilters,
} from "./audit";

// The actions the backend writes to audit_events (backend/app/models/audit_events.py).
const BACKEND_AUDIT_ACTIONS: AuditAction[] = [
  "import.created",
  "import.completed",
  "import.failed",
  "exception.proposed",
  "exception.approved",
  "exception.rejected",
  "exception.reopened",
];
const ORGANIZATION_ID = "2f6c1d3e-8a4b-4c7d-9e1f-0a1b2c3d4e5f";

const roundTrip = (filters: AuditFilters) =>
  parseAuditFilters(new URLSearchParams(buildAuditQueryString(filters)));

describe("audit action labels", () => {
  test("cover every backend audit action", () => {
    expect([...AUDIT_ACTIONS].sort()).toEqual([...BACKEND_AUDIT_ACTIONS].sort());
    for (const action of BACKEND_AUDIT_ACTIONS) {
      expect(getAuditActionLabel(action)).toBe(AUDIT_ACTION_LABELS[action]);
    }
  });

  test("fall back to the raw value for an unknown action", () => {
    expect(getAuditActionLabel("exception.merged")).toBe("exception.merged");
  });

  test("label the import_batch and exception target types", () => {
    expect(getTargetTypeLabel("import_batch")).toBe(TARGET_TYPE_LABELS.import_batch);
    expect(getTargetTypeLabel("exception")).toBe("Exception");
  });
});

describe("parseAuditFilters", () => {
  test("uses defaults for missing or invalid values", () => {
    expect(
      parseAuditFilters(
        new URLSearchParams("organization=not-a-uuid&action=drop.table&target_type=user&page=0"),
      ),
    ).toEqual({ organizationId: "", action: "", targetType: "", page: 1 });
  });

  test("keeps valid values", () => {
    expect(
      parseAuditFilters(
        new URLSearchParams(
          `organization=${ORGANIZATION_ID}&action=exception.approved&target_type=exception&page=3`,
        ),
      ),
    ).toEqual({
      organizationId: ORGANIZATION_ID,
      action: "exception.approved",
      targetType: "exception",
      page: 3,
    });
  });
});

describe("audit query round trip", () => {
  test("parsing a built query returns the same filters", () => {
    const filters: AuditFilters = {
      organizationId: ORGANIZATION_ID,
      action: "import.failed",
      targetType: "import_batch",
      page: 2,
    };
    expect(roundTrip(filters)).toEqual(filters);
  });

  test("leaves out empty filters and the first page", () => {
    const filters: AuditFilters = { organizationId: "", action: "", targetType: "", page: 1 };
    expect(buildAuditQueryString(filters)).toBe("");
  });
});

describe("auditRequestQuery", () => {
  test("fetches one extra row to know whether a next page exists", () => {
    const filters: AuditFilters = { organizationId: "", action: "", targetType: "", page: 3 };
    expect(auditRequestQuery(filters, ORGANIZATION_ID)).toEqual({
      organization_id: ORGANIZATION_ID,
      action: undefined,
      target_type: undefined,
      limit: PAGE_SIZE + 1,
      offset: 2 * PAGE_SIZE,
    });
  });
});

describe("pickOrganization", () => {
  const first = {
    id: "11111111-1111-4111-8111-111111111111",
    name: "First",
    role: "analyst" as const,
  };
  const second = { id: ORGANIZATION_ID, name: "Second", role: "reviewer" as const };

  test("selects the organization named in the URL", () => {
    expect(pickOrganization([first, second], ORGANIZATION_ID)).toBe(second);
  });

  test("falls back to the first organization", () => {
    expect(pickOrganization([first, second], "")).toBe(first);
  });

  test("returns nothing when the user has no organizations", () => {
    expect(pickOrganization([], "")).toBeUndefined();
  });
});
