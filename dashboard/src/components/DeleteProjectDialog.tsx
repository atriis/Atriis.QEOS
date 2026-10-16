import { FormEvent, useEffect, useId, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { Project, deleteProject } from "../api/orgs";
import ErrorBanner from "./ErrorBanner";

const GRACE_DAYS = 7; // PROJECT_DELETE_GRACE_DAYS

/** Settings → Data's danger zone (spec 2026-10-16). Destructive Confirmation in place (DESIGN.md: no modal): the
 *  trigger swaps for a group that says what is deleted and when, points at the export, and needs the project name
 *  typed exactly before the danger button works. Cancel and Escape back out and return focus to the trigger. */
export default function DeleteProjectDialog({ project, onDeleted }: { project: Project; onDeleted: () => void }) {
  const [asking, setAsking] = useState(false);
  const [typed, setTyped] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const fieldRef = useRef<HTMLInputElement>(null);
  const returnFocus = useRef(false);
  const titleId = useId();
  const fieldId = useId();
  const remove = useMutation({ mutationFn: () => deleteProject(project.id), onSuccess: onDeleted });
  const held = project.legal_hold != null;
  const matches = typed.trim() === project.name;

  useEffect(() => {
    if (asking) fieldRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [asking]);

  function open() {
    setTyped("");
    remove.reset();
    setAsking(true);
  }
  function cancel() {
    returnFocus.current = true;
    setAsking(false);
  }
  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (matches && !remove.isPending) remove.mutate();
  }

  return (
    <div className="danger-zone">
      <h3>Delete this project</h3>
      {!asking ? (
        <>
          <p className="muted">
            The project is hidden at once and deleted permanently {GRACE_DAYS} days later, everywhere. Until then any
            owner or admin can restore it from the project list.
          </p>
          <button ref={triggerRef} type="button" onClick={open} disabled={held}>
            <Trash2 size={15} aria-hidden="true" /> Delete project
          </button>
          {held && <p className="muted">Release the legal hold before deleting this project.</p>}
        </>
      ) : (
        <form
          className="delete-confirm"
          role="group"
          aria-labelledby={titleId}
          onSubmit={onSubmit}
          onKeyDown={(e) => {
            if (e.key === "Escape") cancel();
          }}
        >
          <p id={titleId} className="delete-confirm-title">Delete {project.name}?</p>
          <p>
            Its runs, results, logs, test cases, suites, API keys and settings are deleted permanently in {GRACE_DAYS} days.
            Until then any owner or admin can restore it.
          </p>
          <p className="muted">Want a copy? Use <strong>Download all results</strong> above first.</p>
          <label htmlFor={fieldId}>Type the project name to confirm</label>
          <input
            id={fieldId}
            ref={fieldRef}
            autoComplete="off"
            spellCheck={false}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
          {remove.error != null && <ErrorBanner error={remove.error} />}
          <div className="button-row">
            <button type="submit" className="danger" disabled={!matches || remove.isPending}>
              {remove.isPending ? "Deleting…" : `Delete permanently in ${GRACE_DAYS} days`}
            </button>
            <button type="button" onClick={cancel}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
