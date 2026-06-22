import { Link, Route, Routes } from "react-router-dom";
import RunDetailPage from "./pages/RunDetailPage";
import SearchPage from "./pages/SearchPage";
import SiteListPage from "./pages/SiteListPage";
import SiteRunsPage from "./pages/SiteRunsPage";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <h1>
            <Link to="/">http-validator</Link>
          </h1>
          <p>Browse validation runs and search indexed checks.</p>
        </div>
        <nav className="app-nav">
          <Link to="/">Sites</Link>
          <Link to="/search">Search</Link>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<SiteListPage />} />
        <Route path="/sites/:siteSlug" element={<SiteRunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
      </Routes>
    </div>
  );
}