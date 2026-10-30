"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import Pagination from "@/components/exceptions/Pagination";
import RunSummary from "@/components/exceptions/RunSummary";
import styles from "@/components/exceptions/exceptions.module.css";
import { useLatestRun } from "@/components/exceptions/useLatestRun";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { apiErrorMessage } from "@/lib/auth";
import {
  MATCH_RULE_LABELS,
  MATCH_RULES,
  PAGE_SIZE,
  buildMatchQueryString,
  getRuleLabel,
  matchesRequestQuery,
  parseMatchFilters,
  type MatchFilters,
} from "@/lib/exceptions";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

type MatchItem = components["schemas"]["MatchItem"];
type TransactionSummary = components["schemas"]["TransactionSummary"];

export default function MatchesPage() {
  useDocumentTitle("Matches");
  return (
    <AppShell>
      <Suspense fallback={<p>Loading…</p>}>
        <Matches />
      </Suspense>
    </AppShell>
  );
}

function Matches() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const query = useSearchParams().toString();
  const filters = useMemo(() => parseMatchFilters(new URLSearchParams(query)), [query]);
  const { run, error: runError, retry: retryRun } = useLatestRun(workspaceId);
  const runId = run?.id;

  const [matches, setMatches] = useState<MatchItem[]>();
  const [matchesError, setMatchesError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!runId) return;
    let ignore = false;
    setMatches(undefined);
    setMatchesError(null);
    api
      .GET("/api/v1/reconciliation-runs/{run_id}/matches", {
        params: { path: { run_id: runId }, query: matchesRequestQuery(filters) },
      })
      .then(({ data, error, response }) => {
        if (ignore) return;
        if (response.ok && data) setMatches(data);
        else setMatchesError(apiErrorMessage(error));
      })
      .catch(() => {
        if (!ignore) setMatchesError("Could not reach the server. Please try again.");
      });
    return () => {
      ignore = true;
    };
  }, [runId, filters, attempt]);

  const updateFilters = useCallback(
    (changes: Partial<MatchFilters>) => {
      const current = parseMatchFilters(new URLSearchParams(window.location.search));
      const next = buildMatchQueryString({ ...current, ...changes });
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  if (runError) {
    return (
      <div className={styles.page}>
        <h1>Matches</h1>
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
        <h1>Matches</h1>
        <p aria-live="polite">Loading…</p>
      </div>
    );
  }

  if (run === null) {
    return (
      <div className={styles.page}>
        <h1>Matches</h1>
        <section className={styles.panel}>
          <h2>No completed run yet</h2>
          <p className={styles.muted}>
            Run reconciliation from the workspace page to see matches here.
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

  const visibleMatches = matches?.slice(0, PAGE_SIZE) ?? [];
  const hasNext = (matches?.length ?? 0) > PAGE_SIZE;

  return (
    <div className={styles.page}>
      <h1>Matches</h1>
      <RunSummary workspaceId={workspaceId} run={run} active="matches" />
      <div role="search" className={styles.filters}>
        <div className={styles.field}>
          <label htmlFor="match-rule">Rule</label>
          <select
            id="match-rule"
            value={filters.rule}
            onChange={(event) =>
              updateFilters({ rule: event.target.value as MatchFilters["rule"], page: 1 })
            }
          >
            <option value="">All rules</option>
            {MATCH_RULES.map((rule) => (
              <option key={rule} value={rule}>
                {MATCH_RULE_LABELS[rule]}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div aria-live="polite">
        {matchesError && (
          <p role="alert" className={styles.error}>
            {matchesError}{" "}
            <button
              type="button"
              className={styles.button}
              onClick={() => setAttempt((n) => n + 1)}
            >
              Try again
            </button>
          </p>
        )}
        {!matchesError && matches === undefined && <p aria-busy="true">Loading matches…</p>}
      </div>
      {!matchesError && matches !== undefined && (
        <>
          {visibleMatches.length > 0 ? (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <caption className={styles.visuallyHidden}>Matches for the latest run</caption>
                <thead>
                  <tr>
                    <th scope="col">Rule</th>
                    <th scope="col">Left</th>
                    <th scope="col">Right</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleMatches.map((match) => (
                    <tr key={match.id}>
                      <td>{getRuleLabel(match.rule)}</td>
                      <td>
                        <TransactionCell transaction={match.left_transaction} />
                      </td>
                      <td>
                        <TransactionCell transaction={match.right_transaction} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className={styles.muted}>
              {filters.rule ? "No matches use this rule." : "This run has no matches."}
            </p>
          )}
          <Pagination
            page={filters.page}
            rowCount={visibleMatches.length}
            hasNext={hasNext}
            onPageChange={(page) => updateFilters({ page })}
          />
        </>
      )}
    </div>
  );
}

function TransactionCell({ transaction }: { transaction: TransactionSummary }) {
  return (
    <>
      <span className={styles.stacked}>
        {transaction.source_name} · {transaction.external_id}
      </span>
      <span className={styles.stacked}>
        {transaction.amount} {transaction.currency}
      </span>
      <span className={styles.stacked}>{transaction.occurred_at}</span>
    </>
  );
}
