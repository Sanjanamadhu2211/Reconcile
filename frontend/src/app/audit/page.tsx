"use client";

import { Suspense } from "react";
import AppShell from "@/components/AppShell";
import AuditTrail from "@/components/audit/AuditTrail";

export default function AuditPage() {
  return (
    <AppShell>
      <Suspense fallback={<p>Loading…</p>}>
        <AuditTrail />
      </Suspense>
    </AppShell>
  );
}
