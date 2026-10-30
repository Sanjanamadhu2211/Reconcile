import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { apiErrorMessage } from "@/lib/auth";

export type WorkspaceOut = components["schemas"]["WorkspaceOut"];
export type WorkspaceCreate = components["schemas"]["WorkspaceCreate"];
export type OrganizationOut = components["schemas"]["OrganizationOut"];
export type ReconciliationRunSummary = components["schemas"]["ReconciliationRunSummary"];
export type ReconciliationRunOut = components["schemas"]["ReconciliationRunOut"];
export type WorkspaceSummary = components["schemas"]["WorkspaceSummary"];

export const DEFAULT_TOLERANCE_HOURS = 24;

export function reviewerOrganizations(organizations: OrganizationOut[]): OrganizationOut[] {
  return organizations.filter((organization) => organization.role === "reviewer");
}

export async function listWorkspaces(): Promise<WorkspaceOut[]> {
  const { data, error, response } = await api.GET("/api/v1/workspaces");
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function createWorkspace(input: WorkspaceCreate): Promise<WorkspaceOut> {
  const { data, error, response } = await api.POST("/api/v1/workspaces", { body: input });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function getWorkspace(workspaceId: string): Promise<WorkspaceOut> {
  const { data, error, response } = await api.GET("/api/v1/workspaces/{workspace_id}", {
    params: { path: { workspace_id: workspaceId } },
  });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function listOrganizations(): Promise<OrganizationOut[]> {
  const { data, error, response } = await api.GET("/api/v1/organizations");
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function createOrganization(name: string): Promise<OrganizationOut> {
  const { data, error, response } = await api.POST("/api/v1/organizations", {
    body: { name },
  });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function listReconciliationRuns(
  workspaceId: string,
  limit = 10,
): Promise<ReconciliationRunSummary[]> {
  const { data, error, response } = await api.GET(
    "/api/v1/workspaces/{workspace_id}/reconciliation-runs",
    { params: { path: { workspace_id: workspaceId }, query: { limit } } },
  );
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function getWorkspaceSummary(workspaceId: string): Promise<WorkspaceSummary> {
  const { data, error, response } = await api.GET("/api/v1/workspaces/{workspace_id}/summary", {
    params: { path: { workspace_id: workspaceId } },
  });
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}

export async function createReconciliationRun(workspaceId: string): Promise<ReconciliationRunOut> {
  const { data, error, response } = await api.POST(
    "/api/v1/workspaces/{workspace_id}/reconciliation-runs",
    { params: { path: { workspace_id: workspaceId } } },
  );
  if (!response.ok || !data) throw new Error(apiErrorMessage(error));
  return data;
}
