"""Публичный верификатор не судит журнал, для которого у него нет рецепта (ADR-282).

Замер 2026-09-09 на живом дереве:

    $ python3 scripts/verify_spa.py data/audit_chain.jsonl
    [A] decision chain : valid=False  length=22810  broken_at=0
    ✗ decision_log: chain broken at row 0
    VERDICT: FAILED

При этом собственный верификатор той же цепочки отвечал
``{'valid': True, 'length': 22810, 'broken_at': None}``. То есть инструмент, которым сайт
предлагает нас проверить, сообщал ПРОВАЛ о честном артефакте. Причин было две, и обе —
«обобщающая ветка»: классификатор объявлял цепочкой решений любую строку с `entry_hash`,
а разбор аргументов дополнительно клал в ту же поверхность любой явно переданный `.jsonl`,
который не удалось распознать («back-compat»).

Хеш-журналов в проекте больше, чем поверхностей верификатора: `audit_chain` несёт
`execution_reconciliation`, `cycle_inputs` — `cycle_inputs`, и оба той же общей формы.

# FROZEN-DATE-OK: historical-incident — числа замера (22810 записей, VERDICT FAILED) и есть
# предмет теста; живых часов в файле нет.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("verify_spa", _ROOT / "scripts" / "verify_spa.py")
vs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(vs)


def _chain_row(seq, event_type, payload, prev):
    canon = json.dumps({"seq": seq, "ts": "2030-01-01T00:00:00+00:00", "event_type": event_type,
                        "payload": payload, "prev_hash": prev},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {"seq": seq, "ts": "2030-01-01T00:00:00+00:00", "event_type": event_type,
            "payload": payload, "prev_hash": prev,
            "entry_hash": hashlib.sha256(canon.encode()).hexdigest()}


def _write_chain(path, event_type, n=3):
    prev = "0" * 64
    rows = []
    for i in range(n):
        r = _chain_row(i, event_type, {"i": i}, prev)
        prev = r["entry_hash"]
        rows.append(r)
    path.write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")
    return path


# ── распознавание: чужой тип события не становится цепочкой решений ───────────────────
@pytest.mark.parametrize("event_type", ["execution_reconciliation", "cycle_inputs",
                                        "cycle", "risk_event", "something_new"])
def test_a_foreign_event_type_is_not_classified_as_the_decision_chain(tmp_path, event_type):
    p = _write_chain(tmp_path / "audit_chain.jsonl", event_type)
    assert vs._sniff_jsonl_kind(p) is None, event_type


@pytest.mark.parametrize("event_type", list(vs.VERIFIABLE_EVENT_TYPES))
def test_every_event_type_with_a_recipe_is_still_recognized(tmp_path, event_type):
    """Обратное направление: типы, для которых рецепт ЕСТЬ, распознаются как прежде."""
    p = _write_chain(tmp_path / "x.jsonl", event_type)
    assert vs._sniff_jsonl_kind(p) is not None, event_type


def test_a_row_without_an_event_type_still_falls_back_to_the_decision_chain(tmp_path):
    """Совместимость сохранена там, где она настоящая: старые строки без `event_type`."""
    p = tmp_path / "decision_log.jsonl"
    p.write_text(json.dumps({"seq": 0, "entry_hash": "a" * 64, "prev_hash": "0" * 64}) + "\n",
                 encoding="utf-8")
    assert vs._sniff_jsonl_kind(p) == "decision_log"


def test_a_file_named_decision_log_is_still_recognized_by_name(tmp_path):
    p = tmp_path / "decision_log.jsonl"
    p.write_text("", encoding="utf-8")
    assert vs._classify_by_name(p) == "decision_log"


# ── разбор аргументов: явный незнакомый файл не занимает поверхность [A] ───────────────
def test_an_explicit_unrecognized_jsonl_is_recorded_not_adopted(tmp_path):
    p = _write_chain(tmp_path / "audit_chain.jsonl", "execution_reconciliation")
    found = vs._resolve_inputs([str(p)]) if hasattr(vs, "_resolve_inputs") else None
    if found is None:
        pytest.fail("_resolve_inputs не найден — проверка не состоялась, а не прошла")
    assert found["decision_log"] is None, "чужой журнал занял поверхность [A]"
    assert p in (found.get("unrecognized") or []), "файл не назван нераспознанным"


def test_an_explicit_real_decision_log_is_still_adopted(tmp_path):
    p = tmp_path / "decision_log.jsonl"
    p.write_text(json.dumps({"seq": 0, "entry_hash": "a" * 64, "prev_hash": "0" * 64}) + "\n",
                 encoding="utf-8")
    found = vs._resolve_inputs([str(p)])
    assert found["decision_log"] == p


def test_the_verifier_never_calls_a_foreign_chain_broken(tmp_path):
    """Итог для пользователя: незнакомый журнал НЕ объявляется сломанным.

    Передан только он ⇒ верификатор честно отказывает «нечего проверять» (fail-CLOSED,
    прежнее и верное поведение). Чего он больше НЕ делает — так это не судит его чужим
    рецептом и не печатает «chain broken at row 0» про валидную цепочку."""
    p = _write_chain(tmp_path / "audit_chain.jsonl", "execution_reconciliation")
    if not hasattr(vs, "run"):
        pytest.fail("vs.run не найден — проверка не состоялась, а не прошла")
    report = vs.run([str(p)])
    assert report.get("decision_chain") is None, "чужой журнал всё ещё судится поверхностью [A]"
    errs = [str(e) for e in (report.get("errors") or [])]
    assert not any("chain broken" in e for e in errs), errs
    assert any("no recognizable public files" in e for e in errs), errs


def test_a_foreign_chain_next_to_a_real_surface_does_not_spoil_the_verdict(tmp_path):
    """Живой случай 09.09: `audit_chain.jsonl` рядом с `book_commitments.jsonl` ⇒ вердикт OK.

    До правки тот же набор давал «✗ decision_log: chain broken at row 0 · VERDICT: FAILED»."""
    foreign = _write_chain(tmp_path / "audit_chain.jsonl", "execution_reconciliation")
    # Настоящая форма строки поверхности [J]: у коммита есть дата решения и его хеш.
    book = tmp_path / "book_commitments.jsonl"
    row = _chain_row(0, "book_commit",
                     {"cycle_date": "2030-01-01", "commitment_hash": "b" * 64,
                      "reveal_delay_days": 1}, "0" * 64)
    book.write_text(json.dumps(row, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False) + "\n", encoding="utf-8")
    report = vs.run([str(foreign), str(book)])
    errs = [str(e) for e in (report.get("errors") or [])]
    assert not any("chain broken" in e for e in errs), errs
    assert report.get("decision_chain") is None
    assert report["ok"] is True, errs


def test_supplying_nothing_verifiable_still_fails_closed(tmp_path):
    """Контроль обратного направления: «не распознан» не смеет проходить как «есть что проверять»."""
    p = _write_chain(tmp_path / "audit_chain.jsonl", "cycle_inputs")
    report = vs.run([str(p)])
    assert report["ok"] is False and report["errors"]
