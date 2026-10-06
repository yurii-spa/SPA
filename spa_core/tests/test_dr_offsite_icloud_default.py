"""RM-TRUTH-01 C10: offsite default resolves to iCloud Drive when signed in, stand-in otherwise;
an unresponsive destination is a RECORDED refusal, never a hang or a silent pass."""
from pathlib import Path

from spa_core.dr import offsite_copy


def test_default_is_icloud_when_parent_exists(tmp_path, monkeypatch):
    parent = tmp_path / "CloudDocs"; parent.mkdir()
    monkeypatch.delenv("SPA_OFFSITE_DEST", raising=False)
    monkeypatch.setattr(offsite_copy, "ICLOUD_PARENT", parent)
    monkeypatch.setattr(offsite_copy, "ICLOUD_DEST", parent / "SPA_backups" / "dr_offsite")
    assert offsite_copy.resolve_dest() == parent / "SPA_backups" / "dr_offsite"


def test_default_is_standin_without_icloud(tmp_path, monkeypatch):  # reverse control
    monkeypatch.delenv("SPA_OFFSITE_DEST", raising=False)
    monkeypatch.setattr(offsite_copy, "ICLOUD_PARENT", tmp_path / "absent")
    assert offsite_copy.resolve_dest() == offsite_copy.STANDIN_DEST


def test_env_and_explicit_still_win(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_OFFSITE_DEST", str(tmp_path / "env"))
    assert offsite_copy.resolve_dest() == tmp_path / "env"
    assert offsite_copy.resolve_dest(tmp_path / "x") == tmp_path / "x"


def test_unresponsive_dest_is_recorded_refusal(tmp_path, monkeypatch):
    import json
    import spa_core.persistence.backup as pb
    src = tmp_path / "src"; src.mkdir()
    (src / "spa_state_2026-10-07.tar.gz").write_bytes(b"x" * 64)
    monkeypatch.setattr(pb, "_probe_backup_root", lambda root, t: "backup root did not respond within 20s")
    status = tmp_path / "st.json"
    code = offsite_copy.run(backup_dir=src, dest_dir=tmp_path / "d", status_path=status)
    doc = json.loads(status.read_text())
    assert code != 0 and doc["verified"] is False and doc["error"].startswith("dest_unresponsive")
    assert not (tmp_path / "d" / "spa_state_2026-10-07.tar.gz").exists()
