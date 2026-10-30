"use client";

import { use, useCallback, useEffect, useState } from "react";
import AppShell from "@/components/AppShell";
import BatchHistory from "@/components/BatchHistory";
import ImportWizard from "@/components/ImportWizard";
import { errorText } from "@/lib/errors";
import { listImports, type ImportBatchOut } from "@/lib/imports";

interface ImportsPageProps {
  params: Promise<{ workspaceId: string }>;
}

export default function ImportsPage({ params }: ImportsPageProps) {
  const { workspaceId } = use(params);
  const [batches, setBatches] = useState<ImportBatchOut[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    try {
      setBatches(await listImports(workspaceId));
      setHistoryError(null);
    } catch (err) {
      setHistoryError(errorText(err));
    }
  }, [workspaceId]);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  return (
    <AppShell>
      <div className="page-header">
        <h1>Imports</h1>
      </div>
      <ImportWizard workspaceId={workspaceId} onUploaded={loadHistory} />
      <BatchHistory batches={batches} error={historyError} />
    </AppShell>
  );
}
