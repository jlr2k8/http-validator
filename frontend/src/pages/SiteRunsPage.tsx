import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { formatDate, getSiteRuns, type Run } from "../api";

export default function SiteRunsPage() {
  const { siteSlug = "" } = useParams();
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!siteSlug) return;
    setLoading(true);
    getSiteRuns(siteSlug)
      .then((payload) => setRuns(payload.runs))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [siteSlug]);

  return (
    <>
      <div className="breadcrumb">
        <Link to="/">Sites</Link> / {siteSlug}
      </div>

      <section className="panel">
        <h2>Run history</h2>
        {loading && <p className="muted">Loading runs…</p>}
        {error && <div className="error-box">{error}</div>}
        {!loading && !error && runs.length === 0 && (
          <p className="empty-state">No runs found for this site.</p>
        )}
        {!loading && !error && runs.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Finished</th>
                <th>Label</th>
                <th>OK</th>
                <th>Bad</th>
                <th>Total</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run._id}>
                  <td>{formatDate(run.finished_at)}</td>
                  <td>{run.run_label}</td>
                  <td>{run.summary?.ok ?? 0}</td>
                  <td>{run.summary?.bad ?? 0}</td>
                  <td>{run.summary?.total ?? 0}</td>
                  <td>
                    <Link to={`/runs/${run._id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}