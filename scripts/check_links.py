#!/usr/bin/env python3
"""Check that external links in markdown files are still alive.

Usage:
    python scripts/check_links.py README.md people.md [--timeout 10] [--skip SUBSTRING]

The script extracts inline markdown links from the given files and issues HTTP
HEAD requests (falling back to GET when a server rejects HEAD) to verify each
URL. Broken links are reported with the file, line number, and link text, and
the script exits with a non-zero status if any link is broken.

Skipped automatically:

* in-page anchors (``#...``)
* non-http(s) schemes (``mailto:``, ``tel:``, ``javascript:``, ...)
* relative URLs (no scheme)

The HTTP layer is isolated in :func:`http_status` so tests can substitute a
fake fetcher; no network access is required to run the test suite.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import requests

# Matches inline markdown links: [text](url) and [text](url "title").
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)(?:\s+[\"'][^\"']*[\"'])?\)")

# Schemes that are never checked over the network.
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "ftp:", "file:")

# Status codes for which a HEAD request is unreliable and a GET fallback is
# attempted (some servers reject HEAD or require a full GET).
HEAD_FALLBACK_STATUSES = (401, 403, 405, 501)

USER_AGENT = "awesome-computer-vision-link-checker/1.0"

# A fetcher takes (url, timeout) and returns (status_code, final_url).
Fetcher = Callable[[str, float], tuple[int, str]]


@dataclass(frozen=True)
class Link:
    """A markdown link found in a file."""

    url: str
    line: int
    text: str


@dataclass(frozen=True)
class CheckResult:
    """The outcome of checking a single URL."""

    url: str
    ok: bool
    status: Optional[int]
    error: Optional[str] = None


def extract_links(markdown: str) -> list[Link]:
    """Extract inline markdown links with their 1-based line numbers."""
    links: list[Link] = []
    for lineno, line in enumerate(markdown.splitlines(), start=1):
        for match in LINK_RE.finditer(line):
            links.append(Link(url=match.group(2), line=lineno, text=match.group(1)))
    return links


def should_check(url: str) -> bool:
    """Return True for http(s) URLs that are worth checking."""
    if url.startswith("#") or url.startswith(SKIP_SCHEMES):
        return False
    return url.startswith("http://") or url.startswith("https://")


def http_status(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Return ``(status_code, final_url)`` for *url*.

    Uses a HEAD request and falls back to a streaming GET for servers that
    reject HEAD (e.g. 403/405). Raises :class:`requests.RequestException` on
    network errors, timeouts, and DNS failures.
    """
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        response = session.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code in HEAD_FALLBACK_STATUSES:
            response.close()
            response = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
        status, final_url = response.status_code, response.url
        response.close()
        return status, final_url
    finally:
        session.close()


def check_url(url: str, fetcher: Fetcher, timeout: float = 10.0) -> CheckResult:
    """Check a single URL with the given fetcher, never raising."""
    try:
        status, _final_url = fetcher(url, timeout)
    except Exception as exc:  # noqa: BLE001 - report any failure as "broken"
        return CheckResult(url=url, ok=False, status=None, error=str(exc))
    return CheckResult(url=url, ok=200 <= status < 400, status=status)


def check_file(
    path: str,
    fetcher: Fetcher,
    timeout: float = 10.0,
    skip: Iterable[str] = (),
    workers: int = 8,
) -> tuple[int, list[tuple[Link, CheckResult]]]:
    """Check all external links in a markdown file.

    Returns ``(links_checked, broken)`` where *broken* is a list of
    ``(Link, CheckResult)`` tuples for every failing URL. Links are checked
    concurrently with a small thread pool (``workers=1`` disables it).
    """
    with open(path, encoding="utf-8") as fh:
        markdown = fh.read()

    links = [
        link
        for link in extract_links(markdown)
        if should_check(link.url) and not any(pattern in link.url for pattern in skip)
    ]

    def check(link: Link) -> tuple[Link, CheckResult]:
        return link, check_url(link.url, fetcher, timeout=timeout)

    broken: list[tuple[Link, CheckResult]] = []
    if workers > 1 and len(links) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for link, result in pool.map(check, links):
                if not result.ok:
                    broken.append((link, result))
    else:
        for link, result in (check(link) for link in links):
            if not result.ok:
                broken.append((link, result))
    return len(links), broken


def main(argv: Optional[list[str]] = None) -> int:
    # Report non-ASCII link text reliably regardless of the console's default
    # encoding (Windows consoles default to cp1252, which crashes on BOMs and
    # accented characters).
    stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
    if stdout_reconfigure is not None:
        stdout_reconfigure(encoding="utf-8")
    stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
    if stderr_reconfigure is not None:
        stderr_reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+", metavar="FILE", help="markdown file(s) to check")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="per-request timeout in seconds (default: 10)",
    )
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="SUBSTRING",
        help="skip URLs containing this substring (repeatable)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="number of concurrent checks (default: 8, 1 disables concurrency)",
    )
    args = parser.parse_args(argv)

    total = 0
    broken: list[tuple[str, Link, CheckResult]] = []
    for path in args.files:
        try:
            checked, file_broken = check_file(
                path,
                http_status,
                timeout=args.timeout,
                skip=args.skip,
                workers=args.workers,
            )
        except OSError as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        total += checked
        for link, result in file_broken:
            detail = result.error if result.status is None else f"HTTP {result.status}"
            print(f"FAIL {path}:{link.line} [{link.text}] {link.url} ({detail})", flush=True)
            broken.append((path, link, result))

    print(f"\nchecked {total} links, {len(broken)} broken", flush=True)
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())