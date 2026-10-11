import { ALL_BRANCHES } from "../pages/report/useReportFilters";
import { viewLink } from "./links";

test("a widget's branch joins its full-view link; absent, the link names no branch where that means every branch", () => {
  expect(viewLink("/projects/42/trends", { bucket: "week" }, "main")).toBe("/projects/42/trends?bucket=week&branch=main");
  expect(viewLink("/projects/42/trends", { bucket: "week" }, undefined)).toBe("/projects/42/trends?bucket=week");
  expect(viewLink("/projects/42/flaky", {}, undefined)).toBe("/projects/42/flaky");
  expect(viewLink("/projects/42/runs", {}, "feat/a b")).toBe("/projects/42/runs?branch=feat%2Fa%20b");
});

test("on the report, where no branch means the default branch, an absent branch sends branch=*", () => {
  expect(viewLink("/projects/42/report", { period: "30" }, undefined, { everyBranch: ALL_BRANCHES }))
    .toBe("/projects/42/report?period=30&branch=*");
  expect(viewLink("/projects/42/report", {}, "main", { everyBranch: ALL_BRANCHES })).toBe("/projects/42/report?branch=main");
});
