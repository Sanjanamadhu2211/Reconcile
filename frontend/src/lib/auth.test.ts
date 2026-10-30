import { describe, expect, test } from "bun:test";
import { apiErrorMessage, authErrorMessage } from "./auth";

describe("authErrorMessage", () => {
  test("maps each Google sign-in code to a friendly message", () => {
    expect(authErrorMessage("google_invalid_state")).toBe(
      "Your sign-in attempt expired. Please try again.",
    );
    expect(authErrorMessage("google_unverified_email")).toBe(
      "Your Google account does not have a verified email address.",
    );
    expect(authErrorMessage("google_account_conflict")).toContain("password");
  });

  test("falls back to a generic message for unknown codes", () => {
    expect(authErrorMessage("google_something_new")).toBe("Sign-in failed. Please try again.");
  });

  test("returns null when there is no error code", () => {
    expect(authErrorMessage(null)).toBeNull();
    expect(authErrorMessage("")).toBeNull();
  });
});

describe("apiErrorMessage", () => {
  test("reads a plain detail string", () => {
    expect(apiErrorMessage({ detail: "Invalid email or password" })).toBe(
      "Invalid email or password",
    );
  });

  test("reads field validation messages", () => {
    const body = {
      detail: [{ loc: ["body", "password"], msg: "String should have at least 10 characters" }],
    };
    expect(apiErrorMessage(body)).toBe("password: String should have at least 10 characters");
  });

  test("falls back when the body is not an error envelope", () => {
    expect(apiErrorMessage(undefined)).toBe("Something went wrong. Please try again.");
  });
});
