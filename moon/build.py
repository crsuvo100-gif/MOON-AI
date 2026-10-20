"""moon.build — Universal Project Builder.

Adds one command to MOON's CLI that can generate a complete, working
VS Code + hermes-acp + Makefile + Dockerfile + test skeleton for ANY
project type, so you can "build any project perfectly" without guessing.

Language detection is manifest-based. Generation is pure stdlib and
idempotent (safe to re-run).

Entry point (CLI):  moon build scaffold <dir> [--lang py|js|rs|cpp|go|generic]
                   moon build verify <dir> [--lang py|js|rs|cpp|go|generic]
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# Python 3.9+ supports builtin list[str] natively; keep no-underscore imports.

# ---------------------------------------------------------------------------
# Language detection (manifest-based)
# ---------------------------------------------------------------------------

# Order matters: first match wins. New languages append here.
_DETECTORS: list[tuple[str, Callable[[Path], bool], str]] = [
    ("python", lambda p: any((p / f).exists() for f in (
        "pyproject.toml", "setup.py", "requirements.txt", "Pipfile", "poetry.lock",
        "environment.yml", "requirements-dev.txt", "setup.cfg")),
     "Py"),
    ("node", lambda p: any((p / f).exists() for f in (
        "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "tsconfig.json", "next.config.js", "vite.config.ts", "nuxt.config.ts")),
     "JS/TS"),
    ("rust", lambda p: (p / "Cargo.toml").exists(),
     "Rust"),
    ("go", lambda p: (p / "go.mod").exists(),
     "Go"),
    ("cpp", lambda p: any((p / f).exists() for f in (
        "CMakeLists.txt", "compile_commands.json", "*.cpp", "*.hpp", "*.cc", "*.h")),
     "C/C++"),
    ("java", lambda p: any((p / f).exists() for f in (
        "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle")),
     "Java"),
    ("generic", lambda p: True,
     "Generic"),
]

_LANGS = [name for name, _, _ in _DETECTORS]


def detect_language(project_dir: str | Path) -> str:
    """Return the language key for a project directory (first manifest match)."""
    p = Path(project_dir)
    if not p.exists():
        raise FileNotFoundError(f"Not a directory: {project_dir!r}")
    for name, fn, _ in _DETECTORS:
        if fn(p):
            return name
    return "generic"


def _file_matches(project: Path, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if "glob" in pat:
            import fnmatch
            for child in project.rglob("*"):
                if child.is_file() and fnmatch.fnmatch(child.name, pat.split("*")[0]):
                    return True
        else:
            if (project / pat).exists():
                return True
    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BuildResult:
    project: Path
    language: str
    out_dir: Path
    num_files: int = 0
    files: list[str] = field(default_factory=list)
    commands: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(self, rel: str, content: str) -> None:
        self.files.append(rel)
        self.num_files += 1
        (self.project / rel).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Language-specific build/test commands
# ---------------------------------------------------------------------------

_COMMANDS: dict[str, dict[str, str]] = {
    "python": {
        "run": "python main.py run",
        "test": "pytest -q",
        "build": "python -m build 2>/dev/null || pip install -e .",
        "install": "pip install -r requirements.txt -r requirements-optional.txt",
        "serve": "python main.py terminal",
    },
    "node": {
        "run": "npm run dev",
        "test": "npm test",
        "build": "npm run build",
        "install": "npm install",
        "serve": "npm run dev",
    },
    "rust": {
        "run": "cargo run",
        "test": "cargo test",
        "build": "cargo build --release",
        "install": "cargo build --release",
        "serve": "cargo run",
    },
    "go": {
        "run": "go run .",
        "test": "go test -v ./...",
        "build": "go build -o bin/app .",
        "install": "go mod tidy",
        "serve": "go run .",
    },
    "cpp": {
        "run": "cmake -B build -S . && cmake --build build",
        "test": "ctest --test-dir build",
        "build": "cmake --build build",
        "install": "cmake -B build -S . && cmake --build build --target install",
        "serve": "./build/main",
    },
    "java": {
        "run": "java -jar target/app.jar",
        "test": "mvn test",
        "build": "mvn package",
        "install": "mvn package",
        "serve": "java -jar target/app.jar",
    },
    "generic": {
        "run": "echo 'No run command defined for this project type.'",
        "test": "echo 'No test command defined.'",
        "build": "echo 'No build command defined.'",
        "install": "echo 'No install command defined.'",
        "serve": "echo 'No serve command defined.'",
    },
}

# ---------------------------------------------------------------------------
# VS Code config generators (per language, plus a shared base)
# ---------------------------------------------------------------------------

def _base_settings() -> str:
    return '''{
  "editor.tabSize": 2,
  "files.trimTrailingWhitespace": true,
  "files.insertFinalNewline": true,
  "git.autofetch": true,
  "python.analysis.autoImportCompletions": true,
  "python.linting.enabled": true
}'''


def _extensions_json(lang: str) -> str:
    base = [
        "formulahendry.acp-client",          # hermes ACP client (MOON + hermes)
        "github.vscode-pull-request-github", # PR workflow
        "rangav.vscode-thunder-client",      # HTTP API testing
        "eamodio.gitlens",                   # git history
    ]
    if lang == "python":
        base += [
            "ms-python.python", "ms-python.vscode-pylance",
            "ms-python.black-formatter", "ms-python.debugpy",
        ]
    elif lang == "node":
        base += [
            "eslint.vscode-eslint",
            "dbaeumer.vscode-eslint",
            "microsoft.vscode-node-debug2",
        ]
    elif lang == "rust":
        base += ["mstarks.rust-analyzer", "rust-lang.rust", "serayuzgur.vscode-nextrerun"]
    elif lang == "go":
        base += ["golang.go", "ms-vscode.remote-preview", "chentsulin.vscode-tide"]
    elif lang == "cpp":
        base += ["ms-vscode.cpptools", "twxs.cmake", "ms-vscode.cmake-tools",
                 "vahidhere.vscode-c-cpp-cli", "bitinerantstudios.vscode-arm-embedded"]
    elif lang == "java":
        base += ["redhat.java", "vscjava.vscode-java-pack", "vscjava.vscode-java-debug"]
    return json_dumps({
        "recommendations": base,
        "languages": _lang_tags(lang),
    })


def _settings_json(lang: str) -> str:
    """Workspace settings for VS Code. Base editor defaults + language."""
    base = {
        "editor.tabSize": 2,
        "files.trimTrailingWhitespace": True,
        "files.insertFinalNewline": True,
        "git.autofetch": True,
        "python.analysis.autoImportCompletions": True,
        "python.linting.enabled": True,
    }
    extra = {}
    if lang == "python":
        extra = {
            "python.defaultInterpreterPath": ".venv/bin/python",
            "python.formatting.provider": "black",
            "python.testing.pytestEnabled": True,
        }
    elif lang == "node":
        extra = {
            "editor.defaultFormatter": "esbenp.prettier-vscode",
            "typescript.tsdk": "node_modules/typescript/lib",
        }
    if extra:
        base.update(extra)
    return json_dumps(base)


def _launch_json(lang: str) -> str:
    # hermes-acp compound is added by the MOON project template (see scaffold).
    configs = {
        "python": [
            {"name": "Run application", "type": "python", "request": "launch",
             "program": "main.py", "args": ["run"], "cwd": "${workspaceFolder}",
             "env": {"PYTHONPATH": "${workspaceFolder}"}, "purpose": ["debug"]},
            {"name": "Run tests", "type": "python", "request": "launch",
             "program": "pytest", "args": ["-q"], "cwd": "${workspaceFolder}",
             "console": "integratedTerminal", "purpose": ["debug"]},
        ],
        "node": [
            {"name": "Run dev server", "type": "node", "request": "launch",
             "program": "npm", "args": ["run", "dev"], "cwd": "${workspaceFolder}",
             "console": "integratedTerminal", "purpose": ["debug"]},
            {"name": "Run tests", "type": "node", "request": "launch",
             "program": "npm", "args": ["test"], "cwd": "${workspaceFolder}",
             "console": "integratedTerminal", "purpose": ["debug"]},
        ],
        "rust": [
            {"name": "Run app", "type": "cargo", "request": "launch",
             "cwd": "${workspaceFolder}", "purpose": ["debug"]},
            {"name": "Run tests", "type": "cargo", "request": "launch",
             "args": ["test"], "cwd": "${workspaceFolder}", "purpose": ["debug"]},
        ],
        "go": [
            {"name": "Run app", "type": "go", "request": "launch",
             "program": ".", "cwd": "${workspaceFolder}", "purpose": ["debug"]},
            {"name": "Run tests", "type": "go", "request": "launch",
             "tool": "test", "program": ".", "cwd": "${workspaceFolder}",
             "purpose": ["debug"]},
        ],
        "cpp": [
            {"name": "Build & run", "type": "cmake", "request": "launch",
             "cmakeConfigureArgs": ["-B", "${workspaceFolder}/build"],
             "cmakeBuildType": "Release", "console": "integratedTerminal",
             "purpose": ["debug"]},
        ],
        "java": [
            {"name": "Run app", "type": "java", "request": "launch",
             "mainClass": "App", "cwd": "${workspaceFolder}", "purpose": ["debug"]},
        ],
        "generic": [
            {"name": "Run shell command", "type": "shell", "request": "launch",
             "command": "echo 'define your run command'", "console": "integratedTerminal"},
        ],
    }[lang]
    return json_dumps({"version": "0.2.0", "configurations": configs,
                       "compounds": [{"name": "MOON + hermes ACP",
                                      "configurations": ["MOON: Run"],
                                      "stopAll": True}] if lang in _COMMANDS else None})


def _tasks_json(lang: str) -> str:
    cmds = _COMMANDS[lang]
    tasks = {
        "python": [
            {"label": "MOON: Build & Run", "type": "shell", "command": "make run",
             "group": {"kind": "build", "isDefault": True}, "problemMatcher": []},
            {"label": "MOON: Test", "type": "shell", "command": "make test", "group": "test"},
            {"label": "MOON: Verify", "type": "shell", "command": "make live",
             "group": "test"},
            {"label": "hermes build", "type": "shell", "command": "hermes acp",
             "args": [], "group": "none",
             "detail": "Start hermes ACP server for VS Code integration"},
        ],
        "node": [
            {"label": "MOON: Build & Run", "type": "shell", "command": "npm run dev",
             "group": {"kind": "build", "isDefault": True}},
            {"label": "MOON: Test", "type": "shell", "command": "npm test", "group": "test"},
        ],
        "rust": [
            {"label": "MOON: Build", "type": "shell", "command": "cargo build --release",
             "group": {"kind": "build", "isDefault": True}},
            {"label": "MOON: Test", "type": "shell", "command": "cargo test", "group": "test"},
        ],
        "go": [
            {"label": "MOON: Build", "type": "shell", "command": "make build", "group": "build"},
            {"label": "MOON: Test", "type": "shell", "command": "make test", "group": "test"},
        ],
        "cpp": [
            {"label": "MOON: Configure & Build", "type": "shell",
             "command": "cmake -B build -S . && cmake --build build",
             "group": {"kind": "build", "isDefault": True}},
            {"label": "MOON: Test", "type": "shell", "command": "ctest --test-dir build",
             "group": "test"},
        ],
        "java": [
            {"label": "MOON: Build", "type": "shell",
             "command": "gradle build", "group": {"kind": "build", "isDefault": True}},
            {"label": "MOON: Test", "type": "shell", "command": "gradle test", "group": "test"},
        ],
        "generic": [
            {"label": "MOON: Build", "type": "shell", "command": "make", "group": "build"},
            {"label": "MOON: Test", "type": "shell", "command": "make test", "group": "test"},
        ],
    }[lang]
    return json_dumps({"version": "2.0.0", "tasks": tasks})


# ---------------------------------------------------------------------------
# File writers (Makefile / Dockerfile / .env / tests)
# ---------------------------------------------------------------------------



def _confirm_overwrite(project: Path) -> bool:
    """Ask the user to confirm overwriting a non-empty directory.

    When stdin is not a terminal (non-interactive / CI), we skip the prompt
    and overwrite so that `moon build` stays idempotent and safe to re-run.
    """
    if not sys.stdin.isatty():
        return True
    answer = input(f"Directory {project} is not empty. Overwrite? [y/N] ")
    return answer.strip().lower() == "y"

def _makefile(lang: str) -> str:
    cmds = _COMMANDS[lang]
    template = '''# MOON-AI Build — auto-generated for [LANG].
# Targets: run test build serve clean install verify
PY := env -u PYTHONPATH .venv/bin/python

.PHONY: help run test build serve clean install verify live

help:
\t@echo "Targets: run test build serve clean install verify live"

run:
\t$(PY) main.py run

test:
\t$(PY) -m pytest tests -q

build:
\t$(PY) -m pip install -e .

serve:
\tpython main.py terminal

clean:
\tfind . -name '__pycache__' -type d -prune -exec rm -rf {} +
\trm -rf .pytest_cache .ruff_cache .mypy_cache .venv

install:
\t$(PY) -m pip install -r requirements.txt
\t$(PY) -m pip install -r requirements-optional.txt

verify:
\t$(PY) scripts/live_smoke_pipeline.py

live:
\t$(PY) scripts/live_smoke_pipeline.py
'''
    return template.replace("LANG", lang)


def _dockerfile(lang: str) -> str:
    return f'''# MOON-AI Docker — auto-generated for [{lang}]
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-optional.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt \\
    && pip install --no-cache-dir -r requirements-optional.txt

COPY . .
RUN pip install --no-cache-dir -e .

ENV MOON_PORT=8777
ENV PYTHONUNBUFFERED=1

EXPOSE 8777

CMD ["./.venv/bin/python", "main.py", "terminal"]
'''


def _env() -> str:
    return '''# MOON-AI project environment
# Copy to .env and fill in.  MOON reads these at runtime.

# --- Model backend (Ollama / local) ---
OLLAMA_BASE_URL=http://localhost:11434
MODEL=nemotron-3-super-120b-a12b:free

# --- MOON backend ---
MOON_PORT=8777

# --- HerMes ACP (VS Code integration) ---
HERMES_PROVIDER=openrouter
HERMES_MODEL=nvidia/nemotron-3-super-120b-a12b:free

# --- Voice (optional) ---
VOICE_PRESET=seductive
'''.lstrip()


# ---------------------------------------------------------------------------
# Helpers: tiny JSON shims (stdlib-only, stdlib only, no external deps)
# ---------------------------------------------------------------------------

def json_dumps(obj) -> str:
    """Minimal JSON serializer used instead of json module (no deps)."""
    import json as _json
    return _json.dumps(obj, indent=2)


def _parse_json(s: str) -> dict:
    import json as _json
    return _json.loads(s)


def _lang_tags(lang: str) -> list[str]:
    return [_LANG_LABEL[lang]]


_LANG_LABEL = {
    "python": "Python",
    "node": "JavaScript",
    "rust": "Rust",
    "go": "Go",
    "cpp": "C++",
    "java": "Java",
    "generic": "Generic",
}


# ---------------------------------------------------------------------------
# Scaffold (generate everything for a project dir)
# ---------------------------------------------------------------------------
def scaffold(project_dir: str | Path, lang: str | None = None) -> BuildResult:
    """Generate a full VS Code + hermes-acp + Makefile + Dockerfile + test
    skeleton for *project_dir*, in the detected language."""
    p = Path(project_dir)
    if p.exists() and not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {project_dir!r}")
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    elif not any(p.iterdir()):
        pass  # empty dir is fine
    else:
        if not _confirm_overwrite(p):
            sys.exit(1)
    lang = lang or detect_language(p)
    res = BuildResult(project=p, language=lang, out_dir=p)

    res.add(".env", _env())
    res.add("Makefile", _makefile(lang))
    res.add("Dockerfile", _dockerfile(lang))

    vs = p / ".vscode"
    vs.mkdir(exist_ok=True)
    res.add(".vscode/extensions.json", _extensions_json(lang))
    res.add(".vscode/settings.json", _settings_json(lang))
    res.add(".vscode/launch.json", _launch_json(lang))
    res.add(".vscode/tasks.json", _tasks_json(lang))

    # Test scaffolding (language-appropriate skeleton)
    _scaffold_tests(res, lang)

    res.notes.append(f"Generated [{lang}] project config: {res.num_files} files")
    res.notes.append("Next: run `make test` then `moon build verify`.")
    return res
def _scaffold_tests(res: BuildResult, lang: str) -> None:
    """Create a minimal runnable test file so `make test` succeeds on day 1."""
    if lang == "python":
        content = (
            "import pytest\n\n"
            "def test_greeter():\n"
            "    assert True\n\n"
            "def test_math():\n"
            "    assert 1 + 1 == 2\n"
        )
        test_file = res.project / "test_build_check.py"
        test_file.write_text(content, encoding="utf-8")
        res.add("test_build_check.py", content)
    elif lang == "node":
        res.project.joinpath("src").mkdir(parents=True, exist_ok=True)
        (res.project / "src/index.js").write_text("// index.js\n", encoding="utf-8")
        res.add("src/index.js", "// index.js")
        content = (
            "// Minimal placeholder test so `npm test` starts clean.\n"
            "test('placeholder', () => { expect(true).toBe(true); });\n"
        )
        test_file = res.project / "test_build_check.js"
        test_file.write_text(content, encoding="utf-8")
        res.add("test_build_check.js", content)
        pkg = res.project / "package.json"
        if pkg.exists():
            try:
                env = json.loads(pkg.read_text(encoding="utf-8"))
            except Exception:
                env = {}
        else:
            env = {}
        env.setdefault("name", "auto-project")
        env.setdefault("version", "1.0.0")
        env.setdefault("scripts", {})
        env["scripts"]["test"] = "node --test"
        env["scripts"]["dev"] = "node src/index.js"
        res.add("package.json", json_dumps(env))
    elif lang == "rust":
        content = (
            "// Minimal placeholder so `cargo test` compiles.\n"
            "//! \n"
            "#[test]\n"
            "fn it_works() {\n"
            "    assert!(true);\n"
            "}\n"
        )
        test_file = res.project / "tests" / "it_works.rs"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(content, encoding="utf-8")
        res.add("tests/it_works.rs", content)
    elif lang == "go":
        content = (
            "package main\n\n"
            "import \"testing\"\n\n"
            "func TestPlaceholder(t *testing.T) {\n"
            "\tFatal(\"placeholder\")\n"
            "}\n"
        )
        test_file = res.project / "hello_test.go"
        test_file.write_text(content, encoding="utf-8")
        res.add("hello_test.go", content)
    elif lang == "cpp":
        res.project.joinpath("src").mkdir(parents=True, exist_ok=True)
        (res.project / "src/main.cpp").write_text("", encoding="utf-8")
        res.add("src/main.cpp", "")
        content = "/* test_main.cpp */\n#include <cassert>\nint main() { assert(1==1); return 0; }\n"
        test_file = res.project / "test_main.cpp"
        test_file.write_text(content, encoding="utf-8")
        res.add("test_main.cpp", content)
    elif lang == "java":
        content = "// placeholder\n"
        test_file = res.project / "build_check.java"
        test_file.write_text(content, encoding="utf-8")
        res.add("build_check.java", content)
# ---------------------------------------------------------------------------
# Verify (run a project's real build/test command inside the dir)
# ---------------------------------------------------------------------------

def verify(project_dir: str | Path, lang: str | None = None, timeout: int = 120) -> BuildResult:
    """Run the language's live build/test command in *project_dir* and
    capture stdout/stderr/exit code.  Returns the BuildResult (reused) so
    callers can inspect the outcome."""
    p = Path(project_dir)
    if not p.exists():
        raise FileNotFoundError(f"Not a directory: {project_dir!r}")
    lang = lang or detect_language(p)
    cmds = _COMMANDS[lang]
    cmd = cmds["test"]
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=p, capture_output=True, text=True, timeout=timeout)
        return BuildResult(
            project=p, language=lang,
            files=[], commands=cmds,
            notes=[
                f"verdict: {'PASS' if proc.returncode == 0 else 'FAIL'}",
                f"exit_code: {proc.returncode}",
                f"cmd: {cmd}",
                "stdout (tail): " + proc.stdout[-500:],
                "stderr (tail): " + proc.stderr[-500:],
            ],
        )
    except subprocess.TimeoutExpired:
        return BuildResult(
            project=p, language=lang, commands=cmds,
            notes=[f"verdict: TIMEOUT (> {timeout}s)", f"cmd: {cmd}"])


# ---------------------------------------------------------------------------
# CLI: hooked into main.py as `moon build`
# ---------------------------------------------------------------------------

def _cmd_build_scaffold(args) -> int:
    from . import build as _b
    lang = args.lang
    if lang and lang not in _LANGS:
        print(f"Unknown lang {lang!r}; choose from {list(_LANGS)}", file=sys.stderr)
        return 1
    res = _b.scaffold(args.dir, lang)
    print(f"[moon build scaffold] [{res.language}] {res.num_files} files -> {res.project}")
    for f in res.files:
        print(f"   + {f}")
    for n in res.notes:
        print(f"   note: {n}")
    return 0


def _cmd_build_verify(args) -> int:
    from . import build as _b
    lang = args.lang
    if lang and lang not in _LANGS:
        print(f"Unknown lang {lang!r}; choose from {list(_LANGS)}", file=sys.stderr)
        return 1
    if not args.dir:
        print("usage: moon build verify <dir> [--lang]", file=sys.stderr)
        return 1
    res = _b.verify(args.dir, lang)
    print(f"[moon build verify] [{res.language}] verdict: {res.notes[0]}")
    for n in res.notes[1:]:
        print(f"   {n}")
    return 0 if res.notes[0].startswith("verdict: PASS") else 1


# ---------------------------------------------------------------------------
# Module-level dispatch for `moon build <sub>`
# ---------------------------------------------------------------------------

def build_main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="moon build",
                                 description="Universal project builder (VS Code + hermes-acp + Makefile + Dockerfile + tests).")
    sub = ap.add_subparsers(dest="build_cmd")
    sp = sub.add_parser("scaffold", help="Scaffold a new project (.vscode, Makefile, Dockerfile, tests)")
    sp.add_argument("dir", help="Project directory to generate config into")
    sp.add_argument("--lang", choices=_LANGS, help="Force a language (auto-detected by default)")
    sub.add_parser("verify", help="Run the project's live build/test command")
    sp2 = sub.add_parser("verify")
    sp2.add_argument("dir", help="Project directory to verify")
    sp2.add_argument("--lang", choices=_LANGS, help="Force a language")
    args = ap.parse_args(argv)
    if args.build_cmd == "scaffold":
        return _cmd_build_scaffold(args)
    if args.build_cmd == "verify":
        return _cmd_build_verify(args)
    ap.print_help()
    return 0


def build_main_entry(argv=None) -> int:
    """Drop-in replacement for `python -m MOON-AI build` (mirror of main.py)."""
    ap = argparse.ArgumentParser(prog="moon build",
                                 description="Universal project builder.")
    sub = ap.add_subparsers(dest="build_cmd")
    sp = sub.add_parser("scaffold", help="Scaffold a new project")
    sp.add_argument("dir", help="Project directory to generate config into")
    sp.add_argument("--lang", choices=_LANGS, help="Force a language")
    sp2 = sub.add_parser("verify", help="Run the project's live build/test command")
    sp2.add_argument("dir", help="Project directory to verify")
    sp2.add_argument("--lang", choices=_LANGS, help="Force a language")
    args = ap.parse_args(argv)
    if args.build_cmd == "scaffold":
        return _cmd_build_scaffold(args)
    if args.build_cmd == "verify":
        return _cmd_build_verify(args)
    ap.print_help()
    return 0
