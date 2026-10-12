import { accuracyDays, caughtText, impactAccuracyQuery, impactAccuracyStaleKeys, normally, runImpactQuery } from "./impactQueries";

test("the Report's period when it is the last 7, 14 or 30 days, else 30", () => {
  expect(accuracyDays(7, "2026-10-12", "2026-10-12")).toBe(7);
  expect(accuracyDays(14, "2026-10-12", "2026-10-12")).toBe(14);
  expect(accuracyDays(30, "2026-10-12", "2026-10-12")).toBe(30);
  expect(accuracyDays(90, "2026-10-12", "2026-10-12")).toBe(30);
  expect(accuracyDays(7, "2026-10-05", "2026-10-12")).toBe(30); // a past week is not "the last 7 days"
});

test("base rates as people say them, and nothing when there is none", () => {
  expect(normally(0.03)).toBe("normally 3%");
  expect(normally(0.1333)).toBe("normally 13%");
  expect(normally(0.004)).toBe("normally under 1%");
  expect(normally(0)).toBe("normally 0%");
  expect(normally(null)).toBeNull();
});

test("caught out of the new failures, with the locale's grouping", () => {
  expect(caughtText(9, 3)).toBe("9 of 12 new failures");
  expect(caughtText(1, 0)).toBe("1 of 1 new failure");
  expect(caughtText(1200, 34)).toBe("1,200 of 1,234 new failures");
});

test("the accuracy lives under the Report's key, so the Report's Refresh covers it", () => {
  expect(impactAccuracyQuery(42, 7).queryKey).toEqual(["report", 42, "impact-accuracy", 7]);
  expect(impactAccuracyStaleKeys(42)).toEqual([["report", 42, "impact-accuracy"]]);
  expect(runImpactQuery(42, 61).queryKey).toEqual(["run-impact", 42, 61]);
});
