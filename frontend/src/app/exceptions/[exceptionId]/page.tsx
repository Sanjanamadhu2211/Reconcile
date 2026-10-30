"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import AppShell from "@/components/AppShell";
import ExceptionActions from "@/components/exceptions/ExceptionActions";
import styles from "@/components/exceptions/exceptions.module.css";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/auth";
import {
  getCandidateIds,
  getCategoryLabel,
  getStatusLabel,
  type ExceptionItem,
} from "@/lib/exceptions";

type Load =
  | { state: "loading" }
  | { state: "ready"; exception: ExceptionItem }
  | { state: "missing" }
  | { state: "error"; message: string };

export default function ExceptionDetailPage() {
  return (
    <AppShell>
      <ExceptionDetail />
    </AppShell>
  );
}

function ExceptionDetail() {
  const { exceptionId } = useParams<{ exceptionId: string }>();
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    let ignore = false;
    setLoad({ state: "loading" });
    api
      .GET("/api/v1/exceptions/{exception_id}", {
        params: { path: { exception_id: exceptionId } },
      })
      .then(({ data, error, response }) => {
        if (ignore) return;
        if (response.status === 404) setLoad({ state: "missing" });
        else if (response.ok && data) setLoad({ state: "ready", exception: data });
        else setLoad({ state: "error", message: apiErrorMessage(error) });
      })
      .catch(() => {
        if (!ignore)
          setLoad({ state: "error", message: "Could not reach the server. Please try again." });
      });
    return () => {
      ignore = true;
    };
  }, [exceptionId]);

  if (load.state === "loading") {
    return (
      <div className={styles.page}>
        <p aria-live="polite">Loading…</p>
      </div>
    );
  }

  if (load.state === "missing") {
    return (
      <div className={styles.page}>
        <h1>Exception not found</h1>
        <p className={styles.muted}>
          This exception does not exist or you do not have access to it.
        </p>
        <p>
          <Link href="/workspaces" className={styles.link}>
            Back to workspaces
          </Link>
        </p>
      </div>
    );
  }

  if (load.state === "error") {
    return (
      <div className={styles.page}>
        <h1>Exception</h1>
        <p className={styles.error} role="alert">
          {load.message}
        </p>
      </div>
    );
  }

  const { exception } = load;
  const { transaction, import_row: importRow } = exception;
  const candidates = getCandidateIds(exception.details);

  return (
    <div className={styles.page}>
      <h1>{getCategoryLabel(exception.category)} exception</h1>
      <p className={styles.muted}>
        Status: {getStatusLabel(exception.status)} · Version {exception.version}
      </p>

      <section className={styles.panel} aria-labelledby="exception-record-heading">
        <h2 id="exception-record-heading">Record</h2>
        {transaction ? (
          <dl className={styles.details}>
            <dt>Source</dt>
            <dd>{transaction.source_name}</dd>
            <dt>External ID</dt>
            <dd>{transaction.external_id}</dd>
            <dt>Amount</dt>
            <dd>
              {transaction.amount} {transaction.currency}
            </dd>
            <dt>Occurred at</dt>
            <dd>{transaction.occurred_at}</dd>
          </dl>
        ) : (
          <dl className={styles.details}>
            <dt>Import batch</dt>
            <dd>{importRow?.batch_id}</dd>
            <dt>Row</dt>
            <dd>{importRow?.row_number}</dd>
          </dl>
        )}
      </section>

      {candidates.length > 0 && (
        <section className={styles.panel} aria-labelledby="exception-candidates-heading">
          <h2 id="exception-candidates-heading">Candidate records</h2>
          <ul className={styles.list}>
            {candidates.map((candidate) => (
              <li key={candidate}>{candidate}</li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.panel} aria-labelledby="exception-run-heading">
        <h2 id="exception-run-heading">Reconciliation run</h2>
        <p className={styles.muted}>{exception.reconciliation_run_id}</p>
      </section>

      <ExceptionActions />
    </div>
  );
}
