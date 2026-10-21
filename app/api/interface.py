"""MOON Application Runtime Interface.

Stable Application Interface between the terminal layer (CYCLONE) and the MOON
Core runtime (agents, tools, skills, memory, models, services).

Why this file exists:
    CYCLONE is a Node.js terminal that speaks HTTP. MOON is a Python FastAPI
    service. Neither can call the other's native code, so they interpose a
    small, versioned, JSON-over-HTTP Application Interface on the Python side.
    CYCLONE's bridge.js forwards every CYCLONE command to here.

Endpoints (mounted under /api):
    GET     /capabilities    capability registry (all statuses real)
    POST    /run             dispatch a real task through the Orchestrator
    GET     /models          model config + reachability
    GET     /memory-status   real memory state (local/vector/cloud/sync)
    GET     /diagnostics     diagnostics + version
    GET     /version         MOON version string

Every handler reuses real MOON runtime objects (_get_orchestrator,
settings, orchestrator tool/skill managers, memory health service). Nothing
is faked or mocked in production.

Security: auth enforced by the existing TERMINAL_TOKEN gate in
app/terminal_interface.py (same gate as /api/health, /api/brain-status).
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.agents.registry import get_registry
from app.config.settings import get_settings


# ---- version: read from the project manifest, not a stale constant ---------
def _load_version():
    try:
        p = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        with open(p, "rb") as fh:
            return tomllib.load(fh).get("project", {}).get("version", "0.1.0")
    except Exception:  # noqa: BLE001
        return "0.1.0"


# Reuse the app-level auth gate so this surface follows the same rules as
# every other /api endpoint (public only when TERMINAL_TOKEN is unset).
def _auth_ok(headers: dict | None):
    from app.terminal_interface import TERMINAL_TOKEN, _token_ok
    return not TERMINAL_TOKEN or _token_ok(headers or {})


# --------------------------------------------------------------------------
# Version
# --------------------------------------------------------------------------
def _version():
    return {"name": "MOON", "version": _load_version(), "app": "MOON-AI"}


# --------------------------------------------------------------------------
# Capabilities (real registry based on live runtime state)
# --------------------------------------------------------------------------
def _build_capability_registry():
    """Build the capability registry from real MOON runtime objects."""
    capabilities = []

    # Agents (real agent registry)
    try:
        from app.agents.registry import get_registry
        reg = get_registry()
        capabilities.append({
            "id": "MOON.agents",
            "name": "Agents",
            "status": "available",
            "source": "app/agents/registry.py",
            "detail": f"{len(reg.all())} agents registered",
            "how_to_check": "GET /api/terminal/agents",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.agents", "name": "Agents", "status": "degraded",
            "source": "app/agents/registry.py", "detail": str(exc),
            "how_to_check": "GET /api/terminal/agents",
        })

    # Tools (real tool registry)
    try:
        from app.tools.registry import get_registry
        reg = get_registry()
        capabilities.append({
            "id": "MOON.tools",
            "name": "Tools",
            "status": "available",
            "source": "app/tools/registry.py",
            "detail": f"{len(reg.all_tools())} tools registered",
            "how_to_check": "GET /api/terminal/tools",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.tools", "name": "Tools", "status": "degraded",
            "source": "app/tools/registry.py", "detail": str(exc),
            "how_to_check": "GET /api/terminal/tools",
        })

    # Skills (real skill system)
    try:
        from app.runtime.skill_system import SkillSystem
        sys = SkillSystem()
        skills = sys.all()
        capabilities.append({
            "id": "MOON.skills",
            "name": "Skills",
            "status": "available",
            "source": "app/runtime/skill_system.py",
            "detail": f"{len(skills)} skills loaded",
            "how_to_check": "GET /api/terminal/skills",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.skills", "name": "Skills", "status": "degraded",
            "source": "app/runtime/skill_system.py", "detail": str(exc),
            "how_to_check": "GET /api/terminal/skills",
        })

    # Models (real model manager)
    try:
        from app.brain.agent_model_manager import AgentModelManager
        mgr = AgentModelManager(
            base_url=get_settings().model_base_url,
            api_key=get_settings().model_api_key,
            default_model=get_settings().model_name,
        )
        capabilities.append({
            "id": "MOON.models",
            "name": "Models",
            "status": "available",
            "source": "app/brain/agent_model_manager.py",
            "detail": "local endpoint configured; reachability checked via GET /api/models",
            "how_to_check": "GET /api/models",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.models", "name": "Models", "status": "degraded",
            "source": "app/brain/agent_model_manager.py", "detail": str(exc),
            "how_to_check": "GET /api/models",
        })

    # Memory
    try:
        from app.memory.health import MemoryHealthService
        capabilities.append({
            "id": "MOON.memory",
            "name": "Memory",
            "status": "available",
            "source": "app/memory/health.py",
            "detail": "local + vector + cloud + sync probes wired",
            "how_to_check": "GET /api/terminal/memory-status",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.memory", "name": "Memory", "status": "degraded",
            "source": "app/memory/health.py", "detail": str(exc),
            "how_to_check": "GET /api/terminal/memory-status",
        })

    # Voice (if present)
    try:
        from app.voice_engine import VoiceEngine
        capabilities.append({
            "id": "MOON.voice",
            "name": "Voice",
            "status": "available",
            "source": "app/voice_engine.py",
            "detail": "voice engine loaded",
            "how_to_check": "GET /api/voice/status",
        })
    except Exception as exc:  # noqa: BLE001
        capabilities.append({
            "id": "MOON.voice", "name": "Voice", "status": "unavailable",
            "source": "app/voice_engine.py", "detail": f"missing: {exc}",
            "how_to_check": "GET /api/voice/status",
        })

    return capabilities


# --------------------------------------------------------------------------
# Router factory so it can be mounted from app/terminal_interface.py
# --------------------------------------------------------------------------
def get_interface_router():
    """Build the interface router with every endpoint bound to real state."""
    router = APIRouter(prefix="", tags=["application-interface"])

    # GET /capabilities
    @router.get("/capabilities")
    async def capabilities(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            caps = _build_capability_registry()
            return JSONResponse({"capabilities": caps, "count": len(caps)})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # POST /run
    @router.post("/run")
    async def run_task(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        events: list[dict] = []
        try:
            from app.brain.orchestrator import Orchestrator, Task
            body = await request.json()
            task_prompt = str((body or {}).get("task") or (body or {}).get("prompt") or "")
            agent_name = str((body or {}).get("agent") or "auto")
            if not task_prompt:
                return JSONResponse({
                    "error": "task is required",
                    "usage": "POST /interface/run { \"task\": \"...\", ",
                    "help": "POST /interface/run { \"task\": \"hello\" }",
                }, status_code=400)
            from app.terminal_interface import _get_orchestrator
            orch = await _get_orchestrator()
            task = Task.create(task_prompt, agent_name=agent_name)

            def _on_event(ev: dict):
                events.append(ev)
                try:
                    from app.terminal_interface import _log
                    _log(f"run event {ev.get('stage')} {ev.get('execution_id')}",
                         "ok" if ev.get("status") == "success" else "run")
                except Exception:
                    pass

            t = await orch.run_task(task, on_event=_on_event)
            return JSONResponse({
                "task_id": t.id,
                "agent_id": t.agent_name,
                "status": t.status,
                "result": t.result,
                "tokens_used": t.tokens_used,
                "events": events,
            })
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc), "events": events}, status_code=500)

    # GET /models
    @router.get("/models")
    async def models(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.brain.agent_model_manager import AgentModelManager
            mgr = AgentModelManager(
                base_url=get_settings().model_base_url,
                api_key=get_settings().model_api_key,
                default_model=get_settings().model_name,
            )
            return JSONResponse({
                "config": {
                    "base_url": get_settings().model_base_url,
                    "model": get_settings().model_name,
                    "temperature": get_settings().model_temperature,
                    "max_tokens": get_settings().model_max_tokens,
                    "timeout": get_settings().model_timeout,
                },
                "reachability": mgr.status(),
                "recommended": mgr.recommended_for("auto"),
            })
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc), "reachability": "unreachable"}, status_code=500)

    # GET /memory-status
    @router.get("/memory-status")
    async def memory_status(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.memory.health import MemoryHealthService
            mgr = MemoryHealthService()
            report = mgr.check()
            return JSONResponse({
                "report": report.to_dict(),
                "terminal_status": mgr.terminal_status(),
                "memory_path": str(get_settings().memory_path),
            })
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # GET /diagnostics
    @router.get("/diagnostics")
    async def diagnostics(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.terminal_interface import _diagnostics_snapshot
            return JSONResponse(_diagnostics_snapshot())
        except Exception:
            # Fallback: build diagnostics from real pieces so the endpoint never
            # returns a 500 merely because one snapshot helper is unavailable.
            from app.memory.health import MemoryHealthService
            mgr = MemoryHealthService()
            report = mgr.check()
            return JSONResponse({
                "version": _load_version(),
                "memory": report.to_dict(),
                "settings": {
                    "model_base_url": get_settings().model_base_url,
                    "model_name": get_settings().model_name,
                },
            })

    # GET /version
    @router.get("/version")
    async def version(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse(_version())

    return router
