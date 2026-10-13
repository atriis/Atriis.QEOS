import { locateFailedStep, matchesStep, scenarioSteps, stepLines } from "./failedStep";

const FEATURE = [
  "Feature: Search",                 // 1
  "  Background:",                   // 2
  "    Given I am logged in",        // 3
  "",                                // 4
  "  Scenario Outline: by city",     // 5
  "    When I search <city>",        // 6
  "    Then I see results",          // 7
  "      | name |",                  // 8
  "      | x    |",                  // 9
  "    Examples:",                   // 10
  "      | city   |",                // 11
  "      | Lisbon |",                // 12
  "",                                // 13
  "  Scenario: docs",                // 14
  "    Given a note:",               // 15
  '      """',                       // 16
  "      Then not a step",           // 17
  '      """',                       // 18
  "    Then it is saved",            // 19
].join("\n");

test("scenarioSteps returns the Background's steps then the scenario's, with lines", () => {
  expect(scenarioSteps(FEATURE, 5)).toEqual([
    { line: 3, text: "Given I am logged in" },
    { line: 6, text: "When I search <city>" },
    { line: 7, text: "Then I see results" },
  ]);
});

test("skips data tables and doc strings", () => {
  expect(scenarioSteps(FEATURE, 14).map((s) => s.line)).toEqual([3, 15, 19]);
});

test("matches by line when the text agrees", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "When I search Lisbon", line: 6 })).toBe(1);
});

test("a stale line falls back to the text", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "Then I see results", line: 6 })).toBe(2);
});

test("text only, and a Background step", () => {
  const steps = scenarioSteps(FEATURE, 5);
  expect(locateFailedStep(steps, { text: "Given I am logged in" })).toBe(0);
  expect(locateFailedStep(steps, { text: "When I book" })).toBeNull();
});

test("matches a template with regex characters", () => {
  expect(matchesStep('When I pay "<amount>"', 'When I pay "$10.00 (EUR)"')).toBe(true);
  expect(matchesStep("When I pay (cash)", "When I pay (cash)")).toBe(true);
  expect(matchesStep("When I pay (cash)", "When I pay cash")).toBe(false);
});

test("handles CRLF", () => {
  expect(stepLines("Scenario: s\r\n  Given a\r\n  When b\r\n")).toEqual([{ line: 2, text: "Given a" }, { line: 3, text: "When b" }]);
});

test("a Rule resets the Background", () => {
  const ruled = ["Feature: F", "  Background:", "    Given outer", "  Rule: r", "    Scenario: s", "      When x"].join("\n");
  expect(scenarioSteps(ruled, 5).map((s) => s.text)).toEqual(["When x"]);
});
