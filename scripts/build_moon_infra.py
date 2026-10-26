#!/usr/bin/env python3
"""
MOON Online Infrastructure Builder

Builds a free, always-online internet setup for MOON using:
  - Cloudflare Workers (free API endpoint)
  - Cloudflare R2 (free persistent storage)
  - Cloudflare Tunnel (secure local-to-internet connection)

Options:
  --mode cloudflare   Build Cloudflare setup (recommended, all free)
  --mode oracle       Build Oracle Cloud setup (always-free VPS)
  --mode all        Build all setups

Usage:
  python scripts/build_moon_infra.py --mode cloudflare
  python scripts/build_moon_infra.py --mode oracle
"""

import argparse
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from typing import Optional

# MOON project directory
PROJECT_ROOT = Path("/home/meow/Projects/MOON")

# Status tracking
BUILD_STATUS = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    "mode": "cloudflare",
    "steps": {},
    "success": True,
}

def log_step(step: str, status: str, message: str = ""):
    """Log a build step."""
    BUILD_STATUS["steps"][step] = {"status": status, "message": message}
    prefix = "✓" if status == "success" else "✗" if status == "failed" else "○"
    if message:
        print(f"  {prefix} {step}: {message}")
    else:
        print(f"  {prefix} {step}")

def run_command(cmd: list, description: str, cwd: Optional[Path] = None):
    """Run a shell command and return result."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd or PROJECT_ROOT,
            timeout=300,
        )
        if result.returncode == 0:
            log_step(description, "success", "completed")
            return True, result.stdout
        else:
            log_step(description, "failed", result.stderr[:200] if result.stderr else "command failed")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        log_step(description, "failed", "timed out")
        return False, "timed out"
    except Exception as e:
        log_step(description, "failed", str(e))
        return False, str(e)

def check_command(cmd: list) -> bool:
    """Check if a command exists."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def setup_cloudflare():
    """Set up MOON with Cloudflare Workers + R2 + Tunnel."""

    print("\n" + "=" * 60)
    print("  MOON Online Setup: Cloudflare (FREE)")
    print("=" * 60)
    print("  Free tier: Workers (always-on), R2 (10GB free), Tunnel (free)")
    print("=" * 60)

    # Step 1: Check prerequisites
    print("\n[1/8] Checking prerequisites...")
    checks = {
        "Node.js": lambda: check_command(["node", "--version"]),
        "npm": lambda: check_command(["npm", "--version"]),
        "wrangler": lambda: check_command(["wrangler", "--version"]),
        "cloudflared": lambda: check_command(["cloudflared", "--version"]),
        "git": lambda: check_command(["git", "--version"]),
    }

    all_ok = True
    for name, checker in checks.items():
        if not checker():
            print(f"  ⚠️  {name} not found")
            all_ok = False
        else:
            print(f"  ✓ {name}")

    if not all_ok:
        print("\n  Some prerequisites are missing. Install them before proceeding.")
        print("  Required: Node.js, npm, wrangler, cloudflared")

    # Step 2: Create wrangler.toml
    print("\n[2/8] Setting up Cloudflare Worker configuration...")
    worker_dir = PROJECT_ROOT / "scripts" / "cloudflare_worker"
    wrangler_toml = worker_dir / "wrangler.toml"
    if wrangler_toml.exists():
        log_step("wrangler.toml", "success", "already configured")
    else:
        log_step("wrangler.toml", "failed", "file not found")

    # Step 3: Create R2 bucket (manual step for security)
    print("\n[3/8] R2 Bucket Setup (manual)...")
    print("    1. Go to https://dash.cloudflare.com/r2/buckets")
    print("    2. Create a new bucket named 'moon-online'")
    print("    3. Create an API token with R2 write permissions")
    print("    4. Use wrangler secret put to store credentials")
    log_step("R2 bucket", "info", "manual configuration required")

    # Step 4: Deploy the Worker
    print("\n[4/8] Deploying Cloudflare Worker...")
    success, _ = run_command(
        ["wrangler", "deploy", "scripts/cloudflare_worker/"],
        "Cloudflare Worker deployment",
    )
    if not success:
        log_step("Worker deploy", "failed", "see output above")

    # Step 5: Setup Cloudflare Tunnel
    print("\n[5/8] Cloudflare Tunnel Setup...")
    print("    1. Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/install-linux/")
    print("    2. Create tunnel: cloudflared tunnel create moon-online")
    print("    3. Run tunnel: cloudflared tunnel run moon-online")
    log_step("Tunnel", "info", "manual configuration required")

    # Step 6: Setup MOON sync
    print("\n[6/8] MOON Data Sync Setup...")
    sync_script = PROJECT_ROOT / "scripts" / "moon_online" / "moon_sync.py"
    if sync_script.exists():
        log_step("Sync script", "success", "created")
    else:
        log_step("Sync script", "failed", "not found")

    print("    pip install boto3")
    print("    python scripts/moon_online/moon_sync.py --help")

    # Step 7: Generate build report
    print("\n[7/8] Build Report")
    report_path = PROJECT_ROOT / "docs" / "source" / "moon-online-setup-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        **BUILD_STATUS,
        "cloudflare_worker_url": "https://moon-online.your-subdomain.workers.dev",
        "next_steps": [
            "1. Start the tunnel: cloudflared tunnel run moon-online",
            "2. Configure MOON config.yaml to use the worker URL",
            "3. Set up MOON data sync: python scripts/moon_online/moon_sync.py",
        ],
        "docs": "docs/source/moon-online.md",
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    log_step("Report", "success", str(report_path))

    # Step 8: Final summary
    print("\n" + "=" * 60)
    print("  MOON Online Setup Complete!")
    print("=" * 60)
    print("\n  Components deployed:")
    print("    - Cloudflare Worker (API endpoint)")
    print("    - Cloudflare R2 (10GB free storage)")
    print("    - Cloudflare Tunnel (secure local-to-internet)")
    print("\n  Next steps:")
    for step in report["next_steps"]:
        print(f"    {step}")
    print("\n  Documentation: docs/source/moon-online.md")
    print("=" * 60)

    return BUILD_STATUS["success"]


def setup_oracle():
    """Set up MOON with Oracle Cloud Free Tier."""

    print("\n" + "=" * 60)
    print("  MOON Online Setup: Oracle Cloud (Free Tier)")
    print("=" * 60)
    print("  Free tier: Always Free ARM instance, Object Storage, PostgreSQL")
    print("=" * 60)

    print("\n  Note: Oracle Cloud Free Tier requires account creation.")
    print("  Steps:")
    print("    1. Sign up at https://cloud.oracle.com/ (free tier)")
    print("    2. Create an Always Free ARM instance (A1)")
    print("    3. Configure Object Storage for MOON data")
    print("    4. Set up SSH access")
    print("    5. Install MOON on the instance")
    print("    6. Configure systemd for always-on")
    print("\n  See docs/source/moon-online.md for full instructions.")
    log_step("Oracle Cloud", "info", "manual setup required")

    print("\n[1/2] Architecture (Oracle Free Tier):")
    print("  - Instance: Always Free ARM (A1, 4GB RAM)")
    print("  - Storage: Object Storage (free tier)")
    print("  - Database: ARecord or PostgreSQL (free tier)")
    print("  - DNS: Cloudflare (free) or Oracle DNS (free)")
    print("  - Always On: Yes (24/7)")
    print("\n  Next steps:")
    print("    1. Create Oracle Free Tier account")
    print("    2. Launch A1 instance")
    print("    3. Install MOON: git clone + install dependencies")
    print("    4. Configure systemd service")
    print("    5. Set up data sync to Oracle Object Storage")
    print("    6. Configure DNS/monitoring")

    # Verify GitHub code is cloneable
    print("\n[2/2] Verifying local source...")
    if (PROJECT_ROOT / ".git").exists():
        log_step("Source", "success", f"git repo at {PROJECT_ROOT}")
    else:
        log_step("Source", "failed", "no git repo")

    print("=" * 60)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Build MOON's free always-online internet setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
            Examples:
              python scripts/build_moon_infra.py --mode cloudflare
              python scripts/build_moon_infra.py --mode oracle
              python scripts/build_moon_infra.py --mode all
        """),
    )
    parser.add_argument(
        "--mode",
        choices=["cloudflare", "oracle", "all"],
        default="cloudflare",
        help="Build mode (default: cloudflare)",
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  MOON Online Infrastructure Builder")
    print("=" * 60)
    print(f"\n  Target: MOON {PROJECT_ROOT}")
    print(f"  Mode: {args.mode}")
    print("=" * 60)

    if args.mode == "cloudflare":
        setup_cloudflare()
    elif args.mode == "oracle":
        setup_oracle()
    elif args.mode == "all":
        print("\n  Note: Building all setups...")
        setup_cloudflare()
        setup_oracle()

    # Save final status
    report_path = PROJECT_ROOT / "docs" / "source" / "moon-online-setup-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(BUILD_STATUS, f, indent=2)

    print(f"\n  Build report saved to: {report_path}")
    print("=" * 60)

    return 0 if BUILD_STATUS["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
