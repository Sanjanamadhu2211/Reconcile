import { describe, expect, test } from "bun:test";
import { documentTitleFor } from "./useDocumentTitle";

describe("documentTitleFor", () => {
  test("puts the page name in front of the app name", () => {
    expect(documentTitleFor("Workspaces")).toBe("Workspaces · Reconcile");
  });

  test("uses the app name alone when no page name is given", () => {
    expect(documentTitleFor()).toBe("Reconcile");
    expect(documentTitleFor("")).toBe("Reconcile");
  });
});
