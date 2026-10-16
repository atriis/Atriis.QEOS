import { useEffect } from "react";
import { Outlet, useLocation, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { getProject, myRole } from "../api/orgs";
import PendingDeletion, { isPendingInfo } from "../components/PendingDeletion";
import { pageTitle, useFocusOnNavigate } from "../routeFocus";
import { projectRest, viewTitle } from "../lib/viewTitle";

/** Project frame inside the app shell: sets the document title (view + project) around the current view.
 *  The org and project live in the top bar's breadcrumb; each view renders its own PageHeader. */
export default function ProjectLayout() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const project = useQuery({
    queryKey: ["project", id],
    queryFn: () => getProject(id),
    // 410: pending deletion (spec 2026-10-16), an answer rather than a failure
    retry: (count, err) => !(err instanceof ApiError && err.status === 410) && count < 3,
  });
  const body = project.error instanceof ApiError && project.error.status === 410
    ? (project.error.body as { detail?: unknown } | undefined)?.detail : undefined;
  const pending = isPendingInfo(body) ? body : null;
  const role = useQuery({
    queryKey: ["my-role", pending?.organization_id],
    queryFn: () => myRole(pending!.organization_id),
    enabled: pending != null,
  });
  const location = useLocation();

  const projectName = project.data?.name;
  useEffect(() => {
    document.title = pageTitle(viewTitle(projectRest(location.pathname)), projectName ?? `Project ${projectId}`);
  }, [location.pathname, projectName, projectId]);
  useFocusOnNavigate();

  return (
    <div className="page">
      <div id="content" tabIndex={-1}>
        {pending ? (
          <PendingDeletion
            projectId={id}
            info={pending}
            canRestore={["owner", "admin"].includes(role.data?.role ?? "")}
          />
        ) : (
          <Outlet />
        )}
      </div>
    </div>
  );
}
