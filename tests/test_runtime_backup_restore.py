import pytest

from app.runtime.backup import restore


def test_restore_preserves_existing_files_without_confirmation(tmp_path):
    snapshot = tmp_path / "snapshot"
    source = snapshot / "data" / "agents" / "settings.json"
    source.parent.mkdir(parents=True)
    source.write_text("snapshot", encoding="utf-8")
    root = tmp_path / "project"
    target = root / "data" / "agents" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text("live", encoding="utf-8")

    with pytest.raises(PermissionError, match="overwrite existing runtime files"):
        restore(snapshot, root)
    assert target.read_text(encoding="utf-8") == "live"

    restored = restore(snapshot, root, confirmed=True)
    assert "data" in restored
    assert target.read_text(encoding="utf-8") == "snapshot"


def test_restore_creates_new_files_without_overwrite_confirmation(tmp_path):
    snapshot = tmp_path / "snapshot"
    source = snapshot / "voices" / "voice.json"
    source.parent.mkdir(parents=True)
    source.write_text("new", encoding="utf-8")
    root = tmp_path / "project"

    restored = restore(snapshot, root)
    assert "voices" in restored
    assert (root / "voices" / "voice.json").read_text(encoding="utf-8") == "new"


def test_restore_rejects_snapshot_symlinks(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private.txt").write_text("private", encoding="utf-8")
    try:
        (snapshot / "data").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable")

    with pytest.raises(ValueError, match="symbolic link"):
        restore(snapshot, tmp_path / "project")


def test_backup_collision_never_overwrites_existing_snapshot(tmp_path, monkeypatch):
    import app.runtime.backup as backup_module

    root = tmp_path / "project"
    source = root / "data" / "state.json"
    source.parent.mkdir(parents=True)
    source.write_text("original", encoding="utf-8")
    monkeypatch.setattr(backup_module, "_project_root", lambda: root)
    monkeypatch.setattr(backup_module, "_snapshot_name", lambda: "fixed-name")

    first = backup_module.backup(tmp_path / "backups")
    existing = (first / "data" / "state.json").read_text(encoding="utf-8")
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already exists"):
        backup_module.backup(tmp_path / "backups")
    assert (first / "data" / "state.json").read_text(encoding="utf-8") == existing


def test_failed_backup_copy_leaves_no_visible_partial_snapshot(tmp_path, monkeypatch):
    import app.runtime.backup as backup_module

    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    monkeypatch.setattr(backup_module, "_project_root", lambda: root)
    monkeypatch.setattr(backup_module, "_snapshot_name", lambda: "failed-copy")
    monkeypatch.setattr(
        backup_module.shutil, "copytree", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("copy failed"))
    )

    backup_root = tmp_path / "backups"
    with pytest.raises(OSError, match="copy failed"):
        backup_module.backup(backup_root)
    assert not (backup_root / "failed-copy").exists()
    assert not list(backup_root.glob(".moon-backup-*"))


def test_restore_cli_passes_explicit_overwrite_confirmation(monkeypatch, tmp_path):
    import app.runtime.backup
    import main
    import moon.__main__ as moon_cli

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    captured = {}

    def fake_restore(path, *, confirmed=False):
        captured["path"] = path
        captured["confirmed"] = confirmed
        return []

    monkeypatch.setattr(app.runtime.backup, "restore", fake_restore)
    assert main._cmd_restore(snapshot, confirm_overwrite=False) == 0
    assert captured == {"path": snapshot, "confirmed": False}
    assert main._cmd_restore(snapshot, confirm_overwrite=True) == 0
    assert captured == {"path": snapshot, "confirmed": True}

    args = moon_cli._build_parser().parse_args(
        ["restore", str(snapshot), "--confirm-overwrite"]
    )
    assert args.confirm_overwrite is True
