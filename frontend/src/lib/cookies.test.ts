import { describe, expect, test } from "bun:test";
import { readCookie } from "./cookies";

describe("readCookie", () => {
  test("reads the named cookie", () => {
    expect(readCookie("csrf_token", "session=abc; csrf_token=tok123")).toBe("tok123");
  });

  test("returns null when the cookie is absent", () => {
    expect(readCookie("csrf_token", "session=abc")).toBeNull();
  });

  test("does not match cookies that merely start with the name", () => {
    expect(readCookie("csrf", "csrf_token=tok123")).toBeNull();
  });

  test("keeps equals signs inside the value", () => {
    expect(readCookie("csrf_token", "csrf_token=tok=123; other=1")).toBe("tok=123");
  });

  test("handles an empty cookie string", () => {
    expect(readCookie("csrf_token", "")).toBeNull();
  });
});
