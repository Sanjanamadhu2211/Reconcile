import { describe, expect, test } from "bun:test";
import { addCsrfHeader } from "./client";

describe("addCsrfHeader", () => {
  test("adds the CSRF header to state-changing requests", () => {
    const request = new Request("http://localhost/api/v1/auth/logout", { method: "POST" });
    addCsrfHeader(request, "session=abc; csrf_token=tok123");
    expect(request.headers.get("X-CSRF-Token")).toBe("tok123");
  });

  test("leaves read-only requests without the header", () => {
    const request = new Request("http://localhost/api/v1/auth/me", { method: "GET" });
    addCsrfHeader(request, "session=abc; csrf_token=tok123");
    expect(request.headers.get("X-CSRF-Token")).toBeNull();
  });

  test("sends nothing when the CSRF cookie is missing", () => {
    const request = new Request("http://localhost/api/v1/auth/logout", { method: "POST" });
    addCsrfHeader(request, "session=abc");
    expect(request.headers.get("X-CSRF-Token")).toBeNull();
  });
});
