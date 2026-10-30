"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import AppShell from "@/components/AppShell";
import { errorText } from "@/lib/errors";
import {
  DEFAULT_TOLERANCE_HOURS,
  createOrganization,
  createWorkspace,
  listOrganizations,
  listWorkspaces,
  reviewerOrganizations,
  type OrganizationOut,
  type WorkspaceOut,
} from "@/lib/workspaces";

export default function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<WorkspaceOut[]>([]);
  const [organizations, setOrganizations] = useState<OrganizationOut[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [found, orgs] = await Promise.all([listWorkspaces(), listOrganizations()]);
      setWorkspaces(found);
      setOrganizations(orgs);
      setLoaded(true);
    } catch (err) {
      setError(errorText(err));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const reviewerOrgs = reviewerOrganizations(organizations);

  return (
    <AppShell>
      <div className="page-header">
        <h1>Workspaces</h1>
      </div>

      {error && (
        <div aria-live="polite">
          <p className="form-error">{error}</p>
          {!loaded && (
            <button type="button" className="retry-button" onClick={load}>
              Try again
            </button>
          )}
        </div>
      )}
      {!loaded && !error && <p className="loading">Loading…</p>}

      {loaded && organizations.length === 0 && (
        <section className="empty-state">
          <h2>Create an organization</h2>
          <p>An organization holds your workspaces. Its creator becomes a reviewer.</p>
          <OrganizationForm onCreated={load} />
        </section>
      )}

      {loaded && reviewerOrgs.length > 0 && (
        <section className="card">
          <h2 className="card-title">New workspace</h2>
          <WorkspaceForm organizations={reviewerOrgs} onCreated={load} />
        </section>
      )}

      {loaded && (
        <section className="table-section">
          {workspaces.length === 0 ? (
            <p className="empty-state">No workspaces yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Organization</th>
                  <th scope="col">Tolerance</th>
                </tr>
              </thead>
              <tbody>
                {workspaces.map((workspace) => (
                  <tr key={workspace.id}>
                    <td>
                      <Link href={`/workspaces/${workspace.id}`} className="link">
                        {workspace.name}
                      </Link>
                    </td>
                    <td>
                      {organizations.find((org) => org.id === workspace.organization_id)?.name ??
                        "—"}
                    </td>
                    <td>{workspace.timestamp_tolerance_hours} hours</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </AppShell>
  );
}

function OrganizationForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createOrganization(name);
      onCreated();
    } catch (err) {
      setError(errorText(err));
      setSubmitting(false);
    }
  }

  return (
    <form className="form-group" onSubmit={handleSubmit}>
      <label htmlFor="organization-name">Organization name</label>
      <input
        id="organization-name"
        name="name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <div aria-live="polite">{error && <p className="form-error">{error}</p>}</div>
      <button type="submit" className="btn" disabled={submitting}>
        {submitting ? "Creating…" : "Create organization"}
      </button>
    </form>
  );
}

function WorkspaceForm({
  organizations,
  onCreated,
}: {
  organizations: OrganizationOut[];
  onCreated: () => void;
}) {
  const [organizationId, setOrganizationId] = useState(organizations[0].id);
  const [name, setName] = useState("");
  const [tolerance, setTolerance] = useState(String(DEFAULT_TOLERANCE_HOURS));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const hours = Number(tolerance);
    if (!(hours > 0)) {
      setError("Tolerance must be a positive number of hours.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await createWorkspace({
        organization_id: organizationId,
        name,
        timestamp_tolerance_hours: hours,
      });
      setName("");
      setTolerance(String(DEFAULT_TOLERANCE_HOURS));
      onCreated();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="form-group" onSubmit={handleSubmit}>
      <label htmlFor="workspace-organization">Organization</label>
      <select
        id="workspace-organization"
        value={organizationId}
        onChange={(event) => setOrganizationId(event.target.value)}
      >
        {organizations.map((org) => (
          <option key={org.id} value={org.id}>
            {org.name}
          </option>
        ))}
      </select>
      <label htmlFor="workspace-name">Workspace name</label>
      <input
        id="workspace-name"
        name="name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <label htmlFor="workspace-tolerance">Timestamp tolerance (hours)</label>
      <input
        id="workspace-tolerance"
        name="timestamp_tolerance_hours"
        type="number"
        min={1}
        required
        value={tolerance}
        onChange={(event) => setTolerance(event.target.value)}
      />
      <div aria-live="polite">{error && <p className="form-error">{error}</p>}</div>
      <button type="submit" className="btn" disabled={submitting}>
        {submitting ? "Creating…" : "Create workspace"}
      </button>
    </form>
  );
}
