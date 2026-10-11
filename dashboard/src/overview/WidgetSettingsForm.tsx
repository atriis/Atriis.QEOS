import { type FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { branchesViewQuery } from "../lib/healthQueries";
import { CATALOG, type SettingName, type StoredWidget, type WidgetSettings } from "./catalog";
import { definitionOf, widgetTitle, withDefaults } from "./widgets/registry";

const LABELS: Record<SettingName, string> = {
  rows: "Rows", period: "Period", granularity: "View", branch: "Branch", author: "Your name in git",
};
const VIEW_NAMES: Record<string, string> = { day: "Daily", week: "Weekly", month: "Monthly" };

interface Props {
  projectId: number;
  widget: StoredWidget;
  onApply: (settings: WidgetSettings) => void;
  onClose: () => void;
}

/** A widget's settings, inline in its card: only the values the catalogue allows. Escape closes it. */
export default function WidgetSettingsForm({ projectId, widget, onApply, onClose }: Props) {
  const def = definitionOf(widget.type);
  const [values, setValues] = useState<WidgetSettings>(() => (def ? withDefaults(def, widget.settings) : {}));
  const branches = useQuery({ ...branchesViewQuery(projectId), enabled: def?.settings.includes("branch") ?? false });
  if (def === undefined) return null;
  const title = widgetTitle(widget);
  const fieldId = (name: SettingName) => `ov-${widget.id}-${name}`;
  const set = (name: SettingName, value: string | number) => setValues((v) => ({ ...v, [name]: value }) as WidgetSettings);
  // All branches is no branch setting at all (an empty option, which no git branch can be named)
  const setBranch = (value: string) => setValues((v) => {
    const next = { ...v };
    if (value) next.branch = value;
    else delete next.branch;
    return next;
  });
  const branchNames = [...new Set((branches.data ?? []).flatMap((b) => (b.branch ? [b.branch] : [])))].sort();
  if (values.branch && !branchNames.includes(values.branch)) branchNames.unshift(values.branch);

  function submit(event: FormEvent) {
    event.preventDefault();
    const out: WidgetSettings = { ...values };
    const author = out.author?.trim();
    // Empty means "my QEOS full name", the widget's default
    if (author) out.author = author;
    else delete out.author;
    onApply(out);
  }

  return (
    <form
      className="widget-settings"
      aria-label={`${title} settings`}
      onSubmit={submit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
    >
      {def.settings.map((name) => {
        const spec = CATALOG.settings[name];
        if (name === "branch") {
          return (
            <div className="widget-setting" key={name}>
              <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
              <select id={fieldId(name)} value={values.branch ?? ""} onChange={(e) => setBranch(e.target.value)}>
                <option value="">All branches</option>
                {branchNames.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
          );
        }
        if (spec.kind === "text") {
          return (
            <div className="widget-setting" key={name}>
              <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
              <input
                id={fieldId(name)}
                value={values.author ?? ""}
                maxLength={spec.max_length}
                aria-describedby={`${fieldId(name)}-hint`}
                onChange={(e) => set(name, e.target.value)}
              />
              <span className="muted" id={`${fieldId(name)}-hint`}>As git records it. Empty: your QEOS full name.</span>
            </div>
          );
        }
        return (
          <div className="widget-setting" key={name}>
            <label htmlFor={fieldId(name)}>{LABELS[name]}</label>
            <select
              id={fieldId(name)}
              value={String(values[name] ?? "")}
              onChange={(e) => set(name, typeof spec.values[0] === "number" ? Number(e.target.value) : e.target.value)}
            >
              {spec.values.map((v) => (
                <option key={String(v)} value={String(v)}>
                  {name === "period" ? `${v} days` : name === "granularity" ? VIEW_NAMES[String(v)] : String(v)}
                </option>
              ))}
            </select>
          </div>
        );
      })}
      <div className="button-row">
        <button type="submit" className="primary">Apply</button>
        <button type="button" onClick={onClose}>Close</button>
      </div>
    </form>
  );
}
