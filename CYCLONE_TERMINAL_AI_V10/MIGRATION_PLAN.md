# 📋 MIGRATION PLAN — MOON-AI-AGENT (Python/FastAPI)
**Source:** /home/meow/Projects/MOON | **Target:** same folder (clean standard structure)
**Logic unchanged.** Only file/folder organization. Duplicates: 0.

## Migration Table (old → new → reason)

| # | Old Path | New Path | Reason |
|---|----------|----------|--------|
| 1 | `.venv/` | *(removed)* | Virtual env (7.1G) — never commit. Already gitignored. |
| 2 | `.pre_commit_checkpoint/` | *(removed)* | 2.4G binary blob containing venv+gradio. Not needed. |
| 3 | `.mypy_cache/` | *(removed)* | Build cache. Already gitignored. |
| 4 | `.pytest_cache/` | *(removed)* | Build cache. Already gitignored. |
| 5 | `.ruff_cache/` | *(removed)* | Build cache. Already gitignored. |
| 6 | `moon_ai_agent.egg-info/` | *(removed)* | Build artifact. |
| 7 | `.probe_system_info.py` | *(removed)* | Debug scratch file. |
| 8 | `__pycache__/` (5,043 dirs) | *(removed)* | Python cache. Already gitignored. |
| 9 | `regexr/` | *(removed)* | Empty (only .gitmodules references it). |
| 10 | `probes/` | *(removed)* | Empty. |
| 11 | `doc/` | `docs/` (merged) | Old docs (2020) consolidated into canonical `docs/`. |
| 12 | `.env` | `.env.example` (already existed) | Secrets must not be tracked; .env already gitignored. |
| 13 | `capabilities/installed/` | `capabilities/installed/` (keep) | Runtime capability data — gitignored. |
| 14 | `plugins/generated/` | `plugins/generated/` (keep) | Runtime plugin data — gitignored. |
| 15 | `data/` | `data/` (keep, gitignore) | Runtime exec db, memory, knowledge — not source. |
| 16 | `home/` | `home/` (keep, gitignore) | Agent home dirs — not source. |
| 17 | `voices/` | `voices/` (keep) | Voice data (alice.wav + registry.json). |
| 18 | `web/` | `web/` (keep) | Web interface (moon_terminal.html + backend). |
| 19 | `skills/` | `skills/` (keep) | 40+ skill corpus — source. |
| 20 | `tests/` | `tests/` (keep) | Test suite — source. |
| 21 | `scripts/` | `scripts/` (keep) | 30+ scripts — source. |
| 22 | `deploy/` | `deploy/` (keep) | 20+ systemd unit files — source. |
| 23 | `apps/` | `apps/` (keep) | cyclone + moon_ui apps — source. |
| 24 | `capabilities/` | `capabilities/` (keep) | Capability system — source. |
| 25 | `connections/` | `connections/` (keep) | Connections system — source. |
| 26 | `plugins/` | `plugins/` (keep) | Plugin loader — source. |
| 27 | `moon/` | `moon/` (keep) | Main package entry. |
| 28 | `app/` | `app/` (keep) | Main application code (342 .py files). |

## Key decisions
- **Keep** all source code logic 100% unchanged. Only `.py` file CONTENT untouched.
- **Remove** only temp/backup/caches/empty dirs (each is gitignored, never tracked).
- **Merge** `doc/` (old, 2020) → `docs/` (canonical).
- **Add** `.env.example` (already existed), ensure all secrets are gitignored.
- **Default configs:** `ruff.toml`, `.pyrefly.toml`, `mypy.ini` exist in app/ — keep.
- **CI:** .github/workflows/ci.yml exists — keep + ensure .gitignore excludes caches.

## Post-migration git workflow
1. `git add -A`
2. Verify .gitignore excludes all temp files
3. `git commit -m "chore: reorganize project into standard Python/FastAPI structure"`
4. Ask user for GitHub info (STEP 5) → push → verify fresh clone.
