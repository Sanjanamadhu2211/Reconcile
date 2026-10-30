"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import DashboardSummary from "@/components/dashboard/DashboardSummary";
import ExportLinks from "@/components/ExportLinks";
import { errorText } from "@/lib/errors";
import { useDocumentTitle } from "@/lib/useDocumentTitle";
import {
  createReconciliationRun,
  getWorkspace,
  getWorkspaceSummary,
  listReconciliationRuns,
  type ReconciliationRunOut,
  type ReconciliationRunSummary,
  type WorkspaceOut,
  type WorkspaceSummary,
} from "@/lib/workspaces";

interface WorkspacePageProps {
  params: Promise<{ workspaceId: string }>;
}

export default function WorkspacePage({ params }: WorkspacePageProps) {
  const { workspaceId } = use(params);
  const [workspace, setWorkspace] = useState<WorkspaceOut | null>(null);
  useDocumentTitle(workspace?.name ?? "Workspace");
  const [runs, setRuns] = useState<ReconciliationRunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [runResult, setRunResult] = useState<ReconciliationRunOut | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const loadSummary = useCallback(async () => {
    setSummaryError(null);
    try {
      setSummary(await getWorkspaceSummary(workspaceId));
    } catch (err) {
      setSummaryError(errorText(err));
    }
  }, [workspaceId]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [found, history] = await Promise.all([
        getWorkspace(workspaceId),
        listReconciliationRuns(workspaceId),
      ]);
      setWorkspace(found);
      setRuns(history);
    } catch (err) {
      setError(errorText(err));
    }
  }, [workspaceId]);

  async function runReconciliation() {
    setRunning(true);
    setRunResult(null);
    setRunError(null);
    try {
      setRunResult(await createReconciliationRun(workspaceId));
      setRuns(await listReconciliationRuns(workspaceId));
      await loadSummary();
    } catch (err) {
      setRunError(errorText(err));
    } finally {
      setRunning(false);
    }
  }

  useEffect(() => {
    load();
    loadSummary();
  }, [load, loadSummary]);

  return (
    <AppShell>
      <div aria-live="polite">
        {error && (
          <>
            <p role="alert" className="form-error">
              {error}
            </p>
            <button type="button" className="retry-button" onClick={load}>
              Retry
            </button>
          </>
        )}
      </div>
      {!workspace && !error && (
        <p className="loading" aria-busy="true">
          Loading…
        </p>
      )}
      {workspace && (
        <>
          <div className="page-header">
            <h1>{workspace.name}</h1>
            <div className="page-actions">
              <Link href={`/workspaces/${workspaceId}/imports`} className="action-link">
                Imports
              </Link>
              <Link href={`/workspaces/${workspaceId}/exceptions`} className="action-link">
                Exceptions
              </Link>
            </div>
          </div>
          <p>Timestamp tolerance: {workspace.timestamp_tolerance_hours} hours</p>

          <DashboardSummary
            workspaceId={workspaceId}
            summary={summary}
            error={summaryError}
            onRetry={loadSummary}
          />

          <section className="card">
            <h2 className="card-title">Reconciliation</h2>
            <button type="button" className="btn" onClick={runReconciliation} disabled={running}>
              {running ? "Running…" : "Run reconciliation"}
            </button>
            <div aria-live="polite">
              {runError && (
                <p role="alert" className="form-error">
                  {runError}
                </p>
              )}
              {runResult && (
                <p>
                  Run {runResult.status}: {runResult.matches_count} matches,{" "}
                  {runResult.exceptions_count} exceptions.
                </p>
              )}
            </div>
          </section>

          <section className="card">
            <h2 className="card-title">Exports</h2>
            <ExportLinks workspaceId={workspaceId} />
          </section>

          <section className="table-section">
            <h2>Recent runs</h2>
            {runs.length === 0 ? (
              <p className="empty-state">No runs yet.</p>
            ) : (
              <div className="table-wrapper">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Status</th>
                      <th scope="col">Matches</th>
                      <th scope="col">Exceptions</th>
                      <th scope="col">Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.id}>
                        <td>{run.status}</td>
                        <td>{run.matches_count}</td>
                        <td>{run.exceptions_count}</td>
                        <td>{run.started_at ? new Date(run.started_at).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </AppShell>
  );
}
