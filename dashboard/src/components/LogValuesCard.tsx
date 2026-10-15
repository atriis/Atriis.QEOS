import { FormEvent, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../api/http";
import { addLogPattern, listLogPatterns, previewLogPattern, removeLogPattern, type LogScan } from "../api/logPatterns";
import { plural } from "../lib/words";
import ConfirmButton from "./ConfirmButton";
import ErrorBanner from "./ErrorBanner";

interface Props {
  projectId: number;
  /** Undefined while the role is loading: the list shows, the controls wait. */
  canEdit: boolean | undefined;
}

/** The help's examples (spec §4.1); clicking one fills the expression. */
export const PATTERN_EXAMPLES = ['tripId="(\\d+)"', 'routeKey="([^"]+)"', 'status="([^"]+)"'];
const FIELDS = ["name", "pattern", "link_template"] as const;
type Field = (typeof FIELDS)[number];
/** While past runs are scanned the list is read again this often, so "Scanning past runs…" goes away by itself. */
const SCAN_POLL_MS = 3000;
/** A queued scan waits for the next add or restart: a slow poll is enough to notice when it starts. */
const QUEUED_POLL_MS = 30_000;

/** How often the list is read again for a scan state: 3 s running, 30 s queued, not at all when idle. */
export function scanPollInterval(state: LogScan["state"] | undefined): number | false {
  return state === "running" ? SCAN_POLL_MS : state === "queued" ? QUEUED_POLL_MS : false;
}
const HELP_LABEL = "How values are captured";

/** Settings card for log-value patterns (ADR-032), next to Masking and built like it. */
export default function LogValuesCard({ projectId, canEdit }: Props) {
  const qc = useQueryClient();
  const queryKey = ["log-patterns", projectId];
  const [name, setName] = useState("");
  const [pattern, setPattern] = useState("");
  const [link, setLink] = useState("");
  const [sample, setSample] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);
  const id = useId();
  const nameInput = useRef<HTMLInputElement>(null);
  const patternInput = useRef<HTMLInputElement>(null);
  const linkInput = useRef<HTMLInputElement>(null);
  const helpButton = useRef<HTMLButtonElement>(null);

  const patterns = useQuery({
    queryKey,
    queryFn: () => listLogPatterns(projectId),
    refetchInterval: (query) => scanPollInterval(query.state.data?.scan.state),
  });
  const preview = useMutation({
    mutationFn: (input: { name: string; pattern: string; sample: string }) =>
      previewLogPattern(projectId, input.name, input.pattern, input.sample),
  });
  const add = useMutation({
    mutationFn: () => addLogPattern(projectId, { name: name.trim(), pattern, link_template: link.trim() || null }),
    onSuccess: () => {
      setName("");
      setPattern("");
      setLink("");
      setSample("");
      preview.reset();
      return qc.invalidateQueries({ queryKey });
    },
  });
  const remove = useMutation({
    mutationFn: (patternId: number) => removeLogPattern(projectId, patternId),
    onSuccess: () => qc.invalidateQueries({ queryKey }),
  });

  // A refusal about one field is shown under it; anything else (the limit, a 500) is a banner
  const error = add.error ?? preview.error;
  const errorField: Field | null =
    error instanceof ApiError && FIELDS.includes(error.code as Field) ? (error.code as Field) : null;
  const fieldError = (field: Field) => (errorField === field && error instanceof ApiError ? error.detail : null);
  const describedBy = (field: Field) => `${id}-${field}-hint${errorField === field ? ` ${id}-${field}-error` : ""}`;
  useEffect(() => {
    const target = { name: nameInput, pattern: patternInput, link_template: linkInput }[errorField ?? "name"];
    if (errorField) target.current?.focus();
  }, [error, errorField]);

  function applyExample(example: string) {
    setPattern(example);
    setHelpOpen(false);
    patternInput.current?.focus();
  }
  function closeHelpOnEscape(e: KeyboardEvent) {
    if (e.key !== "Escape" || !helpOpen) return;
    e.preventDefault();
    setHelpOpen(false);
    helpButton.current?.focus();
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    preview.reset();
    add.mutate();
  }

  const rows = patterns.data?.patterns;
  const found = preview.data?.values;
  return (
    <div className="card">
      <h2>Log values</h2>
      <p className="muted">
        Show values your tests log, such as the trip a booking scenario created, on every Last runs bar and on the
        test case page. Each pattern is a regular expression matched against the result's log after masking.
      </p>

      {patterns.error != null && <ErrorBanner error={patterns.error} onRetry={() => patterns.refetch()} />}
      {patterns.isPending && <p className="muted">Loading patterns…</p>}
      {rows?.length === 0 && <p className="muted">This project has no log-value patterns.</p>}
      {rows != null && rows.length > 0 && (
        <table className="data">
          <thead>
            <tr>
              <th>Name</th>
              <th>Pattern</th>
              <th>Link</th>
              {canEdit && <th><span className="sr-only">Actions</span></th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id}>
                <td><code>{p.name}</code></td>
                <td className="wrap-anywhere"><code>{p.pattern}</code></td>
                <td className="wrap-anywhere">
                  {p.link_template ? <code>{p.link_template}</code> : <span className="muted">None</span>}
                </td>
                {canEdit && (
                  <td className="row-actions">
                    <ConfirmButton
                      label="Remove"
                      ariaLabel={`Remove pattern ${p.name}`}
                      question={`Remove ${p.name}? Its values disappear from every run.`}
                      confirmLabel="Remove"
                      onConfirm={() => remove.mutate(p.id)}
                      disabled={remove.isPending}
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {patterns.data?.scan.state === "running" && <p className="muted" role="status">Scanning past runs…</p>}
      {patterns.data?.scan.state === "queued" && (
        <p className="muted" role="status">Scan queued; it runs when a pattern is added or the service restarts.</p>
      )}
      {remove.error != null && <ErrorBanner error={remove.error} />}

      {canEdit === false && <p className="muted">Only owners, admins and members can add or remove patterns.</p>}
      {canEdit && (
        <form className="form-stack masking-form" onSubmit={onSubmit}>
          <h4>Add a pattern</h4>
          <label>
            Name
            <input
              ref={nameInput}
              required
              maxLength={32}
              autoComplete="off"
              spellCheck={false}
              placeholder="trip_id"
              aria-invalid={errorField === "name" || undefined}
              aria-describedby={describedBy("name")}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <span id={`${id}-name-hint`} className="muted field-hint">
              The label in tooltips. Lowercase letters, digits, underscores.
            </span>
            {fieldError("name") && <span id={`${id}-name-error`} className="field-error">{fieldError("name")}</span>}
          </label>

          <div className="field-with-help" onKeyDown={closeHelpOnEscape}>
            <div className="field-with-help-head">
              <label htmlFor={`${id}-pattern`}>Regular expression</label>
              <button
                ref={helpButton}
                type="button"
                className="help-toggle"
                aria-label={HELP_LABEL}
                aria-expanded={helpOpen}
                aria-controls={`${id}-help`}
                onClick={() => setHelpOpen((open) => !open)}
              >
                ?
              </button>
            </div>
            {helpOpen && (
              <div id={`${id}-help`} className="help-popover" role="group" aria-label={HELP_LABEL}>
                <p>
                  With one capture group <code>( … )</code>, the value is that part. Without a group, the whole match
                  is the value. Values come from the masked log, so a masked value is never captured.
                </p>
                <p>Examples:</p>
                <ul className="help-examples">
                  {PATTERN_EXAMPLES.map((example) => (
                    <li key={example}>
                      <button type="button" className="fchip mono" onClick={() => applyExample(example)}>{example}</button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <input
              id={`${id}-pattern`}
              ref={patternInput}
              required
              maxLength={256}
              autoComplete="off"
              spellCheck={false}
              className="mono"
              placeholder={'tripId="(\\d+)"'}
              aria-invalid={errorField === "pattern" || undefined}
              aria-describedby={describedBy("pattern")}
              value={pattern}
              onChange={(e) => setPattern(e.target.value)}
            />
            <span id={`${id}-pattern-hint`} className="muted field-hint">
              RE2 syntax: no backreferences or lookarounds. At most one capture group.
            </span>
            {fieldError("pattern") && (
              <span id={`${id}-pattern-error`} className="field-error">{fieldError("pattern")}</span>
            )}
          </div>

          <label>
            <span>Link <span className="muted">(optional)</span></span>
            <input
              ref={linkInput}
              inputMode="url"
              maxLength={500}
              autoComplete="off"
              spellCheck={false}
              placeholder="https://backoffice.example.com/trips/{value}"
              aria-invalid={errorField === "link_template" || undefined}
              aria-describedby={describedBy("link_template")}
              value={link}
              onChange={(e) => setLink(e.target.value)}
            />
            <span id={`${id}-link_template-hint`} className="muted field-hint">
              Each value becomes a link here, with <code>{"{value}"}</code> replaced by the value. https only.
            </span>
            {fieldError("link_template") && (
              <span id={`${id}-link_template-error`} className="field-error">{fieldError("link_template")}</span>
            )}
          </label>

          <label>
            <span>Log lines <span className="muted">(optional, never saved)</span></span>
            <textarea
              rows={3}
              spellCheck={false}
              placeholder={'INFO 20:23:24 [App] Trip id captured from booking flow tripId="3960562"'}
              value={sample}
              onChange={(e) => setSample(e.target.value)}
            />
          </label>
          {found != null && (
            <div role="status" className="preview-result">
              <span className="muted">
                {found.length === 0 ? "No values found in these lines." : `${plural(found.length, "value", "values")} found:`}
              </span>
              {found.length > 0 && (
                <ul className="chip-list" aria-label="Values found">
                  {found.map((value) => (
                    <li key={value} className="chip"><code>{preview.variables?.name}: {value}</code></li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {error != null && errorField == null && <ErrorBanner error={error} />}
          <div className="button-row">
            <button
              type="button"
              onClick={() => preview.mutate({ name: name.trim(), pattern, sample })}
              disabled={preview.isPending || !name.trim() || !pattern || !sample}
            >
              {preview.isPending ? "Previewing…" : "Preview"}
            </button>
            <button type="submit" disabled={add.isPending}>
              {add.isPending ? "Adding…" : "Add pattern"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
