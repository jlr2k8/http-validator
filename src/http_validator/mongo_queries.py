from __future__ import annotations

import collections
from typing import Any

from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

from http_validator import mongo_store


def get_db(mongo_uri: str, db_name: str) -> tuple[MongoClient, Database]:
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    return client, client[db_name]


def list_sites(db: Database) -> list[str]:
    return sorted(db[mongo_store.RUNS_COL].distinct("site_slug"))


def list_runs(db: Database, site_slug: str, *, limit: int = 20) -> list[dict[str, Any]]:
    cursor = (
        db[mongo_store.RUNS_COL]
        .find({"site_slug": site_slug})
        .sort("finished_at", -1)
        .limit(max(1, limit))
    )
    return list(cursor)


def get_run(db: Database, run_id: str | ObjectId) -> dict[str, Any] | None:
    oid = ObjectId(run_id) if not isinstance(run_id, ObjectId) else run_id
    return db[mongo_store.RUNS_COL].find_one({"_id": oid})


def list_checks(
    db: Database,
    run_id: str | ObjectId,
    *,
    ok: bool | None = None,
    note: str | None = None,
) -> list[dict[str, Any]]:
    oid = ObjectId(run_id) if not isinstance(run_id, ObjectId) else run_id
    query: dict[str, Any] = {"run_id": oid}
    if ok is not None:
        query["ok"] = ok
    if note is not None:
        query["note"] = note
    return list(db[mongo_store.CHECKS_COL].find(query).sort("url", 1))


def checks_grouped_by_source_page(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_page: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in checks:
        page = row.get("source_page") or ""
        by_page[page].append(row)
    out: list[dict[str, Any]] = []
    for source_page in sorted(by_page.keys()):
        rows = sorted(by_page[source_page], key=lambda r: (r.get("url") or "", r.get("ok", False)))
        out.append({"source_page": source_page, "checks": rows})
    return out