#!/usr/bin/env python3
"""Контроль двери CLI «заработанное освобождение носителя» В ОБЕ СТОРОНЫ (ADR-1051).

ЗАЧЕМ. До ADR-1051 `carried_to` был параметром БИБЛИОТЕЧНОГО вызова и только им: из
`scripts/orchestrator_queue.py` честная дорога «содержимое уехало ВОТ ТУДА» была
НЕДОСТИЖИМА. Замер цикла #1187 по производителю записей: все ДЕСЯТЬ карточек, закрытых
без машинного критерия, записаны одноразовым `python3 -c` (`argv: "-c"`, десять разных
pid за 24 дня) — то есть сессии шли мимо CLI, а не мимо правила.

Условие при этом НЕ ослаблено ни на байт: судит его та же единственная копия
`carried_release` (ADR-501), и обещанный путь по-прежнему не освобождает ничего. Ровно
это здесь и меряется — ДВЕ сцены, отличающиеся РОВНО существованием названного пути,
и ответы ПРОТИВОПОЛОЖНЫЕ.

Карточка сцены лежит в одноразовом каталоге, а не в трекере: `audit_path_for` не
опознаёт такое дерево и журнал перехода не пишет — живое состояние не трогается.

Только stdlib, оффлайн.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CLI = _REPO / "scripts" / "orchestrator_queue.py"

_CARD = ("---\n"
         "trackerStatus:\n"
         "  type: inbox\n"
         "title: носитель\n"
         "status: done\n"
         "---\n\n"
         "тело\n")


def _scene(tmp_path: Path, *, with_target: bool) -> tuple[Path, Path]:
    card = tmp_path / "inbox-nositel.md"
    card.write_text(_CARD, encoding="utf-8")
    target = tmp_path / "cel-nositelya.md"
    if with_target:
        target.write_text("предмет носителя уехал сюда", encoding="utf-8")
    return card, target


def _run(card: Path, target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLI), "set-status", str(card), "done",
         "--carried-to", str(target),
         "--closed-by", "control:test_queue_cli_carried_release",
         "--evidence", "сцена контроля двери CLI (ADR-1051)"],
        capture_output=True, text=True, cwd=str(card.parent), timeout=180)


def test_an_existing_target_frees_the_carrier_from_the_cli(tmp_path) -> None:
    """Положительная сторона: путь СУЩЕСТВУЕТ ⇒ освобождение записано И НАПЕЧАТАНО."""
    card, target = _scene(tmp_path, with_target=True)
    res = _run(card, target)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    # Печать — часть ответа: молчание сделало бы «освободили носителя» неотличимым от
    # «просто поменяли статус» (инв. #17).
    assert "носитель освобождён" in res.stdout, res.stdout
    assert "carried_to:" in card.read_text(encoding="utf-8"), card.read_text(encoding="utf-8")


def test_a_promised_target_is_refused_by_the_cli(tmp_path) -> None:
    """Обратная сторона: путь НЕ существует ⇒ ОТКАЗ, и карточка не тронута.

    Без этой стороны флаг был бы опт-аутом с нулевой ценой: достаточно было бы его
    написать. Сцена отличается от предыдущей РОВНО существованием файла-цели.
    """
    card, target = _scene(tmp_path, with_target=False)
    before = card.read_text(encoding="utf-8")
    res = _run(card, target)
    assert res.returncode == 2, f"stdout={res.stdout}\nstderr={res.stderr}"
    assert "REFUSED" in res.stderr, res.stderr
    assert card.read_text(encoding="utf-8") == before, "отказавший вызов всё-таки правил карточку"
    assert "носитель освобождён" not in res.stdout, res.stdout


def test_the_flag_is_declared_by_the_cli(tmp_path) -> None:
    """Вопрос «умеет ли инструмент принять вход» задаётся ОТДЕЛЬНО, одним зовом `--help`.

    Дословный урок `pyflakes` (`.claude/rules/deployment.md`): код возврата рабочего
    прогона на этот вопрос не отвечает — рассогласование ВЕРСИЙ доложилось бы как
    находка о проводке.
    """
    res = subprocess.run([sys.executable, str(_CLI), "set-status", "--help"],
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert "--carried-to" in res.stdout, res.stdout
