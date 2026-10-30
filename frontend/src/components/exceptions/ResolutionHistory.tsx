import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/auth";
import { getDecisionLabel, type ResolutionOut } from "@/lib/resolutions";
import styles from "./exceptions.module.css";

interface ResolutionHistoryProps {
  exceptionId: string;
  version: number;
}

export default function ResolutionHistory({ exceptionId, version }: ResolutionHistoryProps) {
  const [history, setHistory] = useState<ResolutionOut[]>();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  // The version changes with every decision, so the timeline reloads after each action.
  useEffect(() => {
    let ignore = false;
    setError(null);
    api
      .GET("/api/v1/exceptions/{exception_id}/history", {
        params: { path: { exception_id: exceptionId } },
      })
      .then(({ data, error, response }) => {
        if (ignore) return;
        if (response.ok && data) setHistory(data);
        else setError(apiErrorMessage(error));
      })
      .catch(() => {
        if (!ignore) setError("Could not reach the server. Please try again.");
      });
    return () => {
      ignore = true;
    };
  }, [exceptionId, version, attempt]);

  return (
    <section className={styles.panel} aria-labelledby="exception-history-heading">
      <h2 id="exception-history-heading">History</h2>
      {error && (
        <>
          <p className={styles.error} role="alert">
            {error}
          </p>
          <button
            type="button"
            className={styles.button}
            onClick={() => setAttempt((current) => current + 1)}
          >
            Retry
          </button>
        </>
      )}
      {!error && history === undefined && <p className={styles.muted}>Loading history…</p>}
      {history?.length === 0 && <p className={styles.muted}>No decisions yet.</p>}
      {history && history.length > 0 && (
        <ol className={styles.timeline}>
          {history.map((item) => (
            <li key={item.exception_version}>
              <div className={styles.timelineHeader}>
                <strong>{getDecisionLabel(item.decision)}</strong>
                <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
              </div>
              <p className={styles.muted}>
                {item.actor_email ?? "Unknown"} · Version {item.exception_version}
              </p>
              {item.note && <p className={styles.note}>{item.note}</p>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
