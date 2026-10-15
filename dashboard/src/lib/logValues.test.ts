import { linkFor, logFileName, markValues, mergeValues, valueLines } from "./logValues";

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

test("markValues wraps each value with its pattern name and keeps everything else as text", () => {
  const segments = markValues('INFO tripId="3960562" <b>&amp;</b> routeKey="wasToBos"', [
    { name: "trip_id", values: ["3960562"] },
    { name: "route_key", values: ["wasToBos"] },
  ]);
  expect(segments).toEqual([
    { text: 'INFO tripId="' }, { text: "3960562", name: "trip_id" },
    { text: '" <b>&amp;</b> routeKey="' }, { text: "wasToBos", name: "route_key" }, { text: '"' },
  ]);
  expect(markValues("plain", [])).toEqual([{ text: "plain" }]);
  expect(markValues("", [{ name: "x", values: ["x"] }])).toEqual([{ text: "" }]);
});

test("overlapping values mark the longer one, never inside a mark", () => {
  const segments = markValues("id=3960562 and 396", [
    { name: "short", values: ["396"] },
    { name: "long", values: ["3960562"] },
  ]);
  expect(segments).toEqual([
    { text: "id=" }, { text: "3960562", name: "long" }, { text: " and " }, { text: "396", name: "short" },
  ]);
});

test("a 64 KB log with many values is marked in well under a second", () => {
  const text = Array.from({ length: 3000 }, (_, i) => `INFO line ${i} tripId="${1000 + (i % 200)}"`).join("\n");
  const groups = Array.from({ length: 20 }, (_, g) => ({
    name: `p${g}`, values: Array.from({ length: 20 }, (_, i) => String(1000 + g * 20 + i)),
  }));
  const started = performance.now();
  const marked = markValues(text, groups).filter((s) => s.name).length;
  expect(performance.now() - started).toBeLessThan(1000);
  expect(marked).toBeGreaterThanOrEqual(3000); // every tripId, plus line numbers that happen to equal a value
});

test("logFileName keeps letters, digits, dots, dashes and underscores", () => {
  expect(logFileName("Books a trip / Lisbon?", 61)).toBe("Books_a_trip_Lisbon-run-61.txt");
  expect(logFileName("", 7)).toBe("result-run-7.txt");
});
