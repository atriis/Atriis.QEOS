import {
  ClipboardList, FileText, FlaskConical, GitBranch, LayoutDashboard, ListChecks, Settings, Shuffle, TrendingUp,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/** A project's views, in rail order: the rail lists them and the command palette offers them as pages. */
export const PROJECT_VIEWS: { to: string; label: string; icon: LucideIcon }[] = [
  { to: "overview", label: "Overview", icon: LayoutDashboard },
  { to: "runs", label: "Runs", icon: ListChecks },
  { to: "tests", label: "Test results", icon: FlaskConical },
  { to: "flaky", label: "Flaky", icon: Shuffle },
  { to: "branches", label: "Branches", icon: GitBranch },
  { to: "trends", label: "Trends", icon: TrendingUp },
  { to: "report", label: "Report", icon: FileText },
  { to: "cases", label: "Test cases", icon: ClipboardList },
  { to: "settings", label: "Settings", icon: Settings },
];
