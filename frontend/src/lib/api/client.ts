import createClient from "openapi-fetch";
import { readCookie } from "../cookies";
import type { paths } from "./schema";

const CSRF_COOKIE = "csrf_token";
const CSRF_HEADER = "X-CSRF-Token";
const STATE_CHANGING_METHODS = ["POST", "PUT", "PATCH", "DELETE"];

export function addCsrfHeader(request: Request, cookieString: string): void {
  if (!STATE_CHANGING_METHODS.includes(request.method)) return;
  const token = readCookie(CSRF_COOKIE, cookieString);
  if (token) {
    request.headers.set(CSRF_HEADER, token);
  }
}

export const api = createClient<paths>({
  baseUrl: "",
  credentials: "same-origin",
});

api.use({
  onRequest: ({ request }) => {
    addCsrfHeader(request, typeof document === "undefined" ? "" : document.cookie);
  },
});
