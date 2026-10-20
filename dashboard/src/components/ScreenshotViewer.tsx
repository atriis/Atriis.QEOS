import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ExternalLink, X } from "lucide-react";
import { Screenshot, getResultScreenshots, getScreenshotBlob } from "../api/screenshots";
import ErrorBanner from "./ErrorBanner";

type Props = {
  projectId: number;
  runId: number;
  resultId: number;
  /** The step the person clicked; the viewer opens on its first image (text first, then line, as the Gherkin view matches). */
  initialStep?: { text: string; line: number | null };
  open: boolean;
  onClose: () => void;
};

type Group = { label: string; first: number; count: number };

/** What a screenshot is called: a hook image has no step of its own. */
function labelOf(s: Screenshot): string {
  if (s.hook === "before") return "Start of scenario";
  if (s.hook === "after") return "End of scenario";
  return s.step_text;
}

function sameStep(a: Screenshot, b: Screenshot): boolean {
  return a.hook === b.hook && a.step_text === b.step_text && a.step_line === b.step_line;
}

/** Consecutive images of one step make one group. */
function groupShots(shots: Screenshot[]): Group[] {
  const groups: Group[] = [];
  shots.forEach((s, i) => {
    if (i > 0 && sameStep(shots[i - 1], s)) groups[groups.length - 1].count += 1;
    else groups.push({ label: labelOf(s), first: i, count: 1 });
  });
  return groups;
}

function startIndex(shots: Screenshot[], step?: Props["initialStep"]): number {
  if (!step) return 0;
  const byText = shots.findIndex((s) => s.hook === null && s.step_text === step.text);
  if (byText >= 0) return byText;
  const byLine = step.line == null ? -1 : shots.findIndex((s) => s.hook === null && s.step_line === step.line);
  return Math.max(0, byLine);
}

const FOCUSABLE = "button:not(:disabled), a[href]";

/** A result's step screenshots (ADR-036): a dialog with the steps listed and one image at a time, fetched when it is
 *  shown (with the Bearer token, so as a blob) and its object URL revoked when the dialog closes. Arrow keys page,
 *  Escape closes, and the image opens full size in a new tab. Nothing is requested while it is closed. */
export default function ScreenshotViewer(props: Props) {
  return props.open ? <Viewer {...props} /> : null;
}

function Viewer({ projectId, runId, resultId, initialStep, onClose }: Props) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const query = useQuery({
    queryKey: ["result-screenshots", projectId, runId, resultId],
    queryFn: () => getResultScreenshots(projectId, runId, resultId),
    staleTime: Infinity,
  });
  const shots = useMemo(() => query.data?.screenshots ?? [], [query.data]);
  const groups = useMemo(() => groupShots(shots), [shots]);
  const [chosen, setChosen] = useState<number | null>(null);
  const index = Math.min(chosen ?? startIndex(shots, initialStep), Math.max(0, shots.length - 1));
  const current: Screenshot | undefined = shots[index];
  const group = groups.filter((g) => g.first <= index).at(-1);

  // A real modal, as the command palette: its own node on <body>, everything else inert, no scroll under it.
  // Focus goes back to where it was on close.
  const host = useMemo(() => document.createElement("div"), []);
  useLayoutEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    document.body.appendChild(host);
    const others = Array.from(document.body.children).filter((el) => el !== host && !el.hasAttribute("inert"));
    others.forEach((el) => el.setAttribute("inert", ""));
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      others.forEach((el) => el.removeAttribute("inert"));
      document.body.style.overflow = overflow;
      host.remove();
      opener?.focus?.();
    };
  }, [host]);
  useEffect(() => closeRef.current?.focus(), []);

  const step = useCallback((by: number) => {
    setChosen((c) => {
      const from = Math.min(c ?? startIndex(shots, initialStep), shots.length - 1);
      return Math.max(0, Math.min(shots.length - 1, from + by));
    });
  }, [shots, initialStep]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onClose(); }
      else if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
      else if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
      else if (e.key === "Tab") {
        const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
        if (items.length === 0) return;
        const first = items[0];
        const last = items[items.length - 1];
        const active = document.activeElement;
        const inside = dialogRef.current?.contains(active);
        if (e.shiftKey && (active === first || !inside)) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && (active === last || !inside)) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, step]);

  // One object URL per image shown, kept while the dialog is open (paging back is free), all revoked on close
  const urls = useRef(new Map<number, string>());
  const [url, setUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const currentId = current?.id;
  useEffect(() => {
    if (currentId === undefined) return;
    setImageError(null);
    const cached = urls.current.get(currentId);
    if (cached) { setUrl(cached); return; }
    setUrl(null);
    let stale = false;
    getScreenshotBlob(projectId, currentId).then(
      (blob) => {
        if (stale) return;
        const made = URL.createObjectURL(blob);
        urls.current.set(currentId, made);
        setUrl(made);
      },
      (err) => { if (!stale) setImageError(err); },
    );
    return () => { stale = true; };
  }, [projectId, currentId, attempt]);
  useEffect(() => {
    const map = urls.current;
    return () => { map.forEach((u) => URL.revokeObjectURL(u)); map.clear(); };
  }, []);

  const label = current ? labelOf(current) : "";
  const position = current && group ? index - group.first + 1 : 0;
  const alt = group && group.count > 1 ? `${label}, image ${position} of ${group.count}` : label;

  return createPortal(
    <>
      <div className="shot-backdrop" aria-hidden="true" onMouseDown={onClose} />
      <div ref={dialogRef} className="shot-viewer" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <div className="shot-head">
          <h2 id={titleId}>Screenshots</h2>
          <button ref={closeRef} type="button" className="ghost" aria-label="Close screenshots" onClick={onClose}>
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        {query.isPending && <p className="muted shot-note" role="status">Loading screenshots…</p>}
        {query.error != null && <ErrorBanner error={query.error} onRetry={() => query.refetch()} />}
        {query.data != null && shots.length === 0 && <p className="muted shot-note">No screenshots for this result.</p>}
        {current && (
          <div className="shot-body">
            <ol className="shot-steps" aria-label="Steps with screenshots">
              {groups.map((g) => (
                <li key={g.first}>
                  <button type="button" className="shot-step" aria-current={g === group ? "true" : undefined}
                    onClick={() => setChosen(g.first)}>
                    <span className="shot-step-label">{g.label}</span>
                    {g.count > 1 && <span className="shot-count">{g.count}</span>}
                  </button>
                </li>
              ))}
            </ol>
            <div className="shot-stage">
              <div className="shot-frame">
                {url && <img src={url} alt={alt} />}
                {!url && imageError == null && <p className="muted" role="status">Loading image…</p>}
                {imageError != null && <ErrorBanner error={imageError} onRetry={() => setAttempt((a) => a + 1)} />}
              </div>
              <div className="shot-tools">
                <button type="button" aria-label="Previous screenshot" disabled={index === 0} onClick={() => step(-1)}>
                  <ChevronLeft size={16} aria-hidden="true" />
                </button>
                <span className="shot-position" role="status" aria-live="polite">{index + 1} of {shots.length}</span>
                <button type="button" aria-label="Next screenshot" disabled={index === shots.length - 1} onClick={() => step(1)}>
                  <ChevronRight size={16} aria-hidden="true" />
                </button>
                {url && (
                  <a className="shot-full" href={url} target="_blank" rel="noopener noreferrer">
                    Open full size <ExternalLink size={14} aria-hidden="true" />
                  </a>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>,
    host,
  );
}
