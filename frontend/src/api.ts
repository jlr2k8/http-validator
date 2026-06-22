export type RunSummary = {
  total: number;
  ok: number;
  bad: number;
};

export type Run = {
  _id: string;
  site_slug: string;
  run_label: string;
  start_url: string;
  started_at: string;
  finished_at: string;
  summary: RunSummary;
};

export type Check = {
  run_id?: string;
  site_slug?: string;
  run_label?: string;
  url: string;
  source_page: string;
  ok: boolean;
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  note: string;
  finished_at?: string;
};

export type PageGroup = {
  source_page: string;
  checks: Check[];
};

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function getSites() {
  return fetchJson<{ sites: string[] }>("/api/sites");
}

export function getSiteRuns(siteSlug: string, limit = 20) {
  return fetchJson<{ site_slug: string; runs: Run[] }>(
    `/api/sites/${encodeURIComponent(siteSlug)}/runs?limit=${limit}`,
  );
}

export function getRunChecks(
  runId: string,
  filters?: { ok?: boolean; note?: string },
) {
  const params = new URLSearchParams();
  if (filters?.ok !== undefined) params.set("ok", String(filters.ok));
  if (filters?.note) params.set("note", filters.note);
  const query = params.toString();
  return fetchJson<{
    run_id: string;
    site_slug: string;
    run_label: string;
    summary: RunSummary;
    checks: Check[];
  }>(`/api/runs/${runId}/checks${query ? `?${query}` : ""}`);
}

export function getRunByPage(runId: string) {
  return fetchJson<{
    run_id: string;
    site_slug: string;
    run_label: string;
    finished_at: string;
    summary: RunSummary;
    pages: PageGroup[];
  }>(`/api/runs/${runId}/by-page`);
}

export function searchChecks(query: string, siteSlug?: string, ok?: boolean) {
  const params = new URLSearchParams({ q: query });
  if (siteSlug) params.set("site_slug", siteSlug);
  if (ok !== undefined) params.set("ok", String(ok));
  return fetchJson<{ query: string; site_slug?: string; results: Check[] }>(
    `/api/search/checks?${params.toString()}`,
  );
}

export function formatDate(value: string | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function formatLatency(value: number | null | undefined) {
  if (value == null) return "—";
  return `${value.toFixed(1)} ms`;
}