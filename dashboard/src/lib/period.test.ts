import { addDays, checkRange, dayStartIso, formatPeriod, presetRange } from "./period";

test("formatPeriod repeats the year only when the range crosses one", () => {
  expect(formatPeriod("2026-09-09", "2026-10-08")).toBe("9 Sep – 8 Oct 2026");
  expect(formatPeriod("2025-12-20", "2026-01-05")).toBe("20 Dec 2025 – 5 Jan 2026");
});

test("checkRange names the problem and the fields it is about", () => {
  const today = "2026-10-16";
  expect(checkRange("2026-10-01", "2026-10-16", today)).toBeNull();
  expect(checkRange("2026-10-01", "", today)).toEqual({ message: "Give both From and To", fields: ["to"] });
  expect(checkRange("", "2026-10-16", today)).toEqual({ message: "Give both From and To", fields: ["from"] });
  expect(checkRange("2026-13-01", "2026-10-16", today)).toEqual({ message: "Dates must be calendar days", fields: ["from"] });
  expect(checkRange("2026-10-16", "2026-10-01", today)).toEqual({ message: "From must be on or before To", fields: ["from", "to"] });
  expect(checkRange(addDays(today, -100), today, today)).toEqual({ message: "The period can be at most 90 days", fields: ["from", "to"] });
  expect(checkRange(today, addDays(today, 1), today)).toEqual({ message: "To cannot be after today", fields: ["to"] });
  expect(checkRange(addDays(today, -420), addDays(today, -410), today)).toEqual({ message: "From can be at most 400 days ago", fields: ["from"] });
});

test("presetRange is the last N days ending today", () => {
  expect(presetRange("7", "2026-10-16")).toEqual({ from: "2026-10-10", to: "2026-10-16" });
  expect(presetRange("30", "2026-10-16")).toEqual({ from: "2026-09-17", to: "2026-10-16" });
});

test("dayStartIso is the local start of the day, optionally of the next one", () => {
  const start = new Date(2026, 9, 16).toISOString();
  expect(dayStartIso("2026-10-16")).toBe(start);
  expect(dayStartIso("2026-10-16", 1)).toBe(new Date(2026, 9, 17).toISOString());
});
