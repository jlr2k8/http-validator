from __future__ import annotations

import datetime
from typing import Any

RUNS_COL = "link_validation_runs"
CHECKS_COL = "link_validation_checks"


def _check_bson(run_id: Any, site_slug: str, r: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "site_slug": site_slug,
        "url": r.url,
        "source_page": r.source_page,
        "ok": r.ok,
        "status_code": r.status_code,
        "latency_ms": r.latency_ms,
        "error": r.error,
        "note": r.note,
    }


def _ensure_indexes(db: Any) -> None:
    runs = db[RUNS_COL]
    checks = db[CHECKS_COL]
    runs.create_index([("site_slug", 1), ("finished_at", -1)])
    runs.create_index([("site_slug", 1), ("run_label", 1)])
    checks.create_index([("run_id", 1)])
    checks.create_index([("site_slug", 1), ("ok", 1)])
    checks.create_index([("site_slug", 1), ("finished_at", -1)])
    checks.create_index([("site_slug", 1), ("url", 1)])


def save_validation_run(
    mongo_uri: str,
    db_name: str,
    *,
    start_url: str,
    site_slug: str,
    run_label: str,
    started_at: datetime.datetime,
    finished_at: datetime.datetime,
    options: dict[str, Any],
    results: list[Any],
    good_count: int,
    bad_count: int,
) -> Any:
    try:
        from pymongo import MongoClient
    except ImportError as exc:
        raise RuntimeError(
            "MongoDB support requires pymongo. Install with: pip install -e ."
            " (or pip install pymongo)"
        ) from exc

    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=datetime.timezone.utc)
    if finished_at.tzinfo is None:
        finished_at = finished_at.replace(tzinfo=datetime.timezone.utc)

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10_000)
    try:
        db = client[db_name]
        _ensure_indexes(db)

        run_doc: dict[str, Any] = {
            "start_url": start_url,
            "site_slug": site_slug,
            "run_label": run_label,
            "started_at": started_at,
            "finished_at": finished_at,
            "options": options,
            "summary": {
                "total": len(results),
                "ok": good_count,
                "bad": bad_count,
            },
        }
        ins = db[RUNS_COL].insert_one(run_doc)
        run_id = ins.inserted_id

        if results:
            rows = [_check_bson(run_id, site_slug, r) for r in results]
            for row in rows:
                row["finished_at"] = finished_at
            db[CHECKS_COL].insert_many(rows, ordered=False)

        return run_id
    finally:
        client.close()
