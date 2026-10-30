"use client";

import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { authErrorMessage, googleSignInEnabled, login } from "@/lib/auth";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    setError(authErrorMessage(new URLSearchParams(window.location.search).get("error")));
    googleSignInEnabled().then(setGoogleEnabled);
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <h1>Sign in</h1>
      <div aria-live="polite" className="error-region">
        {error && <p className="form-error">{error}</p>}
      </div>
      <form className="auth-form" onSubmit={handleSubmit}>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
      {googleEnabled && (
        <a className="button-link" href="/api/v1/auth/google/login">
          Continue with Google
        </a>
      )}
      <p className="auth-switch">
        No account yet? <Link href="/register">Create one</Link>
      </p>
    </main>
  );
}
