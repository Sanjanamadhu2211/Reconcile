"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { fetchCurrentUser, logout, type User } from "@/lib/auth";
import { errorText } from "@/lib/errors";

interface AppShellProps {
  children: ReactNode;
}

export default function AppShell({ children }: AppShellProps) {
  const [user, setUser] = useState<User | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  async function loadUser() {
    setError(null);
    try {
      const found = await fetchCurrentUser();
      if (found === null) {
        window.location.replace("/login");
        return;
      }
      setUser(found);
      setLoaded(true);
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function handleLogout() {
    setLoggingOut(true);
    setError(null);
    try {
      await logout();
      window.location.assign("/login");
    } catch (err) {
      setError(errorText(err));
      setLoggingOut(false);
    }
  }

  useEffect(() => {
    loadUser();
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <Link href="/workspaces" className="app-title">
            Reconcile
          </Link>
          <nav className="app-nav" aria-label="Main navigation">
            <Link href="/workspaces" className="nav-link">
              Workspaces
            </Link>
            <Link href="/audit" className="nav-link">
              Audit
            </Link>
          </nav>
          {user && (
            <div className="app-user">
              <span className="user-email">{user.email}</span>
              <button
                type="button"
                className="logout-button"
                onClick={handleLogout}
                disabled={loggingOut}
                aria-busy={loggingOut}
              >
                {loggingOut ? "Logging out…" : "Log out"}
              </button>
            </div>
          )}
        </div>
      </header>
      <main className="app-main">
        <div aria-live="polite" className="error-region">
          {error && <p className="form-error">{error}</p>}
        </div>
        {error && !loaded && (
          <button type="button" className="retry-button" onClick={loadUser}>
            Try again
          </button>
        )}
        {loaded && children}
        {!loaded && !error && <p className="loading">Loading…</p>}
      </main>
    </div>
  );
}
