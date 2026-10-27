"""Разбор входящих: отчёт без правки карточек — тип, готовность, дубли, возраст (ADR-154 §3)."""
from datetime import datetime, timezone

from spa_core.owner_queue import triage as t

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — triage(..., now=NOW)


def _w(d, name, fm, body=""):
    (d / name).write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n" + body,
                          encoding="utf-8")


def test_counts_ready_dups_and_never_touches_cards(tmp_path):
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "Проверь дашборд", "created": "2026-10-20"})
    _w(tmp_path, "inbox-b.md", {"status": "new", "title": "Проверь, дашборд!", "intake_kind": "task"},
       "проба: problem_absent:x\n")
    _w(tmp_path, "inbox-c.md", {"status": "done", "title": "Проверь дашборд"})
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    r = t.triage(tmp_path, now=NOW)
    assert (r["new_total"], r["ready"], r["kind_unknown"]) == (2, 1, 1)
    assert r["dup_groups"] == [["inbox-a.md", "inbox-b.md"]]
    assert r["age_unmeasured"] == 1 and r["oldest_days"] == 7.0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before, "разбор правит карточки"


def test_cli_writes_report_and_unmeasured_is_loud(tmp_path, capsys):
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "x"})
    out = tmp_path / "r.json"
    assert t.main(["--tracker-dir", str(tmp_path), "--out", str(out)]) == 0 and out.exists()
    assert "РАЗБОР ВХОДЯЩИХ" in capsys.readouterr().out
    assert t.main(["--tracker-dir", str(tmp_path), "--out", str(tmp_path / "f" / "x" / "\0bad")]) == 2
    assert "НЕ ИЗМЕРЕН" in capsys.readouterr().out
