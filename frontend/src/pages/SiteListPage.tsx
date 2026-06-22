import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getSites } from "../api";

export default function SiteListPage() {
  const [sites, setSites] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getSites()
      .then((payload) => setSites(payload.sites))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <section className="panel">
        <h2>Sites</h2>
        {loading && <p className="muted">Loading sites…</p>}
        {error && <div className="error-box">{error}</div>}
        {!loading && !error && sites.length === 0 && (
          <p className="empty-state">
            No runs yet. Run the crawler with Mongo enabled, then refresh this page.
          </p>
        )}
        {!loading && !error && sites.length > 0 && (
          <div className="site-grid">
            {sites.map((site) => (
              <Link key={site} to={`/sites/${encodeURIComponent(site)}`} className="site-card">
                <strong>{site}</strong>
                <div className="muted">View run history</div>
              </Link>
            ))}
          </div>
        )}
      </section>
    </>
  );
}