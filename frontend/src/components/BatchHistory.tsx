"use client";

import { useEffect, useState } from "react";
import {
  ERROR_PAGE_SIZE,
  listImportErrors,
  type ImportBatchOut,
  type ImportErrorOut,
} from "@/lib/imports";
import { errorText } from "@/lib/errors";

interface BatchHistoryProps {
  batches: ImportBatchOut[] | null;
  error: string | null;
}

export default function BatchHistory({ batches, error }: BatchHistoryProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = batches?.find((batch) => batch.id === selectedId) ?? batches?.[0] ?? null;

  return (
    <section className="table-section" aria-labelledby="batch-history-title">
      <h2 id="batch-history-title">Import history</h2>
      {error && <p className="form-error">{error}</p>}
      {batches === null && !error && <p className="loading">Loading…</p>}
      {batches?.length === 0 && <p className="empty-state">No imports yet.</p>}
      {batches && batches.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">File</th>
              <th scope="col">Source</th>
              <th scope="col">Status</th>
              <th scope="col">Rows</th>
              <th scope="col">Failed</th>
              <th scope="col">Started</th>
              <th scope="col">
                <span className="visually-hidden">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {batches.map((batch) => (
              <tr key={batch.id}>
                <td>{batch.filename ?? "—"}</td>
                <td>{batch.source_name}</td>
                <td>{batch.status}</td>
                <td>
                  {batch.rows_processed} of {batch.rows_total}
                </td>
                <td>{batch.rows_failed}</td>
                <td>{new Date(batch.created_at).toLocaleString()}</td>
                <td>
                  <button
                    type="button"
                    className="btn-secondary"
                    aria-pressed={selected?.id === batch.id}
                    onClick={() => setSelectedId(batch.id)}
                  >
                    Errors
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected && <BatchErrors key={selected.id} batch={selected} />}
    </section>
  );
}

function BatchErrors({ batch }: { batch: ImportBatchOut }) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<ImportErrorOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listImportErrors(batch.id, offset)
      .then((found) => {
        if (!active) return;
        setRows(found);
        setError(null);
      })
      .catch((err) => {
        if (active) setError(errorText(err));
      });
    return () => {
      active = false;
    };
  }, [batch.id, offset]);

  return (
    <section id="import-errors" className="table-section" aria-labelledby="import-errors-title">
      <h3 id="import-errors-title">Row errors for {batch.filename ?? "this import"}</h3>
      {error && <p className="form-error">{error}</p>}
      {rows?.length === 0 && offset === 0 && <p className="empty-state">No row errors.</p>}
      {rows && rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th scope="col">Row</th>
              <th scope="col">Status</th>
              <th scope="col">Error code</th>
              <th scope="col">Detail</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.row_number}>
                <td>{row.row_number}</td>
                <td>{row.validation_status}</td>
                <td>{row.error_code ?? "—"}</td>
                <td>{row.error_detail ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="pagination-controls">
        <button
          type="button"
          onClick={() => setOffset(Math.max(0, offset - ERROR_PAGE_SIZE))}
          disabled={offset === 0}
        >
          Previous
        </button>
        <button
          type="button"
          onClick={() => setOffset(offset + ERROR_PAGE_SIZE)}
          disabled={!rows || rows.length < ERROR_PAGE_SIZE}
        >
          Next
        </button>
      </div>
    </section>
  );
}
