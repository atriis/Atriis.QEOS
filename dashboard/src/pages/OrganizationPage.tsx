import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  InvitationCreated, ROLES, createInvitation, listInvitations, listMembers,
  listMyOrganizations, myRole, removeMember, revokeInvitation,
} from "../api/orgs";
import { microsoftEnabled } from "../auth/ssoProviders";
import ConfirmButton from "../components/ConfirmButton";
import ErrorBanner from "../components/ErrorBanner";
import MicrosoftRolesCard from "../components/MicrosoftRolesCard";
import SecretBlock from "../components/SecretBlock";
import PageHeader from "../components/PageHeader";

const MANAGER_ROLES = ["owner", "admin"];

export default function OrganizationPage() {
  const { orgId } = useParams();
  const id = Number(orgId);
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");
  const [created, setCreated] = useState<InvitationCreated | null>(null);
  const location = useLocation();
  const navigate = useNavigate();
  // A welcome passed by the invitation page; read once, then dropped from history so a reload does not repeat it
  const [notice, setNotice] = useState(() => (location.state as { notice?: string } | null)?.notice ?? "");
  useEffect(() => {
    if ((location.state as { notice?: string } | null)?.notice) navigate(location.pathname + location.search, { replace: true, state: null });
  }, [location, navigate]);

  const orgs = useQuery({ queryKey: ["orgs"], queryFn: listMyOrganizations });
  const me = useQuery({ queryKey: ["org", id, "me"], queryFn: () => myRole(id) });
  const members = useQuery({ queryKey: ["org", id, "members"], queryFn: () => listMembers(id) });
  const invitations = useQuery({ queryKey: ["org", id, "invitations"], queryFn: () => listInvitations(id) });

  const canManage = me.data != null && MANAGER_ROLES.includes(me.data.role);
  const isOwner = me.data?.role === "owner";
  const org = orgs.data?.find((o) => o.id === id);

  const invite = useMutation({
    mutationFn: () => createInvitation(id, email, role),
    onSuccess: (invitation) => {
      setCreated(invitation);
      setEmail("");
      setNotice("");
      qc.invalidateQueries({ queryKey: ["org", id, "invitations"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (invitationId: number) => revokeInvitation(id, invitationId),
    onSuccess: () => {
      setNotice("Invitation revoked.");
      qc.invalidateQueries({ queryKey: ["org", id, "invitations"] });
    },
  });
  const remove = useMutation({
    mutationFn: (memberId: number) => removeMember(id, memberId),
    onSuccess: () => {
      setNotice("Member removed.");
      qc.invalidateQueries({ queryKey: ["org", id, "members"] });
    },
  });

  const error = orgs.error ?? me.error ?? members.error ?? invitations.error;
  const pending = invitations.data?.filter((i) => i.accepted_at === null) ?? [];

  return (
    <div className="page">
      <PageHeader title={org?.name ?? `Organization ${id}`} actions={<Link to="/">Choose a project</Link>} />
      {error != null && <ErrorBanner error={error} onRetry={() => members.refetch()} />}
      {(invite.error ?? revoke.error ?? remove.error) != null && (
        <ErrorBanner error={(invite.error ?? revoke.error ?? remove.error)!} />
      )}
      <p role="status" className="live-note">{notice}</p>

      <div className="card">
        <h2>Members</h2>
        {members.isPending && <p className="muted">Loading members…</p>}
        {members.data && (
          <table className="data">
            <thead>
              <tr>
                <th>User</th><th>Role</th><th>Status</th><th>Since</th>
                {canManage && <th><span className="sr-only">Actions</span></th>}
              </tr>
            </thead>
            <tbody>
              {members.data.map((member) => (
                <tr key={member.id}>
                  <td>{member.email ?? `user ${member.user_id}`}</td>
                  <td>
                    {member.role}
                    {member.managed_by === "entra" && <> <span className="badge badge-muted" title="Managed by Entra">Entra<span className="sr-only">, managed by Entra</span></span></>}
                  </td>
                  <td>{member.status}</td>
                  <td>{new Date(member.created_at).toLocaleDateString()}</td>
                  {canManage && (
                    <td>
                      {member.managed_by === "entra" ? (
                        <>
                          <button type="button" aria-disabled="true" onClick={(e) => e.preventDefault()}
                            aria-label={`Remove ${member.email ?? `user ${member.user_id}`}`}
                            aria-describedby={`entra-managed-${member.id}`}
                            title="Managed by Entra: remove the app role instead.">
                            Remove
                          </button>
                          <span id={`entra-managed-${member.id}`} className="sr-only">Managed by Entra: remove the app role instead.</span>
                        </>
                      ) : (
                        <ConfirmButton
                          label="Remove"
                          ariaLabel={`Remove ${member.email ?? `user ${member.user_id}`}`}
                          question={`Remove ${member.email ?? `user ${member.user_id}`}? They lose access to every project in this organization.`}
                          confirmLabel="Remove"
                          onConfirm={() => remove.mutate(member.id)}
                          disabled={remove.isPending}
                        />
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Invitations</h2>
        {canManage && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              invite.mutate();
            }}
            className="inline-form"
          >
            <label>
              Email
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Role
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLES.filter((r) => r !== "owner").map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </label>
            <button type="submit" disabled={invite.isPending}>Invite</button>
          </form>
        )}
        {created && (
          <SecretBlock label={`Invitation for ${created.email}`} value={`${window.location.origin}/invitations/${created.token}`}
            copyLabel={`Copy the invitation link for ${created.email}`} copyText="Copy link"
            note="Send this link to the invitee. This is shown once: it cannot be shown again." />
        )}
        {invitations.isPending && <p className="muted">Loading invitations…</p>}
        {pending.length === 0 && invitations.data && <p className="muted">No pending invitations.</p>}
        {pending.length > 0 && (
          <table className="data">
            <thead>
              <tr>
                <th>Email</th><th>Role</th><th>Expires</th>
                {canManage && <th><span className="sr-only">Actions</span></th>}
              </tr>
            </thead>
            <tbody>
              {pending.map((invitation) => (
                <tr key={invitation.id}>
                  <td>{invitation.email}</td>
                  <td>{invitation.role}</td>
                  <td>{new Date(invitation.expires_at).toLocaleDateString()}</td>
                  {canManage && (
                    <td>
                      <ConfirmButton
                        label="Revoke"
                        ariaLabel={`Revoke invitation for ${invitation.email}`}
                        question={`Revoke the invitation for ${invitation.email}? The link stops working.`}
                        confirmLabel="Revoke"
                        onConfirm={() => revoke.mutate(invitation.id)}
                        disabled={revoke.isPending}
                      />
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isOwner && microsoftEnabled() && (
        <MicrosoftRolesCard orgId={id} approved={orgs.data?.find((o) => o.id === id)?.entra_sync_approved} />
      )}
    </div>
  );
}
