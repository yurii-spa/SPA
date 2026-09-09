"""Режим скрипта, который правит запись о деньгах, ОБЪЯВЛЯЕТСЯ, а не выводится (ADR-283).

Что случилось 2026-09-09. Агент набрал `python3 scripts/reconcile_paper_evidence.py --help`,
чтобы прочитать справку. Справки у скрипта не было, а безопасный режим был устроен так:

    reconcile(dry_run="--dry-run" in sys.argv)

То есть **любой** аргумент, кроме этой точной строки, означал «пиши в data/». Запуск молча
исправил 32 дня из 62 в живом `data/paper_evidence.json`. Ущерба не случилось (правка совпала
с решением владельца ADR-128 §2, все прочие поля сохранены, расхождение стало нулём), но
безопасный режим не имеет права зависеть от того, набрал ли человек флаг ровно так, как ждёт
`in sys.argv`. Безопасного УМОЛЧАНИЯ у такого скрипта тоже быть не должно.

# FROZEN-DATE-OK: historical-incident — дата и числа инцидента (32 из 62) и есть предмет
# теста; живых часов в файле нет.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "reconcile_paper_evidence", _ROOT / "scripts" / "reconcile_paper_evidence.py")
rec = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(rec)


@pytest.mark.parametrize("argv,expected", [
    (["prog"], "usage"),                       # без аргументов писать НЕЛЬЗЯ
    (["prog", "--help"], "usage"),             # ровно тот запуск, что записал 32 дня
    (["prog", "-h"], "usage"),
    (["prog", "help"], "usage"),
    (["prog", "--bogus"], "usage"),            # незнакомый флаг — не команда «применяй»
    (["prog", "--dry"], "usage"),              # опечатка в самом безопасном флаге
    (["prog", "--dry-run", "--apply"], "usage"),   # два режима сразу — отказ
    (["prog", "--dry-run"], "dry"),
    (["prog", "--apply"], "apply"),
])
def test_only_an_explicit_flag_selects_a_mode(argv, expected):
    assert rec._mode_from_argv(argv) == expected, argv


def test_the_incident_command_no_longer_writes():
    """Тот самый запуск: `--help` обязан быть справкой, а не записью."""
    assert rec._mode_from_argv(["prog", "--help"]) != "apply"


def test_apply_is_the_only_way_to_write():
    """Единственный путь к записи — слово `--apply`, названное вслух."""
    writing = [a for a in (["--help"], ["-h"], ["--bogus"], ["--dry"], [], ["--dry-run"])
               if rec._mode_from_argv(["prog"] + a) == "apply"]
    assert writing == [], writing


def test_usage_text_names_both_modes():
    """Справка обязана называть оба режима — иначе человек снова угадает флаг."""
    assert "--dry-run" in rec._USAGE and "--apply" in rec._USAGE


def test_reconcile_still_does_its_job_on_a_copy(tmp_path, monkeypatch):
    """Контроль обратного направления: сама сверка не ослаблена.

    Кривая канонична, у записи о деньгах два расхождения ⇒ оба выровнены, прочие поля целы."""
    import json
    curve = {"daily": [{"date": "2030-01-01", "close_equity": 100.0},
                       {"date": "2030-01-02", "close_equity": 200.0}]}
    evid = {"base_capital": 100.0, "days": [
        {"date": "2030-01-01", "equity_value": 111.0, "apy_pct": 4.0, "notes": "keep me"},
        {"date": "2030-01-02", "equity_value": 200.0, "apy_pct": 5.0, "notes": "keep me too"}]}
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(curve), encoding="utf-8")
    (tmp_path / "paper_evidence.json").write_text(json.dumps(evid), encoding="utf-8")
    monkeypatch.setattr(rec, "_CURVE", tmp_path / "equity_curve_daily.json")
    monkeypatch.setattr(rec, "_EVID", tmp_path / "paper_evidence.json")
    res = rec.reconcile(dry_run=False)
    # Обе записи числятся исправленными: у первой расходилось `equity_value`, у второй —
    # производный `day_return_pct` (сверка правит и его; см. условие в `reconcile`).
    assert res["fixed"] == 2 and res["days"] == 2
    after = json.loads((tmp_path / "paper_evidence.json").read_text())["days"]
    assert [d["equity_value"] for d in after] == [100.0, 200.0]
    assert [d["notes"] for d in after] == ["keep me", "keep me too"]
    assert [d["apy_pct"] for d in after] == [4.0, 5.0]


def test_dry_run_changes_nothing_on_disk(tmp_path, monkeypatch):
    import json
    curve = {"daily": [{"date": "2030-01-01", "close_equity": 100.0}]}
    evid = {"base_capital": 100.0,
            "days": [{"date": "2030-01-01", "equity_value": 111.0, "apy_pct": 4.0}]}
    (tmp_path / "equity_curve_daily.json").write_text(json.dumps(curve), encoding="utf-8")
    ep = tmp_path / "paper_evidence.json"; ep.write_text(json.dumps(evid), encoding="utf-8")
    before = ep.read_bytes()
    monkeypatch.setattr(rec, "_CURVE", tmp_path / "equity_curve_daily.json")
    monkeypatch.setattr(rec, "_EVID", ep)
    res = rec.reconcile(dry_run=True)
    assert res["fixed"] == 1 and res["dry_run"] is True
    assert ep.read_bytes() == before, "dry-run записал файл"
