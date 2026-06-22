from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from http_validator import es_store, mongo_queries
from http_validator.cli import DEFAULT_MONGO_URI

DEFAULT_ES_URL = es_store.DEFAULT_ES_URL


def _mongo_uri() -> str:
    return os.environ.get("MONGODB_URI", DEFAULT_MONGO_URI)


def _mongo_db() -> str:
    return os.environ.get("MONGODB_DB", "http_validator")


def _es_url() -> str | None:
    value = os.environ.get("ELASTICSEARCH_URL", DEFAULT_ES_URL)
    if value.lower() in ("", "none", "off", "false", "0"):
        return None
    return value


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


class HealthResponse(BaseModel):
    mongo: bool
    elasticsearch: bool


def create_app() -> FastAPI:
    app = FastAPI(title="http-validator API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        mongo_ok = False
        es_ok = False
        try:
            client, _db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
            client.close()
            mongo_ok = True
        except Exception:
            mongo_ok = False

        es_url = _es_url()
        if es_url:
            try:
                from elasticsearch import Elasticsearch

                es_client = Elasticsearch(es_url, request_timeout=5)
                es_ok = bool(es_client.ping())
            except Exception:
                es_ok = False

        return HealthResponse(mongo=mongo_ok, elasticsearch=es_ok)

    @app.get("/api/sites")
    def list_sites() -> dict[str, Any]:
        client, db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
        try:
            return {"sites": mongo_queries.list_sites(db)}
        finally:
            client.close()

    @app.get("/api/sites/{site_slug}/runs")
    def list_site_runs(
        site_slug: str,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict[str, Any]:
        client, db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
        try:
            runs = mongo_queries.list_runs(db, site_slug, limit=limit)
            return {"site_slug": site_slug, "runs": _serialize(runs)}
        finally:
            client.close()

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        try:
            ObjectId(run_id)
        except InvalidId as exc:
            raise HTTPException(status_code=400, detail="Invalid run_id") from exc

        client, db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
        try:
            run = mongo_queries.get_run(db, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            return {"run": _serialize(run)}
        finally:
            client.close()

    @app.get("/api/runs/{run_id}/checks")
    def get_run_checks(
        run_id: str,
        ok: bool | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        try:
            ObjectId(run_id)
        except InvalidId as exc:
            raise HTTPException(status_code=400, detail="Invalid run_id") from exc

        client, db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
        try:
            run = mongo_queries.get_run(db, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            checks = mongo_queries.list_checks(db, run_id, ok=ok, note=note)
            return {
                "run_id": run_id,
                "site_slug": run.get("site_slug"),
                "run_label": run.get("run_label"),
                "summary": run.get("summary"),
                "checks": _serialize(checks),
            }
        finally:
            client.close()

    @app.get("/api/runs/{run_id}/by-page")
    def get_run_by_page(run_id: str) -> dict[str, Any]:
        try:
            ObjectId(run_id)
        except InvalidId as exc:
            raise HTTPException(status_code=400, detail="Invalid run_id") from exc

        client, db = mongo_queries.get_db(_mongo_uri(), _mongo_db())
        try:
            run = mongo_queries.get_run(db, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail="Run not found")
            checks = mongo_queries.list_checks(db, run_id)
            pages = mongo_queries.checks_grouped_by_source_page(checks)
            return {
                "run_id": run_id,
                "site_slug": run.get("site_slug"),
                "run_label": run.get("run_label"),
                "finished_at": _serialize(run.get("finished_at")),
                "summary": run.get("summary"),
                "pages": _serialize(pages),
            }
        finally:
            client.close()

    @app.get("/api/search/checks")
    def search_checks(
        q: str = Query(min_length=1),
        site_slug: str | None = None,
        ok: bool | None = None,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        es_url = _es_url()
        if not es_url:
            raise HTTPException(status_code=503, detail="Elasticsearch is not configured")

        try:
            hits = es_store.search_checks(
                es_url,
                query=q,
                site_slug=site_slug,
                ok=ok,
                limit=limit,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        return {"query": q, "site_slug": site_slug, "results": hits}

    static_root = os.environ.get("STATIC_ROOT")
    if static_root:
        static_dir = Path(static_root)
    else:
        static_dir = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("API_PORT", "8080")))
    uvicorn.run("http_validator.api.main:app", host=host, port=port, reload=False)