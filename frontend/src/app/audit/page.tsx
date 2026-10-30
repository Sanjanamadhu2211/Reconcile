"use client";

import { Suspense } from "react";
import AppShell from "@/components/AppShell";
import AuditTrail from "@/components/audit/AuditTrail";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

export default function AuditPage() {
  useDocumentTitle("Audit trail");
  return (
    <AppShell>
      <Suspense fallback={<p>Loading…</p>}>
        <AuditTrail />
      </Suspense>
    </AppShell>
  );
}
