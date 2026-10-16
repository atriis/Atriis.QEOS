import { useFocusReturn } from "../lib/useFocusReturn";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Plus } from "lucide-react";
import {
  MyOrganization, Project, createOrganization, createProject, formatPurgeDate, listMembers, listMyOrganizations,
  listProjects, restoreProject, slugify,
} from "../api/orgs";
import ErrorBanner from "../components/ErrorBanner";
import PageHeader from "../components/PageHeader";

const MANAGER_ROLES = ["owner", "admin"];

/** One organization: its projects as tiles, and project creation for its managers. */
function OrgProjects({ org }: { org: MyOrganization }) {
  const qc = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const newProjectRef = useFocusReturn<HTMLButtonElement>(formOpen);
  const [name, setName] = useState("");
  const canCreate = MANAGER_ROLES.includes(org.role);
  // Owners and admins also see projects pending deletion, greyed, to restore them (spec 2026-10-16)
  const projects = useQuery({
    queryKey: ["projects", org.id, canCreate],
    queryFn: () => listProjects(org.id, { includePending: canCreate }),
  });
  const anyPending = (projects.data ?? []).some((p) => p.deletion);
  const members = useQuery({
    queryKey: ["members", org.id],
    queryFn: () => listMembers(org.id),
    enabled: canCreate && anyPending,
  });
  const restore = useMutation({
    mutationFn: (projectId: number) => restoreProject(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects", org.id] }),
  });
  const deleter = (p: Project) => members.data?.find((m) => m.user_id === p.deletion?.deleted_by)?.email ?? null;
  const create = useMutation({
    mutationFn: () => createProject(org.id, name.trim()),
    onSuccess: () => {
      setFormOpen(false);
      setName("");
      qc.invalidateQueries({ queryKey: ["projects", org.id] });
    },
  });

  return (
    <section className="org-block" aria-labelledby={`org-${org.id}`}>
      <div className="org-block-head">
        <div>
          <h2 id={`org-${org.id}`}>{org.name}</h2>
          <span className="muted">
            Your role: {org.role} · <Link className="inline-link" to={`/organizations/${org.id}`}>Members and invitations</Link>
          </span>
        </div>
        {canCreate && !formOpen && (
          <button ref={newProjectRef} onClick={() => setFormOpen(true)}>
            <Plus size={16} aria-hidden="true" /> New project
          </button>
        )}
      </div>

      {canCreate && formOpen && (
        <form
          className="card inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label>
            Project name
            <input required autoFocus value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <button className="primary" type="submit" disabled={create.isPending}>Create project</button>
          <button type="button" onClick={() => setFormOpen(false)}>Cancel</button>
          {create.error != null && <ErrorBanner error={create.error} />}
        </form>
      )}

      {projects.error != null && <ErrorBanner error={projects.error} onRetry={() => projects.refetch()} />}
      {projects.isPending && <p className="muted">Loading projects…</p>}
      {projects.data?.length === 0 && (
        <p className="muted">No projects in this organization{canCreate ? " yet — create the first one." : "."}</p>
      )}
      {projects.data != null && projects.data.length > 0 && (
        <div className="project-grid">
          {projects.data.map((project) => project.deletion ? (
            <div key={project.id} className="project-tile is-pending" role="group"
              aria-label={`${project.name}, deletion pending`}>
              <span className="project-tile-name">
                <FolderKanban size={18} aria-hidden="true" /> {project.name}
              </span>
              <span className="pending-line">
                Deletion pending · removed on {formatPurgeDate(project.deletion.purge_at)}
                {deleter(project) && ` · deleted by ${deleter(project)}`}
              </span>
              <button type="button" onClick={() => restore.mutate(project.id)}
                disabled={restore.isPending} aria-label={`Restore ${project.name}`}>
                Restore
              </button>
            </div>
          ) : (
            <Link key={project.id} className="project-tile" to={`/projects/${project.id}/overview`}>
              <FolderKanban size={18} aria-hidden="true" /> {project.name}
            </Link>
          ))}
        </div>
      )}
      {restore.error != null && <ErrorBanner error={restore.error} />}
    </section>
  );
}

export default function PickerPage() {
  const qc = useQueryClient();
  const [orgFormOpen, setOrgFormOpen] = useState(false);
  const newOrgRef = useFocusReturn<HTMLButtonElement>(orgFormOpen);
  const [orgName, setOrgName] = useState("");
  const [orgSlug, setOrgSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);

  const orgs = useQuery({ queryKey: ["orgs"], queryFn: listMyOrganizations });
  const createOrg = useMutation({
    mutationFn: () => createOrganization(orgName.trim(), orgSlug),
    onSuccess: () => {
      setOrgFormOpen(false);
      setOrgName("");
      setOrgSlug("");
      setSlugEdited(false);
      qc.invalidateQueries({ queryKey: ["orgs"] });
    },
  });

  return (
    <div className="page">
      <PageHeader
        title="Projects"
        actions={!orgFormOpen ? (
          <button ref={newOrgRef} onClick={() => setOrgFormOpen(true)}>
            <Plus size={16} aria-hidden="true" /> New organization
          </button>
        ) : undefined}
      />

      {orgFormOpen && (
        <form
          className="card inline-form"
          onSubmit={(e) => {
            e.preventDefault();
            createOrg.mutate();
          }}
        >
          <label>
            Name
            <input
              required
              autoFocus
              value={orgName}
              onChange={(e) => {
                setOrgName(e.target.value);
                if (!slugEdited) setOrgSlug(slugify(e.target.value));
              }}
            />
          </label>
          <label>
            Slug
            <input
              required
              pattern="[a-z0-9-]+"
              value={orgSlug}
              onChange={(e) => {
                setSlugEdited(true);
                setOrgSlug(e.target.value);
              }}
            />
          </label>
          <button className="primary" type="submit" disabled={createOrg.isPending}>Create organization</button>
          <button type="button" onClick={() => setOrgFormOpen(false)}>Cancel</button>
          {createOrg.error != null && <ErrorBanner error={createOrg.error} />}
        </form>
      )}

      {orgs.error != null && <ErrorBanner error={orgs.error} onRetry={() => orgs.refetch()} />}
      {orgs.isPending && <p className="muted">Loading organizations…</p>}
      {orgs.data?.length === 0 && !orgFormOpen && (
        <div className="card">
          <h2>Welcome to QEOS</h2>
          <p className="muted">
            You are not a member of any organization yet. Create one to start a project, or open
            the invitation link a teammate sent you.
          </p>
        </div>
      )}
      {orgs.data?.map((org) => <OrgProjects key={org.id} org={org} />)}
    </div>
  );
}
