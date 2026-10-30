import { describe, expect, test } from "bun:test";
import { reviewerOrganizations, type OrganizationOut } from "./workspaces";

describe("reviewerOrganizations", () => {
  test("keeps only the organizations where the user is a reviewer", () => {
    const organizations: OrganizationOut[] = [
      { id: "1", name: "Acme", role: "analyst" },
      { id: "2", name: "Globex", role: "reviewer" },
    ];
    expect(reviewerOrganizations(organizations)).toEqual([organizations[1]]);
  });

  test("is empty when the user only analyses", () => {
    expect(reviewerOrganizations([{ id: "1", name: "Acme", role: "analyst" }])).toEqual([]);
  });
});
