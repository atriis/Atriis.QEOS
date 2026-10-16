import { apiFetch } from "./http";

export interface MyOrganization {
  id: number;
  name: string;
  slug: string;
  role: string;
}

export interface Project {
  id: number;
  name: string;
  organization_id?: number; // present on GET /projects/{id}; list rows may omit it
  my_role?: string;
  settings?: { result_retention_days: number };
  legal_hold?: LegalHold | null;
  /** Set while the project is pending deletion (owners and admins see it with include_pending). */
  deletion?: Deletion | null;
}

/** A pending deletion (spec 2026-10-16): restorable by owners and admins until purge_at. */
export interface Deletion {
  deleted_at: string;
  deleted_by: number | null;
  purge_at: string;
}

export interface LegalHold {
  since: string;
  by: number | null;
  reason: string | null;
}

/** While on hold, retention deletes nothing of the project. Owners and admins only. */
export function placeLegalHold(projectId: number, reason: string): Promise<Project> {
  return apiFetch(`/api/v1/projects/${projectId}/legal-hold`, {
    method: "PUT",
    body: JSON.stringify({ reason }),
  });
}

export function releaseLegalHold(projectId: number): Promise<Project> {
  return apiFetch(`/api/v1/projects/${projectId}/legal-hold`, { method: "DELETE" });
}

export interface Member {
  id: number;
  organization_id: number;
  user_id: number;
  email: string | null; // enriched from auth-service, best effort
  role: string;
  status: string;
  created_at: string;
  updated_at: string | null;
  /** "entra" when a Microsoft app role sets this role (ADR-033); the member cannot be removed by hand. */
  managed_by: "entra" | null;
}

/** An Entra app role value and the organization role it grants (ADR-033). Never owner. */
export interface SsoRoleMapping {
  id: number;
  app_role: string;
  role: string;
  created_at: string | null;
}

export const MAPPED_ROLES = ["admin", "member", "viewer"] as const;

export function listSsoRoleMappings(orgId: number): Promise<SsoRoleMapping[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings`);
}

export function createSsoRoleMapping(orgId: number, appRole: string, role: string): Promise<SsoRoleMapping> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ app_role: appRole, role }),
  });
}

export function deleteSsoRoleMapping(orgId: number, mappingId: number): Promise<void> {
  return apiFetch(`/api/v1/organizations/${orgId}/sso-role-mappings/${mappingId}`, { method: "DELETE" });
}

export interface InvitationPreview {
  organization_id: number;
  organization_name: string;
  email: string;
  role: string;
  expires_at: string;
}

export function previewInvitation(token: string): Promise<InvitationPreview> {
  return apiFetch(`/api/v1/invitations/${encodeURIComponent(token)}`);
}

export interface InvitationSummary {
  id: number;
  organization_id: number;
  email: string;
  role: string;
  invited_by_user_id: number;
  expires_at: string;
  created_at: string;
  accepted_at: string | null;
}

// The raw token is returned only by the create call, never by the list
export interface InvitationCreated extends InvitationSummary {
  token: string;
}

export const ROLES = ["owner", "admin", "member", "viewer", "billing_manager"] as const;

export function listMyOrganizations(): Promise<MyOrganization[]> {
  return apiFetch("/api/v1/organizations");
}

export function createOrganization(name: string, slug: string): Promise<MyOrganization> {
  return apiFetch("/api/v1/organizations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, slug }),
  });
}

export function createProject(orgId: number, name: string): Promise<Project> {
  return apiFetch(`/api/v1/organizations/${orgId}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }), // the slug is derived server-side
  });
}

// What the backend accepts for a slug: lowercase, digits, dashes
export function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // strip the accents the normalize split off
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

export function listMembers(orgId: number): Promise<Member[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/members`);
}

export function myRole(orgId: number): Promise<{ role: string }> {
  return apiFetch(`/api/v1/organizations/${orgId}/members/me`);
}

export function removeMember(orgId: number, memberId: number): Promise<void> {
  return apiFetch(`/api/v1/organizations/${orgId}/members/${memberId}`, { method: "DELETE" });
}

export function listInvitations(orgId: number): Promise<InvitationSummary[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/invitations`);
}

export function createInvitation(orgId: number, email: string, role: string): Promise<InvitationCreated> {
  return apiFetch(`/api/v1/organizations/${orgId}/invitations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
}

export function revokeInvitation(orgId: number, invitationId: number): Promise<void> {
  return apiFetch(`/api/v1/organizations/${orgId}/invitations/${invitationId}`, { method: "DELETE" });
}

export function acceptInvitation(token: string): Promise<Member> {
  return apiFetch(`/api/v1/invitations/${encodeURIComponent(token)}/accept`, { method: "POST" });
}

/** `includePending` also lists projects pending deletion; project-service honours it for owners and admins only. */
export function listProjects(orgId: number, opts: { includePending?: boolean } = {}): Promise<Project[]> {
  return apiFetch(`/api/v1/organizations/${orgId}/projects${opts.includePending ? "?include_pending=true" : ""}`);
}

/** Pending deletion for PROJECT_DELETE_GRACE_DAYS (7), restorable by owners and admins, then purged everywhere. */
export function deleteProject(projectId: number): Promise<void> {
  return apiFetch(`/api/v1/projects/${projectId}`, { method: "DELETE" });
}

export function restoreProject(projectId: number): Promise<Project> {
  return apiFetch(`/api/v1/projects/${projectId}/restore`, { method: "POST" });
}

// Fixed names: Intl's en-GB says "Sept" in newer ICU (as in lib/period)
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "23 Oct 2026, 14:05" in the reader's time zone. */
export function formatPurgeDate(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}, ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function getProject(projectId: number): Promise<Project> {
  return apiFetch(`/api/v1/projects/${projectId}`);
}
