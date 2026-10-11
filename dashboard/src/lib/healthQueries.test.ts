import { flakyHealthQuery, flakyWindowQuery, passRateWeeksQuery } from "./healthQueries";

test("the weekly pass rate adds a branch to its key only when one is chosen, so the Cases tile shares the default", () => {
  expect(passRateWeeksQuery(42, "UTC").queryKey).toEqual(["trends", 42, "overview-weeks", "UTC"]);
  expect(passRateWeeksQuery(42, "UTC", "main").queryKey).toEqual(["trends", 42, "overview-weeks", "UTC", "main"]);
});

test("another flaky window uses the Flaky view's own key", () => {
  expect(flakyHealthQuery(42).queryKey).toEqual(["flaky", 42, "health"]);
  expect(flakyWindowQuery(42, 30).queryKey).toEqual(["flaky", 42, 30, 5, 0.3, "", false]);
});
