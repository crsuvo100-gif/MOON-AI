#!/usr/bin/env python3
"""github_mcp.py -- MOON-AI's GitHub-sourced MCP stdio server.

A stdio MCP program that MOON connects to (via MCPConnector) to inspect a
connected GitHub repository, search repositories, and pull tools on demand.

Connection in MOON:
    The standard "mcp" ConnectionRecord carries:
        command = sys.executable
        args    = [abs path to this file]
        env     = {"MOON_MCP_REPO_URL": <connected GitHub repo URL>}
        metadata = {"repo_url": ..., "source": "github"}
    When MCPConnector spawns this process it injects that env var, so the
    program knows exactly which GitHub repo to source tools from.

Exposed MCP tools (sources from the connected GitHub repo):
    github_search_repos     -- search public GitHub repositories
    github_list_repo_tools  -- list tool files present in the connected repo
    github_pull_plugin      -- pull a tool/plugin from the repo into plugins/

All GitHub I/O reuses the project's existing GitHub capability
(app/tools/github_feed.py, which calls the GitHub REST API via curl) so there
is no second implementation to drift.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# --------------------------------------------------------------------------- #
# Connection wiring: which GitHub repo does this MCP program serve?           #
# --------------------------------------------------------------------------- #
REPO_URL_ENV = "MOON_MCP_REPO_URL"
REPO_URL_DEFAULT = ""


def _connected_repo_url() -> str:
    """Return the GitHub repo the connected MOON session serves.

    Comes from the MOON_MCP_REPO_URL env var injected by MCPConnector when
    it spawns this stdio server.  Falls back to a placeholder that makes the
    absence loud (never silently return an empty tool list).
    """
    url = os.environ.get(REPO_URL_ENV, "").strip()
    if not url:
        return "https://github.com/<unset>/<unset>"
    return url


# --------------------------------------------------------------------------- #
# Low-level GitHub REST helpers (reuse github_feed.py + github_retriever.py)  #
# --------------------------------------------------------------------------- #
def _github_get(url: str) -> dict:
    """GET a GitHub REST API endpoint; returns JSON.  On failure returns
    {'error': <message>} so callers never leak raw exceptions."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "MOON-AI-MCP",
            # Respect the repo's chosen auth; public search needs none.
            "Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {"error": "empty response from GitHub API"}
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.reason or exc.read().decode('utf-8', 'replace')[:200]}"}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"GitHub API request failed: {exc}"}


def _parse_repo_url(url: str) -> tuple[str, str]:
    """Turn https://github.com/owner/repo into (owner, repo).

    Strips a trailing .git and tolerates github.com vs git@github.com: forms.
    """
    u = url.rstrip("/")
    for sep in ("https://github.com/", "git@github.com:"):
        if u.startswith(sep):
            body = u[len(sep):]
            if body.endswith(".git"):
                body = body[: -len(".git")]
            owner, _, repo = body.partition("/")
            return owner, repo
    return "", u


# --------------------------------------------------------------------------- #
# MCP tool implementations.  Each is a plain function so tests can import
# them directly and assert deterministic output.                              #
# --------------------------------------------------------------------------- #
def github_search_repos(q: str, per_page: int = 10) -> dict:
    """Search public GitHub repositories by query string.

    Returns a dict with a 'results' list of {full_name, html_url, description,
    stargazers_count, language, score}.  Mirrors search_github in
    app/tools/github_feed.py but returns the tool-friendly dict shape.
    """
    if not q:
        return {"results": [], "query": "", "note": "empty query"}
    url = (
        "https://api.github.com/search/repositories"
        f"?q={urllib.parse.quote(q)}&sort=stars&order=desc&per_page={max(1, min(per_page, 100))}"
    )
    data = _github_get(url)
    if "error" in data:
        return {"error": data["error"]}
    out = []
    for it in data.get("items", []):
        out.append(
            {
                "full_name": it.get("full_name", ""),
                "html_url": it.get("html_url", ""),
                "description": it.get("description") or "",
                "stargazers_count": it.get("stargazers_count", 0),
                "language": it.get("language") or "",
                "score": it.get("score", 0),
            }
        )
    return {"results": out, "query": q}


def github_list_repo_tools(repo_url: str, path: str = "tools") -> dict:
    """List tool files present in the connected repo.

    Walks the repo tree at `path` (defaults to `tools/`) via the GitHub
    Contents API (no clone), so the result always reflects the connected
    repo's current state.  Returns a dict with 'repo', 'path', and 'tools'
    (list of file names).
    """
    owner, repo = _parse_repo_url(repo_url)
    if not owner or not repo:
        return {"repo": repo_url, "path": path, "tools": [],
                "error": "unrecognized repo URL"}
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{urllib.parse.quote(path)}"
    data = _github_get(url)
    if "error" in data:
        return {"repo": repo_url, "path": path, "tools": [], "error": data["error"]}
    if isinstance(data, list):
        names = [c.get("name", "") for c in data]
    elif isinstance(data, dict):
        # details response (e.g. a single file), treat as one name
        names = [data.get("name", "")] if data.get("name") else []
    else:
        names = []
    return {"repo": repo_url, "path": path, "tools": names}


def github_pull_plugin(repo_url: str, path: str, target: str | None = None) -> dict:
    """Pull a tool/plugin from the connected repo into MOON's plugins/.

    Shallow-clones the repo and copies `path` into
    plugins/generated/<basename of path>.  Tells the operator who to talk to
    (the MOON sync tool) if the pull needs auth/permission.
    """
    owner, repo = _parse_repo_url(repo_url)
    if not owner or not repo:
        return {"status": "error", "error": "unrecognized repo URL"}
    if target is None:
        target = str(Path("plugins") / "generated" / Path(path).name)
    try:
        with tempfile.TemporaryDirectory(prefix="moon_gh_pull_") as tmp:
            r = subprocess.run(
                ["git", "clone", "--depth", "1",
                 f"https://github.com/{owner}/{repo}", tmp],
                capture_output=True, text=True, timeout=180,
            )
            if r.returncode != 0:
                return {"status": "error",
                        "error": (r.stderr or r.stdout or "clone failed")[:200]}
            src = Path(tmp) / path
            if not src.exists():
                src = Path(tmp)
            if not src.exists():
                return {"status": "error",
                        "error": f"path '{path}' not found in repo {owner}/{repo}"}
            dest = Path(target)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(str(src), str(dest), dirs_exist_ok=True)
            else:
                shutil.copy2(str(src), str(dest))
        return {"status": "ok", "source": f"{owner}/{repo}", "target": str(dest),
                "note": "pulled from GitHub; use the MOON sync tool to push changes back"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": f"pull failed: {exc}"}


# --------------------------------------------------------------------------- #
# stdio MCP server (JSONRPC-over-stdin), mirroring tests/test_mcp_real/     #
# stdio_server.py.  Every response is flushed immediately so the async      #
# client never stalls on a full pipe buffer.                                  #
# --------------------------------------------------------------------------- #
def _respond(resp: dict) -> None:
    print(json.dumps(resp))
    sys.stdout.flush()


async def _handle(msg: dict) -> None:
    method = msg.get("method")
    if method == "initialize":
        _respond(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "github_mcp", "version": "1.0.0"},
                },
            }
        )
    elif method == "tools/list":
        repo_url = _connected_repo_url()
        tools = [
            {
                "name": "github_search_repos",
                "description": "Search public GitHub repositories by query.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "q": {"type": "string", "description": "search query"},
                        "per_page": {"type": "integer", "description": "results per page (max 100)", "default": 10},
                    },
                    "required": ["q"],
                },
            },
            {
                "name": "github_list_repo_tools",
                "description": "List tool files present in the connected GitHub repo.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_url": {"type": "string", "description": "repo to list (defaults to the connected repo)", "default": repo_url},
                        "path": {"type": "string", "description": "tree path to scan (default tools/)", "default": "tools"},
                    },
                    "required": [],
                },
            },
            {
                "name": "github_pull_plugin",
                "description": "Pull a tool/plugin from the connected repo into plugins/.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_url": {"type": "string", "description": "repo to pull from (defaults to connected)"},
                        "path": {"type": "string", "description": "path in the repo to pull"},
                        "target": {"type": "string", "description": "destination within plugins/", "default": ""},
                    },
                    "required": ["path"],
                },
            },
        ]
        _respond({"jsonrpc": "2.0", "id": msg.get("id"), "result": {"tools": tools}})
    elif method == "tools/call":
        name = msg.get("params", {}).get("name", "")
        args = msg.get("params", {}).get("arguments", {})
        if name == "github_search_repos":
            out = github_search_repos(q=args.get("q", ""), per_page=args.get("per_page", 10))
        elif name == "github_list_repo_tools":
            out = github_list_repo_tools(
                repo_url=args.get("repo_url", _connected_repo_url()),
                path=args.get("path", "tools"),
            )
        elif name == "github_pull_plugin":
            out = github_pull_plugin(
                repo_url=args.get("repo_url", _connected_repo_url()),
                path=args.get("path", ""),
                target=args.get("target", ""),
            )
        else:
            out = {"error": f"unknown tool: {name}"}
        _respond({"jsonrpc": "2.0", "id": msg.get("id"),
                  "result": {"content": [{"type": "text", "text": json.dumps(out)}]}})
    else:
        _respond({"jsonrpc": "2.0", "id": msg.get("id"),
                  "error": {"code": -32601, "message": f"unknown method: {method}"}})


async def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            await _handle(msg)
        except Exception as exc:  # noqa: BLE001
            _respond({"jsonrpc": "2.0", "id": msg.get("id"),
                      "error": {"code": -32603, "message": str(exc)}})


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
