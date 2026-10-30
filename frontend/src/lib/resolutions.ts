import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ResolutionAction = "propose" | "approve" | "reject" | "reopen";
export type ResolutionOut = components["schemas"]["ResolutionOut"];
export type Role = components["schemas"]["Role"];
type NoteRequest = components["schemas"]["NoteRequest"];
type OrganizationOut = components["schemas"]["OrganizationOut"];

export const ACTION_LABELS: Record<ResolutionAction, string> = {
  propose: "Propose",
  approve: "Approve",
  reject: "Reject",
  reopen: "Reopen",
};

export const NOTE_REQUIRED: Record<ResolutionAction, boolean> = {
  propose: true,
  approve: false,
  reject: true,
  reopen: true,
};

const DECISION_LABELS: Record<string, string> = {
  propose: "Proposed",
  approve: "Approved",
  reject: "Rejected",
  reopen: "Reopened",
};

const NETWORK_MESSAGE = "Could not reach the server. Please try again.";
const STALE_MESSAGE = "This exception changed, reload to see the latest";
const NOTE_REQUIRED_MESSAGE = "A note is required for this step.";

const requests = {
  propose: (exceptionId: string, body: NoteRequest) =>
    api.POST("/api/v1/exceptions/{exception_id}/propose", {
      params: { path: { exception_id: exceptionId } },
      body,
    }),
  approve: (exceptionId: string, body: NoteRequest) =>
    api.POST("/api/v1/exceptions/{exception_id}/approve", {
      params: { path: { exception_id: exceptionId } },
      body,
    }),
  reject: (exceptionId: string, body: NoteRequest) =>
    api.POST("/api/v1/exceptions/{exception_id}/reject", {
      params: { path: { exception_id: exceptionId } },
      body,
    }),
  reopen: (exceptionId: string, body: NoteRequest) =>
    api.POST("/api/v1/exceptions/{exception_id}/reopen", {
      params: { path: { exception_id: exceptionId } },
      body,
    }),
};

// Reviewers approve, reject and reopen; analysts only propose.
// An unknown role (several organizations) keeps every action and lets the server decide.
export function availableActions(status: string, role: Role | undefined): ResolutionAction[] {
  const canReview = role !== "analyst";
  switch (status) {
    case "open":
      return ["propose"];
    case "proposed":
      return canReview ? ["approve", "reject"] : [];
    case "resolved":
      return canReview ? ["reopen"] : [];
    default:
      return [];
  }
}

export function roleForOrganizations(organizations: OrganizationOut[]): Role | undefined {
  return organizations.length === 1 ? organizations[0].role : undefined;
}

export function resolutionBody(version: number, note: string): NoteRequest {
  return { version, note: note.trim() };
}

export function submitResolution(
  exceptionId: string,
  action: ResolutionAction,
  version: number,
  note: string,
) {
  return requests[action](exceptionId, resolutionBody(version, note));
}

// status is undefined when the request never got a response.
export function resolutionErrorMessage(status: number | undefined, serverMessage: string): string {
  if (status === undefined) return NETWORK_MESSAGE;
  if (status === 409) return STALE_MESSAGE;
  if (status === 422) return NOTE_REQUIRED_MESSAGE;
  return serverMessage;
}

export function getDecisionLabel(decision: string): string {
  return DECISION_LABELS[decision] ?? decision;
}
