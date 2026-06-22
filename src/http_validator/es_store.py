from __future__ import annotations

import datetime
from typing import Any

RUNS_INDEX = "validation-runs"
CHECKS_INDEX = "validation-checks"
DEFAULT_ES_URL = "http://127.0.0.1:9200"


def _iso_dt(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.isoformat()


def _normalize_search_query(query: str) -> str:
    q = query.strip()
    lower = q.lower()
    for prefix in ("https://", "http://"):
        if lower.startswith(prefix):
            q = q[len(prefix) :]
            break
    return q.strip("/")


def _wildcard_literal(value: str) -> str:
    escaped = ""
    for ch in value:
        if ch in ("\\", "*", "?"):
            escaped += "\\" + ch
        else:
            escaped += ch
    return escaped


def _ensure_indices(client: Any) -> None:
    if not client.indices.exists(index=RUNS_INDEX):
        client.indices.create(
            index=RUNS_INDEX,
            mappings={
                "properties": {
                    "run_id": {"type": "keyword"},
                    "site_slug": {"type": "keyword"},
                    "run_label": {"type": "keyword"},
                    "start_url": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "started_at": {"type": "date"},
                    "finished_at": {"type": "date"},
                    "summary": {
                        "properties": {
                            "total": {"type": "integer"},
                            "ok": {"type": "integer"},
                            "bad": {"type": "integer"},
                        }
                    },
                }
            },
        )

    if not client.indices.exists(index=CHECKS_INDEX):
        client.indices.create(
            index=CHECKS_INDEX,
            mappings={
                "properties": {
                    "run_id": {"type": "keyword"},
                    "site_slug": {"type": "keyword"},
                    "run_label": {"type": "keyword"},
                    "start_url": {"type": "keyword"},
                    "url": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "source_page": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "ok": {"type": "boolean"},
                    "status_code": {"type": "integer"},
                    "latency_ms": {"type": "float"},
                    "error": {"type": "text"},
                    "note": {"type": "keyword"},
                    "finished_at": {"type": "date"},
                }
            },
        )


def index_validation_run(
    es_url: str,
    *,
    run_id: Any,
    start_url: str,
    site_slug: str,
    run_label: str,
    started_at: datetime.datetime,
    finished_at: datetime.datetime,
    options: dict[str, Any],
    results: list[Any],
    good_count: int,
    bad_count: int,
) -> None:
    try:
        from elasticsearch import Elasticsearch, helpers
    except ImportError as exc:
        raise RuntimeError(
            "Elasticsearch support requires the elasticsearch package. "
            "Install with: pip install -e '.[web]'"
        ) from exc

    client = Elasticsearch(es_url, request_timeout=30)
    if not client.ping():
        raise RuntimeError(f"Elasticsearch is not reachable at {es_url}")

    _ensure_indices(client)
    run_id_str = str(run_id)

    client.index(
        index=RUNS_INDEX,
        id=run_id_str,
        document={
            "run_id": run_id_str,
            "start_url": start_url,
            "site_slug": site_slug,
            "run_label": run_label,
            "started_at": _iso_dt(started_at),
            "finished_at": _iso_dt(finished_at),
            "options": options,
            "summary": {
                "total": len(results),
                "ok": good_count,
                "bad": bad_count,
            },
        },
        refresh="wait_for",
    )

    if not results:
        return

    actions = []
    for r in results:
        actions.append(
            {
                "_index": CHECKS_INDEX,
                "_id": f"{run_id_str}:{r.url}",
                "_source": {
                    "run_id": run_id_str,
                    "site_slug": site_slug,
                    "run_label": run_label,
                    "start_url": start_url,
                    "url": r.url,
                    "source_page": r.source_page,
                    "ok": r.ok,
                    "status_code": r.status_code,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                    "note": r.note,
                    "finished_at": _iso_dt(finished_at),
                },
            }
        )

    helpers.bulk(client, actions, refresh="wait_for", raise_on_error=True)


def search_checks(
    es_url: str,
    *,
    query: str,
    site_slug: str | None = None,
    ok: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:
        raise RuntimeError(
            "Elasticsearch support requires the elasticsearch package. "
            "Install with: pip install -e '.[web]'"
        ) from exc

    client = Elasticsearch(es_url, request_timeout=15)
    if not client.ping():
        raise RuntimeError(f"Elasticsearch is not reachable at {es_url}")

    needle = _normalize_search_query(query)
    if not needle:
        return []

    pattern = f"*{_wildcard_literal(needle)}*"
    should: list[dict[str, Any]] = [
        {"wildcard": {"url.keyword": {"value": pattern, "case_insensitive": True}}},
        {"wildcard": {"source_page.keyword": {"value": pattern, "case_insensitive": True}}},
        {"wildcard": {"site_slug": {"value": pattern, "case_insensitive": True}}},
        {"wildcard": {"start_url": {"value": pattern, "case_insensitive": True}}},
        {"match_phrase": {"error": query.strip()}},
    ]
    must: list[dict[str, Any]] = [{"bool": {"should": should, "minimum_should_match": 1}}]
    filters: list[dict[str, Any]] = []
    if site_slug:
        filters.append({"term": {"site_slug": site_slug}})
    if ok is not None:
        filters.append({"term": {"ok": ok}})

    body: dict[str, Any] = {
        "size": max(1, min(limit, 200)),
        "query": {"bool": {"must": must, "filter": filters}},
        "sort": [{"finished_at": "desc"}, {"url.keyword": "asc"}],
    }

    response = client.search(
        index=CHECKS_INDEX,
        size=body["size"],
        query=body["query"],
        sort=body["sort"],
    )
    hits = response.get("hits", {}).get("hits", [])
    return [hit["_source"] for hit in hits]