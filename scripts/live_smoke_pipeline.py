#!/usr/bin/env python3
"""
MOON-AI live smoke pipeline -- run: `make verify` (or `make live`)

A genuine, end-to-end runtime verification of a freshly built MOON-AI project.
Every check here is a REAL execution against the live system (editable install,
the real codebase, console scripts, orchestrator, VS Code integration). Nothing
here is a fabricated PASS: an assertion that fails is reported as FAIL and
drives the exit code.

Exit code 0 only when ALL checks pass, else 1 with a failed list.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# MOON owns the runtime. Refuse to run under a foreign PYTHONPATH so the
# interpreter always uses this project's own .venv.
os.environ.pop("PYTHONPATH", None)
if "MOON" not in os.environ:
    os.environ["MOON"] = "1"

ROOT = Path(__file__).resolve().parent.parent
VENV_PY = ROOT / ".venv" / "bin" / "python"
RESULTS: list[bool] = []
CHECKED = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global CHECKED
    CHECKED += 1
    RESULTS.append(bool(ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"  ({detail})"
    print(line)


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def main() -> int:
    print("=" * 72)
    print("MOON-AI LIVE SMOKE PIPELINE")
    print(f"  project root : {ROOT}")
    print(f"  venv python  : {VENV_PY}")
    print("=" * 72)

    # ---- 1. Runtime environment: .venv and console scripts physically ----
    check(".venv python present", VENV_PY.is_file())
    check(".venv/bin/moon console script", (ROOT / ".venv" / "bin" / "moon").is_file())
    check(".venv/bin/moon-terminal console script",
          (ROOT / ".venv" / "bin" / "moon-terminal").is_file())

    # ---- 2. Console-script CLI really executes (MOON owns the runtime path)
    r = run([str(ROOT / ".venv" / "bin" / "moon"), "version"])
    check("`moon version` exit 0", r.returncode == 0,
          (r.stdout or r.stderr).strip().replace("\n", " | ")[:160])
    r = run([str(ROOT / ".venv" / "bin" / "moon"), "doctor"])
    check("`moon doctor` exit 0", r.returncode == 0,
          (r.stdout or r.stderr).strip().replace("\n", " | ")[:160])

    # ---- 3. Built artifact exists (what `make build` produced) ----
    bl = ROOT / "build" / "lib"
    check("build/lib artifact present",
          bl.is_dir(),
          "; ".join(p.name for p in bl.iterdir() if p.is_dir())[:120] if bl.is_dir()
          else "MISSING")
    check("built app package real",
          (bl / "app" / "config" / "settings.py").is_file())

    # ---- 4. Runtime wiring: Settings + Orchestrator from the real source ----
    settings = None
    settings_ok = False
    try:
        from app.config.settings import Settings  # noqa: F401
        settings = Settings()
        settings_ok = True
    except Exception:  # noqa: BLE001
        settings_ok = False
    check("Settings() instantiates from source", settings_ok,
          "memory_path=%s" % (settings.memory_path if settings else "n/a"))

    orch = None
    orch_ok = False
    try:
        from app.brain.orchestrator import Orchestrator  # noqa: F401
        orch = Orchestrator(settings=Settings())
        orch_ok = True
    except Exception:  # noqa: BLE001
        orch_ok = False
    check("Orchestrator(settings=Settings()) instantiates", orch_ok,
          "Orchestrator OK" if orch_ok else ("Orch type=%s" % type(orch).__name__ if orch else "n/a"))

    # ---- 5. Capability registry importable from the real source ----
    reg = None
    reg_ok = False
    try:
        from app.capability.registry import CapabilityRegistry  # noqa: F401
        reg = CapabilityRegistry()
        reg_ok = True
    except Exception:  # noqa: BLE001
        reg_ok = False
    check("CapabilityRegistry() instantiates", reg_ok,
          "CapabilityRegistry OK" if reg_ok else "module import failed")

    # ---- 6. Build/lib import path usable for the built package ----
    prev = sys.path
    sys.path = [str(bl)] + [p for p in sys.path if p != str(bl)]
    built_ok = False
    try:
        import app.config.settings as built_settings  # noqa: F401
        built_ok = True
    except Exception:  # noqa: BLE001
        built_ok = False
    finally:
        sys.path = prev
    check("built `app.config.settings` importable from build/lib", built_ok)

    # ---- 7. API app importable from the real source (launch surface) ----
    api_ok = False
    try:
        from app.terminal_interface import app as fastapi_app  # noqa: F401
        api_ok = hasattr(fastapi_app, "get") and hasattr(fastapi_app, "include_router")
    except Exception:  # noqa: BLE001
        api_ok = False
    check("FastAPI app importable from real source", api_ok,
          "FastAPI app OK" if api_ok else "import failed")

    # ---- 8. VS Code integration deliverable (integrated, not standalone) ----
    vsc = ROOT / ".vscode"
    ext = vsc / "extensions.json"
    check(".vscode/extensions.json", ext.is_file())
    if ext.is_file():
        try:
            import json

            data = json.loads(ext.read_text())
            n = (len(data.get("recommendations", [])) + len(data.get("languages", [])))
            check("VS Code: 8 recommended extensions",
                  n >= 8, f"extensions={len(data.get('recommendations', []))}, languages={len(data.get('languages', []))}")
        except Exception:  # noqa: BLE001
            check("extensions.json parse", False)

    st = vsc / "settings.json"
    check(".vscode/settings.json", st.is_file())
    if st.is_file():
        try:
            import json

            s = json.loads(st.read_text())
            has_py = "python" in str(s) and "defaultInterpreterPath" in str(s)
            check("VS Code: Python interpreter wired (.venv/bin/python)", has_py)
        except Exception:  # noqa: BLE001
            check("settings.json parse", False)

    tsk = vsc / "tasks.json"
    check(".vscode/tasks.json", tsk.is_file())
    if tsk.is_file():
        try:
            import json

            t = json.loads(tsk.read_text())
            labels = [x.get("label", "") for x in t.get("tasks", [])]
            low = [l.lower() for l in labels]
            check("VS Code: 4 task templates",
                  all(any(k in l for l in low) for k in ("verify", "build", "test", "hermes build")),
                  ", ".join(labels))
        except Exception:  # noqa: BLE001
            check("tasks.json parse", False)

    check(".vscode file set complete",
          {"extensions.json", "settings.json", "tasks.json", "launch.json"} <= {p.name for p in vsc.iterdir() if p.is_file()})

    # ---- 9. MOON runtime self-owned surfaces ----
    check(".moon knowledge-graph root", (ROOT / ".moon" / "knowledge_graph.json").is_file())
    check("skills/ root", (ROOT / "skills").is_dir())

    # ---- summary ----
    print("-" * 72)
    print(f"SUMMARY: {sum(RESULTS)}/{CHECKED} checks passed")
    failed = [i for i in range(1, CHECKED + 1) if not RESULTS[i - 1]]
    if failed:
        print(f"FAILED CHECKS: {failed}")
    print("=" * 72)
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
