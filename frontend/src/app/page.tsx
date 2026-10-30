"use client";

import { useEffect, useState } from "react";
import { fetchCurrentUser, logout, type User } from "@/lib/auth";

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    fetchCurrentUser()
      .then((found) => {
        if (found === null) {
          window.location.replace("/login");
        } else {
          setUser(found);
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
      })
      .finally(() => setLoading(false));
  }, []);

  async function handleLogout() {
    setLoggingOut(true);
    setError(null);
    try {
      await logout();
      window.location.assign("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not log out. Please try again.");
      setLoggingOut(false);
    }
  }

  if (loading) {
    return (
      <main className="home-page">
        <p aria-live="polite">Loading…</p>
      </main>
    );
  }

  return (
    <main className="home-page">
      <h1>Reconcile</h1>
      <div aria-live="polite" className="error-region">
        {error && <p className="form-error">{error}</p>}
      </div>
      {user && (
        <>
          <p className="signed-in-as">Signed in as {user.email}</p>
          <button type="button" onClick={handleLogout} disabled={loggingOut}>
            {loggingOut ? "Logging out…" : "Log out"}
          </button>
        </>
      )}
    </main>
  );
}
