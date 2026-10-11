import { partialMatchKey } from "@tanstack/react-query";
import { latestRunQuery } from "../overview/queries";
import { runsFirstPageQuery, runsPagesStaleKey } from "./runQueries";

test("the runs pages' stale key covers every filtered page and not the latest-run query", () => {
  const stale = runsPagesStaleKey(42);
  expect(partialMatchKey(runsFirstPageQuery(42, {}).queryKey, stale)).toBe(true);
  expect(partialMatchKey(runsFirstPageQuery(42, { branch: "main", status: "failing", author: "Ada" }).queryKey, stale)).toBe(true);
  expect(partialMatchKey(latestRunQuery(42).queryKey, stale)).toBe(false);
  expect(partialMatchKey(runsFirstPageQuery(43, {}).queryKey, stale)).toBe(false);
});
