"""ADR-533: the new experiment records survive a backup → restore round trip.

# LLM_FORBIDDEN

The books (with their ``experiments`` and mechanic sub-books) are top-level ``data/*.json``; the run
evidence is ``data/paper_observations/*.jsonl``. Both must be in the daily archive, and restoring the
archive must give back byte-identical files. Sandboxed: the module's data/backup dirs point at tmp.
"""
from __future__ import annotations

import importlib.util
import json
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("spa_daily_backup", REPO / "scripts" / "daily_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_experiments_and_observations_round_trip(tmp_path, monkeypatch):
    m = _load()
    data = tmp_path / "data"
    (data / "paper_observations").mkdir(parents=True)
    book = {"equity": 1.0, "experiments": [{"experiment_id": "aggressive-susde-loop-v1@d0", "status": "active",
                                             "initial_state": {"equity_usd": 1.0}}],
            "loop": {"status": "flat", "events": [{"event": "opened"}]}, "daily_history": [{"date": "d0"}]}
    (data / "lp_paper_trading.json").write_text(json.dumps(book), encoding="utf-8")
    (data / "paper_observations" / "aggressive.jsonl").write_text('{"slot": "s1"}\n{"slot": "s2"}\n', encoding="utf-8")
    for crit in ("golive_status.json", "equity_curve_daily.json", "paper_evidence_history.json",
                 "current_positions.json"):
        (data / crit).write_text("{}", encoding="utf-8")      # the archive refuses without its critical set
    import sqlite3
    sqlite3.connect(data / "track.db").close()
    monkeypatch.setattr(m, "_DATA", str(data))
    monkeypatch.setattr(m, "_BACKUPS", str(tmp_path / "backups"))
    res = m.snapshot(date_str="2000-01-01")
    arc = next(Path(tmp_path / "backups").glob("*.tar.gz"))
    assert m.verify(str(arc))["valid"] is True, res
    out = tmp_path / "restored"
    with tarfile.open(arc) as tf:
        names = tf.getnames()
        tf.extractall(out, filter="data")
    want = {"lp_paper_trading.json", "paper_observations/aggressive.jsonl"}
    assert all(any(n.endswith(rel) for n in names) for rel in want), names
    for rel in want:
        restored = next(p for p in out.rglob(Path(rel).name) if p.is_file())
        assert restored.read_bytes() == (data / rel).read_bytes(), rel
