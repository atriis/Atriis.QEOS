import { lazy } from "react";
import { runsPagesStaleKey } from "../../lib/runQueries";
import { viewLink } from "../links";
import type { WidgetDefinition } from "./types";

export const myFailures: WidgetDefinition = {
  type: "my_failures",
  title: "My recent failures",
  description: "Failed runs whose commit author is you, matched by your name in git.",
  defaultSize: "normal",
  settings: ["author", "rows"],
  // No author: the widget uses the signed-in person's QEOS full name
  defaults: { rows: 5 },
  Component: lazy(() => import("./MyFailuresWidget")),
  // The default name is not known here, so only a set author joins the link (plan Ruling 19)
  link: (projectId, settings) =>
    viewLink(`/projects/${projectId}/runs`, settings.author ? { status: "failing", author: settings.author } : { status: "failing" }, undefined),
  staleKeys: (projectId) => [runsPagesStaleKey(projectId)],
};
