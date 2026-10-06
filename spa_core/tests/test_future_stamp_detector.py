"""future_stamp_detector — три исхода (инв. #17), контракт C3(d)/C8(d) ADR-580.

Время — ВХОД (`.claude/rules/deployment.md`, приём №1): `now` передаётся явно, обе стороны
сравнения закреплены друг за друга, литеральной даты как предмета здесь нет.

# FROZEN-DATE-OK: injected-clock — все отметки выводятся из NOW и передаются в
# scan_data_dir(..., now=NOW); единственный путь, где время берётся у стенных часов, —
# main() (`datetime.now(timezone.utc)`), и test_main_cli_exit_codes подменяет `fsd.datetime`
# на класс, чей `.now()` возвращает тот же NOW, так что обе стороны сравнения закреплены
# и там.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import future_stamp_detector as fsd

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FixedNow(datetime):
    """``datetime`` подкласс, чей ``.now()`` всегда отдаёт модульный якорь NOW.

    Подставляется в ``fsd.datetime`` только для теста CLI-входа (``main()``), который
    сам вызывает стенные часы и не принимает ``now=`` параметром. Всё остальное
    поведение (``fromisoformat`` и конструктор) наследуется без изменений.
    """

    @classmethod
    def now(cls, tz=None):  # noqa: D102 - сигнатура stdlib
        return NOW if tz is not None else NOW.replace(tzinfo=None)


def _write(tmp_path: Path, name: str, doc: dict) -> None:
    (tmp_path / name).write_text(json.dumps(doc), encoding="utf-8")


def test_no_json_files_is_measured_zero_not_unchecked(tmp_path):
    """Каталог есть, артефактов нет — ``OK`` (измерено и равно нулю), не «не измерено»."""
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK
    assert doc["corrupt"] == []


def test_a_future_stamp_is_corrupt(tmp_path):
    _write(tmp_path, "x.json", {"generated_at": (NOW + timedelta(hours=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.CORRUPT
    assert doc["corrupt"][0]["path"] == "x.json"
    assert doc["corrupt"][0]["stamp_key"] == "generated_at"
    assert doc["corrupt"][0]["ahead_minutes"] == pytest.approx(60.0, abs=0.1)


def test_a_stamp_within_skew_is_not_corrupt(tmp_path):
    """Инъекция / мелкий перекос часов — не порча: допуск есть не просто так."""
    _write(tmp_path, "x.json", {"generated_at": (NOW + timedelta(minutes=5)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK


def test_a_past_stamp_is_not_corrupt(tmp_path):
    _write(tmp_path, "x.json", {"generated_at": (NOW - timedelta(days=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK


def test_missing_data_dir_is_unchecked_with_a_reason(tmp_path):
    """Каталога нет вовсе — ТРЕТИЙ исход, а не ноль находок."""
    doc = fsd.scan_data_dir(tmp_path / "нет-такого", now=NOW)
    assert doc["status"] == fsd.UNCHECKED
    assert doc["reason"]


def test_non_json_and_unparseable_files_are_skipped_not_fatal(tmp_path):
    (tmp_path / "junk.json").write_text("не json вовсе{{{", encoding="utf-8")
    (tmp_path / "note.txt").write_text("игнор", encoding="utf-8")
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK
    assert doc["corrupt"] == []


def test_a_file_without_any_known_stamp_key_is_named_unchecked_not_silent(tmp_path):
    """F13 (ADR-580 §C3(d), REVIEW_1 amendment, инв. #17): раньше файл без
    распознанного ключа ПРОСТО пропускался — он не числился ни находкой, ни
    замером, и исчезал из отчёта без следа (ровно случай
    `telegram_owner_decisions.json`, у которого отметки верхнего уровня нет
    вовсе). Теперь это НАЗВАННЫЙ третий исход на файл: ``unchecked_files``."""
    _write(tmp_path, "x.json", {"unrelated_field": 1})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK
    assert doc["stamps_read"] == 0
    assert doc["unchecked_files"] == [{"path": "x.json", "reason": "no_stamp"}]


def test_zulu_suffix_is_the_same_moment_as_explicit_offset(tmp_path):
    """Производитель вправе печатать ``Z`` вместо ``+00:00`` — тот же момент."""
    stamp = (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    _write(tmp_path, "x.json", {"generated_at": stamp})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.CORRUPT


def test_naive_stamp_is_unchecked_not_guessed_as_utc(tmp_path):
    """F13 (ADR-580 §C3(d), REVIEW_1 amendment) — CHANGED ASSERTION, инв. #16:
    эта проверка раньше требовала, чтобы наивная (без пояса) отметка молча
    читалась как UTC и давала CORRUPT, если «окажется» из будущего. REVIEW_1
    назвал ровно эту подстановку ложной находкой: писатель, выпустивший
    наивное МЕСТНОЕ время (например +02:00), под старым допущением выглядел
    бы на два часа «из будущего» и получал CORRUPT не по делу. Угадывание
    пояса — тот же класс подмены, который инвариант #17 запрещает (замер
    выдан за измерение). Новое поведение: пояс не назван ⇒ ``unchecked_files``
    с причиной ``"naive"``, никогда не угадываемый UTC. Запись о решении —
    `docs/journal/2026-W40.md` (эта сессия)."""
    naive = (NOW + timedelta(hours=2)).replace(tzinfo=None).isoformat()
    _write(tmp_path, "x.json", {"generated_at": naive})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK, "наивная отметка не имеет права стать находкой угадыванием"
    assert doc["corrupt"] == []
    assert doc["unchecked_files"] == [
        {"path": "x.json", "stamp_key": "generated_at", "stamp": naive, "reason": "naive"}]


def test_a_genuinely_future_naive_stamp_still_never_becomes_corrupt(tmp_path):
    """Положительный контроль обратной стороны: даже отметка, которая была бы
    CORRUPT при любом разумном поясе (намного дальше допуска в любую сторону
    часового смещения), всё равно уходит в ``unchecked`` — пояс не назван,
    поэтому сравнивать нечем, а не «наверное, не страшно»."""
    naive = (NOW + timedelta(days=400)).replace(tzinfo=None).isoformat()
    _write(tmp_path, "x.json", {"generated_at": naive})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK
    assert doc["unchecked_files"][0]["reason"] == "naive"


def test_updated_at_is_a_recognised_stamp_key(tmp_path):
    """F13 (ADR-580 §C3(d), REVIEW_1 amendment): `data/telegram_bot_capabilities.json`
    (маячок бота, область OWNER_CONTROL_HEALTH) несёт отметку под ключом
    ``updated_at`` — буквальная форма реального файла, сверенная read-only
    05.10. Без этого ключа в `STAMP_KEYS` файл не читался этим прибором ВООБЩЕ."""
    _write(tmp_path, "telegram_bot_capabilities.json",
          {"schema_version": 1, "updated_at": (NOW + timedelta(hours=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW,
                            filenames=["telegram_bot_capabilities.json"])
    assert doc["status"] == fsd.CORRUPT
    assert doc["corrupt"][0]["stamp_key"] == "updated_at"


def test_unparseable_stamp_value_is_named_unchecked_not_silent(tmp_path):
    _write(tmp_path, "x.json", {"generated_at": "не-дата-вовсе"})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK
    assert doc["unchecked_files"] == [
        {"path": "x.json", "stamp_key": "generated_at",
         "stamp": "не-дата-вовсе", "reason": "unparseable"}]


def test_stamp_key_priority_matches_the_g97_probe_order(tmp_path):
    """``generated_at`` — канон; остальные ключи читаются только в его отсутствие."""
    _write(tmp_path, "x.json", {"as_of": (NOW + timedelta(hours=1)).isoformat(),
                                "generated_at": (NOW - timedelta(days=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW)
    assert doc["status"] == fsd.OK, "generated_at (прошлое) обязан победить as_of (будущее)"


def test_filenames_param_narrows_the_scan_to_a_named_scope(tmp_path):
    """C3: у каждой области свой допуск — файл не из списка не считается, даже
    если у него отметка из будущего. OWNER_CONTROL_HEALTH не судит за
    PRODUCT_DATA_HEALTH (`equity_curve_daily.json`), у которой свой, отдельно
    откалиброванный допуск в `agent_health_monitor.CLOCK_SKEW_H`."""
    _write(tmp_path, "owner_decision_pending.json",
           {"generated_at": (NOW + timedelta(hours=1)).isoformat()})
    _write(tmp_path, "equity_curve_daily.json",
           {"generated_at": (NOW + timedelta(hours=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW, filenames=["owner_decision_pending.json"])
    assert doc["files_scanned"] == 1
    assert [c["path"] for c in doc["corrupt"]] == ["owner_decision_pending.json"]


def test_empty_filenames_list_is_a_completed_zero_scan(tmp_path):
    """Пустой НАЗВАННЫЙ список — законченный замер по пустому населению (``OK``),
    а не повод падать и не «не измерено»."""
    _write(tmp_path, "owner_decision_pending.json",
           {"generated_at": (NOW + timedelta(hours=1)).isoformat()})
    doc = fsd.scan_data_dir(tmp_path, now=NOW, filenames=[])
    assert doc["status"] == fsd.OK
    assert doc["files_scanned"] == 0


def test_a_named_file_that_does_not_exist_is_simply_absent_not_fatal(tmp_path):
    doc = fsd.scan_data_dir(tmp_path, now=NOW, filenames=["нет-такого-файла.json"])
    assert doc["status"] == fsd.OK
    assert doc["files_scanned"] == 0


def test_owner_control_files_constant_names_the_inc1_artifact():
    """`owner_decision_pending.json` — буквально файл из INC-1 — обязан быть в области."""
    assert "owner_decision_pending.json" in fsd.OWNER_CONTROL_FILES


def test_main_cli_exit_codes(tmp_path, capsys, monkeypatch):
    """0 — OK, 1 — CORRUPT, 2 — НЕ ИЗМЕРЕНО. Коды возврата различают три исхода.

    ``main()`` сам берёт `datetime.now(timezone.utc)` — единственное место модуля,
    где время не входной параметр. Подменяем `fsd.datetime` на класс с тем же
    якорем NOW, что и остальной файл, и выводим отметку из НЕГО же (``NOW + 1ч``),
    а не из произвольной будущей константы: обе стороны сравнения закреплены.
    """
    monkeypatch.setattr(fsd, "datetime", _FixedNow)
    assert fsd.main(["--data-dir", str(tmp_path)]) == 0

    _write(tmp_path, "x.json", {"generated_at": (NOW + timedelta(hours=1)).isoformat()})
    assert fsd.main(["--data-dir", str(tmp_path)]) == 1

    assert fsd.main(["--data-dir", str(tmp_path / "нет-такого")]) == 2
