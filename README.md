# HTTP Link Validator

Simple Python project that:
- crawls same-host HTML pages in parallel from a start URL (recursive fan-out: each page's discovered links schedule new crawl tasks, bounded by `--workers` and `--max-pages`),
- extracts links (`href` / `src`),
- checks HTTP health for each unique link (also in parallel),
- writes per-run logs under `results/<hostname>/` (from the start URL, e.g. `results/www.example.com/`),
- separate good / bad files per run with timestamped names,
- **stores each run in MongoDB** (local Docker by default; see below).

- **HTML:** `a href`, `area href`, `form action` (and `button` / `input formaction`), `link href`, `img` / `iframe` / `frame` / `script` / `embed` / `object data` / `video|audio|source`, `img longdesc`.
- **`<base href>`** is respected when resolving relative URLs.
- **Redirects:** final URL after redirects is used when extracting links.
- **Sitemaps (default on):** reads `robots.txt` / `sitemap.xml` (and variants) and **adds any `<loc>` not already seen during the crawl** to the HTTP-check list. The crawl itself **starts only from your URL** (e.g. homepage) and fans out by following links on each page - sitemap does not jump the queue. Sitemap-only rows are logged with `found_on=<your start URL>`. Apex and `www` match for sitemap inclusion.
- **Not possible without a real browser:** links created only by JavaScript after load (e.g. many SPA client-only routes) are not seen unless they appear in the raw HTML, JSON in page, or sitemap.
- **Bot / WAF walls (Cloudflare, etc.):** if the server returns a challenge page (often HTTP 403 + "Just a moment..."), stdlib HTTP cannot pass the check - crawl and sitemap fetch will be empty. The start URL is still checked so `*-bad.txt` can record the failure. Use a normal browser session/network, or feed URLs from a sitemap you can open locally / fetch without the wall.

Use `--no-sitemap` to skip loading the sitemap (checks are only URLs discovered by the homepage-first crawl).

## Project Structure

- `src/http_validator/cli.py` main implementation
- `src/http_validator/mongo_store.py` MongoDB inserts
- `src/http_validator/es_store.py` Elasticsearch indexing after each run
- `src/http_validator/mongo_queries.py` shared Mongo read helpers
- `src/http_validator/api/` FastAPI read API for the dashboard
- `frontend/` React dashboard (Vite)
- `link_validator.py` convenience entrypoint for local runs
- `query_validator_data.py` print Mongo history for a site (`--json`, `--json-by-page`)
- `toggle_venv.sh` source to activate/deactivate `.venv`
- `docker-compose.yml` / `Makefile` local MongoDB + Elasticsearch (`make`)
- `pyproject.toml` package metadata and dependencies

## Install

On **Debian / Ubuntu / WSL**, the system Python is often [PEP 668](https://peps.python.org/pep-0668/) “externally managed”: `pip install` without a venv fails with `externally-managed-environment`. Use a **virtual environment** (recommended):

```bash
# One-time: ensure venv module exists
sudo apt update && sudo apt install -y python3-venv

cd ~/http-validator   # or your clone path
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Use that environment whenever you work on the project:

```bash
cd ~/http-validator && source .venv/bin/activate
python3 link_validator.py https://example.com
# or: http-validator https://example.com
```

`pip install -e .` pulls in `pymongo`. For Elasticsearch indexing and the read API, also install the web extra:

```bash
pip install -e ".[web]"
```

Re-run install inside the venv after `pyproject.toml` changes.

**Avoid** `pip install --break-system-packages` on the system interpreter unless you know you need it.

## MongoDB (default)

Each successful crawl **also** writes to Mongo unless you pass `--no-mongo`.

1. Start Mongo locally (from repo root, data persists in a Docker volume):

   ```bash
   docker-compose up -d
   ```

2. Run the validator as usual — no extra flags. It uses `mongodb://127.0.0.1:27017` unless `MONGODB_URI` is set (or you pass `--mongo-uri`).

   ```bash
   python3 link_validator.py https://example.com
   ```

3. **Stop** Mongo without deleting data: `docker-compose down`. Do not use `docker compose down -v` locally unless you intend to wipe the volume.

**Collections** (database name `http_validator`, or `MONGODB_DB` / `--mongo-db`):

| Collection | Contents |
|------------|----------|
| `link_validation_runs` | One document per run (`site_slug`, `run_label`, `summary`, `started_at`, `finished_at`, `options`, …). |
| `link_validation_checks` | One document per checked URL (`run_id`, `url`, `ok`, `note`, `status_code`, `latency_ms`, …). |

**Example** (`mongosh`):

```javascript
use http_validator
db.link_validation_runs.find({ site_slug: "www.example.com" }).sort({ finished_at: -1 }).limit(3)
var r = db.link_validation_runs.find().sort({ finished_at: -1 }).limit(1).next()
db.link_validation_checks.find({ run_id: r._id, ok: false })
```

If Mongo is not reachable, the run still finishes and text logs are written; you will see `MongoDB write failed: …` on stderr.

## Elasticsearch (default after Mongo write)

After a successful Mongo write, each run is also indexed in Elasticsearch unless you pass `--no-es`.

1. Start local infra (Mongo + Elasticsearch):

   ```bash
   docker-compose up -d
   ```

2. Activate the project venv, then install the web extra (required on Debian/Ubuntu/WSL — system `pip` is blocked):

   ```bash
   source .venv/bin/activate   # or: source ./toggle_venv.sh
   pip install -e ".[web]"
   ```

3. Run the validator as usual. It uses `http://127.0.0.1:9200` unless `ELASTICSEARCH_URL` is set (or you pass `--es-url`).

   ```bash
   python3 link_validator.py https://example.com
   ```

**Indices:**

| Index | Contents |
|-------|----------|
| `validation-runs` | One document per run (summary + metadata). |
| `validation-checks` | One document per checked URL (denormalized run fields for search). |

If Elasticsearch is not reachable, the run still finishes; you will see `Elasticsearch indexing failed: …` on stderr.

## Dashboard (React + read API)

### Local dev

Uses **Vite** for the UI (hot reload on :5173, proxies `/api` to FastAPI on :8000).

```bash
docker-compose up -d                    # Mongo + Elasticsearch
source .venv/bin/activate && pip install -e ".[web]"
./scripts/dev.sh                        # Vite :5173 + API :8000
python3 link_validator.py https://example.com
```

**API endpoints:**

- `GET /api/health` — Mongo + Elasticsearch connectivity
- `GET /api/sites` — distinct crawled sites
- `GET /api/sites/{site_slug}/runs` — run history
- `GET /api/runs/{run_id}/checks` — checks for one run
- `GET /api/runs/{run_id}/by-page` — checks grouped by source page
- `GET /api/search/checks?q=...` — full-text search (Elasticsearch)

## Run

Installed command:

```bash
http-validator https://example.com
```

Or run directly from repo root:

```bash
python3 link_validator.py https://example.com
```

After each run, results are written under a host-named subfolder, for example:
- `results/www.example.com/2026-03-26-12-44pm-PDT-good.txt`
- `results/www.example.com/2026-03-26-12-44pm-PDT-bad.txt`

Non-default ports use `hostname-port` (e.g. `localhost-8080`).

**Custom log paths:** `--good-output` and `--bad-output` take a file path **exactly as you pass it** (relative paths are relative to the **current working directory**). `--results-dir` is **not** prepended to those paths. If you set only one of them, the other file still uses the usual layout: `<results-dir>/<hostname>/<run-label>-good.txt` or `-bad.txt` (same timestamp/label on both when omitted).

Example — bad links in a fixed file, good links still under `results/`:

```bash
python3 link_validator.py https://example.com --bad-output ./artifacts/bad-links.txt
```

Exit code behavior:
- `0` if all checked links are healthy
- `1` if any bad/slow link is found
- `2` for invalid input

## Options

- `--max-pages 2000` max same-host HTML pages to crawl (`0` = no limit until the frontier is empty)
- `--workers 16` thread count for crawling and link checks
- `--timeout 8` request timeout in seconds
- `--latency-threshold 2` mark link as slow if response exceeds seconds
- `--include-external` validate off-domain links too
- `--insecure` disable TLS cert validation (testing only)
- `--user-agent "http-validator/0.1"` custom User-Agent
- `--results-dir results` base directory; default logs go in `results/<hostname>/`
- `--run-label <label>` custom file prefix instead of generated timestamp
- `--good-output <path>` write healthy links to this file (path as-is; not combined with `--results-dir`)
- `--bad-output <path>` write bad/slow/error links to this file (path as-is; not combined with `--results-dir`)
- `--no-mongo` do not write this run to MongoDB
- `--mongo-uri <uri>` MongoDB URI (overrides `MONGODB_URI`; default URI is `mongodb://127.0.0.1:27017` when unset)
- `--mongo-db <name>` database name (default `http_validator` or `MONGODB_DB`)
- `--no-es` do not index this run in Elasticsearch
- `--es-url <url>` Elasticsearch URL (overrides `ELASTICSEARCH_URL`; default `http://127.0.0.1:9200`)

## Example

```bash
python3 link_validator.py https://my-site.com --max-pages 50 --include-external
```
