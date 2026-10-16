import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { MAPPED_ROLES, createSsoRoleMapping, deleteSsoRoleMapping, listSsoRoleMappings } from "../api/orgs";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

/** Owners map Entra app roles to admin, member or viewer (ADR-033). Owners are never granted by a mapping. */
export default function MicrosoftRolesCard({ orgId }: { orgId: number }) {
  const qc = useQueryClient();
  const key = ["org", orgId, "sso-role-mappings"];
  const mappings = useQuery({ queryKey: key, queryFn: () => listSsoRoleMappings(orgId) });
  const [appRole, setAppRole] = useState("");
  const [role, setRole] = useState<string>("member");
  const [fieldError, setFieldError] = useState("");

  const add = useMutation({
    mutationFn: () => createSsoRoleMapping(orgId, appRole.trim(), role),
    onSuccess: () => { setAppRole(""); setFieldError(""); qc.invalidateQueries({ queryKey: key }); },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) setFieldError("This app role is already mapped.");
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteSsoRoleMapping(orgId, id),
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    setFieldError("");
    add.mutate();
  }

  const addError = add.error != null && !(add.error instanceof ApiError && add.error.status === 409) ? add.error : null;
  const actionError = addError ?? remove.error;

  return (
    <div className="card">
      <h2>Microsoft roles</h2>
      <p className="muted">
        People assigned to these app roles in Entra get the role below at each Microsoft sign-in. Owners are always granted by hand.
      </p>
      {mappings.error != null && <ErrorBanner error={mappings.error} onRetry={() => mappings.refetch()} />}
      {actionError != null && <ErrorBanner error={actionError} />}
      {mappings.isPending && <p className="muted">Loading app roles…</p>}
      {mappings.data && mappings.data.length === 0 && <p className="muted">No app roles mapped yet.</p>}
      {mappings.data && mappings.data.length > 0 && (
        <table className="data">
          <thead>
            <tr><th>App role</th><th>QEOS role</th><th><span className="sr-only">Actions</span></th></tr>
          </thead>
          <tbody>
            {mappings.data.map((m) => (
              <tr key={m.id}>
                <td><code>{m.app_role}</code></td>
                <td>{m.role}</td>
                <td>
                  <ConfirmButton
                    label="Remove"
                    ariaLabel={`Remove mapping ${m.app_role}`}
                    question="Remove this mapping? Members keep their role until their next Microsoft sign-in."
                    confirmLabel="Remove"
                    onConfirm={() => remove.mutate(m.id)}
                    disabled={remove.isPending}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <form className="inline-form" onSubmit={onSubmit}>
        <label>
          App role
          <input value={appRole} onChange={(e) => setAppRole(e.target.value)} placeholder="QEOS.Member" required maxLength={100}
            aria-invalid={fieldError ? "true" : undefined} aria-describedby={fieldError ? "sso-role-error" : undefined} />
        </label>
        <label>
          QEOS role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            {MAPPED_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <button type="submit" disabled={add.isPending}>Add</button>
      </form>
      {fieldError && <p id="sso-role-error" className="field-error">{fieldError}</p>}
    </div>
  );
}
