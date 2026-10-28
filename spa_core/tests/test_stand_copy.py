"""`utils.stand_copy.copy_data_tree` (ADR-846 §3): стенд переписи — та же копия, только быстрее.

Клон APFS (macOS) и прежний цикл copytree/copy2 обязаны давать ОДИНАКОВОЕ дерево — байты, времена, права;
исключённые имена не копируются; запись в стенд не доходит до источника; отказ `cp` — прежняя копия.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from spa_core.utils import stand_copy as sc


def _seed(root: Path) -> None:
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "a.json").write_text('{"a": 1}\n')
    (root / "sub" / "b.jsonl").write_text("x\ny\n")
    (root / "sub" / "deep" / "c.bin").write_bytes(os.urandom(4096))
    (root / "backups").mkdir()
    (root / "backups" / "big.tgz").write_bytes(b"0" * 100)
    os.utime(root / "a.json", ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))


def _manifest(root: Path) -> dict:
    out = {}
    for dp, _d, fs in os.walk(root):
        for f in fs:
            p = Path(dp) / f
            st = p.stat()
            out[str(p.relative_to(root))] = (hashlib.sha256(p.read_bytes()).hexdigest(),
                                             st.st_mtime_ns // 1000, st.st_mode)
    return out


def test_clone_and_fallback_give_the_same_tree(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _seed(src)
    sc.copy_data_tree(src, tmp_path / "one", ("backups",))
    monkeypatch.setattr(sys, "platform", "linux")
    assert sc.copy_data_tree(src, tmp_path / "two", ("backups",)) == "copy"
    one, two = _manifest(tmp_path / "one"), _manifest(tmp_path / "two")
    assert one == two
    assert "backups/big.tgz" not in one and "a.json" in one and "sub/deep/c.bin" in one


def test_writing_into_the_stand_never_reaches_the_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    _seed(src)
    before = _manifest(src)
    dst = tmp_path / "stand"
    sc.copy_data_tree(src, dst, ("backups",))
    (dst / "a.json").write_text('{"a": 2}\n')
    (dst / "sub" / "b.jsonl").write_text("changed\n")
    assert _manifest(src) == before


def test_failed_cp_falls_back_to_the_old_copy(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    _seed(src)
    monkeypatch.setattr(sys, "platform", "darwin")

    def boom(*_a, **_k):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout=b"", stderr=b"no clone")
    monkeypatch.setattr(sc.subprocess, "run", boom)
    assert sc.copy_data_tree(src, tmp_path / "stand", ("backups",)) == "copy"
    assert (tmp_path / "stand" / "sub" / "deep" / "c.bin").read_bytes() == (src / "sub" / "deep" / "c.bin").read_bytes()


def test_judge_stand_does_not_carry_backups(tmp_path):
    """Проводка исключения у стенда судьи: `backups/` (≈0,9 ГБ в проде) в стенд не копируется."""
    from spa_core.monitoring import judge_alone_price as jap
    src = tmp_path / "src"
    src.mkdir()
    _seed(src)
    jap._copy_data(src, tmp_path / "stand")
    assert not (tmp_path / "stand" / "backups").exists()
    assert (tmp_path / "stand" / "a.json").is_file()
