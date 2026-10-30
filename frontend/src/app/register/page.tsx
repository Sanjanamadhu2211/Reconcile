"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import styles from "@/components/auth/auth.module.css";
import { register } from "@/lib/auth";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

export default function RegisterPage() {
  useDocumentTitle("Create account");
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
    <main className={styles.page}>
      <h1>Create an account</h1>
      <div aria-live="polite" className="error-region">
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
      </div>
      <form className={styles.form} onSubmit={handleSubmit}>
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
          aria-describedby="password-hint"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <p id="password-hint" className={styles.hint}>
          At least 10 characters.
        </p>
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className={styles.switch}>
        Already have an account? <Link href="/login">Sign in</Link>
      </p>
    </main>
  );
}
