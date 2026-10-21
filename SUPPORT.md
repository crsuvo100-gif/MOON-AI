# Support

## Getting help

1. **Check the docs.** Start with `README.md` (Quick start, commands, install).
2. **Free forum:** open an issue with the `question` or `support` label — we will
   answer and keep it searchable.
3. **Bug reports:** follow `.github/ISSUE_TEMPLATE/bug_report.md`.
4. **Feature requests:** follow `.github/ISSUE_TEMPLATE/feature_request.md`.

## Where to find help

- **Self-hosting docs:** `README.md` (install, `moon` CLI, services).
- **Voice/CLI:** `make voice`, `moon terminal`, `moon --help`.
- **Code base:** `app/` — the agent runtime, agents, tools, brain, API, skills.
- **Deploy:** `deploy/` (systemd units), `Dockerfile`, `install.sh`.

## Commercial / red-team ops

MOON is a self-hosted cyber-expert agent (defence + offensive). For professional
or on-premises engagements, contact the maintainer directly (email in the commit
trailer of `README.md`, or via the private security advisory in `SECURITY.md`).
Do not open public issues with operational details; use the private channel.

## Response expectations

- Issues are triaged within 48 hours.
- Live-model (`@pytest.mark.live`) tests auto-skip when Ollama is unreachable;
  CI only runs them when Ollama is reachable. Do not treat skips as failures.

## Disclaimer

MOON is a research/tooling project. Only operate on systems you own or have
explicit written authorisation to test. The maintainer is not responsible for
misuse.
