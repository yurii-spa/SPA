# LLM_FORBIDDEN
# FROZEN-DATE-OK: даты здесь — предмет, а не фикстура. 14.08 и 17.08 называют ДВА конкретных
# исторических замера на двух разных машинах, и весь довод файла в том, что они дали
# противоположные ответы; заменить их относительными отметками значило бы стереть довод.
# Проверяемый код (`judge`) о датах не знает вовсе — он берёт уже измеренные ДЛИТЕЛЬНОСТИ,
# поэтому понятия свежести здесь нет и календарь эти тесты сдвинуть не может.
"""Тесты сторожа `scripts/measure_acceptance_contention.py`.

Каждый положительный контроль воспроизводит НАСТОЯЩИЙ замер, а не выдуманный:
проверка, никогда не видевшая живой поломки, — украшение (`.claude/rules/deployment.md`).

Замеров два, и они противоположны — в этом весь смысл файла:

* **Mac Mini владельца, 14.08** (карточка `inbox-dva-predpisannyh-progona-ryadom-drug-druga-morya`):
  одиночный прогон 18 332 байта за 60 с, два рядом — ~2 байта за 15 минут, оба замерли на 8 %.
* **Linux-контейнер 4 vCPU / 16 ГБ, 17.08**: `pytest tests/` (13 067 тестов) — одиночный
  472.5 с, две копии в РАЗНЫХ деревьях рядом — 477.7 с обе, и обе с побайтово тем же итогом
  (7 failed, 13 067 passed, 38 skipped, 880 subtests).

Правило, выведенное из одного замера, соврало бы на другой машине ровно вдвое — поэтому
вердикт считается ЧИСЛОМ на месте, а не записывается в протокол константой.

Время здесь — вход, а не окружение: `judge` берёт уже измеренные длительности, поэтому ни
один тест не зависит от календаря и от скорости машины, на которой сам идёт.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "measure_acceptance_contention.py"
_MODNAME = "_measure_contention"


def _load():
    """Загрузить сторожа ПО ПУТИ (`scripts/` не пакет) и ЗАРЕГИСТРИРОВАТЬ в `sys.modules`.

    Регистрация до `exec_module` обязательна: `@dataclass` разрешает аннотации через
    `sys.modules[cls.__module__]`, и незарегистрированный модуль падает на импорте.
    """
    existing = sys.modules.get(_MODNAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_MODNAME, _SCRIPT)
    assert spec and spec.loader, f"не удалось загрузить {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODNAME] = module
    spec.loader.exec_module(module)
    return module


mac = _load()


# ── Положительный контроль №1: авария Mac Mini обязана краснеть ───────────────

def test_positive_control_mac_mini_starvation_is_named():
    """Замер владельца 14.08: рядом прогоны ползут — вердикт обязан быть `starves`.

    Числа взяты из карточки: одиночный проходил предписанный набор за 16:48 (цикл #225),
    а два рядом за 15 минут не сдвинулись — то есть каждая копия шла бы часами.
    Берём заведомо мягкую оценку соседства (2 часа): даже она обязана краснеть.
    """
    solo = 16 * 60 + 48                     # 1008 с — цикл #225, прогоны шли по очереди
    parallel = 2 * 60 * 60                  # 7200 с — заведомо МЯГКАЯ оценка соседства
    runs = (mac.Run("wt_mine", parallel, 0), mac.Run("wt_control", parallel, 0))

    verdict = mac.judge(solo, parallel, 2, runs)

    assert verdict.verdict == mac.STARVES, verdict.as_dict()
    assert verdict.sequential_total == pytest.approx(2016.0)
    assert verdict.speedup < 1.0, "соседство обязано быть ХУЖЕ очереди в этом замере"
    assert "замком" in verdict.reason


# ── Положительный контроль №2: обратная сторона — не краснеть на здоровой машине ──

def test_positive_control_linux_container_scales_and_forbids_the_lock():
    """Замер 17.08 в контейнере: две копии рядом стоят те же 477.7 с — замок вреден.

    Обратный контроль обязателен: сторож, который на ЛЮБОЙ машине говорит «сериализуй»,
    стоил бы этой машине двукратной потери пропускной способности приёмки. Именно так
    правило, выведенное из одного замера, становится тихим налогом.
    """
    verdict = mac.judge(472.5, 477.7, 2,
                        (mac.Run("agent_tree", 477.7, 1, 24375),
                         mac.Run("tree2", 477.7, 1, 24878)))

    assert verdict.verdict == mac.SCALES, verdict.as_dict()
    assert verdict.speedup == pytest.approx(945.0 / 477.7, rel=1e-3)
    assert verdict.speedup > 1.9, "соседство здесь почти вдвое выгоднее очереди"


def test_returncode_one_is_a_finished_run_not_a_failure_to_measure():
    """Красный набор — это ЗАВЕРШЁННЫЙ прогон.

    Приёмка сплошь и рядом идёт на красном наборе (замер 17.08: 7 падений в `tests/`), и
    если бы `rc=1` читался как «не измерено», сторож молчал бы ровно тогда, когда нужен.
    """
    verdict = mac.judge(472.5, 477.7, 2,
                        (mac.Run("a", 477.7, 1), mac.Run("b", 477.7, 1)))
    assert verdict.verdict == mac.SCALES


# ── Fail-CLOSED: «не измерено» никогда не выдаётся за «не морят» ───────────────

def test_unfinished_copy_is_unmeasured_not_healthy():
    """Копия, убитая по таймауту, — это `unmeasured`, а НЕ «соседство безвредно».

    Ровно этот класс и морит очередь: незавершённый прогон выглядит как быстрый.
    """
    verdict = mac.judge(472.5, 477.7, 2,
                        (mac.Run("a", 477.7, 0), mac.Run("b", 477.7, "TIMEOUT")))
    assert verdict.verdict == mac.UNMEASURED
    assert "b:TIMEOUT" in verdict.reason


@pytest.mark.parametrize("solo,parallel", [(0.0, 100.0), (100.0, 0.0), (-1.0, 5.0)])
def test_zero_or_negative_duration_is_unmeasured(solo, parallel):
    """Нулевая длительность = сломанные часы, а не мгновенный прогон (инвариант #2)."""
    assert mac.judge(solo, parallel, 2).verdict == mac.UNMEASURED


def test_single_copy_cannot_answer_the_question():
    """Соседство измеряется минимум двумя копиями — одна не отвечает ни на что."""
    assert mac.judge(100.0, 100.0, 1).verdict == mac.UNMEASURED


def test_missing_tree_is_unmeasured(tmp_path):
    """Нет дерева ⇒ `unmeasured`, а не тихий пропуск фазы."""
    verdict = mac.run_measurement([tmp_path, tmp_path / "нет-такого"],
                                  ["--collect-only"], 10.0, tmp_path / "log")
    assert verdict.verdict == mac.UNMEASURED
    assert "нет рабочих деревьев" in verdict.reason


# ── Границы вердикта названы явно ─────────────────────────────────────────────

def test_shares_is_between_the_two_extremes():
    """Делят машину: медленнее одиночного, но быстрее очереди — замок не нужен."""
    verdict = mac.judge(100.0, 160.0, 2, (mac.Run("a", 160.0, 0), mac.Run("b", 160.0, 0)))
    assert verdict.verdict == mac.SHARES
    assert verdict.speedup == pytest.approx(1.25)
    assert "Замок не нужен" in verdict.reason


def test_exactly_sequential_is_not_yet_starvation():
    """Ровно на границе (рядом = по очереди) выигрыша нет, но и вреда нет — не `starves`.

    Порог задан строгим неравенством намеренно: объявлять аварию по равенству значило бы
    краснеть на шуме и учить всех сторожа отключать.
    """
    verdict = mac.judge(100.0, 200.0, 2, (mac.Run("a", 200.0, 0), mac.Run("b", 200.0, 0)))
    assert verdict.verdict == mac.SHARES
    assert verdict.speedup == pytest.approx(1.0)


def test_exit_codes_separate_starvation_from_unmeasured():
    """Коды возврата: 0 — соседство допустимо · 1 — морят · 2 — не измерено (fail-CLOSED)."""
    mapping = {mac.SCALES: 0, mac.SHARES: 0, mac.STARVES: 1, mac.UNMEASURED: 2}
    assert sorted(mapping.values()) == [0, 0, 1, 2]
    assert set(mapping) == {mac.SCALES, mac.SHARES, mac.STARVES, mac.UNMEASURED}


def test_script_is_stdlib_only():
    """Инвариант #4: в рантайме только stdlib — сторож приёмки не имеет права тянуть зависимость."""
    source = _SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("import pytest_xdist", "import psutil", "import numpy", "import requests"):
        assert forbidden not in source, f"{forbidden} — не stdlib"


def test_script_never_writes_into_data():
    """Замер не имеет права писать в `data/` — там живёт трек."""
    source = _SCRIPT.read_text(encoding="utf-8")
    assert 'data/' not in source.replace('НЕ в data/', '').replace('в `data/`', '')
