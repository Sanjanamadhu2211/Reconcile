import { useEffect, useState } from "react";
import { chooseLatestCompletedRun, type ReconciliationRunSummary } from "@/lib/exceptions";
import { listReconciliationRuns } from "@/lib/workspaces";

export function useLatestRun(workspaceId: string) {
  const [run, setRun] = useState<ReconciliationRunSummary | null>();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let ignore = false;
    setRun(undefined);
    setError(null);
    listReconciliationRuns(workspaceId, 50)
      .then((runs) => {
        if (!ignore) setRun(chooseLatestCompletedRun(runs));
      })
      .catch((err: unknown) => {
        if (!ignore) setError(err instanceof Error ? err.message : "Could not load the run.");
      });
    return () => {
      ignore = true;
    };
  }, [workspaceId, attempt]);

  return { run, error, retry: () => setAttempt((count) => count + 1) };
}
