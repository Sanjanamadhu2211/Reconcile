import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import Pagination from "@/components/exceptions/Pagination";
import styles from "@/components/exceptions/exceptions.module.css";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import {
  AUDIT_ACTIONS,
  AUDIT_ACTION_LABELS,
  AUDIT_TARGET_TYPES,
  TARGET_TYPE_LABELS,
  auditRequestQuery,
  buildAuditQueryString,
  getAuditActionLabel,
  getTargetTypeLabel,
  parseAuditFilters,
  pickOrganization,
  type AuditEvent,
  type AuditFilters,
} from "@/lib/audit";
import { apiErrorMessage } from "@/lib/auth";
import { PAGE_SIZE } from "@/lib/exceptions";
import { listOrganizations } from "@/lib/workspaces";

type OrganizationOut = components["schemas"]["OrganizationOut"];

export default function AuditTrail() {
  const router = useRouter();
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const filters = useMemo(() => parseAuditFilters(new URLSearchParams(query)), [query]);

  const [organizations, setOrganizations] = useState<OrganizationOut[]>();
  const [events, setEvents] = useState<AuditEvent[]>();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const organization = organizations && pickOrganization(organizations, filters.organizationId);
  const organizationId = organization?.id;

  useEffect(() => {
    let ignore = false;
    setError(null);
    listOrganizations()
      .then((found) => {
        if (!ignore) setOrganizations(found);
      })
      .catch(() => {
        if (!ignore) setError("Could not reach the server. Please try again.");
      });
    return () => {
      ignore = true;
    };
  }, [attempt]);

  useEffect(() => {
    if (!organizationId) return;
    let ignore = false;
    setEvents(undefined);
    setError(null);
    api
      .GET("/api/v1/audit-events", {
        params: { query: auditRequestQuery(filters, organizationId) },
      })
      .then(({ data, error, response }) => {
        if (ignore) return;
        if (response.ok && data) setEvents(data);
        else setError(apiErrorMessage(error));
      })
      .catch(() => {
        if (!ignore) setError("Could not reach the server. Please try again.");
      });
    return () => {
      ignore = true;
    };
  }, [organizationId, filters, attempt]);

  // Reads the URL at call time, the same way the exception queue does.
  const updateFilters = useCallback(
    (changes: Partial<AuditFilters>) => {
      const current = parseAuditFilters(new URLSearchParams(window.location.search));
      const next = buildAuditQueryString({ ...current, ...changes });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  if (error) {
    return (
      <div className={styles.page}>
        <h1>Audit trail</h1>
        <p className={styles.error} role="alert">
          {error}{" "}
          <button type="button" className={styles.button} onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </p>
      </div>
    );
  }

  if (organizations === undefined) {
    return (
      <div className={styles.page}>
        <h1>Audit trail</h1>
        <p aria-live="polite">Loading…</p>
      </div>
    );
  }

  if (organizations.length === 0 || !organization) {
    return (
      <div className={styles.page}>
        <h1>Audit trail</h1>
        <p className={styles.muted}>Create or join an organization to see its audit trail.</p>
      </div>
    );
  }

  const visibleEvents = events?.slice(0, PAGE_SIZE) ?? [];
  const hasNext = (events?.length ?? 0) > PAGE_SIZE;

  return (
    <div className={styles.page}>
      <h1>Audit trail</h1>
      <section className={styles.panel} aria-label="Audit filters">
        <div className={styles.filters}>
          {organizations.length > 1 && (
            <div className={styles.field}>
              <label htmlFor="audit-organization">Organization</label>
              <select
                id="audit-organization"
                value={organization.id}
                onChange={(event) => updateFilters({ organizationId: event.target.value, page: 1 })}
              >
                {organizations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className={styles.field}>
            <label htmlFor="audit-action">Action</label>
            <select
              id="audit-action"
              value={filters.action}
              onChange={(event) =>
                updateFilters({ action: event.target.value as AuditFilters["action"], page: 1 })
              }
            >
              <option value="">All actions</option>
              {AUDIT_ACTIONS.map((action) => (
                <option key={action} value={action}>
                  {AUDIT_ACTION_LABELS[action]}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label htmlFor="audit-target-type">Target type</label>
            <select
              id="audit-target-type"
              value={filters.targetType}
              onChange={(event) =>
                updateFilters({
                  targetType: event.target.value as AuditFilters["targetType"],
                  page: 1,
                })
              }
            >
              <option value="">All targets</option>
              {AUDIT_TARGET_TYPES.map((targetType) => (
                <option key={targetType} value={targetType}>
                  {TARGET_TYPE_LABELS[targetType]}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      {events === undefined && <p aria-live="polite">Loading audit events…</p>}
      {events !== undefined && (
        <>
          {visibleEvents.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">When</th>
                    <th scope="col">Action</th>
                    <th scope="col">Actor</th>
                    <th scope="col">Target</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEvents.map((event) => (
                    <tr key={event.id}>
                      <td>
                        <time dateTime={event.created_at}>
                          {new Date(event.created_at).toLocaleString()}
                        </time>
                      </td>
                      <td>{getAuditActionLabel(event.action)}</td>
                      <td>{event.actor_email}</td>
                      <td>
                        {getTargetTypeLabel(event.target_type)}
                        <br />
                        <span className={styles.muted}>{event.target_id}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className={styles.muted}>No audit events match these filters.</p>
          )}
          <Pagination
            page={filters.page}
            rowCount={visibleEvents.length}
            hasNext={hasNext}
            onPageChange={(page) => updateFilters({ page })}
          />
        </>
      )}
    </div>
  );
}
