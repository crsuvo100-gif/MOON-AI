"""Phase-2 research-pipeline tests (no network or model backend required)."""

import pytest

from app.research import Citation, ResearchPipeline, ResearchResult, build_research_report

# Deterministic DuckDuckGo-style search result page (MOON tool output format):
# "[N] Title\nSource: https://host/path\nsnippet"
FAKE_RESULTS = (
    "[1] Example title one\n"
    "Source: https://example.org/article1\n"
    "First evidence snippet\n"
    "\n"
    "[2] Example title two\n"
    "Source: https://example.com/article2\n"
    "Second evidence snippet"
)


class _FakeSearchTool:
    def __init__(self, *, output: str = FAKE_RESULTS, confirmed: bool = True) -> None:
        self._output = output
        self._confirmed = confirmed

    async def execute(self, query: str = "", **kwargs: object) -> str:
        return self._output


class _PermitAllPermissions:
    def egress_decision(self, host: str, scope: str = "network.egress"):
        return type(  # noqa: E272
            "Decision",
            (),
            {"allowed": True, "tier": "SAFE", "reason": "allowlisted"},
        )()


@pytest.mark.asyncio
async def test_citation_from_valid_url_is_verified():
    c = Citation(url="https://example.org/article", title="Example", snippet="text")
    assert c.verified is True
    assert c.url == "https://example.org/article"


@pytest.mark.asyncio
async def test_citation_from_invalid_url_is_not_verified():
    c = Citation(url="not-a-url", title="Example", snippet="text")
    assert c.verified is False


@pytest.mark.asyncio
async def test_pipeline_returns_citations_with_sources_checked():
    tool = _FakeSearchTool()
    pipeline = ResearchPipeline(tool, permissions=_PermitAllPermissions())
    result = await pipeline.run("arbitrary query")
    # Each distinct host is checked once; the pipeline collapses duplicates to
    # one citation per host (host-based dedup per the pipeline contract).
    assert result.sources_checked == 2
    assert len(result.citations) == 2
    assert result.citations[0].url == "https://example.org/article1"
    assert result.citations[1].url == "https://example.com/article2"
    assert result.citations[0].title == "Example title one"
    assert result.citations[0].snippet == "First evidence snippet"
    assert result.citations[1].snippet == "Second evidence snippet"


@pytest.mark.asyncio
async def test_pipeline_dedupes_duplicate_hosts():
    class _DupTool(_FakeSearchTool):
        async def execute(self, query="", **kwargs):
            return FAKE_RESULTS + FAKE_RESULTS  # two hosts, repeated

    tool = _DupTool()
    pipeline = ResearchPipeline(tool, permissions=_PermitAllPermissions())
    result = await pipeline.run("query")
    hosts = [c.url.split("/")[2] for c in result.citations]
    # Repeated hosts collapse to a single citation per host.
    assert len(hosts) == len(set(hosts)) == 2


@pytest.mark.asyncio
async def test_pipeline_denies_when_permission_manager_denies():
    class _DenyPermissions:
        def egress_decision(self, host, scope="network.egress"):
            return type(  # noqa: E272
                "Decision",
                (),
                {"allowed": False, "tier": "CONFIRMATION", "reason": "needs operator confirmation"},
            )()

    tool = _FakeSearchTool()
    pipeline = ResearchPipeline(tool, permissions=_DenyPermissions())
    with pytest.raises(PermissionError):
        await pipeline.run("query")


@pytest.mark.asyncio
async def test_pipeline_handles_unparseable_search_output():
    tool = _FakeSearchTool(output="connection refused")
    pipeline = ResearchPipeline(tool, permissions=None)
    result = await pipeline.run("query")
    assert result.sources_checked == 0
    assert any("no attributable sources" in n for n in result.notes)


@pytest.mark.asyncio
async def test_build_research_report_is_traceable():
    res = ResearchResult(
        query="test",
        citations=[
            Citation(url="https://example.org/a", title="First", snippet="alpha", verified=True),
            Citation(url="https://example.org/b", title="Second", snippet="beta", verified=False),
        ],
        sources_checked=2,
    )
    report = build_research_report(res)
    assert "query: test" in report
    assert "First" in report and "Second" in report
    assert "https://example.org/a" in report and "https://example.org/b" in report
    assert "verified: True" in report and "verified: False" in report


def test_build_research_report_handles_no_sources():
    report = build_research_report(ResearchResult(query="nope"))
    assert "no sources found" in report
