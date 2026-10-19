import { apiFetch, buildQuery } from "./http";

// Mirrors platforms/test-management-service/src/casebook/schemas/{case,suite}.py

export type Priority = "low" | "medium" | "high" | "critical";
export type CaseStatus = "draft" | "ready" | "archived";

export interface Step {
  action: string;
  expected: string;
}

export interface Case {
  number: number;
  /** TC-<number> */
  key: string;
  title: string;
  description: string | null;
  steps: Step[];
  labels: string[];
  priority: Priority;
  status: CaseStatus;
  /** The automated test (ingestion's test_key) this case is implemented by. */
  automated_test_key: string | null;
  automated_name: string | null;
  created_by: number;
  created_at: string;
  updated_by: number | null;
  updated_at: string | null;
  /** Repo-relative .feature path, for a case imported from Gherkin. */
  source_path: string | null;
  gherkin: string | null;
  /** The Gherkin Feature the case was imported from. */
  feature_name: string | null;
  /** Filled on the single-case read. */
  suites: { id: number; name: string }[];
}

export type CaseInput = Partial<
  Pick<Case, "title" | "description" | "steps" | "labels" | "priority" | "status" | "automated_test_key" | "automated_name">
>;

/** Where a search looks: scenario (title, Gherkin, TC key), feature (feature name or path), or both. */
export type SearchIn = "feature" | "scenario" | "both";
export const SEARCH_IN: SearchIn[] = ["feature", "scenario", "both"];

export interface CaseQuery {
  search?: string;
  search_in?: SearchIn;
  label?: string;
  status?: CaseStatus;
  priority?: Priority;
  include_archived?: boolean;
  origin?: "manual" | "imported";
  folder?: string;
  linked?: "true" | "false";
  feature?: string;
  /** "none": imported, active cases in no repository suite. */
  suite?: "none";
  /** Azure DevOps work item number: matches the label ado-<n>. */
  ado?: string;
  limit: number;
  offset: number;
}

/** Same filters as a JSON body, plus the test keys a latest-result filter resolved to. */
export interface CaseSearchBody extends Omit<CaseQuery, "label" | "linked"> {
  labels?: string[];
  linked?: boolean;
  test_keys: string[];
  keys_mode: "include" | "exclude";
}

const base = (projectId: number) => `/api/v1/projects/${projectId}`;

export function listCases(
  projectId: number,
  q: CaseQuery,
  init: { signal?: AbortSignal } = {},
): Promise<{ total: number; items: Case[] }> {
  const query = buildQuery({ ...q, include_archived: q.include_archived ? "true" : undefined });
  return apiFetch(`${base(projectId)}/cases${query}`, init);
}

/** The most test keys the dashboard sends in one search body; more fall back (or are not counted). */
export const MAX_SEARCH_KEYS = 20000;

export function searchCases(projectId: number, body: CaseSearchBody): Promise<{ total: number; items: Case[] }> {
  return apiFetch(`${base(projectId)}/cases/search`, { method: "POST", body: JSON.stringify(body) });
}

export function listFolders(projectId: number): Promise<{ path: string; count: number }[]> {
  return apiFetch(`${base(projectId)}/case-folders`);
}

export function listFeatures(projectId: number): Promise<{ feature: string; count: number }[]> {
  return apiFetch(`${base(projectId)}/case-features`);
}

/** One .feature file's cases (or every manual case: feature_name, path and folder null), from GET /features. */
export interface FeatureGroup {
  feature_name: string | null;
  path: string | null;
  /** The path's folder, "" for a file at the root. */
  folder: string | null;
  case_count: number;
  /** The first 200 matching cases, by number. */
  case_numbers: number[];
  /** Distinct automated test keys of the matching cases, sorted, at most 200; absent from older servers. */
  test_keys?: string[];
  /** True when the raw file is stored (imported since raw storage). */
  has_source: boolean;
  /** Aggregates over the matching cases; absent from servers that predate them. */
  linked_count?: number;
  top_priority?: Priority | null;
  status_counts?: Partial<Record<CaseStatus, number>>;
}

export interface FeatureQuery {
  search?: string;
  /** Always sent: the server's default (both) is not the dashboard's. */
  search_in: SearchIn;
  folder?: string;
  label?: string;
  status?: "draft" | "ready";
  priority?: Priority;
  linked?: "true" | "false";
  limit: number;
  offset: number;
}

/** Active cases grouped by .feature file: ordered by folder then name, manual group last. */
export function listFeatureGroups(projectId: number, q: FeatureQuery): Promise<{ total: number; items: FeatureGroup[] }> {
  return apiFetch(`${base(projectId)}/features${buildQuery({ ...q })}`);
}

export interface FeatureCase {
  number: number;
  key: string;
  title: string;
  scenario_name: string | null;
  status: CaseStatus;
  priority: Priority;
  automated_test_key: string | null;
  /** 1-based line of the scenario's heading in `content`, when found. */
  line: number | null;
}

export interface FeatureDetail {
  feature_name: string | null;
  path: string;
  folder: string | null;
  /** The raw file as last imported; null until the file is re-imported. */
  content: string | null;
  imported_at: string | null;
  /** In file order (by number when the file is not stored). */
  cases: FeatureCase[];
}

/** One .feature file: 404 when no active case has the path. */
export function getFeatureDetail(projectId: number, path: string): Promise<FeatureDetail> {
  return apiFetch(`${base(projectId)}/features/detail${buildQuery({ path })}`);
}

export function getCase(projectId: number, number: number): Promise<Case> {
  return apiFetch(`${base(projectId)}/cases/${number}`);
}

export function createCase(projectId: number, body: CaseInput): Promise<Case> {
  return apiFetch(`${base(projectId)}/cases`, { method: "POST", body: JSON.stringify(body) });
}

export function updateCase(projectId: number, number: number, changes: CaseInput): Promise<Case> {
  return apiFetch(`${base(projectId)}/cases/${number}`, { method: "PATCH", body: JSON.stringify(changes) });
}

export function listLabels(projectId: number): Promise<{ label: string; count: number }[]> {
  return apiFetch(`${base(projectId)}/case-labels`);
}

export interface Suite {
  id: number;
  name: string;
  description: string | null;
  case_count: number;
  created_at: string;
  updated_at: string | null;
  /** "repository" suites come from a workflow in the product repository and are read-only here. */
  origin?: "manual" | "repository";
  workflow?: string | null;
  group_name?: string | null;
  external_id?: string | null;
  /** "1/2" for the first of two halves of one folder. */
  shard?: string | null;
  test_paths?: string[] | null;
  source_repo?: string | null;
}

/** "1/2" as "Half 1 of 2". */
export function shardText(shard: string): string {
  const [n, of] = shard.split("/");
  return `Half ${n} of ${of}`;
}

export interface SuiteCase {
  number: number;
  key: string;
  title: string;
  status: CaseStatus;
  priority: Priority;
  labels: string[];
  automated_test_key: string | null;
  /** Null for a manual case: a suite run skips it. Absent when the server does not say. */
  source_path?: string | null;
}

export interface SuiteDetail extends Suite {
  cases: SuiteCase[];
}

/** `search` is a case-insensitive contains match on the name; the server refuses an empty one, so it is left out then. */
/** `createdBy: "me"`: only the caller's own suites (the Overview's My suites). */
export function listSuites(
  projectId: number, opts: { search?: string; createdBy?: "me" } = {}, init: { signal?: AbortSignal } = {},
): Promise<Suite[]> {
  const q = buildQuery({ search: opts.search || undefined, created_by: opts.createdBy });
  return apiFetch(`${base(projectId)}/suites${q}`, init);
}

export function getSuite(projectId: number, suiteId: number): Promise<SuiteDetail> {
  return apiFetch(`${base(projectId)}/suites/${suiteId}`);
}

export function createSuite(projectId: number, body: { name: string; description?: string }): Promise<Suite> {
  return apiFetch(`${base(projectId)}/suites`, { method: "POST", body: JSON.stringify(body) });
}

export function updateSuite(
  projectId: number,
  suiteId: number,
  changes: { name?: string; description?: string | null },
): Promise<Suite> {
  return apiFetch(`${base(projectId)}/suites/${suiteId}`, { method: "PATCH", body: JSON.stringify(changes) });
}

/** Replaces the suite's whole ordered list of cases. */
export function setSuiteCases(projectId: number, suiteId: number, numbers: number[]): Promise<SuiteDetail> {
  return apiFetch(`${base(projectId)}/suites/${suiteId}/cases`, { method: "PUT", body: JSON.stringify({ cases: numbers }) });
}

/** Adds cases to the end of a manual suite; the ones already in it are counted, not repeated. */
export function appendSuiteCases(
  projectId: number, suiteId: number, numbers: number[],
): Promise<{ added: number; already: number; suite: SuiteDetail }> {
  return apiFetch(`${base(projectId)}/suites/${suiteId}/cases/append`, { method: "POST", body: JSON.stringify({ cases: numbers }) });
}

export function deleteSuite(projectId: number, suiteId: number): Promise<void> {
  return apiFetch(`${base(projectId)}/suites/${suiteId}`, { method: "DELETE" });
}

export const PRIORITIES: Priority[] = ["low", "medium", "high", "critical"];
export const STATUSES: CaseStatus[] = ["draft", "ready", "archived"];

/** "checkout, Smoke" -> ["checkout", "smoke"]: what the label field accepts. */
export function parseLabels(text: string): string[] {
  return [...new Set(text.split(/[,\s]+/).map((l) => l.trim().toLowerCase()).filter(Boolean))].sort();
}

export type ImportAction = "create" | "update" | "unchanged" | "move" | "reactivate" | "archive" | "skip";
export interface ImportIssue { path: string; line: number | null; message: string }
export interface ImportItem { action: ImportAction; path: string; scenario: string | null; case_number: number | null }
export interface ImportResult {
  plan_hash: string;
  summary: Record<"created" | "updated" | "moved" | "reactivated" | "archived" | "unchanged" | "skipped", number> & { mass_archive?: boolean };
  items: ImportItem[];
  errors: ImportIssue[];
  warnings: ImportIssue[];
}
export interface ImportFile { path: string; content: string }

/** Plans (dryRun) or applies an import of Gherkin files; apply passes the previewed plan's hash. */
export function importCases(
  projectId: number,
  files: ImportFile[],
  opts: { dryRun: boolean; full?: boolean; expectedPlanHash?: string; allowMassArchive?: boolean },
): Promise<ImportResult> {
  const body = { files, full: opts.full ?? false, ...(opts.expectedPlanHash ? { expected_plan_hash: opts.expectedPlanHash } : {}),
    ...(opts.allowMassArchive ? { allow_mass_archive: true } : {}),
  };
  return apiFetch(`${base(projectId)}/cases/import?dry_run=${opts.dryRun}`, { method: "POST", body: JSON.stringify(body) });
}

/** GET /case-areas as the server sends it: short names keep 20,000 cases near 0.5 MB gzipped. */
interface CaseAreasWire {
  generated_at: string;
  counts: { cases: number; linked: number; manual: number };
  folders: string[];
  features: string[];
  labels: string[];
  suites: { id: number; name: string }[];
  cases: { n: number; t: string; k: string | null; fo: number | null; fe: number | null; l: number[]; s: number[] }[];
}

/** One active case, for the report's joins (the dashboard maps test keys to areas; ADR-026). */
export interface CaseArea {
  number: number;
  title: string;
  testKey: string | null;
  /** The directory part of its .feature path; null at the root and for a manual case */
  folder: string | null;
  feature: string | null;
  labels: string[];
  suiteIds: number[];
}

export interface CaseAreas {
  generatedAt: string;
  counts: { cases: number; linked: number; manual: number };
  folders: string[];
  features: string[];
  labels: string[];
  suites: { id: number; name: string }[];
  cases: CaseArea[];
}

/** Every active case in one response; a 409 `too_many_cases` above 50,000. The short names are mapped here, once. */
export async function getCaseAreas(projectId: number, init: { signal?: AbortSignal } = {}): Promise<CaseAreas> {
  const wire = await apiFetch<CaseAreasWire>(`${base(projectId)}/case-areas`, init);
  return {
    generatedAt: wire.generated_at,
    counts: wire.counts,
    folders: wire.folders,
    features: wire.features,
    labels: wire.labels,
    suites: wire.suites,
    cases: wire.cases.map((c) => ({
      number: c.n,
      title: c.t,
      testKey: c.k,
      folder: c.fo === null ? null : wire.folders[c.fo],
      feature: c.fe === null ? null : wire.features[c.fe],
      labels: c.l.map((i) => wire.labels[i]),
      suiteIds: c.s.map((i) => wire.suites[i].id),
    })),
  };
}
