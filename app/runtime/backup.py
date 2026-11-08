"""Cross-platform backup & restore (spec 25).

Pure-Python, ``pathlib``-based implementation that replaces the bash
``scripts/backup.sh`` wrapper with the same behaviour portable to Linux,
macOS and Windows. It snapshots MOON-AI's runtime data (agents, knowledge,
memory, skills, evaluations, logs, the agent_factory sqlite DB and the
optional ``moon_settings.json``) into a timestamped archive directory.

Design rules (non-destructive):
- Never deletes project source files.
- Never overwrites real secrets (``.env`` is explicitly excluded from backups;
  operators back up ``.env`` themselves -- see README).
- Safe to run repeatedly; each run gets a fresh timestamped directory.
- Restore copies a snapshot back over the live ``data/`` tree.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Directories/files under the project root that constitute runtime DATA.
# Source code, agents' *definitions* and config templates are version-controlled
# separately; this module only handles generated/runtime state.
DATA_DIRS = ["data", "capabilities", "connections", "voices"]
DATA_FILES = ["data/agents/agent_factory.db", "data/executions.db", "moon_settings.json"]


def _project_root() -> Path:
    # This module lives in app/runtime; the project root is two levels up.
    return Path(__file__).resolve().parent.parent.parent


def _snapshot_name() -> str:
    return "moon_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def backup(dest_root: Path | None = None) -> Path:
    """Create a timestamped backup of MOON-AI runtime data. Returns the backup dir."""
    root = _project_root()
    dest_root = dest_root or (root / "backups")
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / _snapshot_name()
    if dest.exists():
        raise FileExistsError(f"backup snapshot already exists: {dest}")

    # Stage beside the final path so a failed copy never leaves a visible snapshot.
    with tempfile.TemporaryDirectory(prefix=".moon-backup-", dir=dest_root) as temporary:
        staged = Path(temporary)
        for d in DATA_DIRS:
            src = root / d
            if src.is_dir():
                shutil.copytree(src, staged / d, dirs_exist_ok=True)

        for f in DATA_FILES:
            src = root / f
            if src.is_file():
                (staged / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, staged / f)

        captured = sorted(str(p.relative_to(staged)) for p in staged.rglob("*") if p.is_file())
        (staged / "BACKUP_MANIFEST.txt").write_text(
            "MOON-AI runtime backup\n"
            f"created: {datetime.now().isoformat()}\n"
            f"source_root: {root}\n"
            f"items: {len(captured)}\n"
            + "\n".join(captured),
            encoding="utf-8",
        )
        if dest.exists():
            raise FileExistsError(f"backup snapshot already exists: {dest}")
        staged.rename(dest)
    return dest


def restore(
    snapshot: Path, root: Path | None = None, *, confirmed: bool = False
) -> list[str]:
    """Merge a snapshot into runtime data; replacing existing files needs confirmation."""
    root = Path(root or _project_root()).resolve()
    snapshot = Path(snapshot).resolve()
    if not snapshot.is_dir():
        raise FileNotFoundError(f"backup snapshot not found: {snapshot}")

    sources: list[tuple[Path, Path]] = []
    directories: list[tuple[str, Path, Path]] = []
    conflicts: list[str] = []
    seen: set[Path] = set()

    def add_source(src: Path, relative: Path) -> None:
        if src.is_symlink():
            raise ValueError(f"backup contains a symbolic link: {src}")
        if not src.is_file():
            return
        destination = root / relative
        resolved_destination = destination.resolve()
        if resolved_destination != root and root not in resolved_destination.parents:
            raise ValueError(f"restore path escapes project root: {relative}")
        if destination in seen:
            return
        seen.add(destination)
        if destination.exists():
            if not destination.is_file():
                raise FileExistsError(f"restore target is not a regular file: {destination}")
            conflicts.append(str(relative))
        sources.append((src, destination))

    for d in DATA_DIRS:
        src_dir = snapshot / d
        if src_dir.is_symlink():
            raise ValueError(f"backup contains a symbolic link: {src_dir}")
        if not src_dir.is_dir():
            continue
        destination_dir = root / d
        resolved_dir = destination_dir.resolve()
        if resolved_dir != root and root not in resolved_dir.parents:
            raise ValueError(f"restore directory escapes project root: {d}")
        if destination_dir.exists() and not destination_dir.is_dir():
            raise FileExistsError(f"restore target is not a directory: {destination_dir}")
        directories.append((d, src_dir, destination_dir))
        for src in src_dir.rglob("*"):
            relative = src.relative_to(snapshot)
            if src.is_symlink():
                raise ValueError(f"backup contains a symbolic link: {src}")
            destination = root / relative
            if destination.exists() and not src.is_dir() and not destination.is_file():
                raise FileExistsError(f"restore target is not a regular file: {destination}")
            if src.is_file():
                add_source(src, relative)

    for f in DATA_FILES:
        src = snapshot / f
        if src.is_symlink():
            raise ValueError(f"backup contains a symbolic link: {src}")
        if src.is_file():
            add_source(src, Path(f))

    if conflicts and confirmed is not True:
        raise PermissionError(
            "restore would overwrite existing runtime files; rerun with confirmed=True "
            f"after reviewing: {', '.join(conflicts[:10])}"
        )

    restored: list[str] = []
    for d, src_dir, destination_dir in directories:
        shutil.copytree(src_dir, destination_dir, dirs_exist_ok=True)
        restored.append(d)
    for src, destination in sources:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, destination)
        relative = str(destination.relative_to(root))
        if relative not in restored:
            restored.append(relative)
    return restored


def _cli() -> int:
    ap = argparse.ArgumentParser(description="MOON-AI runtime backup/restore (Python, cross-platform)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup", help="Snapshot runtime data into backups/")
    rp = sub.add_parser("restore", help="Restore a snapshot over live data")
    rp.add_argument("snapshot", help="Path to a backups/moon_<timestamp> directory")
    rp.add_argument(
        "--confirm-overwrite",
        action="store_true",
        help="Allow replacing existing runtime files after reviewing the snapshot",
    )
    args = ap.parse_args()
    if args.cmd == "backup":
        d = backup()
        print(f"BACKUP COMPLETE -> {d}")
        return 0
    if args.cmd == "restore":
        restored = restore(Path(args.snapshot), confirmed=args.confirm_overwrite)
        print(f"RESTORE COMPLETE -> restored: {', '.join(restored) or 'nothing'}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
