import pytest

from app.tools.browser import BrowserTool, _authorize_browser_url
from app.tools.web_search import WebSearchTool


class _SearchResponse:
    status_code = 200
    encoding = "utf-8"

    def __init__(self, chunks):
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size):
        yield from self._chunks

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_browser_blocks_local_and_unapproved_destinations(monkeypatch):
    browser = BrowserTool(enabled=True)
    allowed, reason = await _authorize_browser_url(
        "http://127.0.0.1/admin", browser._permissions, confirmed=False
    )
    assert not allowed and reason
    allowed, _ = await _authorize_browser_url(
        "file:///etc/passwd", browser._permissions, confirmed=True
    )
    assert not allowed

    monkeypatch.setenv("ALLOWED_EGRESS_HOSTS", "public.example")
    monkeypatch.setattr(
        "app.tools.browser.socket.getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))],
    )
    allowed, _ = await _authorize_browser_url(
        "https://public.example/", browser._permissions, confirmed=False
    )
    assert allowed

    monkeypatch.setattr(
        "app.tools.browser.socket.getaddrinfo",
        lambda *args, **kwargs: [(0, 0, 0, "", ("10.0.0.5", 443))],
    )
    allowed, _ = await _authorize_browser_url(
        "https://public.example/", browser._permissions, confirmed=False
    )
    assert not allowed
    allowed, _ = await _authorize_browser_url(
        "https://public.example/", browser._permissions, confirmed=True
    )
    assert allowed


@pytest.mark.asyncio
async def test_web_search_requires_consent_and_returns_verified_source_links(monkeypatch):
    monkeypatch.delenv("ALLOWED_EGRESS_HOSTS", raising=False)
    tool = WebSearchTool()
    blocked = await tool.execute("query")
    assert "confirmation required" in blocked

    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fexample.org%2Farticle">Example title</a>'
        '<a class="result__snippet">Evidence snippet</a>'
    ).encode()
    response = _SearchResponse([html])
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(kwargs)
        return response

    monkeypatch.setattr("requests.get", fake_get)
    result = await tool.execute("query", confirmed=True)
    assert "[1] Example title" in result
    assert "Source: https://example.org/article" in result
    assert "Evidence snippet" in result
    assert captured["allow_redirects"] is False
    assert response.closed


@pytest.mark.asyncio
async def test_web_search_rejects_large_responses(monkeypatch):
    response = _SearchResponse([b"x" * 1_000_000, b"y" * 1_000_001])
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: response)
    result = await WebSearchTool().execute("query", confirmed=True)
    assert "exceeded size limit" in result
    assert response.closed
