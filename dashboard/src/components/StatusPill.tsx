import type { RunVerdict } from "./RunStatusBadge";
import { AlertTriangle, Ban, Check, CheckCircle2, CircleDashed, Clock, Loader2, XCircle, type LucideIcon } from "lucide-react";

export type PillTone = "passed" | "failed" | "errored" | "running" | "queued" | "cancelled" | "skipped" | "ready" | "neutral";

/** The icon beside the word wherever a status colour is used (Never Alone): the shape differs per tone too. */
const ICON: Record<PillTone, LucideIcon | null> = {
  passed: CheckCircle2,
  ready: Check,
  failed: XCircle,
  errored: AlertTriangle,
  running: Loader2,
  queued: Clock,
  cancelled: Ban,
  skipped: CircleDashed,
  neutral: null,
};

/** A small status pill: the word in the tone's readable text colour, a hairline border tinted with the status hue,
 *  and an icon. Neutral states (a draft) are secondary text on a neutral border, with no icon. */
export default function StatusPill({ tone, label, note }: { tone: PillTone; label: string; note?: string }) {
  const Icon = ICON[tone];
  return (
    <span className={`pill pill-${tone}`}>
      {Icon && <Icon size={12} aria-hidden="true" />}
      {note ? `${label} · ${note}` : label}
    </span>
  );
}

const CASE: Record<string, { tone: PillTone; label: string }> = {
  draft: { tone: "neutral", label: "Draft" },
  ready: { tone: "ready", label: "Ready" },
  archived: { tone: "neutral", label: "Archived" },
};

/** A test case's status: draft and archived are neutral; ready carries the passed hue with a plain tick
 *  (not the circled one, so it never reads as a test result). */
export function CaseStatusPill({ status }: { status: string }) {
  const view = CASE[status] ?? { tone: "neutral" as const, label: status };
  return <StatusPill tone={view.tone} label={view.label} />;
}

const VERDICT: Record<RunVerdict, string> = { passed: "Passed", failed: "Failed", errored: "Errored" };

/** A run's verdict in a table row (the larger RunStatusBadge stays for summaries). */
export function RunVerdictPill({ verdict }: { verdict: RunVerdict }) {
  return <StatusPill tone={verdict} label={VERDICT[verdict]} />;
}
