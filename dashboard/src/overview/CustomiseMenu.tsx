import { type RefObject, useEffect, useRef, useState } from "react";
import { ChevronDown, LayoutGrid } from "lucide-react";
import type { LayoutMode } from "../api/overviewLayout";

interface Props {
  /** Owners and admins also get "Edit project default" (spec §2.3). */
  canManage: boolean;
  onPick: (mode: LayoutMode) => void;
  triggerRef: RefObject<HTMLButtonElement | null>;
}

/** Customise in the Overview header. For owners and admins it is a disclosure, as the account menu is: Escape closes
 *  it and returns focus to the button; a click or focus outside closes it. */
export default function CustomiseMenu({ canManage, onPick, triggerRef }: Props) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (e: Event) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("focusin", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("focusin", outside);
    };
  }, [open]);

  if (!canManage) {
    return (
      <button type="button" ref={triggerRef} onClick={() => onPick("personal")}>
        <LayoutGrid size={15} aria-hidden="true" /> Customise
      </button>
    );
  }
  const pick = (mode: LayoutMode) => {
    setOpen(false);
    onPick(mode);
  };
  return (
    <div
      className="customise-menu"
      ref={box}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          setOpen(false);
          triggerRef.current?.focus();
        }
      }}
    >
      <button type="button" ref={triggerRef} aria-expanded={open} aria-controls="customise-options" onClick={() => setOpen((o) => !o)}>
        <LayoutGrid size={15} aria-hidden="true" /> Customise <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <ul id="customise-options" className="customise-popup">
          <li><button type="button" className="menu-item" onClick={() => pick("personal")}>Customise your Overview</button></li>
          <li><button type="button" className="menu-item" onClick={() => pick("project")}>Edit project default</button></li>
        </ul>
      )}
    </div>
  );
}
