import { mergeValues, valueLines } from "./logValues";

test("valueLines: one line per pattern with values, comma-separated, five at most then +N more", () => {
  expect(valueLines([
    { name: "route_key", values: ["wasToBos"] },
    { name: "empty", values: [] },
    { name: "trip_id", values: ["1", "2", "3", "4", "5", "6", "7"] },
  ])).toEqual(["route_key: wasToBos", "trip_id: 1, 2, 3, 4, 5 +2 more"]);
  expect(valueLines([{ name: "trip_id", values: ["1", "2", "3", "4", "5"] }])).toEqual(["trip_id: 1, 2, 3, 4, 5"]);
  expect(valueLines(undefined)).toEqual([]);
});

test("mergeValues: per pattern in name order, values in first-seen order, duplicates removed", () => {
  expect(mergeValues([
    [{ name: "trip_id", values: ["2", "1"] }],
    undefined,
    [{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["1", "3"] }],
  ])).toEqual([{ name: "route_key", values: ["r"] }, { name: "trip_id", values: ["2", "1", "3"] }]);
  expect(mergeValues([])).toEqual([]);
});
