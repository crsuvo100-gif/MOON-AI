# Contributing to MOON

Thanks for wanting to contribute. This file explains how to contribute without
stepping on the project rules below.

## Rules for contributors

1. **Save first.** Every task, work, and build is saved into the source folder
   `/home/meow/Projects/MOON/` (or your local checkout) before any execution.
2. **Verify before you commit.** Run `make test` (or `pytest tests -q`). The
   CI suite must be green when you open a PR.
3. **Nothing secret in Git.** `.env` is git-ignored and never committed.
4. **Small, reviewable PRs.** One concern per PR; large rewrites get split.
5. **No hard-coded developer paths in the core runtime.** The runtime must be
   portable (Linux/macOS/Windows). Only `app/capability/installer.py` handles
   OS/package differences.

## Local workflow

```bash
git clone git@github.com:crsuvo100-gif/MOON.git
cd MOON
python -m venv .venv
. .venv/bin/activate
pip install -e .[runtime]
cp .env.example .env          # supply real secrets; keep .env local
make voice-install            # optional: espeak + sox (+ vosk for mic)
make serve                    # Neural Brain Command Center
```

The `moon` console script is available after `pip install -e .`.

### Testing

- `make test` — runs the full suite.
- `pytest tests -q` — direct invocation with the project's options.
- `pytest tests -q --tb=short` — full output with tracebacks.
- Live-model tests are marked `@pytest.mark.live` and auto-skip when Ollama is
  unreachable; CI (matrix `3.11`/`3.13`) runs them only when Ollama is up.

### Commit messages

Use conventional prefixes:

- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation only
- `chore:` — build, tooling, config
- `test:` — tests only

## Pull requests

- One concern per PR. Update `README.md` and `CHANGELOG.md` when behaviour
  changes.
- CI must be green (`make test` + import sweep).
- See `.github/PULL_REQUEST_TEMPLATE.md` for the checklist.
