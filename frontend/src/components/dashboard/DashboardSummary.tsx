import Link from "next/link";
import {
  batchTiles,
  exceptionTiles,
  formatMatchRate,
  isEmptyDashboard,
  matchRatePercent,
} from "@/lib/dashboard";
import type { WorkspaceSummary } from "@/lib/workspaces";
import styles from "./dashboard.module.css";

interface DashboardSummaryProps {
  workspaceId: string;
  summary: WorkspaceSummary | null;
  error: string | null;
  onRetry: () => void;
}

export default function DashboardSummary({
  workspaceId,
  summary,
  error,
  onRetry,
}: DashboardSummaryProps) {
  if (error) {
    return (
      <section className={styles.panel}>
        <p role="alert" className="form-error">
          {error}
        </p>
        <button type="button" className="retry-button" onClick={onRetry}>
          Retry
        </button>
      </section>
    );
  }

  if (!summary) {
    return (
      <div className={styles.dashboard} aria-busy="true">
        <span className="visually-hidden">Loading dashboard…</span>
        <div className={styles.skeleton} />
        <div className={styles.skeleton} />
        <div className={`${styles.skeleton} ${styles.wide}`} />
      </div>
    );
  }

  if (isEmptyDashboard(summary)) {
    return (
      <section className={styles.panel} aria-labelledby="get-started-title">
        <h2 id="get-started-title">Get started</h2>
        <ol className={styles.steps}>
          <li>
            <Link href={`/workspaces/${workspaceId}/imports`} className="action-link">
              Import a file
            </Link>{" "}
            with orders, payments, refunds, settlements or fees.
          </li>
          <li>Run reconciliation below to match the rows and list the exceptions.</li>
        </ol>
      </section>
    );
  }

  const { imports, latest_run: run, exceptions } = summary;
  const percent = matchRatePercent(run?.match_rate ?? null);
  const tiles = exceptionTiles(workspaceId, exceptions);

  return (
    <div className={styles.dashboard}>
      <section className={styles.panel} aria-labelledby="import-health-title">
        <h2 id="import-health-title">Import health</h2>
        <dl className={styles.stats}>
          {batchTiles(imports.batches_by_status).map(({ key, label, value }) => (
            <Stat key={key} label={label} value={value} />
          ))}
          <Stat label="Rows imported" value={imports.rows_imported} />
          <Stat label="Invalid rows" value={imports.rows_invalid} />
        </dl>
      </section>

      <section className={styles.panel} aria-labelledby="latest-run-title">
        <h2 id="latest-run-title">Latest run</h2>
        {run ? (
          <>
            <dl className={styles.stats}>
              <Stat
                label="Completed"
                value={run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}
              />
              <Stat label="Matches" value={run.matches_count} />
              <Stat label="Exceptions" value={run.exceptions_count} />
            </dl>
            <p className={styles.rate}>
              Match rate <strong>{formatMatchRate(run.match_rate)}</strong>
            </p>
            {percent !== null && (
              <div
                className={styles.bar}
                role="img"
                aria-label={`Match rate ${formatMatchRate(run.match_rate)}`}
              >
                <div className={styles.barFill} style={{ width: `${percent}%` }} />
              </div>
            )}
          </>
        ) : (
          <p className={styles.muted}>
            No completed run yet. Run reconciliation to see the match rate.
          </p>
        )}
      </section>

      <section className={`${styles.panel} ${styles.wide}`} aria-labelledby="recent-imports-title">
        <div className={styles.panelHeader}>
          <h2 id="recent-imports-title">Recent imports</h2>
          <Link href={`/workspaces/${workspaceId}/imports`} className="action-link">
            All imports
          </Link>
        </div>
        {imports.recent_batches.length === 0 ? (
          <p className={styles.muted}>No imports yet.</p>
        ) : (
          <div className={styles.tableScroll}>
            <table>
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                  <th scope="col">Rows</th>
                  <th scope="col">Failed</th>
                  <th scope="col">Started</th>
                </tr>
              </thead>
              <tbody>
                {imports.recent_batches.map((batch) => (
                  <tr key={batch.id}>
                    <td>{batch.filename ?? "—"}</td>
                    <td>{batch.source_name}</td>
                    <td>
                      <span className={`badge badge-${batch.status}`}>{batch.status}</span>
                    </td>
                    <td>{batch.rows_total}</td>
                    <td>{batch.rows_failed}</td>
                    <td>{new Date(batch.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className={`${styles.panel} ${styles.wide}`} aria-labelledby="exceptions-title">
        <h2 id="exceptions-title">Exceptions in latest run</h2>
        {run ? (
          <div className={styles.groups}>
            <TileGroup title="By status" tiles={tiles.statuses} />
            <TileGroup title="By category" tiles={tiles.categories} />
          </div>
        ) : (
          <p className={styles.muted}>Exception counts appear after the first run.</p>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className={styles.stat}>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function TileGroup({
  title,
  tiles,
}: {
  title: string;
  tiles: { key: string; label: string; value: number; href: string }[];
}) {
  return (
    <div>
      <h3 className={styles.groupTitle}>{title}</h3>
      <ul className={styles.tiles}>
        {tiles.map(({ key, label, value, href }) => (
          <li key={key}>
            <Link href={href} className={styles.tile}>
              <span>{label}</span>
              <strong>{value}</strong>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
