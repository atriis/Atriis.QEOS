import { HEADINGS, STEPS } from "./gherkinTokens";

export interface FailedStep { text: string; line?: number }
export interface StepLine { line: number; text: string }

const BACKGROUND = ["Background:", "Contexto:"];
const RULE = ["Rule:", "Regra:"];
const isStep = (t: string) => STEPS.some((k) => t.startsWith(k));
const isHeading = (t: string, set: string[] = HEADINGS) => set.some((h) => t.startsWith(h));
const isBoundary = (t: string) => isHeading(t) || t.startsWith("@");

/** Steps between 1-based lines from..to; table rows and doc strings are not steps. */
export function stepLines(text: string, from = 1, to = Number.MAX_SAFE_INTEGER): StepLine[] {
  const lines = text.split(/\r?\n/);
  const out: StepLine[] = [];
  let fence: string | null = null;
  lines.forEach((raw, i) => {
    const n = i + 1;
    const t = raw.trim();
    if (fence) { if (t.startsWith(fence)) fence = null; return; }
    if (t.startsWith('"""') || t.startsWith("```")) { fence = t.slice(0, 3); return; }
    if (n >= from && n <= to && isStep(t)) out.push({ line: n, text: t });
  });
  return out;
}

/** The trimmed lines, with doc-string fences and their contents blanked so they never read as structure. */
function structure(source: string): string[] {
  let fence: string | null = null;
  return source.split(/\r?\n/).map((raw) => {
    const t = raw.trim();
    if (fence) { if (t.startsWith(fence)) fence = null; return ""; }
    if (t.startsWith('"""') || t.startsWith("```")) { fence = t.slice(0, 3); return ""; }
    return t;
  });
}

/** The steps a scenario runs: the feature Background's, then its Rule's Background's, then its own. */
export function scenarioSteps(source: string, scenarioLine: number): StepLine[] {
  const lines = structure(source);
  let featureBg = 0;
  let ruleBg = 0;
  let inRule = false;
  for (let n = 1; n < scenarioLine && n <= lines.length; n++) {
    const t = lines[n - 1];
    if (isHeading(t, RULE)) { inRule = true; ruleBg = 0; }
    else if (isHeading(t, BACKGROUND)) { if (inRule) ruleBg = n; else featureBg = n; }
  }
  const endBefore = (start: number) => {
    for (let n = start + 1; n <= lines.length; n++) if (isBoundary(lines[n - 1])) return n - 1;
    return lines.length;
  };
  const steps = (start: number) => (start ? stepLines(source, start, endBefore(start)) : []);
  return [...steps(featureBg), ...steps(ruleBg), ...steps(scenarioLine)];
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A step of the case against the step that ran: each <placeholder> matches any non-empty text. */
export function matchesStep(template: string, actual: string): boolean {
  const pattern = template.trim().split(/<[^<>"]+>/).map(escape).join(".+");
  return new RegExp(`^${pattern}$`).test(actual.trim());
}

export function locateFailedStep(steps: StepLine[], failed: FailedStep): number | null {
  if (failed.line != null) {
    const at = steps.findIndex((s) => s.line === failed.line);
    if (at >= 0 && matchesStep(steps[at].text, failed.text)) return at;
  }
  const byText = steps.findIndex((s) => matchesStep(s.text, failed.text));
  return byText >= 0 ? byText : null;
}
