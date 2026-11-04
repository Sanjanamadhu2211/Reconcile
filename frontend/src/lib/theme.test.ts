import { describe, expect, test } from "bun:test";
import { resolveTheme } from "./theme";

describe("resolveTheme", () => {
  test("uses a saved choice before the system preference", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });

  test("uses the system preference when no valid choice is saved", () => {
    expect(resolveTheme(null, true)).toBe("dark");
    expect(resolveTheme("unknown", false)).toBe("light");
  });
});
