"use client";

import { useEffect } from "react";
import { fetchCurrentUser } from "@/lib/auth";

export default function HomePage() {
  useEffect(() => {
    fetchCurrentUser()
      .then((user) => window.location.replace(user ? "/workspaces" : "/login"))
      .catch(() => window.location.replace("/login"));
  }, []);

  return <p className="loading">Loading…</p>;
}
