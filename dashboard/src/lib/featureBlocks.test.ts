import { splitFeature } from "./featureBlocks";

const FILE = ["Feature: F", "  Background:", "    Given bg", "", "  @smoke", "  Scenario: one", "    When a", "",
              "  Scenario: two", "    When b", ""].join("\n");

test("splits the preamble and each scenario, tags included", () => {
  const { preamble, scenarios } = splitFeature(FILE, [6, 9]);
  expect(preamble).toEqual({ start: 1, end: 3, text: "Feature: F\n  Background:\n    Given bg" });
  expect(scenarios.get(6)).toEqual({ start: 5, end: 7, text: "  @smoke\n  Scenario: one\n    When a" });
  expect(scenarios.get(9)).toEqual({ start: 9, end: 10, text: "  Scenario: two\n    When b" });
});
