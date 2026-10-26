---
name: moon-online
description: Build MOON's free always-online internet setup: Cloudflare Worker + R2 storage + Cloudflare Tunnel. One-click setup for MOON to save data and stay active on the internet.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [cloudflare, workers, r2, tunnel, moon, online, always-active]
    category: setup
---

# MOON Always-Online Setup

Build a free, always-online internet setup for MOON using Cloudflare Workers + R2 + Cloudflare Tunnel. This gives MOON a public-facing API endpoint and persistent cloud storage with zero cost.

## Architecture

```
[Mobile/Devices] -> [Cloudflare Worker] -> [Cloudflare Tunnel] -> [MOON local instance]
                                                               |
                                                          [R2 Storage]
```

## Components

1. **Cloudflare Worker** — Always-on API endpoint (free tier)
2. **Cloudflare R2** — Persistent cloud storage (10GB free)
3. **Cloudflare Tunnel** — Secure connection between local MOON and Cloudflare
4. **MOON Sync** — Local script to backup MOON data to R2

## Setup Steps

1. Install `wrangler` (Cloudflare CLI)
2. Configure Cloudflare API token
3. Deploy the Worker
4. Create R2 bucket
5. Install Cloudflare Tunnel
6. Run MOON sync script
7. Update MOON config to use the online endpoint

## Quick Start

```bash
cd /home/meow/Projects/MOON
python scripts/build_moon_infra.py --mode cloudflare
```

## Configuration

See `docs/source/moon-online.md` for full configuration details.

## Notes

- All components are free tier
- R2 provides 10GB storage (free)
- Worker runs on Cloudflare's always-on platform
- Tunnel keeps connection persistent without port forwarding
