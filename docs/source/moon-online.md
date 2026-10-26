# MOON Online Setup: Always-Active Internet + Free Data Save

This document describes how to set up MOON to be **always active on the internet** and **freely save her data** using **absolutely free** infrastructure.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Recommended Setup: Cloudflare (All Free)](#1-recommended-setup-cloudflare-all-free)
3. [Alternative: Oracle Cloud Free Tier](#2-alternative-oracle-cloud-free-tier)
4. [Bytebase Integration (Database Management)](#3-bytebase-integration-database-management)
5. [Data Sync Configuration](#4-data-sync-configuration)
6. [Voice Clones Persistence](#5-voice-clones-persistence)
7. [Always-On Background Process](#6-always-on-background-process)
8. [Verification](#7-verification)
9. [Cost Summary](#9-cost-summary)

---

## Architecture Overview

```
[Internet] → [Cloudflare Worker] → [Cloudflare Tunnel] → [MOON local]
                                              ↓
                                      [R2 Storage]
                                              ↓
                                      [MOON Sync]
```

**Key Principles:**
- **Free tier only** — no paid services required
- **Always online** — Cloudflare Worker is always available
- **Persistent data** — R2 stores MOON's data in the cloud
- **Secure** — Cloudflare Tunnel keeps MOON's local port private
- **No port forwarding** — no need to expose local IP

---

## 1. Recommended Setup: Cloudflare (All Free)

### 1.1 Why Cloudflare?

| Service | Free Tier | MOON Use Case |
|---------|-----------|---------------|
| **Cloudflare Workers** | Always free (20GB CPU, unlimited requests) | Public API endpoint for MOON |
| **Cloudflare R2** | 10GB storage free, 10M API requests/month | MOON data backup |
| **Cloudflare Tunnel** | Free, unlimited tunnels | Expose local MOON to internet |
| **Cloudflare DNS** | Free | Point domain to MOON |

### 1.2 Step-by-Step Setup

#### Step 1: Install Prerequisites

```bash
# Node.js (required for wrangler)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

# Wrangler (Cloudflare CLI)
npm install -g wrangler

# Cloudflare Tunnel
sudo apt install cloudflared
```

#### Step 2: Create R2 Storage

1. Go to https://dash.cloudflare.com/r2/buckets
2. Click **Create bucket**
3. Name: `moon-online`
4. Note: R2 gives you **10GB free** storage — more than enough for MOON's data

#### Step 3: Create API Token

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click **Create Token**
3. Select **R2:Edit** permission
4. Select **Workers:Edit** permission
5. Select **Cloudflare Tunnel:Edit** permission
6. Name: `moon-online-token`
7. Copy the token securely

#### Step 4: Configure Wrangler

```bash
cd /home/meow/Projects/MOON
wrangler login

# Set R2 credentials
wrangler secret put CLOUDFLARE_ACCOUNT_ID
wrangler secret put CLOUDFLARE_BUCKET
wrangler secret put CLOUDFLARE_ACCESS_KEY
wrangler secret put CLOUDFLARE_SECRET_KEY
```

Edit `scripts/cloudflare_worker/wrangler.toml`:
```toml
name = "moon-online"
main = "src/index.js"
compatibility_date = "2025-06-01"
```

#### Step 5: Deploy Worker

```bash
cd /home/meow/Projects/MOON/scripts/cloudflare_worker
wrangler deploy
```

Your worker URL will be: `https://moon-online.your-subdomain.workers.dev`

#### Step 6: Setup Cloudflare Tunnel

```bash
# Create tunnel
cloudflared tunnel create moon-online

# Run tunnel (background)
cloudflared tunnel run moon-online
```

#### Step 7: Configure MOON

Update MOON's config to use the worker URL:

```yaml
online:
  enabled: true
  worker_url: "https://moon-online.your-subdomain.workers.dev"
  tunnel_port: 8777
  r2:
    enabled: true
    bucket: "moon-online"
    account_id: "your-account-id"
    access_key: "[REDACTED]"
    secret_key: "[REDACTED]"
```

#### Step 8: Set Up Data Sync

```bash
cd /home/meow/Projects/MOON
pip install boto3

# Run initial sync
python scripts/moon_online/moon_sync.py \
  --account-id your-account-id \
  --bucket moon-online \
  --access-key "[REDACTED]" \
  --secret-key "[REDACTED]"
```

---

## 2. Alternative: Oracle Cloud Free Tier

### 2.1 Architecture

```
[Internet] → [Oracle Load Balancer] → [MOON VPS] → [MOON Local]
```

### 2.2 Step-by-Step Setup

#### Step 1: Create Oracle Free Tier Account

1. Sign up at https://cloud.oracle.com/account/selfservice
2. Verify your email
3. Set up 2FA

#### Step 2: Create Always-Free Instance

1. Go to https://cloud.oracle.com/compute/instances
2. Click **Create Instance**
3. Select **Always Free** > **ARM** (A1)
4. Choose region: **Mumbai, London, or Frankfurt**
5. Name: `moon-vps`
6. SSH key: Add your public key
7. Create

#### Step 3: Install MOON on the Instance

```bash
# SSH into the instance
ssh opc@<instance-ip>

# Install dependencies
sudo yum install -y git python3 python3-pip

# Clone MOON
git clone https://github.com/crsuvo100-gif/MOON.git /home/moon
cd /home/moon

# Install Python dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install the online sync package
pip install -e scripts/moon_online/
```

#### Step 4: Configure systemd Service

```bash
sudo nano /etc/systemd/system/moon.service

[Unit]
Description=MOON Online Service
After=network.target

[Service]
Type=simple
User=opc
WorkingDirectory=/home/moon
Environment="VIRTUAL_ENV=/home/moon/.venv"
ExecStart=/home/moon/.venv/bin/python main.py terminal
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable moon
sudo systemctl start moon
```

#### Step 5: Configure Oracle Object Storage

```bash
# Install OCI CLI
pip install oci

# Configure
oci os ns get
# Set your namespace
```

Configure MOON to use Oracle Object Storage for backups.

---

## 3. Bytebase Integration (Database Management)

Bytebase is a database management and migration tool that can be used to
manage MOON's SQLite databases in production.

### 3.1 What Bytebase Provides

| Feature | Benefit |
|---------|---------|
| **Database Migrations** | Version control for MOON's SQLite |
| **Schema Management** | Keep DB schema in sync |
| **Backup & Restore** | Automated backups |
| **CI/CD Integration** | Safe DB changes for deployments |

### 3.2 Setup

Bytebase is an optional component — MOON's core always-online functionality
works with or without it. Bytebase is useful for:
- Managing MOON's SQLite database schema across updates
- Automated backups
- Version-controlled database migrations

---

## 4. Data Sync Configuration

### 4.1 MOON Sync Script

The sync script (`scripts/moon_online/moon_sync.py`) backs up MOON's data to
R2 using the R2 API (S3-compatible).

**Syncable directories:**
```
app/        - MOON application data
app/memory/ - Long-term memory
app/data/   - User data
voices/     - Voice clones
.moon/      - MOON sessions
connections/ - Active connections
capabilities/ - MOON capabilities
```

**Incremental sync:** Only changed files are uploaded.

**Checksum verification:** MD5 checksums ensure data integrity.

### 4.2 Configuration

```yaml
# MOON config.yaml
online:
  r2:
    enabled: true
    bucket: "moon-online"
    account_id: "your-account-id"
    region: "auto"
    sync_interval: "daily"  # or "hourly", "weekly"
    include:
      - "app"
      - "app/memory"
      - "app/data"
      - "voices"
    exclude:
      - "node_modules"
      - ".git"
      - "dist"
      - "build"
```

---

## 5. Voice Clones Persistence

Voice clones are stored separately in R2 for easy retrieval.

**R2 path:** `voice/<voice_id>.wav`

**Upload via:**
```bash
python scripts/moon_online/moon_sync.py \
  --upload-voice <voice_id> <path/to/clone.wav>
```

**Retrieve voice:**
```bash
python scripts/moon_online/moon_sync.py \
  --download-voice <voice_id> <destination.wav>
```

---

## 6. Always-On Background Process

### 6.1 Local Machine (MOON runs on your machine)

**Option A: Cloudflare Tunnel (recommended)**

```bash
# Install cloudflared
sudo apt install cloudflared

# Start tunnel in background
nohup cloudflared tunnel run moon-online &
```

Add to your `.bashrc`:
```bash
# Start Cloudflare Tunnel on boot
nohup cloudflared tunnel run moon-online >> ~/.cloudflared-tunnel.log 2>&1 &
```

### 6.2 Linux Server (Oracle Free Tier)

```bash
sudo systemctl enable moon
sudo systemctl start moon
sudo systemctl status moon
```

### 6.3 Ensure Services Start on Boot

**For MOON:**
```bash
sudo systemctl enable moon
```

**For Cloudflare Tunnel:**
```bash
# Create systemd service for cloudflared
sudo nano /etc/systemd/system/cloudflared.service

[Unit]
Description=Cloudflare Tunnel
After=network.target

[Service]
ExecStart=/usr/local/bin/cloudflared tunnel run moon-online
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

---

## 7. Verification

### 7.1 Check Cloudflare Worker

```bash
curl https://moon-online.your-subdomain.workers.dev/api/status
```

Expected response:
```json
{
  "service": "MOON-Online",
  "version": "1.0.0",
  "status": "online",
  "timestamp": "2026-10-26T12:00:00Z"
}
```

### 7.2 Check Cloudflare Tunnel

```bash
cloudflared tunnel list
```

Expected output:
```
moon-online (<tunnel-id>)
```

### 7.3 Check R2 Storage

```bash
python scripts/moon_online/moon_sync.py \
  --account-id <account-id> \
  --bucket moon-online \
  --list
```

### 7.4 Verify MOON Data in R2

```bash
python scripts/moon_online/moon_sync.py \
  --account-id <account-id> \
  --bucket moon-online \
  --sync --dry-run
```

---

## 8. Cost Summary

| Service | Free Tier | Monthly Cost |
|---------|-----------|--------------|
| **Cloudflare Workers** | 20GB CPU, unlimited requests | $0 |
| **Cloudflare R2** | 10GB storage, 10M requests | $0 |
| **Cloudflare Tunnel** | Unrestricted | $0 |
| **Oracle Cloud A1** | 4GB RAM, 24GB storage | $0 |
| **Oracle Object Storage** | Free tier | $0 |
| **Total** | **All free** | **$0/month** |

---

## 9. Troubleshooting

### Worker not accessible
- Ensure the worker is deployed: `wrangler deploy`
- Check wrangler logs: `wrangler tail`
- Verify the route pattern in wrangler.toml

### Tunnel not connecting
- Check cloudflared: `cloudflared tunnel list`
- Verify the tunnel credentials exist
- Check network: ensure outbound HTTPS works

### R2 sync failing
- Verify API token has R2:Edit permission
- Check bucket name matches configuration
- Verify account ID is correct

### MOON can't connect to worker
- Ensure `worker_url` in config.yaml points to the correct worker URL
- Check MOON's firewall allows outbound HTTPS
- Check the worker is accepting requests

---

## 10. Quick Start Command Summary

```bash
# 1. Create R2 bucket (manual)
# 2. Create API token (manual)

# 3. Deploy worker
cd /home/meow/Projects/MOON
wrangler deploy scripts/cloudflare_worker/

# 4. Setup tunnel
cloudflared tunnel create moon-online
cloudflared tunnel run moon-online

# 5. Configure MOON
# Edit scripts/cloudflare_worker/config.yaml

# 6. Sync data
pip install boto3
python scripts/moon_online/moon_sync.py --account-id <id> --bucket moon-online --access-key <key> --secret-key <secret>

# 7. Test
curl https://moon-online.your-subdomain.workers.dev/api/status
```

---

**Status:** Ready for deployment
**Last Updated:** 2026-10-26
**Used by:** MOON (moontwin.ai)
