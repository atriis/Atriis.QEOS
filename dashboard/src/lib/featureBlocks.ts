/** A run of lines of a .feature file: 1-based, inclusive. */
export interface Block { start: number; end: number; text: string }

const isTagOrComment = (l: string) => /^\s*[@#]/.test(l);

/** The file cut into its preamble (Feature, description, Background) and one block per scenario heading:
 *  a block starts at its heading, moved up over the tag/comment lines right above it, and ends before the next
 *  block (trailing blank lines dropped). */
export function splitFeature(content: string, headingLines: number[]): { preamble: Block | null; scenarios: Map<number, Block> } {
  const lines = content.split(/\r?\n/);
  const headings = [...new Set(headingLines)].filter((h) => h >= 1 && h <= lines.length).sort((a, b) => a - b);
  const starts = headings.map((h, i) => {
    let s = h;
    const floor = i > 0 ? headings[i - 1] + 1 : 1;
    while (s - 1 >= floor && isTagOrComment(lines[s - 2])) s--;
    return s;
  });
  const block = (start: number, before: number): Block | null => {
    let end = before;
    while (end >= start && lines[end - 1].trim() === "") end--;
    return end < start ? null : { start, end, text: lines.slice(start - 1, end).join("\n") };
  };
  const scenarios = new Map<number, Block>();
  headings.forEach((h, i) => {
    const b = block(starts[i], (starts[i + 1] ?? lines.length + 1) - 1);
    if (b) scenarios.set(h, b);
  });
  return { preamble: block(1, (starts[0] ?? lines.length + 1) - 1), scenarios };
}
