"use client";

import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import {
  POLL_INTERVAL_MS,
  REQUIRED_HEADERS,
  SOURCE_NAMES,
  calculateProgress,
  describeImportError,
  idempotencyKeyFor,
  listImports,
  matchPollingBatch,
  previewImport,
  uploadImport,
  validateFile,
  type ImportBatchOut,
  type ImportPreviewOut,
  type SourceName,
} from "@/lib/imports";

type Step = "choose" | "preview" | "upload";

const STEPS: { id: Step; label: string }[] = [
  { id: "choose", label: "Choose file" },
  { id: "preview", label: "Preview" },
  { id: "upload", label: "Upload" },
];

const PROBLEM_LIMIT = 20;

interface ImportWizardProps {
  workspaceId: string;
  onUploaded: () => void;
}

export default function ImportWizard({ workspaceId, onUploaded }: ImportWizardProps) {
  const [step, setStep] = useState<Step>("choose");
  const [source, setSource] = useState<SourceName>("orders");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [preview, setPreview] = useState<ImportPreviewOut | null>(null);
  const [pending, setPending] = useState<"preview" | "upload" | null>(null);
  const [error, setError] = useState<{ message: string; retryable: boolean } | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null);
  const [uploadStartedAt, setUploadStartedAt] = useState<Date | null>(null);
  const [liveBatch, setLiveBatch] = useState<ImportBatchOut | null>(null);
  const [result, setResult] = useState<ImportBatchOut | null>(null);

  function resetUpload() {
    setIdempotencyKey(null);
    setUploadStartedAt(null);
    setLiveBatch(null);
    setResult(null);
    setError(null);
  }

  function handleSourceChange(event: ChangeEvent<HTMLSelectElement>) {
    setSource(event.target.value as SourceName);
    resetUpload();
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    setFile(chosen);
    setFileError(chosen ? validateFile(chosen) : null);
    resetUpload();
  }

  async function continueToPreview(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    const problem = validateFile(file);
    setFileError(problem);
    if (problem) return;

    setPending("preview");
    setError(null);
    try {
      setPreview(await previewImport(workspaceId, source, file));
      setStep("preview");
    } catch (err) {
      setError(describeImportError(err));
    } finally {
      setPending(null);
    }
  }

  async function startUpload() {
    if (!file) return;
    const key = idempotencyKeyFor(idempotencyKey);
    const startedAt = uploadStartedAt ?? new Date();
    setIdempotencyKey(key);
    setUploadStartedAt(startedAt);
    setLiveBatch(null);
    setResult(null);
    setError(null);
    setStep("upload");
    setPending("upload");
    try {
      const batch = await uploadImport(workspaceId, source, file, key);
      setResult(batch);
      onUploaded();
    } catch (err) {
      setError(describeImportError(err));
    } finally {
      setPending(null);
    }
  }

  useEffect(() => {
    if (pending !== "upload" || !file || !uploadStartedAt) return;
    const { name } = file;
    const startedAt = uploadStartedAt;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;

    async function poll() {
      const batches = await listImports(workspaceId, 5).catch(() => null);
      if (!active) return;
      if (batches) setLiveBatch(matchPollingBatch(batches, name, startedAt));
      timer = setTimeout(poll, POLL_INTERVAL_MS);
    }

    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [pending, workspaceId, file, uploadStartedAt]);

  const missingHeaders =
    preview?.headers_required.filter((header) => !preview.headers_found.includes(header)) ?? [];
  const currentIndex = STEPS.findIndex((item) => item.id === step);

  return (
    <section className="card" aria-labelledby="new-import-title">
      <h2 id="new-import-title" className="card-title">
        New import
      </h2>
      <ol className="stepper">
        {STEPS.map((item, index) => (
          <li
            key={item.id}
            className={`stepper-step${index < currentIndex ? " completed" : ""}${index === currentIndex ? " active" : ""}`}
            aria-current={index === currentIndex ? "step" : undefined}
          >
            <span className="stepper-circle" aria-hidden="true">
              {index + 1}
            </span>
            <span className="stepper-label">{item.label}</span>
          </li>
        ))}
      </ol>

      {step === "choose" && (
        <form className="form-group" onSubmit={continueToPreview}>
          <label htmlFor="import-source">Source</label>
          <select
            id="import-source"
            value={source}
            onChange={handleSourceChange}
            disabled={pending !== null}
          >
            {SOURCE_NAMES.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <p className="form-hint" id="required-headers">
            Required headers: {REQUIRED_HEADERS[source].join(", ")}
          </p>
          <label htmlFor="import-file">CSV file</label>
          <input
            id="import-file"
            type="file"
            accept=".csv,text/csv"
            required
            aria-describedby="required-headers"
            onChange={handleFileChange}
            disabled={pending !== null}
          />
          <div aria-live="polite">
            {fileError && (
              <p role="alert" className="form-error">
                {fileError}
              </p>
            )}
            {error && (
              <p role="alert" className="form-error">
                {error.message}
              </p>
            )}
          </div>
          <button type="submit" className="btn" disabled={pending !== null}>
            {pending === "preview" ? "Checking file…" : "Preview"}
          </button>
        </form>
      )}

      {step === "preview" && preview && (
        <div>
          <p>
            Valid rows: {preview.valid_rows}. Invalid rows: {preview.invalid_rows}.
          </p>
          <p>Missing headers: {missingHeaders.length > 0 ? missingHeaders.join(", ") : "none"}</p>
          <p>Headers found: {preview.headers_found.join(", ") || "none"}</p>
          {preview.problems.length > 0 && (
            <>
              <h3>
                Problem rows
                {preview.problems.length > PROBLEM_LIMIT &&
                  ` (first ${PROBLEM_LIMIT} of ${preview.problems.length})`}
              </h3>
              <table>
                <thead>
                  <tr>
                    <th scope="col">Row</th>
                    <th scope="col">Status</th>
                    <th scope="col">Error code</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.problems.slice(0, PROBLEM_LIMIT).map((problem) => (
                    <tr key={problem.row_number}>
                      <td>{problem.row_number}</td>
                      <td>{problem.validation_status}</td>
                      <td>{problem.error_code ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <div className="page-actions">
            <button type="button" className="btn-secondary" onClick={() => setStep("choose")}>
              Back
            </button>
            <button type="button" className="btn" onClick={startUpload}>
              Upload file
            </button>
          </div>
        </div>
      )}

      {step === "upload" && (
        <div>
          {pending === "upload" && (
            <div aria-live="polite">
              <div
                className="progress-bar"
                role="progressbar"
                aria-label="Import progress"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={liveBatch ? calculateProgress(liveBatch) : 0}
              >
                <div
                  className="progress-fill"
                  style={{ width: `${liveBatch ? calculateProgress(liveBatch) : 0}%` }}
                />
              </div>
              <p>
                {liveBatch
                  ? `${liveBatch.rows_processed} of ${liveBatch.rows_total} rows processed`
                  : "Starting the import…"}
              </p>
            </div>
          )}
          {result && (
            <div aria-live="polite">
              <p>
                Import {result.status}: {result.rows_processed} of {result.rows_total} rows
                processed, {result.rows_failed} failed.
              </p>
              {result.error_summary && (
                <p role="alert" className="form-error">
                  {result.error_summary}
                </p>
              )}
              <a href="#import-errors" className="action-link">
                View row errors
              </a>
            </div>
          )}
          {error && (
            <div aria-live="polite">
              <p role="alert" className="form-error">
                {error.message}
              </p>
              {error.retryable ? (
                <button type="button" className="retry-button" onClick={startUpload}>
                  Try again
                </button>
              ) : (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    resetUpload();
                    setStep("choose");
                  }}
                >
                  Choose another file
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
