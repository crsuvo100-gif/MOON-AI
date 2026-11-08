# Security

## Reporting a vulnerability

If you discover a security vulnerability in MOON, please report it privately and
responsibly — do not open a public issue.

- **Preferred:** email the maintainer directly (see `SUPPORT.md`).
- **Alternative:** open a private security advisory via GitHub Security Advisories
  on the repository.

Please include:

- A description of the vulnerability and its impact.
- Step-by-step reproduction instructions.
- The affected version(s).
- Any suggested mitigation, if you have one.

We will acknowledge receipt within 48 hours and aim to release a fix within 7 days
for critical issues, with credit to you (unless you request otherwise).

## Scope

MOON is a **self-hosted** agent. Security-relevant areas:

- **Configuration** — secrets live in `.env` (git-ignored, never committed). Back
  up `.env` separately.
- **Model access** — MOON talks to an OpenAI-compatible endpoint. Secure any
  local endpoint (Ollama) and any cloud keys in `.env`.
- **Network** — the HUD and dashboard bind to localhost by default; do not expose
  `127.0.0.1:8777` to untrusted networks without a reverse proxy and auth.
- **Tools/agents** — each agent runs with the privileges granted by the
  orchestrator; restrict access to local-only connections.

## Disclosure

Responsible disclosure is expected. After a fix ships, the vulnerability may be
mentioned in `CHANGELOG.md` (under a security patch entry) and credited to the
reporter if they wish.
