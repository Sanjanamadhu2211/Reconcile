"use client";

import { useEffect } from "react";
import { fetchCurrentUser } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

export default function HomePage() {
  useDocumentTitle();

  useEffect(() => {
    fetchCurrentUser()
      .then((user) => window.location.replace(user ? "/workspaces" : "/login"))
      .catch(() => window.location.replace("/login"));
  }, []);

  return <p className="loading">Loading…</p>;
}
