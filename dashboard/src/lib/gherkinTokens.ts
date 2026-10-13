// Read-only highlighting for imported cases. Keyword lists cover English and Portuguese, the
// languages in use; other languages still render, just without keyword colour.
export type TokenKind = "keyword" | "tag" | "table" | "docstring" | "comment" | "text" | "param" | "string";
export interface Token { kind: TokenKind; text: string }

export const HEADINGS = ["Scenario Outline:", "Scenario Template:", "Scenario:", "Example:", "Examples:", "Background:", "Rule:", "Feature:",
  "Esquema do Cenário:", "Cenário:", "Exemplos:", "Contexto:", "Regra:", "Funcionalidade:"];
export const STEPS = ["Given ", "When ", "Then ", "And ", "But ", "* ", "Dado ", "Dada ", "Quando ", "Então ", "E ", "Mas "];

const PLACEHOLDER = /<[^\s<>"][^<>"]*>/g;

/** Splits text into plain runs and <placeholder> params. */
function withParams(text: string, plain: TokenKind): Token[] {
  const out: Token[] = [];
  let at = 0;
  for (const m of text.matchAll(PLACEHOLDER)) {
    if (m.index! > at) out.push({ kind: plain, text: text.slice(at, m.index) });
    out.push({ kind: "param", text: m[0] });
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push({ kind: plain, text: text.slice(at) });
  return out;
}

/** Step text: "quoted values" are strings (a <placeholder> inside one is still a param); <placeholder>s are params. */
function stepText(text: string): Token[] {
  const out: Token[] = [];
  let at = 0;
  for (const m of text.matchAll(/"[^"]*"/g)) {
    if (m.index! > at) out.push(...withParams(text.slice(at, m.index), "text"));
    out.push(...withParams(m[0], "string"));
    at = m.index! + m[0].length;
  }
  if (at < text.length) out.push(...withParams(text.slice(at), "text"));
  return out;
}

export function tokenizeLine(line: string): Token[] {
  const indent = line.match(/^\s*/)![0];
  const rest = line.slice(indent.length);
  const lead: Token[] = indent ? [{ kind: "text", text: indent }] : [];
  if (rest.startsWith("#")) return [...lead, { kind: "comment", text: rest }];
  if (rest.startsWith("@")) return [...lead, { kind: "tag", text: rest }];
  if (rest.startsWith("|")) return [...lead, ...withParams(rest, "table")];
  if (rest.startsWith('"""') || rest.startsWith("```")) return [...lead, { kind: "docstring", text: rest }];
  const keyword = [...HEADINGS, ...STEPS].find((k) => rest.startsWith(k));
  if (!keyword) return [...lead, { kind: "text", text: rest }];
  const tail = rest.slice(keyword.length);
  const isStep = STEPS.includes(keyword);
  return [...lead, { kind: "keyword", text: keyword }, ...(tail ? (isStep ? stepText(tail) : [{ kind: "text" as const, text: tail }]) : [])];
}
