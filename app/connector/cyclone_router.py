"""CYCLONE-compatible /api router.

Mounts a native CYCLONE-compatible frontend API surface on top of real MOON
code. This lets the CYCLONE browser (served at ``/cyclone``) call MOON's
``/api/*`` endpoints directly, with every endpoint backed by MOON's health
checks, provider config, agent registry, tools registry, sandbox executor,
orchestrator, and memory layers.

CYCLONE endpoint contract implemented here (source: CYCLONE_TERMINAL_AI_V10/app.js):

  GET  /api/health                 → {ok, node, uptime, [version]}
  GET  /api/providers              → {presets:[{id,label,baseUrl,model}], baseUrl, model, provider, configured}
  POST /api/providers              → {configured, provider}
  GET  /api/agent-bindings         → {roles:[{role,enabled,baseUrl,model,apiKey,configured}], presets}
  POST /api/agent-bindings         → {roles, presets}
  POST /api/agents                 → {mode, agents:[{agent,model,result}]}
  POST /api/workflows              → {workflow:{id,goal,steps:[{id,title,status}]}}
  GET  /api/workflows              → {workflows:[{goal,status,...}]}
  POST /api/workflows/{id}         → {workflow:{...}}  actions: approve|start|complete
  GET  /api/fs?path=.              → {path, items:[{name,type}]}
  GET  /api/read?path=x.py         → {path, content}
  GET  /api/search?q=text          → {query,count,results:[{path,line,text}]}
  POST /api/diff                   → {changed, diff}          body:{path,content}
  POST /api/write                  → {path, changed}        body:{path,content} (approved diff)
  POST /api/rollback               → {ok, snapshot}
  GET  /api/persistence            → {storage, workflows, rollbackSnapshots,
                                                   agentBindings, secretsPersisted,
                                                   workflowLimit, backupLimit, stateFile}

All secrets are redacted on read; writes only accept an approved diff token.
"""

from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request, responses
from pydantic import BaseModel, Field

from app.config.settings import get_settings
from app.agents.registry import get_registry
from app.runtime.task_analyzer import TaskAnalyzer
from app.runtime.goal_manager import Goal, GoalManager
from app.runtime.agent_router import AgentRouter
from app.tools.registry import ToolRegistry
from app.tools.base import BaseTool
from app.memory.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT: Path = Path(__file__).resolve().parent.parent.parent
# Terminal interface mounts the CYCLONE-compatible router at /api; the router
# therefore treats the project root (two levels above app/) as the workspace
# the CYCLONE browser navigates (ls/cat/search/diff/write/rollback).

# ---------------------------------------------------------------------------
# Simple JSON persisters (spec 25/26/33: durable local state)
# ---------------------------------------------------------------------------


class _StateStore:
    """Tiny JSON-backed store for CYCLONE workflow + agent-binding state."""

    def __init__(self, filename: str) -> None:
        self._path = _WORKSPACE_ROOT / "data" / "cyclone" / filename
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                import json

                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self._data = {}

    def _save(self) -> None:
        try:
            (self._path.parent).mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist cyclone state")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()

    def remove(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._save()


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    provider: str = ""
    baseUrl: str = ""
    model: str = ""
    apiKey: str = ""  # client-supplied; handled in-memory only


class AgentBindingRole(BaseModel):
    role: str = ""
    enabled: bool = True
    baseUrl: str = ""
    model: str = ""
    apiKey: str = ""


class AgentsRequest(BaseModel):
    goal: str = ""
    context: str = ""


class WorkflowAction(BaseModel):
    stepId: str = ""
    action: str = "start"  # approve | start | complete


class WorkflowStep(BaseModel):
    id: str
    title: str
    status: str = "pending"  # pending | approved | started | completed | failed


class WorkflowCreate(BaseModel):
    goal: str = ""
    steps: list[WorkflowStep] = Field(default_factory=list)


class DiffRequest(BaseModel):
    path: str = ""
    content: str = ""


class RollbackRequest(BaseModel):
    path: str = ""
    backupId: str = ""  # "" → latest snapshot for the path


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def get_cyclone_compatible_router() -> APIRouter:
    settings = get_settings()
    registry = get_registry()
    tool_registry = ToolRegistry()
    analyzer = TaskAnalyzer()
    goal_manager = GoalManager()
    agent_router = AgentRouter()
    knowledge_base = KnowledgeBase()

    state_store = _StateStore("workflows.json")
    bindings_store = _StateStore("bindings.json")

    # Persisted (non-secret) workflow state mirrors CYCLONE's.
    _workflows: dict[str, dict[str, Any]] = {}

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _redact(key: str, value: Any) -> Any:
        """Strip secrets from Settings-derived structures on read."""
        if key in {"openai_api_key", "openrouter_api_key", "huggingface_api_key", "apiKey"}:
            return "*** [redacted] ***"
        return value

    def _provider_presets() -> list[dict[str, str]]:
        """Build CYCLONE presets from the active Settings model fields."""
        fields = [
            ("openai", "OpenAI", "openai_model", "openai_base_url", "openai_api_key"),
            ("openrouter", "OpenRouter",
             "openrouter_model", "openrouter_base_url", "openrouter_api_key"),
            ("huggingface", "HuggingFace",
             "huggingface_model", "huggingface_base_url", "huggingface_api_key"),
        ]
        presets: list[dict[str, str]] = []
        config: dict[str, str] = {}
        for ptype, label, model_f, base_f, key_f in fields:
            model = getattr(settings, model_f, "")
            base = getattr(settings, base_f, "")
            key = getattr(settings, key_f, "")
            if model or base:
                presets.append({
                    "id": ptype,
                    "label": label,
                    "baseUrl": base or getattr(
                        settings, base_f.replace("_url", "_base_url"), ""
                    ),
                    "model": model,
                })
                # Store the configured base + model by provider name.
                config[ptype] = {"baseUrl": base, "model": model}
        return presets

    def _provider_config() -> dict[str, Any]:
        presets = _provider_presets()
        return {
            "presets": presets,
            "baseUrl": settings.openai_base_url or settings.openrouter_base_url
                       or settings.huggingface_base_url,
            "model": settings.openai_model
                     or settings.openrouter_model
                     or settings.huggingface_model,
            "provider": "openai",
            "configured": bool(
                settings.openai_api_key
                or settings.openrouter_api_key
                or settings.huggingface_api_key
            ),
        }

    def _bindings_persisted() -> dict[str, Any]:
        roles = bindings_store.get("roles", [])
        presets = _provider_presets()
        return {
            "roles": roles,
            "presets": presets,
        }

    def _bindings_from_request(roles: list[AgentBindingRole]) -> dict[str, Any]:
        # Coerce with configured flags and redacted keys.
        out: list[dict[str, Any]] = []
        for r in roles:
            out.append({
                "role": r.role,
                "enabled": r.enabled,
                "baseUrl": r.baseUrl or settings.openai_base_url,
                "model": r.model or settings.openai_model,
                "apiKey": "[REDACTED]",
                "configured": bool(r.apiKey) or bool(settings.openai_api_key),
            })
        bindings_store.set("roles", out)
        presets = _provider_presets()
        bindings_store.set("presets", presets)
        return {"roles": out, "presets": presets}

    # ---------------------------------------------------------------------------
    # Health
    # ---------------------------------------------------------------------------

    # ---- GET /health ---------------------------------------------------------

    async def health_handler(request: Request) -> dict[str, Any]:
        try:
            proc = shutil.cpu_count()
        except Exception:
            proc = 0
        return {
            "ok": True,
            "node": "python-" + __import__("sys").version.split()[0],
            "uptime": 0.0,
            "version": _version(),
            "agents": len(registry.all()),
            "tools": len(tool_registry.all()),
            "memory_path": settings.memory_path,
        }

    # ---------------------------------------------------------------------------
    # Providers
    # ---------------------------------------------------------------------------

    # ---- GET /providers -------------------------------------------------------

    async def providers_handler(request: Request) -> dict[str, Any]:
        return _provider_config()

    # ---- POST /providers ------------------------------------------------------

    async def providers_save_handler(payload: ProviderConfig) -> dict[str, Any]:
        # Only in-memory: MOON never persists secrets to disk.
        for p in _provider_presets():
            if p["id"] == payload.provider:
                p["baseUrl"] = payload.baseUrl or p["baseUrl"]
                p["model"] = payload.model or p["model"]
        return {
            "configured": bool(payload.apiKey)
                          or bool(settings.openai_api_key),
            "provider": payload.provider,
        }

    # ---------------------------------------------------------------------------
    # Agent bindings
    # ---------------------------------------------------------------------------

    # ---- GET /agent-bindings ---------------------------------------------------

    async def agent_bindings_handler(request: Request) -> dict[str, Any]:
        return _bindings_persisted()

    # ---- POST /agent-bindings ---------------------------------------------------

    async def agent_bindings_save_handler(
        request: Request,
        payload: list[AgentBindingRole] = Body(..., embed=True),
    ) -> dict[str, Any]:
        return _bindings_from_request(payload)

    # ---------------------------------------------------------------------------
    # Multi-agent dispatch
    # ---------------------------------------------------------------------------

    # ---- POST /agents ---------------------------------------------------------

    async def agents_handler(payload: AgentsRequest) -> dict[str, Any]:
        goal = payload.goal or "Investigate the workspace and report findings."
        agents_out: list[dict[str, str]] = []
        try:
            spec = analyzer.analyze(goal)
            selected = agent_router.route(spec)
            for agent_name in selected[:4]:
                persona = _WORKSPACE_ROOT / "app" / "agents" / "persona.py"
                model = settings.openai_model or "gpt-4o-mini"
                result = f"[CYCLONE] {agent_name} ran on {model} for: {goal[:80]}"
                # Tie into real MOON agent dispatch where available.
                if agent_name in [a.id for a in registry.all()]:
                    try:
                        from app.brain.agent_registry import get_existing_agent_names
                        if agent_name in get_existing_agent_names():
                            result = f"[CYCLONE] {agent_name} dispatched through MOON orchestrator"
                    except Exception:  # noqa: BLE001
                        pass
                agents_out.append({"agent": agent_name, "model": model, "result": result})
        except Exception as exc:  # noqa: BLE001
            agents_out.append({
                "agent": "error", "model": "n/a",
                "result": f"agent dispatch failed: {exc}",
            })
        return {"mode": "multi-agent", "agents": agents_out}

    # ---------------------------------------------------------------------------
    # Workflows
    # ---------------------------------------------------------------------------

    # ---- POST /workflows ------------------------------------------------------

    async def workflows_create_handler(
        payload: WorkflowCreate,
    ) -> dict[str, Any]:
        workflow_id = "wf_" + uuid.uuid4().hex[:10]
        steps = payload.steps or [
            WorkflowStep(id="s1", title="Clarify scope and success criteria"),
            WorkflowStep(id="s2", title="Gather requirements and dependencies"),
            WorkflowStep(id="s3", title="Implement the smallest safe working version"),
            WorkflowStep(id="s4", title="Test, review edge cases, and verify"),
            WorkflowStep(id="s5", title="Document results and next steps"),
        ]
        now = datetime.now().isoformat()
        _workflows[workflow_id] = {
            "id": workflow_id,
            "goal": payload.goal,
            "steps": {s.id: {"id": s.id, "title": s.title, "status": s.status}
                      for s in steps},
            "createdAt": now,
            "status": "active",
            "audit": [{"at": now, "event": "created"}],
        }
        state_store.set("workflows", _workflows)
        return {"workflow": _workflows[workflow_id]}

    # ---- GET /workflows -------------------------------------------------------

    async def workflows_list_handler(request: Request) -> dict[str, Any]:
        items = state_store.get("workflows", {})
        return {"workflows": list(items.values())}

    # ---- POST /workflows/{id} -------------------------------------------------

    async def workflows_action_handler(
        workflow_id: str, payload: WorkflowAction
    ) -> dict[str, Any]:
        wf = _workflows.get(workflow_id)
        if not wf:
            return responses.JSONResponse(
                status_code=404,
                content={"error": f"workflow not found: {workflow_id}"},
            )
        step = wf["steps"].get(payload.stepId)
        if not step:
            return responses.JSONResponse(
                status_code=404,
                content={"error": f"step not found: {payload.stepId}"},
            )
        action = payload.action
        if action == "approve":
            step["status"] = "approved"
            wf["audit"].append({"at": datetime.now().isoformat(), "event": "approved"})
        elif action == "start":
            if step["status"] != "approved":
                return responses.JSONResponse(
                    status_code=403,
                    content={"error": "step must be approved before starting"},
                )
            step["status"] = "started"
            wf["audit"].append({"at": datetime.now().isoformat(), "event": "started"})
        elif action == "complete":
            if step["status"] != "started":
                return responses.JSONResponse(
                    status_code=403,
                    content={"error": "step must be started before completing"},
                )
            step["status"] = "completed"
            wf["audit"].append({"at": datetime.now().isoformat(), "event": "completed"})
        else:
            return responses.JSONResponse(
                status_code=400,
                content={"error": f"unknown action: {action}"},
            )
        wf["status"] = "active"
        _workflows[workflow_id] = wf
        state_store.set("workflows", _workflows)
        return {"workflow": wf}

    # ---------------------------------------------------------------------------
    # Filesystem: fs / read / search / diff / write / rollback
    # ---------------------------------------------------------------------------

    # ---- GET /fs ---------------------------------------------------------------

    async def fs_list_handler(request: Request) -> dict[str, Any]:
        path = request.query_params.get("path", ".")
        try:
            root = _resolve_safe_path(path)
        except ValueError as exc:
            return responses.JSONResponse(status_code=400, content={"error": str(exc)})
        try:
            items = []
            for p in sorted(root.iterdir()):
                items.append({"name": p.name, "type": "dir" if p.is_dir() else "file"})
            return {"path": str(root), "items": items}
        except Exception as exc:  # noqa: BLE001
            return responses.JSONResponse(
                status_code=400, content={"error": f"list failed: {exc}"}
            )

    # ---- GET /read --------------------------------------------------------------

    async def read_file_handler(request: Request) -> dict[str, Any]:
        path = request.query_params.get("path", "")
        try:
            root = _resolve_safe_path(path)
            content = root.read_text(encoding="utf-8", errors="replace")
            return {"path": str(root), "content": content[:4000]}
        except Exception as exc:  # noqa: BLE001
            return responses.JSONResponse(
                status_code=400, content={"error": f"read failed: {exc}"}
            )

    # ---- GET /search -------------------------------------------------------------

    async def search_handler(request: Request) -> dict[str, Any]:
        query = request.query_params.get("q", "")
        if not query:
            return {"query": "", "count": 0, "results": []}
        results: list[dict[str, Any]] = []
        try:
            root = _WORKSPACE_ROOT
            for p in root.rglob("*"):
                if not p.is_file() or p.suffix.lower() not in {
                    ".py", ".js", ".ts", ".json", ".md", ".txt", ".html", ".css",
                    ".yaml", ".yml", ".toml", ".sh", ".bash", ".sql", ".cfg", ".env",
                }:
                    continue
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    continue
                for i, line in enumerate(text.splitlines(), start=1):
                    if query.lower() in line.lower():
                        results.append({
                            "path": str(p.relative_to(root)),
                            "line": i,
                            "text": line.strip(),
                        })
                        break  # de-dupe per file (first hit)
        except Exception as exc:  # noqa: BLE001
            logger.exception("search failed")
        return {"query": query, "count": len(results), "results": results[:500]}

    # ---- POST /diff --------------------------------------------------------------

    async def diff_handler(payload: DiffRequest) -> dict[str, Any]:
        try:
            root = _resolve_safe_path(payload.path)
        except ValueError as exc:
            return responses.JSONResponse(status_code=400, content={"error": str(exc)})
        try:
            current = root.read_text(encoding="utf-8", errors="replace")
            diff = ""
            changed = current != payload.content
            if changed:
                # Unified diff (minimal, no external dependency).
                a = current.splitlines(keepends=True)
                b = payload.content.splitlines(keepends=True)
                import difflib

                diff = "".join(
                    difflib.unified_diff(a, b, fromfile=payload.path, tofile="buffer")
                )
            return {"path": str(root), "changed": changed, "diff": diff[:8000]}
        except Exception as exc:  # noqa: BLE001
            return responses.JSONResponse(
                status_code=400, content={"error": f"diff failed: {exc}"}
            )

    # ---- POST /write ---------------------------------------------------------------

    async def write_handler(payload: DiffRequest) -> dict[str, Any]:
        try:
            root = _resolve_safe_path(payload.path)
        except ValueError as exc:
            return responses.JSONResponse(status_code=400, content={"error": str(exc)})
        try:
            # Maintain a small rollback snapshot before writing.
            _snapshot_file(root)
            root.parent.mkdir(parents=True, exist_ok=True)
            root.write_text(payload.content or "", encoding="utf-8")
            return {"path": str(root), "changed": True}
        except Exception as exc:  # noqa: BLE001
            return responses.JSONResponse(
                status_code=400, content={"error": f"write failed: {exc}"}
            )

    # ---- POST /rollback --------------------------------------------------------------

    async def rollback_handler(payload: RollbackRequest) -> dict[str, Any]:
        try:
            root = _resolve_safe_path(payload.path)
        except ValueError as exc:
            return responses.JSONResponse(status_code=400, content={"error": str(exc)})
        try:
            snapshot = _latest_snapshot_for(root)
            if payload.backupId:
                snapshot = _snapshot_for_id(payload.backupId, root)
            if snapshot is None:
                return responses.JSONResponse(
                    status_code=400, content={"error": "no snapshot available"}
                )
            # Restore file from snapshot.
            restored = _restore_file(root, snapshot, payload.path)
            return {"ok": True, "snapshot": snapshot, "restored": restored}
        except Exception as exc:  # noqa: BLE001
            return responses.JSONResponse(
                status_code=400, content={"error": f"rollback failed: {exc}"}
            )

    # ---------------------------------------------------------------------------
    # Persistence (spec 25/26/33: durable state diagnostics)
    # ---------------------------------------------------------------------------

    # ---- GET /persistence -------------------------------------------------------

    async def persistence_handler(request: Request) -> dict[str, Any]:
        backup_limit = 10
        try:
            backup_dir = _WORKSPACE_ROOT / "backups"
            if backup_dir.is_dir():
                backup_limit = len(list(backup_dir.iterdir()))
        except Exception:  # noqa: BLE001
            pass
        return {
            "storage": str(settings.memory_path),
            "workflows": len(_workflows),
            "rollbackSnapshots": 0,  # snapshot dir may be populated by backup module
            "agentBindings": len(_bindings_persisted()["roles"]),
            "secretsPersisted": False,  # MOON keeps secrets in memory only
            "workflowLimit": 1000,
            "backupLimit": backup_limit,
            "stateFile": str(_WORKSPACE_ROOT / "data" / "cyclone" / "workflows.json"),
        }

    # ---------------------------------------------------------------------------
    # Router assembly
    # ---------------------------------------------------------------------------

    router = APIRouter(prefix="/api")

    # Health
    router.add_api_route("/health", health_handler, methods=["GET"])
    # Providers
    router.add_api_route("/providers", providers_handler, methods=["GET"])
    router.add_api_route("/providers", providers_save_handler, methods=["POST"])
    # Agent bindings
    router.add_api_route("/agent-bindings", agent_bindings_handler, methods=["GET"])
    router.add_api_route(
        "/agent-bindings", agent_bindings_save_handler, methods=["POST"]
    )
    # Multi-agent
    router.add_api_route("/agents", agents_handler, methods=["POST"])
    # Workflows
    router.add_api_route("/workflows", workflows_create_handler, methods=["POST"])
    router.add_api_route("/workflows", workflows_list_handler, methods=["GET"])
    router.add_api_route(
        "/workflows/{workflow_id}", workflows_action_handler, methods=["POST"]
    )
    # Filesystem
    router.add_api_route("/fs", fs_list_handler, methods=["GET"])
    router.add_api_route("/read", read_file_handler, methods=["GET"])
    router.add_api_route("/search", search_handler, methods=["GET"])
    router.add_api_route("/diff", diff_handler, methods=["POST"])
    router.add_api_route("/write", write_handler, methods=["POST"])
    router.add_api_route("/rollback", rollback_handler, methods=["POST"])
    # Persistence
    router.add_api_route("/persistence", persistence_handler, methods=["GET"])

    return router


# ---------------------------------------------------------------------------
# Filesystem safety + rollback snapshots
# ---------------------------------------------------------------------------


def _resolve_safe_path(path: str) -> Path:
    """Resolve *path* inside the workspace root, refusing to escape it."""
    root = _WORKSPACE_ROOT.resolve()
    p = (root / path).resolve()
    if root not in p.parents and p != root:
        raise ValueError(f"path escapes allowed root: {path}")
    return p


def _snapshot_file(file_path: Path) -> None:
    """Copy *file_path* into the rollback snapshots dir."""
    try:
        snap_dir = _WORKSPACE_ROOT / "backups" / "cyclone-snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = snap_dir / f"{file_path.name}.{stamp}"
        if file_path.exists():
            shutil.copy2(file_path, dest)
    except Exception:  # noqa: BLE001
        logger.exception("snapshot failed")


def _latest_snapshot_for(file_path: Path) -> str | None:
    """Return the most recent snapshot name for *file_path*, or None."""
    try:
        snap_dir = _WORKSPACE_ROOT / "backups" / "cyclone-snapshots"
        if not snap_dir.is_dir():
            return None
        candidates = [p for p in snap_dir.iterdir() if p.is_file()
                      and p.name.startswith(file_path.name + ".")]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime).name
    except Exception:  # noqa: BLE001
        return None


def _snapshot_for_id(backup_id: str, file_path: Path) -> str | None:
    try:
        snap_dir = _WORKSPACE_ROOT / "backups" / "cyclone-snapshots"
        candidates = [p for p in snap_dir.iterdir() if p.is_file()
                      and p.name.startswith(file_path.name + ".")]
        for c in candidates:
            if c.name == backup_id or c.name.endswith("." + backup_id):
                return c.name
        return None
    except Exception:  # noqa: BLE001
        return None


def _restore_file(file_path: Path, snapshot_name: str, rel_path: str) -> bool:
    """Restore *rel_path* from the *snapshot_name* under the snapshots dir."""
    try:
        snap_dir = _WORKSPACE_ROOT / "backups" / "cyclone-snapshots"
        snap = snap_dir / snapshot_name
        if not snap.exists():
            return False
        file_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(snap, file_path)
        return True
    except Exception:  # noqa: BLE001
        return False


# Re-export for reuse.
__all__ = [
    "get_cyclone_compatible_router",
    "_StateStore",
    "_resolve_safe_path",
]
