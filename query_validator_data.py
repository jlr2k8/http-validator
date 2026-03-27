#!/usr/bin/env python3
"""Query http-validator MongoDB history for a site (same site_slug as the crawler uses)."""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import sys
from datetime import datetime
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bson import json_util  # type: ignore[import-untyped]
from pymongo import MongoClient

from http_validator.cli import normalize_absolute_url, site_results_subdir
from http_validator import mongo_store

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017"


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _checks_grouped_by_source_page(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_page: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in checks:
        page = row.get("source_page") or ""
        by_page[page].append(row)
    out: list[dict[str, Any]] = []
    for source_page in sorted(by_page.keys()):
        rows = sorted(by_page[source_page], key=lambda r: (r.get("url") or "", r.get("ok", False)))
        out.append({"source_page": source_page, "checks": rows})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List recent validation runs and latest failures for a start URL's site.",
    )
    parser.add_argument(
        "url",
        help="Site URL (e.g. https://www.example.com/) — used to resolve site_slug like the crawler.",
    )
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("MONGODB_URI") or DEFAULT_MONGO_URI,
        help=f"MongoDB URI (default: MONGODB_URI or {DEFAULT_MONGO_URI}).",
    )
    parser.add_argument(
        "--mongo-db",
        default=os.environ.get("MONGODB_DB", "http_validator"),
        help="Database name (default: http_validator or MONGODB_DB).",
    )
    parser.add_argument(
        "--recent",
        type=int,
        default=10,
        metavar="N",
        help="List up to N most recent runs in text mode (default: 10).",
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON document: recent runs + all checks for the latest run.",
    )
    fmt.add_argument(
        "--json-by-page",
        action="store_true",
        help="Print JSON for the latest run only: array of {source_page, checks} (one entry per HTML page).",
    )
    args = parser.parse_args(argv)

    start_url = normalize_absolute_url(args.url)
    if not start_url:
        print("Invalid URL. Provide an absolute http(s) URL.", file=sys.stderr)
        return 2

    site_slug = site_results_subdir(start_url)

    try:
        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
        client.admin.command("ping")
        db = client[args.mongo_db]
        runs_coll = db[mongo_store.RUNS_COL]
        checks_coll = db[mongo_store.CHECKS_COL]
    except Exception as exc:
        print(f"MongoDB connection failed: {exc}", file=sys.stderr)
        return 1

    try:
        runs = list(
            runs_coll.find({"site_slug": site_slug}).sort("finished_at", -1).limit(max(1, args.recent)),
        )

        if args.json:
            payload = {
                "site_slug": site_slug,
                "start_url_normalized": start_url,
                "runs": runs,
            }
            if runs:
                lid = runs[0]["_id"]
                payload["latest_run_checks"] = list(checks_coll.find({"run_id": lid}))
            print(json.dumps(payload, default=json_util.default, indent=2))
            return 0

        if args.json_by_page:
            if not runs:
                print(json.dumps({"site_slug": site_slug, "start_url_normalized": start_url, "pages": []}, indent=2))
                return 0
            latest = runs[0]
            rid = latest["_id"]
            checks = list(checks_coll.find({"run_id": rid}))
            pages = _checks_grouped_by_source_page(checks)
            payload = {
                "site_slug": site_slug,
                "start_url_normalized": start_url,
                "run_label": latest.get("run_label"),
                "run_id": str(rid),
                "finished_at": latest.get("finished_at"),
                "summary": latest.get("summary"),
                "pages": pages,
            }
            print(json.dumps(payload, default=json_util.default, indent=2))
            return 0

        if not runs:
            print(f"No runs found for site_slug={site_slug!r} (from {start_url}).")
            return 0

        print(f"site_slug={site_slug!r}  (from {start_url})\n")
        print(f"{'finished_at':<28} {'run_label':<28} {'ok':>5} {'bad':>5} {'total':>6}")
        print("-" * 80)
        for r in runs:
            fin = r.get("finished_at")
            lab = r.get("run_label", "")
            s = r.get("summary") or {}
            print(
                f"{_fmt_dt(fin):<28} {str(lab):<28} {int(s.get('ok', 0)):>5} {int(s.get('bad', 0)):>5} {int(s.get('total', 0)):>6}",
            )

        latest = runs[0]
        rid = latest["_id"]
        bad = list(checks_coll.find({"run_id": rid, "ok": False}).sort("url", 1))
        print()
        if bad:
            print(f"Latest run ({latest.get('run_label')!r}) — {len(bad)} failing / slow / error rows:\n")
            for row in bad:
                url = row.get("url", "")
                note = row.get("note", "")
                st = row.get("status_code")
                lat = row.get("latency_ms")
                err = row.get("error") or ""
                src = row.get("source_page", "")
                print(f"  {url}")
                print(f"    note={note} status={st} latency_ms={lat} error={err!r}")
                print(f"    found_on={src}\n")
        else:
            print(f"Latest run ({latest.get('run_label')!r}) — no failing rows.")

        print("\nJSON (latest run, grouped by page):  --json-by-page", file=sys.stderr)

        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
