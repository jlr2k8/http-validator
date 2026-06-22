from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime
import os
import pathlib
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, as_completed, wait
from html.parser import HTMLParser


DEFAULT_TIMEOUT = 8.0
DEFAULT_MAX_PAGES = 2000
DEFAULT_WORKERS = 16
DEFAULT_LATENCY_THRESHOLD = 2.0
SITEMAP_MAX_FETCHES = 100
DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017"
DEFAULT_ES_URL = "http://127.0.0.1:9200"


@dataclasses.dataclass
class CheckResult:
    url: str
    source_page: str
    ok: bool
    status_code: int | None
    latency_ms: float | None
    error: str | None
    note: str


class LinkExtractor(HTMLParser):
    """Collect navigation and resource URLs from HTML (href/src/action and related)."""

    def __init__(self, page_url: str) -> None:
        super().__init__()
        self._page_url = page_url
        self._resolve_base = page_url
        self._base_fixed = False
        self.links: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        raw = dict(attrs)
        attrs_dict = {str(k).lower(): (v if v is None else str(v)) for k, v in raw.items()}
        tag_l = tag.lower()

        if tag_l == "base" and not self._base_fixed and attrs_dict.get("href"):
            self._base_fixed = True
            href = attrs_dict["href"].strip()
            resolved = normalize_url(self._page_url, href)
            if resolved:
                self._resolve_base = resolved

        candidates: list[str] = []

        if tag_l == "a" and attrs_dict.get("href"):
            candidates.append(attrs_dict["href"])
        elif tag_l == "area" and attrs_dict.get("href"):
            candidates.append(attrs_dict["href"])
        elif tag_l == "form":
            if "action" not in attrs_dict or attrs_dict.get("action", "").strip() == "":
                candidates.append(self._page_url)
            else:
                candidates.append(attrs_dict["action"].strip())
        elif tag_l == "button" and attrs_dict.get("formaction"):
            candidates.append(attrs_dict["formaction"])
        elif tag_l == "input":
            t = attrs_dict.get("type", "text").lower()
            if attrs_dict.get("formaction") and t in ("submit", "image"):
                candidates.append(attrs_dict["formaction"])
        elif tag_l == "link" and attrs_dict.get("href"):
            candidates.append(attrs_dict["href"])
        elif tag_l in ("img", "script", "iframe", "frame", "embed", "source") and attrs_dict.get("src"):
            candidates.append(attrs_dict["src"])
        elif tag_l == "object" and attrs_dict.get("data"):
            candidates.append(attrs_dict["data"])
        elif tag_l in ("video", "audio") and attrs_dict.get("src"):
            candidates.append(attrs_dict["src"])
        elif tag_l == "img" and attrs_dict.get("longdesc"):
            candidates.append(attrs_dict["longdesc"])

        for c in candidates:
            if c and c.strip():
                self.links.add(c.strip())


def normalize_absolute_url(url: str) -> str | None:
    candidate = url.strip()
    if not candidate:
        return None
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    cleaned = parsed._replace(fragment="")
    return urllib.parse.urlunparse(cleaned)


def normalize_url(base_url: str, raw_link: str) -> str | None:
    candidate = raw_link.strip()
    if not candidate:
        return None
    lower = candidate.lower()
    if lower.startswith(("javascript:", "mailto:", "tel:", "data:")):
        return None

    abs_url = urllib.parse.urljoin(base_url, candidate)
    parsed = urllib.parse.urlparse(abs_url)
    if parsed.scheme not in ("http", "https"):
        return None
    cleaned = parsed._replace(fragment="")
    return urllib.parse.urlunparse(cleaned)


def same_site(url_a: str, url_b: str) -> bool:
    """
    True if URLs are on the same site for crawling / sitemap inclusion.
    Treats apex and www as the same (e.g. example.com vs www.example.com).
    """
    a = urllib.parse.urlparse(url_a).netloc.lower()
    b = urllib.parse.urlparse(url_b).netloc.lower()
    if a == b:
        return True

    def bare(host: str) -> str:
        return host[4:] if host.startswith("www.") else host

    return bare(a) == bare(b)


def probe_blocked_response(
    url: str,
    timeout: float,
    user_agent: str,
    ssl_context: ssl.SSLContext,
) -> tuple[int | None, str | None]:
    """
    One GET to explain why crawl/sitemap might be empty. Returns (status_or_none, stderr_hint_tag).
    hint_tag is cloudflare_or_bot_wall when the body looks like a Cloudflare challenge.
    """
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            return response.getcode(), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(8000)
        except Exception:
            body = b""
        low = body.lower()
        if exc.code == 403 and (
            b"cf-chl" in low or b"cloudflare" in low or b"just a moment" in low or b"__cf_chl" in low
        ):
            return exc.code, "cloudflare_or_bot_wall"
        return exc.code, None
    except Exception:
        return None, None


def fetch_html_page(
    url: str,
    timeout: float,
    user_agent: str,
    ssl_context: ssl.SSLContext,
) -> tuple[str | None, str]:
    """Download URL; return (html body or None, final URL after redirects)."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return None, final_url
            data = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace"), final_url
    except Exception:
        return None, url


def extract_links(page_url: str, html: str) -> set[str]:
    if not html:
        return set()
    parser = LinkExtractor(page_url)
    parser.feed(html)
    links: set[str] = set()
    for raw in parser.links:
        normalized = normalize_url(page_url, raw)
        if normalized:
            links.add(normalized)
    return links


def _xml_local_name(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def fetch_bytes(url: str, timeout: float, user_agent: str, ssl_context: ssl.SSLContext) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            return response.read()
    except Exception:
        return None


def parse_sitemap_document(data: bytes, start_url: str) -> tuple[set[str], list[str]]:
    """
    Parse a sitemap or sitemap index XML document.
    Returns (same-host page URLs for crawling, child sitemap URLs to fetch).
    """
    pages: set[str] = set()
    child_sitemaps: list[str] = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return pages, child_sitemaps

    root_name = _xml_local_name(root.tag)
    if root_name == "sitemapindex":
        for node in root:
            if _xml_local_name(node.tag) != "sitemap":
                continue
            for child in node:
                if _xml_local_name(child.tag) == "loc" and child.text and child.text.strip():
                    child_sitemaps.append(child.text.strip())
    elif root_name == "urlset":
        for node in root:
            if _xml_local_name(node.tag) != "url":
                continue
            for child in node:
                if _xml_local_name(child.tag) == "loc" and child.text and child.text.strip():
                    loc = child.text.strip()
                    normalized = normalize_absolute_url(loc) or normalize_url(start_url, loc)
                    if normalized and same_site(start_url, normalized):
                        pages.add(normalized)
    return pages, child_sitemaps


def discover_sitemap_seed_urls(
    start_url: str,
    timeout: float,
    user_agent: str,
    ssl_context: ssl.SSLContext,
) -> tuple[set[str], str | None]:
    """
    Collect URLs from robots.txt Sitemap directives and sitemap XML (incl. index).
    Returns (page URLs for this site, primary sitemap URL fetched - for logging / result attribution).
    """
    seeds: set[str] = set()
    parsed = urllib.parse.urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    sitemap_queue: collections.deque[str] = collections.deque()
    seen_sitemaps: set[str] = set()

    robots_txt = fetch_bytes(f"{origin}/robots.txt", timeout, user_agent, ssl_context)
    if robots_txt:
        try:
            text = robots_txt.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        for line in text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                _, _, rest = line.partition(":")
                loc = rest.strip()
                if loc and loc not in seen_sitemaps:
                    seen_sitemaps.add(loc)
                    sitemap_queue.append(loc)

    for path in ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"):
        guess = urllib.parse.urljoin(start_url, path)
        if guess not in seen_sitemaps:
            seen_sitemaps.add(guess)
            sitemap_queue.append(guess)

    primary_sitemap: str | None = None
    fetches = 0
    while sitemap_queue and fetches < SITEMAP_MAX_FETCHES:
        sm_url = sitemap_queue.popleft()
        fetches += 1
        body = fetch_bytes(sm_url, timeout, user_agent, ssl_context)
        if body is None:
            continue
        if primary_sitemap is None:
            primary_sitemap = sm_url
        pages, children = parse_sitemap_document(body, start_url)
        seeds |= pages
        for child in children:
            normalized_child = normalize_absolute_url(child) or normalize_url(start_url, child)
            if not normalized_child:
                continue
            if normalized_child not in seen_sitemaps:
                seen_sitemaps.add(normalized_child)
                sitemap_queue.append(normalized_child)

    return seeds, primary_sitemap


def crawl_site(
    start_url: str,
    max_pages: int,
    timeout: float,
    user_agent: str,
    ssl_context: ssl.SSLContext,
    num_workers: int,
) -> dict[str, set[str]]:
    """
    Recursive parallel crawl from the start URL only (usually the homepage). Each URL is a
    thread-pool task; when a page finishes, every same-site clickable link schedules a new task.

    max_pages == 0 means no page-count limit (crawl until no new same-site URLs qualify).
    """
    if num_workers < 1:
        num_workers = 1
    unlimited = max_pages == 0
    max_pages_eff = None if unlimited else max_pages

    page_to_links: dict[str, set[str]] = {}
    visited: set[str] = set()
    visit_lock = threading.Lock()

    def process_url(url: str) -> set[str]:
        """Fetch one URL; record HTML links; return same-host URLs to fan out to."""
        try:
            html, final_url = fetch_html_page(
                url,
                timeout=timeout,
                user_agent=user_agent,
                ssl_context=ssl_context,
            )
            if html is None:
                return set()
            links = extract_links(final_url, html)
        except Exception:
            return set()
        with visit_lock:
            page_to_links[final_url] = page_to_links.get(final_url, set()) | links
        return {u for u in links if same_site(start_url, u)}

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        pending: set[Future[set[str]]] = set()

        def try_schedule(u: str) -> None:
            with visit_lock:
                if u in visited:
                    return
                if max_pages_eff is not None and len(visited) >= max_pages_eff:
                    return
                visited.add(u)
            pending.add(executor.submit(process_url, u))

        try_schedule(start_url)

        while pending:
            done, not_done = wait(pending, return_when=FIRST_COMPLETED)
            pending = set(not_done)
            for fut in done:
                try:
                    child_urls = fut.result()
                except Exception:
                    child_urls = set()
                for link in child_urls:
                    try_schedule(link)

    return page_to_links


def check_link(
    url: str,
    source_page: str,
    timeout: float,
    user_agent: str,
    latency_threshold: float,
    ssl_context: ssl.SSLContext,
) -> CheckResult:
    def _request(method: str) -> tuple[int | None, str | None, float]:
        start = time.perf_counter()
        try:
            request = urllib.request.Request(url, headers={"User-Agent": user_agent}, method=method)
            with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
                elapsed_ms = (time.perf_counter() - start) * 1000
                return response.getcode(), None, elapsed_ms
        except urllib.error.HTTPError as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return exc.code, None, elapsed_ms
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return None, str(exc), elapsed_ms

    status_code, error, latency_ms = _request("HEAD")
    if status_code in (405, 501) and error is None:
        status_code, error, latency_ms = _request("GET")

    if error is not None:
        return CheckResult(url, source_page, False, None, latency_ms, error, "request_failed")
    if status_code is None:
        return CheckResult(url, source_page, False, None, latency_ms, "unknown error", "request_failed")
    if status_code >= 400:
        return CheckResult(url, source_page, False, status_code, latency_ms, None, "bad_status")
    if (latency_ms / 1000.0) > latency_threshold:
        return CheckResult(url, source_page, False, status_code, latency_ms, None, "slow_response")
    return CheckResult(url, source_page, True, status_code, latency_ms, None, "ok")


def iter_unique_links(page_to_links: dict[str, set[str]], start_url: str, include_external: bool) -> list[tuple[str, str]]:
    seen_links: set[str] = set()
    pairs: list[tuple[str, str]] = []
    for page, links in page_to_links.items():
        for link in links:
            if not include_external and not same_site(start_url, link):
                continue
            if link in seen_links:
                continue
            seen_links.add(link)
            pairs.append((link, page))
    return pairs


def build_check_pairs(
    page_to_links: dict[str, set[str]],
    start_url: str,
    sitemap_urls: set[str],
    include_external: bool,
) -> list[tuple[str, str]]:
    """
    URLs to HTTP-check: every unique link found while crawling (found_on = the page that linked it),
    plus any sitemap URL not reached by that crawl - those are still checked and attributed to the
    start URL so logs stay "site-wide" without implying the crawler saw a sitemap row as HTML.
    """
    pairs = iter_unique_links(page_to_links, start_url=start_url, include_external=include_external)
    seen: set[str] = {u for u, _ in pairs}
    for u in sorted(sitemap_urls):
        if not include_external and not same_site(start_url, u):
            continue
        if u in seen:
            continue
        seen.add(u)
        pairs.append((u, start_url))
    if start_url not in seen:
        pairs.append((start_url, "start"))
    return pairs


def _log_field(value: str) -> str:
    """Keep each dump line single-line (no embedded CR/LF/tab runs)."""
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def write_results(results: list[CheckResult], good_path: str, bad_path: str) -> tuple[int, int]:
    good_rows: list[CheckResult] = sorted((r for r in results if r.ok), key=lambda r: r.url)
    bad_rows: list[CheckResult] = sorted((r for r in results if not r.ok), key=lambda r: r.url)

    def write_one_record_per_line(path: str, rows: list[CheckResult], *, bad: bool) -> None:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                status = str(r.status_code) if r.status_code is not None else "-"
                latency = f"{r.latency_ms:.1f}ms" if r.latency_ms is not None else "-"
                url = _log_field(r.url)
                src = _log_field(r.source_page)
                if bad:
                    error = _log_field(r.error or "-")
                    line = (
                        f"{url}\tnote={_log_field(r.note)}\tstatus={status}\t"
                        f"latency={latency}\tfound_on={src}\terror={error}"
                    )
                else:
                    line = f"{url}\tstatus={status}\tlatency={latency}\tfound_on={src}"
                f.write(line)
                f.write("\n")

    write_one_record_per_line(good_path, good_rows, bad=False)
    write_one_record_per_line(bad_path, bad_rows, bad=True)

    return len(good_rows), len(bad_rows)


def default_run_label() -> str:
    now = datetime.datetime.now().astimezone()
    ampm = now.strftime("%p").lower()
    tz = now.strftime("%Z") or "local"
    # Example: 2026-03-26-12-44pm-PDT
    return f"{now.strftime('%Y-%m-%d-%I-%M')}{ampm}-{tz}"


def site_results_subdir(start_url: str) -> str:
    """
    Directory name under results/ for this run, derived from URL (hostname + non-default port).
    Safe on common filesystems (no / \\ : * ? etc.).
    """
    parsed = urllib.parse.urlparse(start_url)
    host = (parsed.hostname or "").lower()
    if not host:
        host = "unknown"
    port = parsed.port
    if port is not None:
        if parsed.scheme == "https" and port == 443:
            port = None
        elif parsed.scheme == "http" and port == 80:
            port = None
    label = host if port is None else f"{host}-{port}"
    cleaned: list[str] = []
    for ch in label:
        if ch.isalnum() or ch in ".-_":
            cleaned.append(ch)
        else:
            cleaned.append("_")
    name = "".join(cleaned).strip("._-") or "unknown"
    # Windows cannot end a path segment with space or dot
    name = name.rstrip(". ").rstrip()
    return (name or "unknown")[:200]


def resolve_output_paths(
    results_dir: str,
    site_slug: str,
    run_label: str | None,
    good_output: str | None,
    bad_output: str | None,
) -> tuple[str, str]:
    """
    Default logs go to results_dir / site_slug / <timestamp>-good.txt.
    If either --good-output or --bad-output is set, that path is used as-is (no extra subfolder).
    """
    label = run_label or default_run_label()
    results_path = pathlib.Path(results_dir)

    if good_output is None and bad_output is None:
        target_dir = results_path / site_slug
        target_dir.mkdir(parents=True, exist_ok=True)
        good_path = target_dir / f"{label}-good.txt"
        bad_path = target_dir / f"{label}-bad.txt"
    else:
        results_path.mkdir(parents=True, exist_ok=True)
        good_path = pathlib.Path(good_output) if good_output else results_path / site_slug / f"{label}-good.txt"
        bad_path = pathlib.Path(bad_output) if bad_output else results_path / site_slug / f"{label}-bad.txt"
        for p in (good_path, bad_path):
            p.parent.mkdir(parents=True, exist_ok=True)

    return str(good_path), str(bad_path)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate links on a website.")
    parser.add_argument("url", help="Starting URL (e.g. https://example.com)")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Max same-host HTML pages to crawl (0 = no limit, crawl until frontier is empty).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Number of concurrent threads for crawling and link checks.",
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Per-request timeout in seconds.")
    parser.add_argument(
        "--latency-threshold",
        type=float,
        default=DEFAULT_LATENCY_THRESHOLD,
        help="Mark links slower than this many seconds as problematic.",
    )
    parser.add_argument("--include-external", action="store_true", help="Also validate off-domain links.")
    parser.add_argument("--insecure", action="store_true", help="Disable SSL certificate verification (not recommended).")
    parser.add_argument("--user-agent", default="http-validator/0.1", help="User-Agent header for requests.")
    parser.add_argument("--results-dir", default="results", help="Directory where per-run log files are written.")
    parser.add_argument("--run-label", default=None, help="Custom run label for output files.")
    parser.add_argument(
        "--good-output",
        default=None,
        help="Write healthy links to this path (used as-is; not joined with --results-dir).",
    )
    parser.add_argument(
        "--bad-output",
        default=None,
        help="Write bad/slow links to this path (used as-is; not joined with --results-dir).",
    )
    parser.add_argument(
        "--no-sitemap",
        action="store_true",
        help="Do not load sitemap.xml for extra URLs to HTTP-check (homepage crawl only).",
    )
    parser.add_argument(
        "--no-mongo",
        action="store_true",
        help="Skip writing this run to MongoDB (default is to write using --mongo-uri or MONGODB_URI or localhost).",
    )
    parser.add_argument(
        "--mongo-uri",
        default=None,
        help=f"MongoDB URI (default: MONGODB_URI env if set, else {DEFAULT_MONGO_URI}).",
    )
    parser.add_argument(
        "--mongo-db",
        default=os.environ.get("MONGODB_DB", "http_validator"),
        help="MongoDB database name (default: http_validator or MONGODB_DB).",
    )
    parser.add_argument(
        "--no-es",
        action="store_true",
        help="Skip indexing this run in Elasticsearch (default indexes when Mongo write succeeds).",
    )
    parser.add_argument(
        "--es-url",
        default=None,
        help=f"Elasticsearch URL (default: ELASTICSEARCH_URL env if set, else {DEFAULT_ES_URL}).",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    start_url = normalize_absolute_url(args.url)
    if not start_url:
        print("Invalid URL. Please provide an absolute http(s) URL.", file=sys.stderr)
        return 2

    if not args.no_mongo:
        try:
            import pymongo  # noqa: F401
        except ImportError:
            print(
                "pymongo is not installed. Runs write to MongoDB by default. From the repo root run:\n"
                "  python3 -m pip install -e .\n"
                "Or skip Mongo for this run:  --no-mongo",
                file=sys.stderr,
            )
            return 2

    run_started = datetime.datetime.now().astimezone()

    ssl_context = ssl.create_default_context()
    if args.insecure:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

    print(f"Crawling from: {start_url}")
    sitemap_urls: set[str] = set()
    sitemap_source: str | None = None
    if not args.no_sitemap:
        sitemap_urls, sitemap_source = discover_sitemap_seed_urls(
            start_url=start_url,
            timeout=args.timeout,
            user_agent=args.user_agent,
            ssl_context=ssl_context,
        )
        if sitemap_urls:
            src = f" ({sitemap_source})" if sitemap_source else ""
            print(f"Sitemap URLs loaded: {len(sitemap_urls)}{src}")
        else:
            print("Sitemap URLs loaded: 0 (no entries for this start URL / robots / sitemap.xml)")

    page_to_links = crawl_site(
        start_url=start_url,
        max_pages=args.max_pages,
        timeout=args.timeout,
        user_agent=args.user_agent,
        ssl_context=ssl_context,
        num_workers=args.workers,
    )
    print(f"Crawled {len(page_to_links)} HTML documents (same site as start URL).")
    if len(page_to_links) == 0 and len(sitemap_urls) == 0:
        status, hint = probe_blocked_response(
            start_url,
            timeout=args.timeout,
            user_agent=args.user_agent,
            ssl_context=ssl_context,
        )
        if hint == "cloudflare_or_bot_wall":
            print(
                "Note: This host returned a bot wall (e.g. Cloudflare \"Just a moment...\"); "
                "this tool cannot execute the challenge JavaScript, so crawl and sitemap stay empty. "
                "Try from a normal residential network, supply a local sitemap file, or a browser-based fetcher.",
                flush=True,
            )
        elif status is not None and status >= 400:
            print(
                f"Note: Start URL returned HTTP {status}; crawl and sitemap seeding are likely blocked the same way.",
                flush=True,
            )

    pairs = build_check_pairs(
        page_to_links,
        start_url,
        sitemap_urls,
        include_external=args.include_external,
    )
    print(f"Unique URLs to check (crawl links + sitemap): {len(pairs)}. Checking...")

    results: list[CheckResult] = []
    workers = max(1, args.workers)
    if pairs:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_pair = {
                executor.submit(
                    check_link,
                    link,
                    source_page,
                    args.timeout,
                    args.user_agent,
                    args.latency_threshold,
                    ssl_context,
                ): (link, source_page)
                for link, source_page in pairs
            }
            for future in as_completed(future_to_pair):
                try:
                    results.append(future.result())
                except Exception as exc:
                    link, source_page = future_to_pair[future]
                    results.append(
                        CheckResult(
                            url=link,
                            source_page=source_page,
                            ok=False,
                            status_code=None,
                            latency_ms=None,
                            error=str(exc),
                            note="request_failed",
                        )
                    )

    site_slug = site_results_subdir(start_url)
    effective_label = args.run_label or default_run_label()
    good_path, bad_path = resolve_output_paths(
        results_dir=args.results_dir,
        site_slug=site_slug,
        run_label=effective_label,
        good_output=args.good_output,
        bad_output=args.bad_output,
    )
    good_count, bad_count = write_results(results, good_path=good_path, bad_path=bad_path)
    print(f"Wrote {good_count} healthy links to {good_path}")
    print(f"Wrote {bad_count} bad/slow links to {bad_path}")

    mongo_uri: str | None = None
    if not args.no_mongo:
        mongo_uri = args.mongo_uri or os.environ.get("MONGODB_URI") or DEFAULT_MONGO_URI

    if mongo_uri:
        from http_validator import mongo_store

        run_finished = datetime.datetime.now().astimezone()
        options_snapshot = {
            "max_pages": args.max_pages,
            "workers": args.workers,
            "timeout": args.timeout,
            "latency_threshold": args.latency_threshold,
            "include_external": args.include_external,
            "insecure": args.insecure,
            "no_sitemap": args.no_sitemap,
        }
        try:
            run_id = mongo_store.save_validation_run(
                mongo_uri,
                args.mongo_db,
                start_url=start_url,
                site_slug=site_slug,
                run_label=effective_label,
                started_at=run_started,
                finished_at=run_finished,
                options=options_snapshot,
                results=results,
                good_count=good_count,
                bad_count=bad_count,
            )
            print(f"Stored run in MongoDB ({args.mongo_db}.{mongo_store.RUNS_COL}): _id={run_id}")

            if not args.no_es:
                es_url = args.es_url or os.environ.get("ELASTICSEARCH_URL") or DEFAULT_ES_URL
                if es_url.lower() not in ("", "none", "off", "false", "0"):
                    from http_validator import es_store

                    try:
                        es_store.index_validation_run(
                            es_url,
                            run_id=run_id,
                            start_url=start_url,
                            site_slug=site_slug,
                            run_label=effective_label,
                            started_at=run_started,
                            finished_at=run_finished,
                            options=options_snapshot,
                            results=results,
                            good_count=good_count,
                            bad_count=bad_count,
                        )
                        print(f"Indexed run in Elasticsearch: run_id={run_id}")
                    except Exception as exc:
                        print(f"Elasticsearch indexing failed: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"MongoDB write failed: {exc}", file=sys.stderr)

    return 1 if bad_count else 0


if __name__ == "__main__":
    raise SystemExit(run())
