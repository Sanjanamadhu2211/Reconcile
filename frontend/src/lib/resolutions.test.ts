import { describe, expect, test } from "bun:test";
import {
  availableActions,
  getDecisionLabel,
  resolutionBody,
  resolutionErrorMessage,
  roleForOrganizations,
  type ResolutionAction,
} from "./resolutions";

describe("availableActions", () => {
  const cases: [string, "analyst" | "reviewer" | undefined, ResolutionAction[]][] = [
    ["open", "analyst", ["propose"]],
    ["open", "reviewer", ["propose"]],
    ["open", undefined, ["propose"]],
    ["proposed", "analyst", []],
    ["proposed", "reviewer", ["approve", "reject"]],
    ["proposed", undefined, ["approve", "reject"]],
    ["resolved", "analyst", []],
    ["resolved", "reviewer", ["reopen"]],
    ["resolved", undefined, ["reopen"]],
    ["unknown", "reviewer", []],
  ];

  test.each(cases)("status %s for role %s", (status, role, expected) => {
    expect(availableActions(status, role)).toEqual(expected);
  });
});

describe("roleForOrganizations", () => {
  const organization = (role: "analyst" | "reviewer") => ({ id: "org-1", name: "Acme", role });

  test("returns the role when the user belongs to one organization", () => {
    expect(roleForOrganizations([organization("analyst")])).toBe("analyst");
  });

  test("returns nothing when the organization cannot be determined", () => {
    expect(roleForOrganizations([])).toBeUndefined();
    expect(roleForOrganizations([organization("analyst"), organization("reviewer")])).toBe(
      undefined,
    );
  });
});

describe("resolutionBody", () => {
  test("sends the version and the trimmed note", () => {
    expect(resolutionBody(3, "  Checked with the bank  ")).toEqual({
      version: 3,
      note: "Checked with the bank",
    });
  });
});

describe("resolutionErrorMessage", () => {
  test("shows the stale-version message for 409", () => {
    expect(resolutionErrorMessage(409, "Version mismatch")).toBe(
      "This exception changed, reload to see the latest",
    );
  });

  test("shows the note-required message for 422", () => {
    expect(resolutionErrorMessage(422, "Field required")).toBe("A note is required for this step.");
  });

  test("shows the server's message for 403, such as self-approval", () => {
    expect(resolutionErrorMessage(403, "You cannot approve your own proposal")).toBe(
      "You cannot approve your own proposal",
    );
  });

  test("shows the connection message when the request never completes", () => {
    expect(resolutionErrorMessage(undefined, "")).toBe(
      "Could not reach the server. Please try again.",
    );
  });
});

describe("getDecisionLabel", () => {
  test("labels each resolution decision", () => {
    expect(["propose", "approve", "reject", "reopen"].map(getDecisionLabel)).toEqual([
      "Proposed",
      "Approved",
      "Rejected",
      "Reopened",
    ]);
  });
});
