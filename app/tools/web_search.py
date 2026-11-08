"""Web search tool with explicit egress consent and source attribution."""

from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

from app.connector.permission import ConnectorPermissionManager
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"
_MAX_RESPONSE_BYTES = 2_000_000
_MAX_QUERY_LENGTH = 500
_RESULT_LIMIT = 5


class _SearchResultsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._active: str | None = None
        self._active_tag: str | None = None
        self._nested_tags = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._active:
            self._nested_tags += 1
        if "result__a" in classes:
            self.results.append(
                {"title": "", "url": attributes.get("href") or "", "snippet": ""}
            )
            self._active = "title"
            self._active_tag = tag
            self._nested_tags = 0
        elif "result__snippet" in classes and self.results:
            self._active = "snippet"
            self._active_tag = tag
            self._nested_tags = 0

    def handle_endtag(self, tag: str) -> None:
        if not self._active:
            return
        if tag == self._active_tag and self._nested_tags == 0:
            self._active = None
            self._active_tag = None
        elif self._nested_tags:
            self._nested_tags -= 1

    def handle_data(self, data: str) -> None:
        if self._active and self.results:
            self.results[-1][self._active] += data


def _source_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlsplit(href)
    if parsed.hostname and parsed.hostname.lower() in {"duckduckgo.com", "www.duckduckgo.com"}:
        destination = parse_qs(parsed.query).get("uddg", [])
        if destination:
            href = destination[0]
            parsed = urlsplit(href)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return urlunsplit(parsed)


def _fetch_search_html(query: str) -> tuple[int, bytes, str]:
    import requests

    response = requests.get(
        _SEARCH_URL,
        params={"q": query},
        timeout=10,
        headers={"User-Agent": "MOON-AI/1.0"},
        allow_redirects=False,
        stream=True,
    )
    try:
        if response.status_code != 200:
            return response.status_code, b"", response.encoding or "utf-8"
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=16384):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_RESPONSE_BYTES:
                raise ValueError("search response exceeded size limit")
            chunks.append(chunk)
        return response.status_code, b"".join(chunks), response.encoding or "utf-8"
    finally:
        response.close()


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the public web and return result titles, snippets, and source URLs. "
        "External searches require operator approval or an explicit host allowlist. "
        "Model-supplied confirmation does not authorize egress."
    )

    def __init__(self, permissions: ConnectorPermissionManager | None = None) -> None:
        self._permissions = permissions or ConnectorPermissionManager()

    async def execute(self, query: str = "", **kwargs: Any) -> str:
        query = (query or "").strip()
        if not query:
            return "[web_search] query is required"
        if len(query) > _MAX_QUERY_LENGTH:
            return f"[web_search] query exceeds {_MAX_QUERY_LENGTH} characters"
        host = urlsplit(_SEARCH_URL).hostname or ""
        decision = self._permissions.egress_decision(host, "network.egress")
        if not decision.allowed and kwargs.get("confirmed") is not True:
            return f"[web_search] confirmation required: {decision.reason}"

        try:
            status, body, encoding = await asyncio.to_thread(_fetch_search_html, query)
            if status != 200:
                return f"[web_search] search provider returned HTTP {status}"
            parser = _SearchResultsParser()
            parser.feed(body.decode(encoding, errors="replace"))

            entries = []
            for result in parser.results:
                title = " ".join(result["title"].split())
                snippet = " ".join(result["snippet"].split())
                source = _source_url(result["url"])
                if title and source:
                    entries.append((title, source, snippet))
                if len(entries) >= _RESULT_LIMIT:
                    break
            if not entries:
                return f"[web_search] no attributable results for: {query}"
            return "\n\n".join(
                f"[{index}] {title}\nSource: {source}\n{snippet}"
                for index, (title, source, snippet) in enumerate(entries, start=1)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("web search failed: %s", exc)
            return f"[web_search] unavailable: {exc}"
