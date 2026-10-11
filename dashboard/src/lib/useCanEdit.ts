import { useQuery } from "@tanstack/react-query";
import { getProject } from "../api/orgs";

// Mirror EDIT_ROLES and MANAGE_ROLES in the services' api/deps.py
const EDIT_ROLES = ["owner", "admin", "member"];
const MANAGE_ROLES = ["owner", "admin"];

/** Whether the signed-in person's role in this project is one of `roles`; undefined while the role loads. */
function useHasProjectRole(projectId: number, roles: readonly string[]): boolean | undefined {
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId) });
  return project.data == null ? undefined : roles.includes(project.data.my_role ?? "");
}

/** Whether the signed-in person may change this project's data; undefined while the role loads. */
export function useCanEdit(projectId: number): boolean | undefined {
  return useHasProjectRole(projectId, EDIT_ROLES);
}

/** Whether the signed-in person may manage this project (e.g. set its Overview default); undefined while the role loads. */
export function useCanManage(projectId: number): boolean | undefined {
  return useHasProjectRole(projectId, MANAGE_ROLES);
}
