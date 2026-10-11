import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { latestRunQuery } from "./queries";
import { newRunStaleKeys } from "./widgets/registry";

/** The latest run, and a refresh of the non-polled figures when a new one arrives (spec §2.7). */
export function useLatestRun(projectId: number) {
  const queryClient = useQueryClient();
  const runs = useQuery(latestRunQuery(projectId));
  const latest = runs.data?.[0];
  const shown = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (shown.current !== undefined && latest?.id !== shown.current) {
      for (const queryKey of newRunStaleKeys(projectId)) void queryClient.invalidateQueries({ queryKey });
    }
    shown.current = latest?.id;
  }, [latest?.id, projectId, queryClient]);
  return { runs, latest };
}
