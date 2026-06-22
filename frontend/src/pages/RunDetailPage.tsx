import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  formatDate,
  formatLatency,
  getRunByPage,
  getRunChecks,
  type Check,
  type PageGroup,
  type RunSummary,
} from "../api";

type ViewMode = "table" | "by-page";

export default function RunDetailPage() {
  const { runId = "" } = useParams();
  const [checks, setChecks] = useState<Check[]>([]);
  const [pages, setPages] = useState<PageGroup[]>([]);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [meta, setMeta] = useState<{ site_slug: string; run_label: string; finished_at?: string }>(
    { site_slug: "", run_label: "" },
  );
  const [filter, setFilter] = useState<"all" | "bad" | "ok">("all");
  const [view, setView] = useState<ViewMode>("table");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!runId) return;
    setLoading(true);
    setError(null);

    const okFilter =
      filter === "all" ? undefined : filter === "ok" ? true : false;

    Promise.all([
      getRunChecks(runId, { ok: okFilter }),
      getRunByPage(runId),
    ])
      .then(([checksPayload, pagePayload]) => {
        setChecks(checksPayload.checks);
        setSummary(checksPayload.summary);
        setPages(pagePayload.pages);
        setMeta({
          site_slug: pagePayload.site_slug,
          run_label: pagePayload.run_label,
          finished_at: pagePayload.finished_at,
        });
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [runId, filter]);

  const badCount = useMemo(() => summary?.bad ?? 0, [summary]);

  return (
    <>
      <div className="breadcrumb">
        <Link to="/">Sites</Link>
        {" / "}
        <Link to={`/sites/${encodeURIComponent(meta.site_slug)}`}>{meta.site_slug}</Link>
        {" / "}
        {meta.run_label || runId}
      </div>

      <section className="panel">
        <h2>Run detail</h2>
        {meta.finished_at && <p className="muted">Finished {formatDate(meta.finished_at)}</p>}

        {summary && (
          <div className="summary-grid">
            <div className="summary-card">
              <strong>{summary.total}</strong>
              <span className="muted">Total checks</span>
            </div>
            <div className="summary-card">
              <strong>{summary.ok}</strong>
              <span className="muted">Healthy</span>
            </div>
            <div className="summary-card">
              <strong>{badCount}</strong>
              <span className="muted">Issues</span>
            </div>
          </div>
        )}

        <div className="toolbar">
          <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
            <option value="all">All checks</option>
            <option value="bad">Issues only</option>
            <option value="ok">Healthy only</option>
          </select>
          <button
            type="button"
            className={view === "table" ? "" : "secondary"}
            onClick={() => setView("table")}
          >
            Table
          </button>
          <button
            type="button"
            className={view === "by-page" ? "" : "secondary"}
            onClick={() => setView("by-page")}
          >
            By page
          </button>
          <Link to={`/search?site=${encodeURIComponent(meta.site_slug)}`}>Search this site</Link>
        </div>

        {loading && <p className="muted">Loading checks…</p>}
        {error && <div className="error-box">{error}</div>}

        {!loading && !error && view === "table" && (
          <ChecksTable checks={checks} />
        )}

        {!loading && !error && view === "by-page" && (
          <div>
            {pages.map((group) => {
              const visible = group.checks.filter((check) => {
                if (filter === "all") return true;
                return filter === "ok" ? check.ok : !check.ok;
              });
              if (visible.length === 0) return null;
              return (
                <div key={group.source_page} className="page-group">
                  <h3>{group.source_page || "(unknown page)"}</h3>
                  <ChecksTable checks={visible} compact />
                </div>
              );
            })}
          </div>
        )}
      </section>
    </>
  );
}

function ChecksTable({ checks, compact = false }: { checks: Check[]; compact?: boolean }) {
  if (checks.length === 0) {
    return <p className="empty-state">No checks match this filter.</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>URL</th>
          {!compact && <th>Found on</th>}
          <th>Code</th>
          <th>Latency</th>
          <th>Note</th>
        </tr>
      </thead>
      <tbody>
        {checks.map((check) => (
          <tr key={`${check.url}:${check.source_page}:${check.note}`}>
            <td>
              <span className={`badge ${check.ok ? "ok" : "bad"}`}>
                {check.ok ? "OK" : "BAD"}
              </span>
            </td>
            <td>
              <a href={check.url} target="_blank" rel="noreferrer">
                {check.url}
              </a>
              {check.error && <div className="muted">{check.error}</div>}
            </td>
            {!compact && <td>{check.source_page}</td>}
            <td>{check.status_code ?? "—"}</td>
            <td>{formatLatency(check.latency_ms)}</td>
            <td>{check.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}