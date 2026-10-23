type Cell = string | number | null;

function escapeCell(value: Cell): string {
  if (value === null) return "";
  const s = String(value);
  // RFC 4180: quote fields containing comma, quote or newline; double quotes.
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

export function toCsv(headers: string[], rows: Cell[][]): string {
  const lines = [headers, ...rows].map((cells) => cells.map(escapeCell).join(","));
  return lines.join("\r\n");
}

export function downloadCsv(filename: string, csv: string): void {
  downloadBlob(filename, new Blob([csv], { type: "text/csv;charset=utf-8" }));
}

const REVOKE_AFTER_MS = 10_000;

export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  // Not at once: some browsers read the URL after click() returns, and an early revoke cancels the download
  setTimeout(() => URL.revokeObjectURL?.(url), REVOKE_AFTER_MS);
}
