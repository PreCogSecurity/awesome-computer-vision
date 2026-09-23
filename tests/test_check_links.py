"""Tests for scripts/check_links.py.

The HTTP layer is exercised through a fake fetcher so the suite runs offline;
one integration test spins up a local ``http.server`` to verify the real
HEAD-with-GET-fallback behavior.
"""

from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

from scripts import check_links

REPO_ROOT = Path(__file__).resolve().parents[1]


def fake_fetcher(status: int = 200, error: Exception | None = None) -> check_links.Fetcher:
    """Build a fetcher that always returns *status* (or raises *error*)."""

    def fetch(url: str, timeout: float = 10.0) -> tuple[int, str]:
        if error is not None:
            raise error
        return status, url

    return fetch


class TestExtractLinks:
    def test_finds_inline_links_with_line_numbers(self):
        markdown = "See [OpenCV](http://opencv.org/) and\n[VLFeat](http://www.vlfeat.org/)."
        assert check_links.extract_links(markdown) == [
            check_links.Link(url="http://opencv.org/", line=1, text="OpenCV"),
            check_links.Link(url="http://www.vlfeat.org/", line=2, text="VLFeat"),
        ]

    def test_handles_link_titles(self):
        markdown = '[Example](https://example.com/ "An example site")'
        assert check_links.extract_links(markdown) == [
            check_links.Link(url="https://example.com/", line=1, text="Example")
        ]

    def test_ignores_reference_style_links(self):
        markdown = "[text][ref]\n\n[ref]: http://example.com/"
        assert check_links.extract_links(markdown) == []

    def test_ignores_malformed_entries(self):
        # Missing closing parenthesis: not a valid inline link.
        markdown = "[broken](http://example.com/never-closed"
        assert check_links.extract_links(markdown) == []

    def test_readme_contains_many_checkable_links(self):
        # Sanity check against the real README: the parser must find the
        # curated links without needing network access.
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        links = [link for link in check_links.extract_links(readme) if check_links.should_check(link.url)]
        assert len(links) > 400


class TestShouldCheck:
    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/",
            "https://example.com/",
            "https://github.com/sindresorhus/awesome",
        ],
    )
    def test_accepts_http_urls(self, url):
        assert check_links.should_check(url)

    @pytest.mark.parametrize(
        "url",
        [
            "#books",
            "mailto:someone@example.com",
            "tel:+15551234567",
            "javascript:void(0)",
            "people.md",
            "scripts/check_links.py",
            "ftp://example.com/file",
        ],
    )
    def test_skips_non_http_urls(self, url):
        assert not check_links.should_check(url)


class TestCheckUrl:
    def test_ok_status(self):
        result = check_links.check_url("https://example.com/", fake_fetcher(200))
        assert result.ok
        assert result.status == 200
        assert result.error is None

    def test_redirect_status_is_ok(self):
        result = check_links.check_url("https://example.com/", fake_fetcher(302))
        assert result.ok

    def test_not_found_is_broken(self):
        result = check_links.check_url("https://example.com/missing", fake_fetcher(404))
        assert not result.ok
        assert result.status == 404

    def test_server_error_is_broken(self):
        result = check_links.check_url("https://example.com/", fake_fetcher(500))
        assert not result.ok

    def test_network_error_is_broken_with_message(self):
        result = check_links.check_url(
            "https://example.com/",
            fake_fetcher(error=TimeoutError("timed out")),
        )
        assert not result.ok
        assert result.status is None
        assert result.error is not None
        assert "timed out" in result.error


class TestCheckFile:
    def test_returns_counts_and_broken_links(self, tmp_path):
        markdown = tmp_path / "links.md"
        markdown.write_text(
            "[Good](https://example.com/ok)\n[Bad](https://example.com/404)\n",
            encoding="utf-8",
        )

        def fetch(url: str, timeout: float = 10.0) -> tuple[int, str]:
            return (200 if "ok" in url else 404), url

        checked, broken = check_links.check_file(str(markdown), fetch)
        assert checked == 2
        assert len(broken) == 1
        link, result = broken[0]
        assert link.url == "https://example.com/404"
        assert link.line == 2
        assert result.status == 404

    def test_skip_patterns_are_excluded(self, tmp_path):
        markdown = tmp_path / "links.md"
        markdown.write_text("[Skip](https://example.com/skip-me)\n", encoding="utf-8")

        checked, broken = check_links.check_file(str(markdown), fake_fetcher(404), skip=("skip-me",))
        # Skipped URLs are not counted as checked and never reported.
        assert checked == 0
        assert broken == []


class TestMain:
    def test_exits_zero_when_all_links_ok(self, tmp_path, monkeypatch, capsys):
        markdown = tmp_path / "ok.md"
        markdown.write_text("[Good](https://example.com/ok)\n", encoding="utf-8")
        monkeypatch.setattr(check_links, "http_status", fake_fetcher(200))

        assert check_links.main([str(markdown)]) == 0
        assert "0 broken" in capsys.readouterr().out

    def test_exits_nonzero_and_reports_broken_links(self, tmp_path, monkeypatch, capsys):
        markdown = tmp_path / "broken.md"
        markdown.write_text(
            "[Good](https://example.com/ok)\n[Bad](https://example.com/404)\n",
            encoding="utf-8",
        )

        def fetch(url: str, timeout: float = 10.0) -> tuple[int, str]:
            return (200 if "ok" in url else 404), url

        monkeypatch.setattr(check_links, "http_status", fetch)

        assert check_links.main([str(markdown)]) == 1
        captured = capsys.readouterr()
        assert "FAIL" in captured.out
        assert "1 broken" in captured.out

    def test_exits_two_for_unreadable_file(self, tmp_path, capsys):
        missing = tmp_path / "does-not-exist.md"
        assert check_links.main([str(missing)]) == 2
        assert "cannot read" in capsys.readouterr().err


class TestHttpStatus:
    """Integration tests against a local HTTP server (no external network)."""

    @pytest.fixture()
    def server(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_HEAD(self):  # noqa: N802 (stdlib naming)
                if self.path == "/ok":
                    self.send_response(200)
                elif self.path == "/missing":
                    self.send_response(404)
                else:
                    self.send_response(405)
                self.end_headers()

            def do_GET(self):  # noqa: N802 (stdlib naming)
                self.send_response(200)
                self.end_headers()

            def log_message(self, format, *args):  # noqa: A002 - silence request logging
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()
            thread.join()

    def test_head_ok(self, server):
        status, _ = check_links.http_status(f"{server}/ok", timeout=5)
        assert status == 200

    def test_head_not_found(self, server):
        status, _ = check_links.http_status(f"{server}/missing", timeout=5)
        assert status == 404

    def test_head_rejected_falls_back_to_get(self, server):
        # The server answers 405 to HEAD and 200 to GET.
        status, _ = check_links.http_status(f"{server}/head-only", timeout=5)
        assert status == 200

    def test_connection_refused_raises(self):
        with pytest.raises(Exception):
            check_links.http_status("http://127.0.0.1:1/", timeout=2)