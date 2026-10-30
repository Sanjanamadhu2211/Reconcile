import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type User = components["schemas"]["UserOut"];

const GOOGLE_SIGN_IN_ERRORS: Record<string, string> = {
  google_invalid_state: "Your sign-in attempt expired. Please try again.",
  google_provider_error: "Google could not complete the sign-in. Please try again.",
  google_invalid_token: "Google sent an unexpected response. Please try again.",
  google_unverified_email: "Your Google account does not have a verified email address.",
  google_account_conflict:
    "This Google account belongs to a different account. Sign in with your password instead.",
};

export async function fetchCurrentUser(): Promise<User | null> {
  const { data, response } = await api.GET("/api/v1/auth/me");
  if (response.status === 401) return null;
  if (!data) throw new Error("Could not reach the server. Please try again.");
  return data;
}

export async function googleSignInEnabled(): Promise<boolean> {
  const { data, response } = await api.GET("/api/v1/auth/providers");
  if (!response.ok || typeof data !== "object" || data === null) return false;
  return "google" in data && data.google === true;
}

export async function login(email: string, password: string): Promise<User> {
  const { data, error, response } = await api.POST("/api/v1/auth/login", {
    body: { email, password },
  });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function register(email: string, password: string): Promise<User> {
  const { data, error, response } = await api.POST("/api/v1/auth/register", {
    body: { email, password },
  });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function logout(): Promise<void> {
  const { error, response } = await api.POST("/api/v1/auth/logout");
  if (!response.ok) throw new Error(apiErrorMessage(error));
}

export function apiErrorMessage(body: unknown): string {
  const detail = readDetail(body);
  if (typeof detail === "string") return detail;

  if (Array.isArray(detail)) {
    const messages = detail.map(describeValidationIssue).filter((message) => message.length > 0);
    if (messages.length > 0) return messages.join(" ");
  }

  return "Something went wrong. Please try again.";
}

export function authErrorMessage(code: string | null): string | null {
  if (!code) return null;
  return GOOGLE_SIGN_IN_ERRORS[code] ?? "Sign-in failed. Please try again.";
}

function readDetail(body: unknown): unknown {
  if (typeof body !== "object" || body === null) return undefined;
  return (body as { detail?: unknown }).detail;
}

function describeValidationIssue(issue: unknown): string {
  if (typeof issue !== "object" || issue === null) return "";
  const { msg, loc } = issue as { msg?: unknown; loc?: unknown };
  if (typeof msg !== "string") return "";
  const field = Array.isArray(loc) && typeof loc[1] === "string" ? `${loc[1]}: ` : "";
  return `${field}${msg}`;
}
