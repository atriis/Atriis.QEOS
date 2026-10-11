import { useEffect, useRef, useState } from "react";

interface Props {
  /** Visible text of the trigger, e.g. "Revoke". */
  label: string;
  /** Accessible name of the trigger when the row needs naming, e.g. "Revoke key ci". */
  ariaLabel?: string;
  /** The consequence, in one sentence: what stops working. */
  question: string;
  confirmLabel: string;
  onConfirm: () => void;
  disabled?: boolean;
  /** The trigger's class, e.g. "primary" for a Save that confirms first. */
  triggerClassName?: string;
  /** "danger" (the default) for destructive actions; "primary" for a consequential save that destroys nothing. */
  confirmClassName?: string;
  /** The back-out button's text ("Cancel" by default). */
  cancelLabel?: string;
}

/** A destructive action that asks in place before acting. The confirm button
 *  takes focus; Cancel and Escape back out and return focus to the trigger. */
export default function ConfirmButton({
  label, ariaLabel, question, confirmLabel, onConfirm, disabled, triggerClassName, confirmClassName = "danger", cancelLabel = "Cancel",
}: Props) {
  const [asking, setAsking] = useState(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);

  useEffect(() => {
    if (asking) confirmRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [asking]);

  function cancel() {
    returnFocus.current = true;
    setAsking(false);
  }

  if (!asking) {
    return (
      <button type="button" ref={triggerRef} className={triggerClassName} aria-label={ariaLabel} onClick={() => setAsking(true)} disabled={disabled}>
        {label}
      </button>
    );
  }
  return (
    <span
      className="confirm"
      role="group"
      aria-label={question}
      onKeyDown={(e) => {
        if (e.key === "Escape") cancel();
      }}
    >
      <span>{question}</span>
      <button
        ref={confirmRef}
        type="button"
        className={confirmClassName}
        onClick={() => {
          returnFocus.current = true;
          setAsking(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </button>
      <button type="button" onClick={cancel}>{cancelLabel}</button>
    </span>
  );
}
