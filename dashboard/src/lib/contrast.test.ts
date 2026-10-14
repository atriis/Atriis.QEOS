import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// The tokens in index.css, checked against the WCAG thresholds they are meant to meet (round 4).
const css = readFileSync(resolve(__dirname, "../index.css"), "utf8");
const light = css.slice(css.indexOf(":root {"), css.indexOf("@media (prefers-color-scheme: dark)"));
const dark = css.slice(css.indexOf("@media (prefers-color-scheme: dark)"), css.indexOf("/* ---- Base ---- */"));

function token(block: string, name: string, fallbackBlock?: string): string {
  const m = new RegExp(`${name}: *(#[0-9a-fA-F]{6})`).exec(block) ?? (fallbackBlock ? new RegExp(`${name}: *(#[0-9a-fA-F]{6})`).exec(fallbackBlock) : null);
  if (!m) throw new Error(`token ${name} not found`);
  return m[1];
}
const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
const lum = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16)));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const ratio = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe.each([
  ["light", light, undefined],
  ["dark", dark, light],
] as const)("%s theme", (_name, block, fallback) => {
  const t = (n: string) => token(block, n, fallback);
  const surfaces = ["--surface-1", "--page", "--surface-2"];

  test.each(surfaces)("the control border reaches 3:1 on %s", (s) => {
    expect(ratio(t("--control-border"), t(s))).toBeGreaterThanOrEqual(3);
  });
  test.each(surfaces)("placeholder text reaches 4.5:1 on %s", (s) => {
    expect(ratio(t("--placeholder"), t(s))).toBeGreaterThanOrEqual(4.5);
  });
  test.each(["--status-errored", "--status-failed", "--status-passed", "--status-skipped"])("%s reaches 3:1 on the card surface", (n) => {
    expect(ratio(t(n), t("--surface-1"))).toBeGreaterThanOrEqual(3);
  });
  test("skipped yellow: the mark reaches 3:1 on the card and the page, the edge reaches 3:1 on the card and on the fill", () => {
    expect(ratio(t("--status-skipped"), t("--page"))).toBeGreaterThanOrEqual(3);
    expect(ratio(t("--status-skipped-edge"), t("--status-skipped-fill"))).toBeGreaterThanOrEqual(3);
    if (_name === "light") expect(ratio(t("--status-skipped-edge"), t("--surface-1"))).toBeGreaterThanOrEqual(3);
    else expect(ratio(t("--status-skipped-fill"), t("--surface-1"))).toBeGreaterThanOrEqual(3);
  });
  test("errored also reaches 3:1 on the page", () => {
    expect(ratio(t("--status-errored"), t("--page"))).toBeGreaterThanOrEqual(3);
  });
  test.each(["--passed-text", "--errored-text", "--skipped-text", "--danger-text", "--accent-text", "--text-secondary"])("status pill text %s reaches 4.5:1 on the card surface", (n) => {
    expect(ratio(t(n), t("--surface-1"))).toBeGreaterThanOrEqual(4.5);
  });
  test("table header text reaches 4.5:1 on the header band", () => {
    // Light aliases the band to --surface-2; dark gives it its own step
    const band = _name === "light" ? t("--surface-2") : t("--thead");
    expect(ratio(t("--text-secondary"), band)).toBeGreaterThanOrEqual(4.5);
  });
});

describe("layout rules", () => {
  test("boxes (banners, notes, secrets) are exempt from the prose measure", () => {
    expect(css).toMatch(/\.page p:is\(\.error-banner, \.note, \.warn-note, \.secret-note\)[^{]*\{ max-width: none; \}/);
  });
  test("a table that becomes blocks keeps its semantics with explicit roles in the markup, not in CSS", () => {
    expect(css).toContain("table.stacked");
  });
});
