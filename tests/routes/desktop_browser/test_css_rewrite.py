"""CSS rewriting in the browser proxy: @import and text/css responses."""
from __future__ import annotations

from unittest.mock import patch
from urllib.parse import quote

import pytest
import respx
from httpx import Response

from tinyagentos.routes.desktop_browser.rewriter import rewrite_html


def _proxy(url: str) -> str:
    return f"/api/desktop/browser/proxy?profile_id=p&url={quote(url, safe='')}"


def test_import_string_in_style_block_is_rewritten():
    html = b'<html><head><style>@import "https://evil.example/x.css"; a{color:red}</style></head></html>'
    out = rewrite_html(html, base_url="https://example.com/", proxy=_proxy)
    assert b"/api/desktop/browser/proxy?profile_id=p&url=https%3A%2F%2Fevil.example%2Fx.css" in out
    assert b'"https://evil.example/x.css"' not in out


def test_import_url_form_in_style_block_is_rewritten():
    html = b"<html><head><style>@import url('/rel.css');</style></head></html>"
    out = rewrite_html(html, base_url="https://example.com/dir/", proxy=_proxy)
    assert b"https%3A%2F%2Fexample.com%2Frel.css" in out


def test_rewrite_css_handles_import_and_url():
    from tinyagentos.routes.desktop_browser.rewriter import rewrite_css

    css = b'@import "a.css";\nbody{background:url(img/b.png)}'
    out = rewrite_css(css, base_url="https://example.com/s/main.css", proxy=_proxy).decode()
    assert "https%3A%2F%2Fexample.com%2Fs%2Fa.css" in out
    assert "https%3A%2F%2Fexample.com%2Fs%2Fimg%2Fb.png" in out


def test_data_uri_with_parentheses_survives():
    from tinyagentos.routes.desktop_browser.rewriter import rewrite_css

    svg = "url(data:image/svg+xml,%3Csvg fill='rgb(0,0,0)'%3E)"
    out = rewrite_css(f"a{{background:{svg}}}".encode(), base_url="https://example.com/", proxy=_proxy)
    assert svg.encode() in out


@pytest.mark.asyncio
class TestProxyRewritesCssResponse:
    @respx.mock
    async def test_text_css_response_is_rewritten(self, client):
        respx.get("http://example.com/s/main.css").mock(
            return_value=Response(
                200,
                content=b'@import "other.css"; a{background:url(i.png)}',
                headers={"content-type": "text/css; charset=utf-8"},
            )
        )
        with patch(
            "tinyagentos.routes.desktop_browser.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            resp = await client.get(
                "/api/desktop/browser/proxy",
                params={"profile_id": "personal", "url": "http://example.com/s/main.css"},
            )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")
        assert b"example.com%2Fs%2Fother.css" in resp.content
        assert b"example.com%2Fs%2Fi.png" in resp.content