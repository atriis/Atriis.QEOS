import { stepLines } from "./failedStep";
import { placeScreenshots } from "./screenshotLines";

const GHERKIN = [
  "Scenario: book",            // 1
  "  Given I am on the page",  // 2
  "  When I book <city>",      // 3
  "  Then it is confirmed",    // 4
].join("\n");
const lines = stepLines(GHERKIN);
const shot = (step_text: string, step_line: number | null, count = 1, hook: "before" | "after" | null = null) =>
  ({ step_text, step_line, hook, count });

test("each step's screenshots go on its line", () => {
  const placed = placeScreenshots(lines, [shot("When I book Lisbon", 3), shot("Then it is confirmed", 4, 2)]);
  expect([...placed.byLine]).toEqual([
    [3, { count: 1, step: { text: "When I book Lisbon", line: 3 } }],
    [4, { count: 2, step: { text: "Then it is confirmed", line: 4 } }],
  ]);
  expect(placed.unplaced).toBe(0);
});

test("a step that is no longer in the Gherkin (edited since the run) is unplaced", () => {
  const placed = placeScreenshots(lines, [shot("When I cancel Lisbon", 3, 2), shot("Then it is confirmed", 4)]);
  expect([...placed.byLine.keys()]).toEqual([4]);
  expect(placed.unplaced).toBe(2);
});

test("a step's own images and a hook group placed on it make one entry, counted together, opening on its own", () => {
  const placed = placeScreenshots(lines, [shot("Then it is confirmed", 4, 2, "after"), shot("Then it is confirmed", 4, 1)]);
  expect(placed.byLine.get(4)).toEqual({ count: 3, step: { text: "Then it is confirmed", line: 4 } });
  expect(placed.byLine.size).toBe(1);
});

test("no screenshot steps: nothing placed, nothing unplaced", () => {
  expect(placeScreenshots(lines, undefined)).toEqual({ byLine: new Map(), unplaced: 0 });
});

test("a locate function decides the shown line; null leaves the images unplaced", () => {
  const placed = placeScreenshots((s) => (s.text === "Given bg" ? null : 7), [shot("Given bg", 2), shot("When a", 5)]);
  expect([...placed.byLine.keys()]).toEqual([7]);
  expect(placed.unplaced).toBe(1);
});
