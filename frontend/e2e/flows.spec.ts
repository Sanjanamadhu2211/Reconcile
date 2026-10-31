import { expect, test, type APIResponse, type Page } from "@playwright/test";

// The flows share one workspace, so they run in order on a single worker.
test.describe.configure({ mode: "serial" });

const workspaceName = `E2E workspace ${Date.now()}`;
const approver = {
  email: `approver-${Date.now()}@example.com`,
  password: "approver-password-1",
};
const ordersCsv = [
  "external_id,amount,currency,occurred_at",
  "E2E-ORD-1,10.00,USD,2026-01-05T10:00:00Z",
  "E2E-ORD-2,20.00,USD,2026-01-05T11:00:00Z",
  "",
].join("\n");

function credentials() {
  const email = process.env.E2E_EMAIL;
  const password = process.env.E2E_PASSWORD;
  if (!email || !password) {
    throw new Error("Set E2E_EMAIL and E2E_PASSWORD to run the end-to-end flows.");
  }
  return { email, password };
}

async function signIn(page: Page, { email, password }: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Workspaces" })).toBeVisible();
}

async function openWorkspace(page: Page) {
  await page.getByRole("link", { name: workspaceName, exact: true }).click();
  await expect(page.getByRole("heading", { name: workspaceName })).toBeVisible();
}

async function postWithCsrf(page: Page, path: string, data: object): Promise<APIResponse> {
  const cookies = await page.context().cookies();
  const csrfToken = cookies.find((cookie) => cookie.name === "csrf_token")?.value ?? "";
  return page.request.post(path, { data, headers: { "X-CSRF-Token": csrfToken } });
}

test("sign in and create a workspace", async ({ page }) => {
  await signIn(page, credentials());

  await page.getByLabel("Workspace name").fill(workspaceName);
  await page.getByRole("button", { name: "Create workspace" }).click();

  await expect(page.getByRole("link", { name: workspaceName, exact: true })).toBeVisible();
});

test("import a CSV and see the batch completed", async ({ page }) => {
  await signIn(page, credentials());
  await openWorkspace(page);
  await page.getByRole("link", { name: "Imports", exact: true }).click();

  await page.getByLabel("CSV file").setInputFiles({
    name: "orders.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(ordersCsv),
  });
  await page.getByRole("button", { name: "Preview" }).click();
  await page.getByRole("button", { name: "Upload file" }).click();

  await expect(page.getByText(/^Import completed:/)).toBeVisible();
  const history = page.getByRole("region", { name: "Import history" });
  await expect(history.getByRole("cell", { name: "completed", exact: true })).toBeVisible();
});

test("approve an exception and see it in the audit trail", async ({ page, request }) => {
  const { email, password } = credentials();
  await signIn(page, { email, password });
  await openWorkspace(page);

  // The two orders from the CSV have no payment, so each becomes an unmatched exception.
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByText(/^Run completed:/)).toBeVisible();
  await page.getByRole("link", { name: "Exceptions", exact: true }).click();
  await page.getByRole("link", { name: "E2E-ORD-1", exact: true }).click();

  await page.getByLabel("Note").fill("No payment found for this order");
  await page.getByRole("button", { name: "Propose" }).click();
  await expect(page.getByText("Status: Proposed")).toBeVisible();
  const exceptionUrl = page.url();

  // Nobody can approve their own proposal, so a second reviewer joins the organization.
  // The request fixture keeps the new account out of the browser session.
  const registered = await request.post("/api/v1/auth/register", { data: approver });
  expect(registered.ok()).toBeTruthy();
  const [organization] = await (await page.request.get("/api/v1/organizations")).json();
  const added = await postWithCsrf(page, `/api/v1/organizations/${organization.id}/members`, {
    email: approver.email,
    role: "reviewer",
  });
  expect(added.ok()).toBeTruthy();

  await page.getByRole("button", { name: "Log out" }).click();
  await signIn(page, approver);
  await page.goto(exceptionUrl);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("Status: Resolved")).toBeVisible();

  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: "Audit trail" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Exception approved", exact: true })).toBeVisible();
});
