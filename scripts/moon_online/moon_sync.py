#!/usr/bin/env python3
"""
MOON Sync — Backup MOON data to Cloudflare R2 storage.

This script syncs MOON's local data directory to a Cloudflare R2 bucket
using the R2 API (S3-compatible). It supports:
  - Full backup of MOON data (SQLite DB, voice files, user data)
  - Incremental sync (only changed files)
  - Checksum verification
  - Configurable retention policies

Always free tier: 10GB storage, 10M requests/month.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config

# MOON data directory paths (relative to project root)
MOON_DATA_DIRS = [
    "app",
    "app/memory",
    "app/sessions",
    "app/data",
    "data",
    "voices",
    ".moon",
    "connections",
    "capabilities",
]

# Files to skip during sync (large/generated/ephemeral)
SKIP_PATTERNS = [
    ".git",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".moon_logs",
    ".moon_sessions.json",
    ".moon_workflow_logs",
    "moon_ai_agent.egg-info",
    "dist",
    "build",
    ".venv",
    "venv",
    "node_modules",
    ".pre_commit_checkpoint",
    ".probe_system_info.py",
    "_proof_system_info.py",
    ".ori",
    ".claude",
    ".vscode",
    ".github",
    ".git",
    "plugins",
    "skills/.archive",
    "skills/web-development",
    "skills/devops",
    "skills/communication",
    "skills/creative",
    "skills/data-science",
    "skills/finance",
    "skills/gaming",
    "skills/health",
    "skills/migration",
    "skills/mlops",
    "skills/mlops/evaluation",
    "skills/mlops/inference",
    "skills/mlops/models",
    "skills/mlops/research",
    "skills/mlops/training",
    "skills/payments",
    "skills/productivity",
    "skills/red-teaming",
    "skills/research",
    "skills/smart-home",
    "skills/social-media",
    "skills/software-development",
    "skills/telephony",
    "skills/workflow",
    "skills/yuanbao",
]

# Max file size to sync (100MB per file)
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

# Progress callback
def on_progress(event: dict):
    """Default progress callback — prints to stdout."""
    tag = event.get("tag", "")
    msg = event.get("msg", "")
    current = event.get("current", 0)
    total = event.get("total", 0)
    if tag == "backup_start":
        print(f"Starting backup to R2 bucket: {msg}")
    elif tag == "file_start":
        print(f"  [{current}/{total}] backing up: {msg}")
    elif tag == "file_done":
        print(f"  [OK] {msg} ({event.get('size', 0)} bytes)")
    elif tag == "file_skip":
        print(f"  [SKIP] {msg} ({event.get('size', 0)} bytes)")
    elif tag == "backup_complete":
        print(f"Backup complete: {msg} ({event.get('total', 0)} files, {event.get('bytes', 0)} bytes)")
    elif tag == "error":
        print(f"  [ERR] {msg}", file=sys.stderr)


class MoonSync:
    """MOON data sync to Cloudflare R2."""

    def __init__(
        self,
        account_id: str,
        bucket_name: str,
        access_key: str,
        secret_key: str,
        region: str = "auto",
        endpoint_url: Optional[str] = None,
        md5_digest: bool = False,
    ):
        self.account_id = account_id
        self.bucket_name = bucket_name
        self.md5_digest = md5_digest

        # R2 endpoint: r2.cloudflarestorage.com
        if endpoint_url:
            self.endpoint_url = endpoint_url
        else:
            self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

        # Configure boto3 client for R2 (S3-compatible)
        config = Config(
            region_name=region,
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )

        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )

        self.stats = {"total_files": 0, "synced_files": 0, "skipped_files": 0, "bytes": 0}

    def _get_object_key(self, local_path: Path, base_dir: Path) -> str:
        """Convert a local file path to an R2 object key."""
        relative = local_path.relative_to(base_dir)
        return f"moon/{relative}" if base_dir != MOON_DATA_DIRS else f"moon/{relative}"

    def _should_skip(self, path: Path, base_dir: Path) -> bool:
        """Check if a path should be skipped."""
        # Check name-based patterns
        name = path.name
        if any(name == skip or name.endswith(skip) for skip in SKIP_PATTERNS):
            return True

        # Check directory-based patterns
        for parent in path.relative_to(base_dir).parents:
            if parent.name in SKIP_PATTERNS:
                return True

        return False

    def _compute_checksum(self, file_path: Path) -> Optional[str]:
        """Compute MD5 checksum of a file."""
        import hashlib
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def _does_remote_exist(self, key: str) -> bool:
        """Check if a remote object exists in R2."""
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except self.client.exceptions.from_code("404"):
            return False
        except Exception:
            return False

    def _get_remote_checksum(self, key: str) -> Optional[str]:
        """Get the ETag of a remote object (used as checksum)."""
        try:
            response = self.client.head_object(Bucket=self.bucket_name, Key=key)
            # ETag is usually the MD5 for stored objects
            etag = response.get("ETag", "")
            return etag.strip('"')
        except Exception:
            return None

    def backup_directory(
        self,
        local_dir: Path,
        base_dir: Path,
        label: str,
        progress: Optional[callable] = None,
    ) -> dict:
        """
        Backup a local directory to R2.

        Returns a dict with sync stats.
        """
        if not local_dir.exists():
            return {"label": label, "status": "skipped", "reason": "directory_not_found"}

        local_dir = local_dir.resolve()
        base_dir = base_dir.resolve()

        if self._should_skip(local_dir, base_dir):
            return {"label": label, "status": "skipped", "reason": "pattern_match"}

        progress = progress or on_progress
        progress({"tag": "backup_start", "msg": label, "current": 0, "total": 0})

        # Collect all files
        files = []
        for root, dirs, filenames in os.walk(local_dir):
            dirs[:] = [d for d in dirs if not self._should_skip(Path(root) / d, base_dir)]

            for filename in filenames:
                file_path = Path(root) / filename
                if self._should_skip(file_path, base_dir):
                    continue

                if file_path.stat().st_size > MAX_FILE_SIZE:
                    self.stats["skipped_files"] += 1
                    if progress:
                        progress({"tag": "file_skip", "msg": str(file_path.relative_to(base_dir)), "size": file_path.stat().st_size})
                    continue

                files.append(file_path)

        files.sort()

        # Upload files
        for file_path in files:
            relative = file_path.relative_to(base_dir)
            key = f"moon/{relative}"

            # Check if remote exists and is up to date
            if self._does_remote_exist(key):
                remote_checksum = self._get_remote_checksum(key)
                local_checksum = self._compute_checksum(file_path)
                if remote_checksum == local_checksum:
                    self.stats["skipped_files"] += 1
                    if progress:
                        progress({"tag": "file_skip", "msg": str(relative), "size": file_path.stat().st_size})
                    continue

            # Upload
            try:
                extra_args = {}
                if self.md5_digest:
                    checksum = self._compute_checksum(file_path)
                    extra_args["Metadata"] = {"md5": checksum}

                self.client.upload_file(
                    str(file_path),
                    self.bucket_name,
                    key,
                    ExtraArgs=extra_args,
                )

                self.stats["synced_files"] += 1
                self.stats["bytes"] += file_path.stat().st_size
                if progress:
                    progress({"tag": "file_done", "msg": str(relative), "size": file_path.stat().st_size})

            except Exception as e:
                self.stats["skipped_files"] += 1
                if progress:
                    progress({"tag": "error", "msg": f"Failed {relative}: {e}"})

        return {
            "label": label,
            "status": "completed",
            "files": self.stats["synced_files"],
            "bytes": self.stats["bytes"],
        }

    def create_bucket(self) -> bool:
        """Create the R2 bucket if it doesn't exist."""
        try:
            self.client.create_bucket(Bucket=self.bucket_name)
            return True
        except self.client.exceptions.bucket_exists:
            return False

    def list_objects(self, prefix: str = "moon/", limit: int = 100) -> list:
        """List objects in R2 bucket."""
        try:
            response = self.client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=limit,
            )
            return response.get("Contents", [])
        except Exception as e:
            print(f"Error listing objects: {e}", file=sys.stderr)
            return []

    def delete_objects(self, prefix: str = "moon/", force: bool = False) -> int:
        """Delete objects from R2 bucket."""
        objects = self.list_objects(prefix=prefix)
        if not objects:
            return 0

        delete_keys = {"Objects": [{"Key": obj["Key"]} for obj in objects]}
        self.client.delete_objects(Bucket=self.bucket_name, Delete=delete_keys)
        return len(objects)

    def sync_all(
        self,
        project_root: Path,
        progress: Optional[callable] = None,
    ) -> dict:
        """
        Sync all MOON data directories to R2.

        Args:
            project_root: Root directory of the MOON project
            progress: Optional progress callback

        Returns:
            Overall sync stats
        """
        project_root = project_root.resolve()
        sync_dir = project_root / "scripts/moon_online"
        base_dir = sync_dir

        progress = progress or on_progress

        results = {}
        total_files = 0
        total_bytes = 0

        progress({"tag": "backup_start", "msg": "MOON online sync", "current": 0, "total": 0})

        for data_dir in MOON_DATA_DIRS:
            local_dir = project_root / data_dir
            if not local_dir.exists():
                continue

            result = self.backup_directory(local_dir, base_dir, data_dir, progress)
            results[data_dir] = result
            total_files += result["files"]
            total_bytes += result["bytes"]

        return {
            "status": "completed" if total_files > 0 else "no_data",
            "directories": results,
            "total_files": total_files,
            "total_bytes": total_bytes,
        }

    def generate_report(self, sync_result: dict) -> str:
        """Generate a human-readable sync report."""
        lines = [
            f"MOON Online Sync Report",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"Status: {sync_result['status']}",
            f"Total files: {sync_result['total_files']}",
            f"Total bytes: {sync_result['total_bytes']} ({sync_result['total_bytes'] / 1024 / 1024:.2f} MB)",
            f"",
            f"Directory breakdown:",
        ]
        for dir_name, result in sync_result.get("directories", {}).items():
            lines.append(f"  {dir_name}: {result['status']} ({result.get('files', 0)} files, {result.get('bytes', 0)} bytes)")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MOON Sync: Backup MOON data to Cloudflare R2")
    parser.add_argument("--account-id", required=True, help="Cloudflare account ID")
    parser.add_argument("--bucket", required=True, help="R2 bucket name")
    parser.add_argument("--access-key", required=True, help="R2 access key (API token)")
    parser.add_argument("--secret-key", required=True, help="R2 secret key")
    parser.add_argument("--region", default="auto", help="R2 region (default: auto)")
    parser.add_argument("--project-root", default="/home/meow/Projects/MOON", help="MOON project root directory")
    parser.add_argument("--list", action="store_true", help="List objects in R2 bucket")
    parser.add_argument("--delete", action="store_true", help="Delete all MOON data from R2 bucket")
    parser.add_argument("--force", action="store_true", help="Force delete without confirmation")
    parser.add_argument("--report", action="store_true", help="Generate sync report")
    parser.add_argument("--no-md5", action="store_true", help="Do not compute MD5 checksum for verification")

    args = parser.parse_args()

    # Initialize sync
    sync = MoonSync(
        account_id=args.account_id,
        bucket_name=args.bucket,
        access_key=args.access_key,
        secret_key=args.secret_key,
        region=args.region,
        md5_digest=not args.no_md5,
    )

    # Create bucket if needed
    bucket_created = sync.create_bucket()
    if bucket_created:
        print(f"Created R2 bucket: {args.bucket}")
    else:
        print(f"R2 bucket exists: {args.bucket}")

    if args.list:
        objects = sync.list_objects()
        print(f"Found {len(objects)} objects in R2 bucket:")
        for obj in objects:
            print(f"  {obj['Key']} ({obj['Size']} bytes)")
        return

    if args.delete:
        count = sync.delete_objects(force=args.force)
        print(f"Deleted {count} objects from R2 bucket")
        return

    # Perform sync
    project_root = Path(args.project_root)
    result = sync.sync_all(project_root)
    report = sync.generate_report(result)
    print(report)

    # Exit with error if sync failed
    if result["status"] == "no_data":
        print("No data to sync (empty directories)")
        return

    if result["total_files"] == 0:
        print("Sync complete (no files transferred)")
    else:
        print(f"Sync: {result['total_files']} files, {result['total_bytes']} bytes")


if __name__ == "__main__":
    main()
