import { linkFor, mergeValues, valueLines } from "./logValues";

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

const T = "https://backoffice.example.com/trips/{value}";

test("linkFor keeps every value inside the template", () => {
  expect(linkFor(T, "3960562")).toBe("https://backoffice.example.com/trips/3960562");
  expect(linkFor(T, "../admin")).toBe("https://backoffice.example.com/trips/..%2Fadmin");
  expect(linkFor(T, "@evil.example")).toBe("https://backoffice.example.com/trips/%40evil.example");
  expect(linkFor(T, "a#b")).toBe("https://backoffice.example.com/trips/a%23b");
  expect(linkFor(T, "x?y=1")).toBe("https://backoffice.example.com/trips/x%3Fy%3D1");
  expect(linkFor(T, "a b")).toBe("https://backoffice.example.com/trips/a%20b");
  expect(linkFor("https://backoffice.example.com/search?trip={value}&tab=1", "a&b"))
    .toBe("https://backoffice.example.com/search?trip=a%26b&tab=1");
  // A whole path segment of dots would move up the path: no link (the chip still copies)
  expect(linkFor(T, "..")).toBeNull();
  expect(linkFor(T, ".")).toBeNull();
});

test("a template that is not https gives no link", () => {
  for (const template of [null, undefined, "", "http://backoffice.example.com/{value}", "javascript:alert(1)//{value}",
    "data:text/html,{value}", "https://{value}.example.com/", "https://backoffice.example.com{value}",
    "https://backoffice.example.com/{value}/{value}", "https://backoffice.example.com/trips",
    "https://user@backoffice.example.com/{value}", "not a url {value}"]) {
    expect(linkFor(template, "1")).toBeNull();
  }
});
