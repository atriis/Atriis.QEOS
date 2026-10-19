import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ListPlus } from "lucide-react";
import { appendSuiteCases, createSuite, listSuites } from "../api/cases";
import { ApiError } from "../api/http";
import ErrorBanner from "./ErrorBanner";

const NEW = "new";

interface Result { suiteId: number; name: string; added: number; already: number }

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** The Cases selection bar's "Add to suite" (spec 2026-10-19 §5.5). A button that opens an inline card (DESIGN.md: no
 *  modal) to pick a manual suite, or make a new one, and append the selected cases. `onDone` runs after cases were
 *  added; the selection is the caller's and stays. Cancel and Escape give focus back to the button. */
export default function AddToSuiteDialog({ projectId, numbers, onDone }: { projectId: number; numbers: number[]; onDone: () => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState("");
  const [name, setName] = useState("");
  const [fieldError, setFieldError] = useState<{ on: "choice" | "name"; text: string } | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  // A suite made by an attempt whose append then failed: a retry appends to it instead of clashing on the name
  const made = useRef<{ id: number; name: string } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const choiceRef = useRef<HTMLSelectElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const doneRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  const ids = useId();
  const choiceErrorId = `${ids}-choice-error`;
  const nameErrorId = `${ids}-name-error`;

  const suites = useQuery({ queryKey: ["suites", projectId], queryFn: () => listSuites(projectId), enabled: open });
  // Repository suites are read-only: only manual ones take cases
  const manual = (suites.data ?? []).filter((s) => s.origin !== "repository");

  const add = useMutation({
    mutationFn: async (): Promise<Result> => {
      let target = choice === NEW ? made.current : manual.find((s) => String(s.id) === choice) ?? null;
      if (!target) {
        const created = await createSuite(projectId, { name: name.trim() });
        target = made.current = { id: created.id, name: created.name };
      }
      const r = await appendSuiteCases(projectId, target.id, numbers);
      return { suiteId: target.id, name: target.name, added: r.added, already: r.already };
    },
    onSuccess: (r) => {
      made.current = null;
      setResult(r);
      qc.invalidateQueries({ queryKey: ["suites", projectId] });
      onDone();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409 && choice === NEW && !made.current) {
        setFieldError({ on: "name", text: "A suite with this name already exists." });
      }
    },
  });

  useEffect(() => {
    if (open && !result) choiceRef.current?.focus();
    else if (open && result) doneRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [open, result]);
  useEffect(() => {
    if (choice === NEW) nameRef.current?.focus();
  }, [choice]);

  function show() {
    setChoice("");
    setName("");
    setFieldError(null);
    setResult(null);
    made.current = null;
    add.reset();
    setOpen(true);
  }
  function close() {
    returnFocus.current = true;
    setOpen(false);
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    if (add.isPending) return;
    if (!choice) {
      setFieldError({ on: "choice", text: "Choose a suite or make a new one." });
      choiceRef.current?.focus();
      return;
    }
    if (choice === NEW && !made.current && !name.trim()) {
      setFieldError({ on: "name", text: "Enter a name for the suite." });
      nameRef.current?.focus();
      return;
    }
    setFieldError(null);
    add.mutate();
  }

  const title = `Add ${plural(numbers.length, "case", "cases")} to a suite`;
  const error = fieldError?.on === "choice" ? fieldError : null;
  const nameError = fieldError?.on === "name" ? fieldError : null;

  return (
    <div className="add-to-suite">
      <button ref={triggerRef} type="button" aria-expanded={open} onClick={() => (open ? close() : show())}>
        <ListPlus size={16} aria-hidden="true" /> Add to suite
      </button>
      {open && (
        <div className="card add-to-suite-card" role="dialog" aria-labelledby={`${ids}-title`}
          onKeyDown={(e) => { if (e.key === "Escape") close(); }}>
          <h3 id={`${ids}-title`}>{title}</h3>
          {result ? (
            <>
              <p role="status">
                {`Added ${plural(result.added, "case", "cases")} to ${result.name}`}
                {result.already > 0 && ` (${result.already} ${result.already === 1 ? "was" : "were"} already there)`}.
              </p>
              <div className="button-row">
                <Link className="button" to={`/projects/${projectId}/suites/${result.suiteId}`}>{`Open ${result.name}`}</Link>
                <button ref={doneRef} type="button" onClick={close}>Close</button>
              </div>
            </>
          ) : (
            <form className="form-stack" onSubmit={submit} noValidate>
              <label>
                Suite
                <select ref={choiceRef} value={choice} aria-invalid={error ? true : undefined}
                  aria-describedby={error ? choiceErrorId : undefined}
                  onChange={(e) => { setChoice(e.target.value); setFieldError(null); add.reset(); }}>
                  <option value="">Choose a suite</option>
                  {manual.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  <option value={NEW}>New suite…</option>
                </select>
              </label>
              {error && <p id={choiceErrorId} className="field-error" role="alert">{error.text}</p>}
              {suites.error != null && <ErrorBanner error={suites.error} onRetry={() => suites.refetch()} />}
              {choice === NEW && (
                <>
                  <label>
                    Name
                    <input ref={nameRef} maxLength={100} autoComplete="off" value={name} aria-invalid={nameError ? true : undefined}
                      aria-describedby={nameError ? nameErrorId : undefined}
                      onChange={(e) => { setName(e.target.value); setFieldError(null); }} placeholder="e.g. Smoke" />
                  </label>
                  {nameError && <p id={nameErrorId} className="field-error" role="alert">{nameError.text}</p>}
                </>
              )}
              {add.error != null && !nameError && <ErrorBanner error={add.error} />}
              <div className="button-row">
                <button type="submit" className="primary" disabled={add.isPending}>{add.isPending ? "Adding…" : "Add"}</button>
                <button type="button" onClick={close}>Cancel</button>
              </div>
            </form>
          )}
        </div>
      )}
    </div>
  );
}
