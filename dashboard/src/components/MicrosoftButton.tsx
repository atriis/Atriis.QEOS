/** "Sign in with Microsoft" as Microsoft's branding asks: the four-square mark beside that exact wording. The mark is
 *  decorative (the text names the action); `primary` is the SSO-only card, where this button is the main action. */
export default function MicrosoftButton({ onClick, busy, primary = false }: { onClick: () => void; busy: boolean; primary?: boolean }) {
  return (
    <button type="button" className={primary ? "sso-button primary" : "sso-button"} onClick={onClick} disabled={busy}>
      <svg className="sso-mark" viewBox="0 0 21 21" width="18" height="18" aria-hidden="true" focusable="false">
        <rect x="1" y="1" width="9" height="9" fill="#f25022" />
        <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
        <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
        <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
      </svg>
      {busy ? "Opening Microsoft…" : "Sign in with Microsoft"}
    </button>
  );
}
