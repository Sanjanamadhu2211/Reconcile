import Link from "next/link";
import type { ReconciliationRunSummary } from "@/lib/exceptions";
import styles from "./exceptions.module.css";

interface RunSummaryProps {
  workspaceId: string;
  run: ReconciliationRunSummary;
  active: "exceptions" | "matches";
}

export default function RunSummary({ workspaceId, run, active }: RunSummaryProps) {
  const tabClass = (tab: RunSummaryProps["active"]) =>
    tab === active ? `${styles.tab} ${styles.tabActive}` : styles.tab;

  return (
    <section className={styles.panel} aria-label="Reconciliation run">
      <dl className={styles.summary}>
        <div>
          <dt>Matches</dt>
          <dd>{run.matches_count}</dd>
        </div>
        <div>
          <dt>Exceptions</dt>
          <dd>{run.exceptions_count}</dd>
        </div>
        <div>
          <dt>Rule version</dt>
          <dd>{run.rule_version}</dd>
        </div>
      </dl>
      <nav aria-label="Run views" className={styles.tabs}>
        <Link
          href={`/workspaces/${workspaceId}/exceptions`}
          className={tabClass("exceptions")}
          aria-current={active === "exceptions" ? "page" : undefined}
        >
          Exceptions
        </Link>
        <Link
          href={`/workspaces/${workspaceId}/matches`}
          className={tabClass("matches")}
          aria-current={active === "matches" ? "page" : undefined}
        >
          Matches
        </Link>
      </nav>
    </section>
  );
}
