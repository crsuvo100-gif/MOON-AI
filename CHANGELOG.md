# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project claims adherence to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `scripts/moon_workflow.py` — save-first workflow runner: every task is saved
  into the source folder before execution; a GitHub-push prompt follows
  completion (`MOON_NO_PROMPT=1` for non-interactive runs).
- `make workflow` / `make auto-work` / `make save` — Makefile targets wired to
  the workflow runner.
- `MOON: Auto Task & Save` — VSCode task that runs the workflow automatically
  in the hermes terminal.
- `make voice-install`, `make voice`, `make voice-test` — female-voice
  (espeak `f5` + SoX timbre chain) entry points.
- `make doctor` — the `python -m moon doctor` health check (Python/deps/config/
  DB/agents/tools/model/git).
- `python -m moon backup` / `restore` — cross-platform runtime backups.
- Full pytest suite under `tests/` (unit, acceptance, terminal, deployment,
  memory, agent, communication, distributed, cognitive/specialist agents).
- `deploy/` — systemd service/timer units (`moon-hud.service`,
  `moon-terminal.service`, `moon-watchdog.service`, monitor units, etc.).

### Fixed
- `scripts/install.sh` — corrected repo-root path handling for the editable
  install, the `moon` symlink, the moon-terminal symlink, and the health-check
  launcher (`python -m moon` instead of relying on cwd).

### Changed
- `scripts/install.sh` now works from any working directory (repo-root
  resolution fix); `moon` and `moon-terminal` are symlinked into `~/.local/bin`.

## [0.1.0] — 2026-10-21

Initial release of MOON, the Neural Brain Command Center autonomous agent.

- Main brain (LongTermMemory + KnowledgeBase), per-agent specialist brains
  (39 agents), continuous self-learning, three.js Neural Brain Command Center UI.
- Female-voice TTS (espeak `f5` + SoX timbre chain).
- Neural Brain Command Center at `http://127.0.0.1:8777`; Flask/SocketIO
  dashboard; ACP integration for VSCode-in-terminal workflow.

See `README.md`, `CONTRIBUTING.md`, and `SECURITY.md` for more.
