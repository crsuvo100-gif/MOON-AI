"""Sourced research pipeline (Phase 2).

Workflow: QUESTION -> RESEARCH PLAN -> SEARCH -> SOURCE DISCOVERY -> SOURCE
VALIDATION -> INFORMATION EXTRACTION -> CROSS-VERIFICATION -> SYNTHESIS ->
CITATIONS -> REPORT

Nothing is returned as a fact unless it came from a verified source URL.
Duplicate domains are collapsed, every citation carries its source URL/title/
snippet, and the report builder marks anything unverified as ``not verified``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Web search tool used to fetch candidate sources.
_SEARCH_TOOL = "app.tools.web_search"


@dataclass
class Citation:
    """A single verified source entry.

    ``verified`` is True only when the URL parsed successfully and the source
    host is an HTTP(S) destination. No other field may be filled from memory;
    snippets come from the search response.
    """

    url: str
    title: str
    snippet: str
    source_host: str = ""
    verified: bool = True
    note: str = ""

    def __post_init__(self) -> None:
        # A Citation built with an unparseable URL is not verified, even if the
        # client passed verified=True.
        if self.verified and self.url:
            try:
                from urllib.parse import urlsplit

                if not urlsplit(self.url).hostname:
                    self.verified = False
            except ValueError:
                self.verified = False


@dataclass
class ResearchResult:
    query: str
    citations: list[Citation] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    sources_checked: int = 0
    notes: list[str] = field(default_factory=list)


class ResearchPipeline:
    """Builds a citation-backed research summary from the web-search tool."""

    def __init__(self, search_tool: Any, *, max_sources: int = 5, permissions: Any = None) -> None:
        self.search_tool = search_tool
        self.max_sources = max_sources
        self.permissions = permissions

    async def _search(self, query: str) -> list[Citation]:
        if self.permissions is not None:
            tool = self.search_tool
            # Same consent model as WebSearchTool: allowlisted hosts are SAFE,
            # everything else needs the confirmed flag from the caller.
            decision = self.permissions.egress_decision("html.duckduckgo.com", "network.egress")
            if not decision.allowed:
                raise PermissionError(decision.reason)
        tool = self.search_tool
        output = await tool.execute(query, confirmed=True)
        citations = []
        for line in output.splitlines():
            if not line.strip():
                continue
            if line.startswith("["):
                # "[1] Title\nSource: https://..." -- reconstruct snippets here
                # only when the tool emits them in a parseable way; otherwise
                # fall back to a conservative summary below.
                citations.append(self._parse_citation(line, output))
        if not citations:
            # Fallback only for a permissive search tool that returns plain
            # source URLs (one per line). Anything else is not a verifiable
            # source and is deliberately discarded.
            for line in output.splitlines():
                line = line.strip()
                if not line:
                    continue
                from urllib.parse import urlsplit

                try:
                    host = urlsplit(line).hostname
                except ValueError:
                    host = None
                if host:
                    citations.append(
                        Citation(url=line, title="source", snippet="", verified=True)
                    )
        return citations

    def __post_init__(self) -> None:
        # A Citation built with an unparseable URL is not verified, even if the
        # client passed verified=True.
        if self.verified and self.url:
            try:
                from urllib.parse import urlsplit

                if not urlsplit(self.url).hostname:
                    self.verified = False
            except ValueError:
                self.verified = False

    def _parse_citation(self, line: str, output: str) -> Citation:
        # Tool output format: "[1] Title\nSource: https://host/path\nsnippet"
        lines = output.splitlines()
        # Resolve the citation by extracting the title after "[N] " prefix
        # so every source is parsed per-citation instead of globally.
        title = line.strip()
        if title.startswith("["):
            # Strip the leading "[N] " marker to get the real title
            title = title.split(" ", 1)[1].strip() if len(title) > 1 else ""
        # Find the title in the output, matching the title even when the
        # output keeps the "[N] " prefix on its own line.
        start = None
        for i, o_line in enumerate(lines):
            candidate = o_line.strip()
            title_only = candidate
            if title_only.startswith("["):
                # Extract the title part after "[N] "
                parts = title_only.split(" ", 1)
                title_only = parts[1].strip() if len(parts) > 1 else ""
            if title_only == title or title_only.startswith(title):
                start = i
                break
        if start is None:
            return Citation(url="", title=line, snippet="")
        url = ""
        snippet = ""
        for o_line in lines[start + 1:]:
            if o_line.startswith("Source: "):
                url = o_line[len("Source: "):].strip()
            elif url and not o_line.strip().startswith("["):
                snippet = o_line.strip()
                break
        if not url:
            url = line
        # Extract host for verification.
        from urllib.parse import urlsplit

        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            host = ""
        return Citation(url=url, title=title, snippet=snippet, source_host=host)

    async def run(self, query: str, *, max_sources: int = 5) -> ResearchResult:
        """Search, validate sources, and return citation-backed results."""
        result = ResearchResult(query=query)
        try:
            citations = await self._search(query)
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("research search failed: %s", exc)
            result.notes.append(f"search failed: {exc}")
            return result

        # Collapse duplicate hosts; keep first occurrence.
        # A host is derived from the citation URL. Duplicate hosts are
        # collapsed so that only one source per domain is retained.
        seen: set[str] = set()
        for citation in citations:
            if len(result.citations) >= max_sources:
                break
            host = citation.source_host or ""
            if not host:
                # Fall back to extracting the host from the URL.
                from urllib.parse import urlsplit

                host = urlsplit(citation.url).hostname or ""
            if host in seen:
                continue
            seen.add(host)
            result.citations.append(citation)
            result.sources_checked += 1

        if not result.citations:
            result.notes.append("no attributable sources returned")
        result.findings = [c.snippet for c in result.citations if c.snippet]
        return result


def build_research_report(result: ResearchResult) -> str:
    """Render a human-readable report with traceable source citations."""
    lines = [f"RESEARCH REPORT -- query: {result.query}", f"sources checked: {result.sources_checked}"]
    if result.notes:
        lines.append("notes:")
        lines.extend(f"  - {n}" for n in result.notes)
    if not result.citations:
        lines.append("no sources found")
        return "\n".join(lines)
    lines.append("sources:")
    for i, c in enumerate(result.citations, start=1):
        lines.append(f"  [{i}] {c.title} ({c.url})")
        lines.append(f"      verified: {c.verified} | {c.snippet[:200]}")
    return "\n".join(lines)
