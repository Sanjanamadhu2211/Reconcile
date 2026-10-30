"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { register } from "@/lib/auth";

export default function RegisterPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await register(email, password);
      window.location.assign("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <h1>Create an account</h1>
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
          autoComplete="new-password"
          minLength={10}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <p className="field-hint">At least 10 characters.</p>
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="auth-switch">
        Already have an account? <Link href="/login">Sign in</Link>
      </p>
    </main>
  );
}
