import { useEffect, useState, type Dispatch } from "react";
import { apiErrorMessage } from "@/lib/auth";
import type { ExceptionItem } from "@/lib/exceptions";
import {
  ACTION_LABELS,
  NOTE_REQUIRED,
  availableActions,
  resolutionErrorMessage,
  roleForOrganizations,
  submitResolution,
  type ResolutionAction,
  type Role,
} from "@/lib/resolutions";
import { listOrganizations } from "@/lib/workspaces";
import styles from "./exceptions.module.css";

interface ExceptionActionsProps {
  exception: ExceptionItem;
  onUpdated: Dispatch<ExceptionItem>;
  onReload: () => void;
}

interface Failure {
  message: string;
  stale: boolean;
}

export default function ExceptionActions({
  exception,
  onUpdated,
  onReload,
}: ExceptionActionsProps) {
  const [role, setRole] = useState<Role>();
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<ResolutionAction | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);

  useEffect(() => {
    let ignore = false;
    listOrganizations()
      .then((organizations) => {
        if (!ignore) setRole(roleForOrganizations(organizations));
      })
      .catch(() => {
        // Without a role the server decides which actions are allowed.
      });
    return () => {
      ignore = true;
    };
  }, []);

  const actions = availableActions(exception.status, role);
  const noteNeeded = actions.some((action) => NOTE_REQUIRED[action]);

  async function runAction(action: ResolutionAction) {
    setPending(action);
    setFailure(null);
    try {
      const { data, error, response } = await submitResolution(
        exception.id,
        action,
        exception.version,
        note,
      );
      if (response.ok && data) {
        setNote("");
        onUpdated(data);
      } else {
        setFailure({
          message: resolutionErrorMessage(response.status, apiErrorMessage(error)),
          stale: response.status === 409,
        });
      }
    } catch {
      setFailure({ message: resolutionErrorMessage(undefined, ""), stale: false });
    } finally {
      setPending(null);
    }
  }

  return (
    <section className={styles.panel} aria-labelledby="exception-actions-heading">
      <h2 id="exception-actions-heading">Actions</h2>
      {actions.length === 0 ? (
        <p className={styles.muted}>No actions are available for this exception.</p>
      ) : (
        <>
          <div className={styles.field}>
            <label htmlFor="resolution-note">Note</label>
            <textarea
              id="resolution-note"
              rows={3}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              disabled={pending !== null}
              aria-describedby={noteNeeded ? "resolution-note-hint" : undefined}
            />
            {noteNeeded && (
              <p id="resolution-note-hint" className={styles.muted}>
                A note is required to propose, reject or reopen.
              </p>
            )}
          </div>
          <div className={styles.filters}>
            {actions.map((action) => (
              <button
                key={action}
                type="button"
                className={styles.button}
                onClick={() => runAction(action)}
                disabled={pending !== null || (NOTE_REQUIRED[action] && note.trim() === "")}
                aria-busy={pending === action}
              >
                {pending === action ? "Saving…" : ACTION_LABELS[action]}
              </button>
            ))}
          </div>
        </>
      )}
      {failure && (
        <div role="alert" className={styles.filters}>
          <p className={styles.error}>{failure.message}</p>
          {failure.stale && (
            <button type="button" className={styles.button} onClick={onReload}>
              Reload
            </button>
          )}
        </div>
      )}
    </section>
  );
}
