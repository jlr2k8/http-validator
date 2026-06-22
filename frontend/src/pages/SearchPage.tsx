import { type FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { formatDate, formatLatency, getSites, searchChecks, type Check } from "../api";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? "";
  const initialSite = searchParams.get("site") ?? "";

  const [query, setQuery] = useState(initialQuery);
  const [siteSlug, setSiteSlug] = useState(initialSite);
  const [sites, setSites] = useState<string[]>([]);
  const [results, setResults] = useState<Check[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [issuesOnly, setIssuesOnly] = useState(false);

  useEffect(() => {
    getSites()
      .then((payload) => setSites(payload.sites))
      .catch(() => setSites([]));
  }, []);

  useEffect(() => {
    if (!initialQuery.trim()) return;
    setQuery(initialQuery);
    setSiteSlug(initialSite);
    void runSearch(initialQuery, initialSite, issuesOnly);
  }, [initialQuery, initialSite]);

  async function runSearch(
    nextQuery: string,
    nextSite: string,
    nextIssuesOnly: boolean,
  ) {
    if (!nextQuery.trim()) return;
    setLoading(true);
    setError(null);
    setResults([]);
    try {
      const payload = await searchChecks(
        nextQuery.trim(),
        nextSite || undefined,
        nextIssuesOnly ? false : undefined,
      );
      setResults(payload.results);
    } catch (err) {
      setResults([]);
      setError(err instanceof Error ? err.message : "Search failed");
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    const params = new URLSearchParams();
    params.set("q", query.trim());
    if (siteSlug) params.set("site", siteSlug);
    setSearchParams(params);
    runSearch(query, siteSlug, issuesOnly);
  }

  return (
    <>
      <div className="breadcrumb">
        <Link to="/">Sites</Link> / Search
      </div>

      <section className="panel">
        <h2>Search checks</h2>
        <p className="muted">
          Search indexed URL checks across completed runs. Hostnames use the crawler slug
          (e.g. <code>www.reddit.com</code>, not <code>reddit.com</code>).
        </p>

        <form className="toolbar" onSubmit={onSubmit}>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search URLs, pages, errors…"
            style={{ minWidth: "280px", flex: 1 }}
          />
          <select value={siteSlug} onChange={(event) => setSiteSlug(event.target.value)}>
            <option value="">All sites</option>
            {sites.map((site) => (
              <option key={site} value={site}>
                {site}
              </option>
            ))}
          </select>
          <label className="muted">
            <input
              type="checkbox"
              checked={issuesOnly}
              onChange={(event) => setIssuesOnly(event.target.checked)}
            />{" "}
            Issues only
          </label>
          <button type="submit">Search</button>
        </form>

        {loading && <p className="muted">Searching…</p>}
        {error && <div className="error-box">{error}</div>}

        {!loading && !error && results.length === 0 && query.trim() && (
          <p className="empty-state">
            No matches for &ldquo;{query}&rdquo;
            {siteSlug ? ` on ${siteSlug}` : ""}. Try <code>www.</code> prefix or clear the site
            filter.
          </p>
        )}

        {!loading && !error && results.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>URL</th>
                <th>Site</th>
                <th>Run</th>
                <th>Found on</th>
                <th>Finished</th>
                <th>Code</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {results.map((check) => (
                <tr key={`${check.run_id}:${check.url}:${check.finished_at}`}>
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
                  <td>{check.site_slug ?? "—"}</td>
                  <td>
                    {check.run_id ? (
                      <Link to={`/runs/${check.run_id}`}>{check.run_label ?? check.run_id}</Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{check.source_page}</td>
                  <td>{formatDate(check.finished_at)}</td>
                  <td>{check.status_code ?? "—"}</td>
                  <td>{formatLatency(check.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}