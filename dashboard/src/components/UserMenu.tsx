import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Building2, LogOut, ShieldCheck } from "lucide-react";
import { logout, meQuery, startGrafanaSession } from "../api/auth";
import { ApiError } from "../api/http";
import { goTo } from "../lib/browser";
import { grafanaPath, markHandoff } from "../lib/grafanaHandoff";
import { clearRecent } from "../lib/recentItems";

/** "pedro.carneiro@x.com" -> "PC", "ana@x.com" -> "AN" */
export function initials(email: string): string {
  const local = email.split("@")[0] ?? "";
  const parts = local.split(/[._+-]+/).filter(Boolean);
  const letters = parts.length >= 2 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return letters.toUpperCase() || "?";
}

const POPUP_ID = "user-menu-popup";

interface Props {
  /** The organization to open from the menu (the current project's, else the first); none hides the item */
  orgId?: number;
}

/** The avatar in the top bar and what it discloses: who is signed in, Security, Organization, Monitoring (superusers, while it is
 *  on) and Sign out.
 *  A disclosure (button + plain list in Tab order), not an ARIA menu: the items are navigation links.
 *  Escape closes it and returns focus to the avatar; a click or focus outside, or following an item, closes it. */
export default function UserMenu({ orgId }: Props) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { pathname } = useLocation();
  const me = useQuery(meQuery);
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);

  const email = me.data?.email;
  const monitoringUrl = me.data?.monitoring_url ?? null;
  const [monitoringBusy, setMonitoringBusy] = useState(false);
  const [monitoringError, setMonitoringError] = useState<string | null>(null);

  useEffect(() => setOpen(false), [pathname]);
  // A refusal is about that click; reopening the menu starts clean
  useEffect(() => {
    if (!open) setMonitoringError(null);
  }, [open]);

  // A press or focus outside closes it, leaving focus where it went
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

  async function onSignOut() {
    setOpen(false);
    await logout();
    // The next account in this tab must not see this one's email, orgs or projects, nor its recent searches
    queryClient.clear();
    clearRecent();
    navigate("/login", { replace: true });
  }

  // Grafana is outside the SPA: hand over its cookie first, then leave (ADR-027). The hand-off is marked
  // so /monitoring asks instead of handing over again if Grafana sends the browser straight back
  // aria-disabled, not disabled, while it runs: a disabled button would drop focus to <body>
  async function onMonitoring() {
    if (monitoringBusy) return;
    setMonitoringError(null);
    setMonitoringBusy(true);
    try {
      const url = await startGrafanaSession();
      markHandoff();
      setOpen(false);
      goTo(grafanaPath(url));
    } catch (error) {
      setMonitoringError(error instanceof ApiError ? error.detail : "Monitoring could not be opened.");
    } finally {
      setMonitoringBusy(false);
    }
  }

  return (
    <div
      className="user-menu"
      ref={box}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          setOpen(false);
          button.current?.focus();
        }
      }}
    >
      <button
        ref={button}
        type="button"
        className="avatar-button"
        aria-label={email ? `Account menu for ${email}` : "Account menu"}
        aria-expanded={open}
        aria-controls={POPUP_ID}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">{email ? initials(email) : ""}</span>
      </button>
      {open && (
        <div className="user-menu-popup" id={POPUP_ID}>
          {email && <p className="user-menu-email">{email}</p>}
          <ul className="user-menu-list">
            <li>
              <Link to="/account/security" className="menu-item" onClick={() => setOpen(false)}>
                <ShieldCheck size={16} aria-hidden="true" /> Security
              </Link>
            </li>
            {orgId !== undefined && (
              <li>
                <Link to={`/organizations/${orgId}`} className="menu-item" onClick={() => setOpen(false)}>
                  <Building2 size={16} aria-hidden="true" /> Organization
                </Link>
              </li>
            )}
            {monitoringUrl && (
              <li>
                <button type="button" className="menu-item" onClick={onMonitoring} aria-disabled={monitoringBusy || undefined}>
                  <Activity size={16} aria-hidden="true" /> Monitoring
                </button>
                {monitoringError && (
                  <p className="field-error user-menu-error" role="alert">
                    {monitoringError}
                  </p>
                )}
              </li>
            )}
            <li className="menu-signout">
              <button type="button" className="menu-item" onClick={onSignOut}>
                <LogOut size={16} aria-hidden="true" /> Sign out
              </button>
            </li>
          </ul>
        </div>
      )}
    </div>
  );
}
