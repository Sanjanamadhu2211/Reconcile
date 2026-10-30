"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import ExceptionFilterBar from "@/components/exceptions/ExceptionFilterBar";
import ExceptionTable from "@/components/exceptions/ExceptionTable";
import ExportLinks from "@/components/ExportLinks";
import Pagination from "@/components/exceptions/Pagination";
import RunSummary from "@/components/exceptions/RunSummary";
import styles from "@/components/exceptions/exceptions.module.css";
import { useLatestRun } from "@/components/exceptions/useLatestRun";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/auth";
import {
  PAGE_SIZE,
  buildQueryString,
  exceptionsRequestQuery,
  parseFilters,
  type ExceptionFilters,
  type ExceptionItem,
} from "@/lib/exceptions";

export default function ExceptionQueuePage() {
  return (
    <AppShell>
      <Suspense fallback={<p>Loading…</p>}>
        <ExceptionQueue />
      </Suspense>
    </AppShell>
  );
}

function ExceptionQueue() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const filters = useMemo(() => parseFilters(new URLSearchParams(query)), [query]);
  const { run, error: runError, retry: retryRun } = useLatestRun(workspaceId);
  const runId = run?.id;

  const [exceptions, setExceptions] = useState<ExceptionItem[]>();
  const [exceptionsError, setExceptionsError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!runId) return;
    let ignore = false;
    setExceptions(undefined);
    setExceptionsError(null);
    api
      .GET("/api/v1/reconciliation-runs/{run_id}/exceptions", {
        params: { path: { run_id: runId }, query: exceptionsRequestQuery(filters) },
      })
      .then(({ data, error, response }) => {
        if (ignore) return;
        if (response.ok && data) setExceptions(data);
        else setExceptionsError(apiErrorMessage(error));
      })
      .catch(() => {
        if (!ignore) setExceptionsError("Could not reach the server. Please try again.");
      });
    return () => {
      ignore = true;
    };
  }, [runId, filters, attempt]);

  // Reads the URL at call time so a debounced search never overwrites filters changed in the meantime.
  const updateFilters = useCallback(
    (changes: Partial<ExceptionFilters>) => {
      const current = parseFilters(new URLSearchParams(window.location.search));
      const next = buildQueryString({ ...current, ...changes });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const changeSearch = useCallback(
    (search: string) => updateFilters({ search, page: 1 }),
    [updateFilters],
  );

  if (runError) {
    return (
      <div className={styles.page}>
        <h1>Exceptions</h1>
        <p className={styles.error} role="alert">
          {runError}
        </p>
        <button type="button" className={styles.button} onClick={retryRun}>
          Try again
        </button>
      </div>
    );
  }

  if (run === undefined) {
    return (
      <div className={styles.page}>
        <h1>Exceptions</h1>
        <p aria-live="polite">Loading…</p>
      </div>
    );
  }

  if (run === null) {
    return (
      <div className={styles.page}>
        <h1>Exceptions</h1>
        <section className={styles.panel}>
          <h2>No completed run yet</h2>
          <p className={styles.muted}>
            Run reconciliation from the workspace page to see exceptions here.
          </p>
          <p>
            <Link href={`/workspaces/${workspaceId}`} className={styles.link}>
              Go to the workspace
            </Link>
          </p>
        </section>
      </div>
    );
  }

  const visibleExceptions = exceptions?.slice(0, PAGE_SIZE) ?? [];
  const hasNext = (exceptions?.length ?? 0) > PAGE_SIZE;

  return (
    <div className={styles.page}>
      <h1>Exceptions</h1>
      <RunSummary workspaceId={workspaceId} run={run} active="exceptions" />
      <ExportLinks workspaceId={workspaceId} />
      <ExceptionFilterBar
        filters={filters}
        onFilterChange={updateFilters}
        onSearchChange={changeSearch}
      />
      <div aria-live="polite">
        {exceptionsError && (
          <p className={styles.error}>
            {exceptionsError}{" "}
            <button
              type="button"
              className={styles.button}
              onClick={() => setAttempt((n) => n + 1)}
            >
              Try again
            </button>
          </p>
        )}
        {!exceptionsError && exceptions === undefined && <p>Loading exceptions…</p>}
      </div>
      {!exceptionsError && exceptions !== undefined && (
        <>
          {visibleExceptions.length > 0 ? (
            <ExceptionTable exceptions={visibleExceptions} />
          ) : (
            <p className={styles.muted}>
              {run.exceptions_count === 0
                ? "This run has no exceptions."
                : "No exceptions match these filters."}
            </p>
          )}
          <Pagination
            page={filters.page}
            rowCount={visibleExceptions.length}
            hasNext={hasNext}
            onPageChange={(page) => updateFilters({ page })}
          />
        </>
      )}
    </div>
  );
}
