# MOON Repository Reorganization Map

This document reflects the actual, verified repository layout in the current working tree of the MOON project. It is a source-of-truth map for maintainers and contributors working in the repo without assuming a hypothetical architecture.

## 1) Verified root layout

```text
/home/meow/Projects/MOON/
├── main.py                     # project entry point for CLI / installer / orchestration
├── pyproject.toml             # packaging metadata and Python project config
├── README.md                  # user-facing start-up and command docs
├── Makefile                   # local developer convenience commands
├── app/                       # core application package
├── moon/                      # bootstrapping / package entry wrappers
├── skills/                    # skill definitions and reusable automation assets
├── tests/                     # project tests and fixtures
├── scripts/                   # maintenance and bootstrap utilities
├── docs/                      # architecture, setup, deployment docs
├── data/                      # runtime or persisted data directories
├── connections/               # connection registry metadata
├── capabilities/              # capability registry and installed capability data
├── deploy/                    # service definitions and runtime deployment materials
├── web/                       # web UI / browser resources
├── apps/                      # app variants or packaged interfaces
├── voices/                    # voice-related runtime assets
├── plugins/                   # optional plugin code / generated runtime integrations
├── probes/                    # runtime probes and checks
├── build/                     # generated build artifacts
├── dist/                      # packaged distributions (if present)
├── .github/                   # GitHub workflow and contribution metadata
├── .env.example               # sample environment config
├── .gitignore                 # local runtime/data exclusions
├── LICENSE                    # license
├── SECURITY.md                # disclosure guidance
├── CONTRIBUTING.md            # project contribution guidance
└── CHANGELOG.md              # release notes
```

## 2) Responsibility-based map

### Application source

- `main.py`
  Project root entry point and orchestrator bootstrap. This is the default CLI entry used by the package installer and local developer workflow.

- `app/`
  Main runtime package. This is the active application implementation. The project is not organized around a single `engine.py`; instead, responsibilities are split across brain, capability, connector, terminal, and utility domains.

### Runtime subsystems

- `app/brain/`
  Core reasoning, orchestration, planning, and memory coordination logic.

- `app/orchestrator/`
  Workflow orchestration layer and orchestration helpers.

- `app/config/`
  Settings, env validation, logging, and config-driven runtime behavior.

- `app/capability/`
  Capability registry and discovery logic for installed or dynamic capabilities.

- `app/connector/`
  Gateway and connection runtime for peer / service / agent integration.

- `app/terminal/`
  Terminal UI and REPL subsystem, including Hermes-compatible terminal behavior.

- `app/tools/`
  Core tool implementations and execution wrappers.

- `app/models/`
  LLM model wrappers and provider-facing interfaces.

- `app/memory/`
  Memory persistence and retrieval logic.

- `app/context/`
  Session and conversation context management.

- `app/verification/`
  Runtime verification and health checks.

### Execution and developer workflow

- `moon/`
  Bootstrapping package for Python module invocation and command dispatch. This preserves compatibility with commands such as `python -m moon` and `python -m moon terminal`.

- `scripts/`
  Convenience scripts, local setup, and maintenance routines.

- `Makefile`
  Standard developer commands for test, build, serve, voice, and install tasks.

- `deploy/`
  Service definitions and operational deployment config.

### Data, state, and local runtime files

These are runtime artifacts and should not be treated as source code unless they are intentionally versioned:

- `data/`
- `connections/`
- `capabilities/`
- `.moon/`
- `.moon_logs/`
- `build/`
- `dist/`
- `plugins/` (when generated)
- `home/` (project-local runtime workspace state)

### Documentation and support

- `docs/`
  Architecture, configuration, installation, troubleshooting, and engineering notes. These documents are the canonical project-level references for local development.

- `README.md`
  Primary project overview and getting-started instructions.

- `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`
  Repository-level project operations and governance metadata.

## 3) File migration and ownership notes

This repository already reflects a responsibility-based structure. The work completed here is not a wholesale rewrite; it is a documentation and classification pass to keep the project traceable and maintainable.

The key rule is:

- keep application logic under `app/`
- keep bootstrap/entry wrappers under `moon/`
- keep runtime-generated data and local state out of the source tree where possible
- keep dev automation in `scripts/` and `deploy/`
- keep docs and engineering notes in `docs/`

## 4) Verified issues observed during audit

- The repo is a single real project rooted at `/home/meow/Projects/MOON` and points at GitHub origin `git@github.com:crsuvo100-gif/MOON-AI.git`.
- The repository is not clean: there are modified tracked files and untracked runtime artifacts in the current working tree.
- Some local files may be generated or user-local data; they should be reviewed before any broad cleanup or push.
- The architecture docs still describe an older project structure that does not fully match the real code tree.

## 5) Safe operational guidance

1. Keep the application package under `app/` as the source of truth.
2. Treat `moon/` as a compatibility layer for packaging and CLI dispatch rather than a second application.
3. Do not delete runtime state or user-local data without explicit review.
4. Prefer documentation and manifest updates over broad file moves when the codebase is already functionally organized.
5. Only stage and push the files that are part of the intended project source and documentation.

## 6) Verification status

This map is based on the live filesystem and Git metadata of the workspace as of the current audit, not on assumptions from earlier docs.
