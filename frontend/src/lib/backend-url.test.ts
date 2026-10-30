import { getBackendUrl } from "./backend-url";
import { test, expect } from "bun:test";

test("backend-url", () => {
  expect(getBackendUrl(undefined)).toBe("http://localhost:8000");

  expect(getBackendUrl("  http://example.com/api  ")).toBe("http://example.com/api");

  expect(getBackendUrl("http://localhost:8000/")).toBe("http://localhost:8000");
  expect(getBackendUrl("http://example.com/path/")).toBe("http://example.com/path");

  expect(getBackendUrl("http://localhost:8000")).toBe("http://localhost:8000");
  expect(getBackendUrl("http://example.com/api")).toBe("http://example.com/api");
});
