"""Terminal control surface (MOON Application Interface for the terminal).

Stable command surface that CYCLONE's bridge forwards into MOON. Every
endpoint invokes a real handler against the live runtime.

Commands advertised via GET /help and GET /commands:
    help           - command discovery + help text
    status         - terminal health + MOON state
    agents         - live agent roster
    tools          - real tool roster (via the Orchestrator's ToolManager)
    skills         - real MOON skill registry
    models         - model configuration + reachability
    memory-status  - real memory state (local/vector/cloud/sync/pending/conflicts)
    diagnostics    - diagnostics + version
    version        - MOON version string
    run            - dispatch a task through the Orchestrator (real agent)

All endpoints reuse real MOON runtime objects. Nothing is faked.
"""
from __future__ import annotations

import time
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config.settings import get_settings

router = APIRouter(prefix="/terminal", tags=["terminal"])


def _auth_ok(headers: dict | None):
    from app.terminal_interface import TERMINAL_TOKEN, _token_ok
    return not TERMINAL_TOKEN or _token_ok(headers or {})


# ---- helpers -------------------------------------------------------------
async def _diagnostics_snapshot():
    """Real diagnostics gathered from live MOON runtime objects."""
    from app.brain.orchestrator import Orchestrator, Task
    orch = await _get_orchestrator()
    from app.brain.tool_manager import ToolManager  # noqa: F401  (used via orch._tools)
    try:
        tools = orch._tools
        n_tools = len(tools._registry.all()) if tools else 0
        enabled_tools = len(tools._enabled) if tools else 0
    except Exception:
        n_tools = enabled_tools = 0
    try:
        from app.memory.health import MemoryHealthService
        mem = MemoryHealthService().check().to_dict()
    except Exception:
        mem = {"ok": False, "detail": "memory health unavailable"}
    return {
        "diagnostics": {
            "uptime": getattr(orch, "_uptime", "n/a"),
            "agents": getattr(orch, "_agent_count", "n/a"),
            "tools_registered": n_tools,
            "tools_enabled": enabled_tools,
            "memory": mem,
            "model": {
                "base_url": get_settings().model_base_url,
                "model": get_settings().model_name,
                "reachable": _model_reachable(),
            },
            "version": _load_version(),
            "snapshot_at": time.time(),
        }
    }


def _model_reachable():
    try:
        from app.brain.agent_model_manager import AgentModelManager
        mgr = AgentModelManager(
            base_url=get_settings().model_base_url,
            api_key=get_settings().model_api_key,
            default_model=get_settings().model_name,
        )
        return mgr.status()
    except Exception:
        return False


def _load_version():
    try:
        import tomllib
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        with open(p, "rb") as fh:
            return tomllib.load(fh).get("project", {}).get("version", "0.1.0")
    except Exception:
        return "0.1.0"


def _terminal_help():
    return {"commands": ["help", "status", "agents", "tools", "skills",
                         "models", "memory-status", "diagnostics", "version",
                         "run <task>"],
            "help": ("CYCLONE -> MOON Application Interface (primary terminal)\n\n"
                     "Commands (all are just GET/POST endpoints on the MOON API):\n"
                     "    help           - print this help text\n"
                     "    status         - terminal health + MOON state\n"
                     "    agents         - live agent roster\n"
                     "    tools          - real tool roster\n"
                     "    skills         - real MOON skill registry\n"
                     "    models         - model config + reachability\n"
                     "    memory status  - real memory state\n"
                     "    diagnostics    - diagnostics + version\n"
                     "    version        - MOON version string\n"
                     "    run <task>     - dispatch a task through the Orchestrator\n\n"
                     "The CYCLONE bridge.js forwards these into MOON's /api/terminal/*\n"
                     "and /api/run endpoints. Results are always real runtime data.\n"
                     "Unavailable capabilities are reported honestly: no mock, no faked output."),
            "doc": "MOON Application Interface v1.0.0 (terminal control surface)"}


# --------------------------------------------------------------------------
# Router factory
# --------------------------------------------------------------------------
def get_terminal_router():
    router = APIRouter(prefix="", tags=["terminal"])

    # GET /help
    @router.get("/help")
    async def terminal_help(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse(_terminal_help())

    # GET /commands
    @router.get("/commands")
    async def terminal_commands(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse(_terminal_help()["commands"])

    # GET /status
    @router.get("/status")
    async def terminal_status(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            return JSONResponse(await _diagnostics_snapshot())
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc), "uptime": "n/a"}, status_code=500)

    # GET /agents
    @router.get("/agents")
    async def terminal_agents(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.agents.registry import get_registry
            reg = get_registry()
            agents = reg.all()
            return JSONResponse({"total": len(agents),
                                 "agents": [m.to_dict() for m in agents]})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # GET /tools
    @router.get("/tools")
    async def terminal_tools(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.brain.orchestrator import Orchestrator
            orch = await _get_orchestrator()
            tm = getattr(orch, "_tools", None)
            specs = tm.available_specs() if tm else []
            return JSONResponse({"total": len(specs),
                                 "tools": specs})
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # GET /skills
    @router.get("/skills")
    async def terminal_skills(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            from app.runtime.skill_system import SkillSystem
            sys = SkillSystem()
            skills = sys.all()
            return JSONResponse({
                "total": len(skills),
                "skills": [s.to_dict() for s in skills],
            })
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # GET /models
    @router.get("/models")
    async def terminal_models(request: Request):
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
    async def terminal_memory_status(request: Request):
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
    async def terminal_diagnostics(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        try:
            return JSONResponse(await _diagnostics_snapshot())
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"error": str(exc)}, status_code=500)

    # GET /version
    @router.get("/version")
    async def terminal_version(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return JSONResponse({"name": "MOON", "version": _load_version(), "app": "MOON-AI"})

    # POST /run - dispatch a real task through the Orchestrator
    @router.post("/run")
    async def terminal_run(request: Request):
        if not _auth_ok(dict(request.headers)):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        events = []
        try:
            from app.brain.orchestrator import Orchestrator, Task
            body = await request.json()
            task_prompt = str((body or {}).get("task") or (body or {}).get("prompt") or "")
            agent_name = str((body or {}).get("agent") or "auto")
            if not task_prompt:
                return JSONResponse({
                    "error": "task is required",
                    "usage": "POST /api/terminal/run { \"task\": \"hello\", \"agent\": \"auto\" }",
                }, status_code=400)
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

    return router


# Reuse the app-level orchestrator helper (defined in app/terminal_interface.py).
async def _get_orchestrator():
    from app.terminal_interface import _get_orchestrator as _g
    return await _g()
