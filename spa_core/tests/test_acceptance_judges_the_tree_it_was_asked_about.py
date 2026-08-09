"""Приёмка обязана судить ТО дерево, о котором спросили, — целиком, а не наполовину.

Находка цикла #172 звучала мягко: на пустом дереве `artifacts_overdue` приходит
пустым списком вместо вердикта. Причина оказалась крупнее формулировки.

`run_acceptance(repo_root=X)` брал признак worktree у `X`, а свежесть артефактов
мерил в `_REPO_ROOT/data` — каталоге дерева, из которого ИМПОРТИРОВАН модуль.
Две половины одного отчёта судили разные деревья, и отчёт называл только одно.

Почему это не косметика. Правило доставки (`.claude/rules/deployment.md`) требует
гонять приёмку до и после любого изменения прод-дерева, а money-path правится
только в изолированном worktree — то есть штатный, предписанный вызов выглядит
ровно так: приёмка спрашивает про ПРОД, а исполняется из worktree. В этом вызове
свежесть мерилась по git-checkout'у, который свеж ПО ПОСТРОЕНИЮ (mtime = момент
создания worktree). Ответ — уверенное «просроченных артефактов нет» и `status: OK`
про дерево, которого никто не смотрел.

Это зеркало аварии 2026-08-08 из шапки `test_acceptance_knows_its_tree`: там
неверное дерево дало ложную ТРЕВОГУ, здесь — ложную ТИШИНУ. Тишина опаснее:
ложную тревогу идут проверять, а «чистый счёт» закрывают не читая. Родовой класс
проекта — сторож честно отвечает на свой вопрос, а читается как ответ на нужный.

Каждый тест здесь — положительный контроль: на неисправленном модуле краснеет.
Проверка в ОБЕ стороны обязательна — «чинить» сторожа, сделав его всегда
пессимистичным, значит завести вечную ложную тревогу, которую выключат.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from spa_core.monitoring import deployment_acceptance as acc


def _tree(root: Path, *, worktree: bool = False) -> Path:
    """Рабочее дерево: у обычного `.git` — каталог, у worktree — файл-ссылка."""
    root.mkdir(parents=True, exist_ok=True)
    if worktree:
        (root / ".git").write_text("gitdir: /elsewhere/.git/worktrees/w\n", encoding="utf-8")
    else:
        (root / ".git").mkdir(exist_ok=True)
    return root


def _data(root: Path, ages_hours: dict) -> Path:
    """data/ с артефактами заданного ВОЗРАСТА — отметки относительные, не даты.

    Порядок предпочтения из правила доставки: литеральная дата в фикстуре свежести
    протухает от одного хода календаря.
    """
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for name, age in ages_hours.items():
        f = d / name
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (now - age * 3600, now - age * 3600))
    return d


STALE = {"current_positions.json": 99.0, "adapter_status.json": 99.0, "agent_health.json": 99.0}
FRESH = {"current_positions.json": 1.0, "adapter_status.json": 1.0, "agent_health.json": 1.0}


@pytest.fixture()
def other_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Дерево, ИЗ КОТОРОГО импортирован модуль, — то самое `_REPO_ROOT`.

    Подменяем его явно: иначе тест зависел бы от свежести живого `data/` репозитория
    и молчал бы ровно тогда, когда должен кричать.
    """
    other = _tree(tmp_path / "imported_from")
    monkeypatch.setattr(acc, "_REPO_ROOT", other)
    return other


# ── тот самый fail-OPEN ─────────────────────────────────────────────────────


def test_stale_prod_is_not_declared_clean_because_the_worktree_is_fresh(
    tmp_path: Path, other_tree: Path,
) -> None:
    """ГЛАВНЫЙ положительный контроль: спросили про прод — отвечать про прод.

    Прод протух (99ч), дерево-с-кодом свежее. До починки вердикт брался у второго:
    `artifacts_overdue == []`. Именно так предписанный правилом вызов «приёмка из
    worktree про прод» выдавал чистый счёт о непроверенном дереве.
    """
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")
    _data(prod, STALE)

    doc = acc.run_acceptance(repo_root=prod, modules=(), write=False)

    overdue = {a["artifact"] for a in doc["artifacts_overdue"]}
    assert overdue == set(STALE), "просрочка ПРОДА обязана быть названа поимённо"
    assert doc["artifacts_unchecked"] is None, "обычное дерево — свежесть измерима"
    assert doc["status"] != acc.OK, "протухшее дерево не может получить чистый счёт"


def test_fresh_prod_is_not_slandered_because_the_imported_tree_is_stale(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Обратная сторона: не заменить ложную тишину на ложную тревогу.

    Починка «мерить всегда пессимистично» покрасила бы это красным, а в проде
    завела бы вечную тревогу — то есть научила бы выключать проверку.
    """
    _data(other_tree, STALE)
    prod = _tree(tmp_path / "prod")
    _data(prod, FRESH)

    doc = acc.run_acceptance(repo_root=prod, modules=(), write=False)

    assert doc["artifacts_overdue"] == [], "свежий прод не обязан отвечать за чужое дерево"


# ── «артефактов нет вовсе» — это вердикт, а не пустой список ────────────────


def test_a_tree_without_data_at_all_gets_a_verdict_naming_the_cause(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Находка карточки в исходной формулировке: молчание — не пропуск.

    Причина названа отдельно от «работа не запускалась»: два состояния лечатся
    по-разному, и слить их в одну строку значит спрятать второе.
    """
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")  # data/ намеренно НЕ создаём

    doc = acc.run_acceptance(repo_root=prod, modules=(), write=False)

    assert len(doc["artifacts_overdue"]) == len(acc.SCHEDULED_ARTIFACTS)
    problems = {a["problem"] for a in doc["artifacts_overdue"]}
    assert all("no data/ directory" in p for p in problems), problems
    assert doc["status"] != acc.OK


def test_missing_file_in_an_existing_data_dir_still_says_never_produced(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Прежний диагноз не размыт: каталог есть, файла нет — «never produced»."""
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")
    _data(prod, {"agent_health.json": 1.0})  # каталог есть, двух файлов нет

    doc = acc.run_acceptance(repo_root=prod, modules=(), write=False)

    problems = {a["artifact"]: a["problem"] for a in doc["artifacts_overdue"]}
    assert problems == {"current_positions.json": "never produced",
                        "adapter_status.json": "never produced"}


# ── квитанция ложится в судимое дерево ──────────────────────────────────────


def test_the_receipt_lands_in_the_tree_that_was_judged(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Отчёт о проде, записанный в data/ worktree, не прочитает никто.

    Тот же дефект, что и в вердикте: путь брался у дерева-с-кодом.
    """
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")
    _data(prod, FRESH)

    acc.run_acceptance(repo_root=prod, modules=(), write=True)

    landed = prod / "data" / acc.STATE_FILENAME
    assert landed.is_file(), "квитанция обязана лежать в судимом дереве"
    assert not (other_tree / "data" / acc.STATE_FILENAME).exists(), \
        "и не обязана появляться в дереве, из которого импортирован модуль"
    assert json.loads(landed.read_text(encoding="utf-8"))["monitor"] == "deployment_acceptance"


# ── приоритет источников: явное сильнее выведенного ─────────────────────────


def test_an_explicit_data_dir_still_beats_repo_root(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Явное указание вызывающего — осознанное решение, его не переопределяем."""
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")
    _data(prod, FRESH)
    explicit = _data(tmp_path / "explicit", STALE)

    doc = acc.run_acceptance(repo_root=prod, data_dir=explicit, modules=(), write=False)

    assert {a["artifact"] for a in doc["artifacts_overdue"]} == set(STALE), \
        "мерить обязаны явно названный каталог, а не выведенный из repo_root"


def test_without_repo_root_the_imported_tree_is_still_the_answer(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Прод-путь не тронут: не спросили про дерево — отвечаем про своё.

    Ровно так приёмку зовёт агент (`python3 -m ...deployment_acceptance` без
    аргументов), и это поведение менять нельзя.
    """
    _data(other_tree, STALE)

    assert {a["artifact"] for a in acc.check_scheduled_artifacts()} == set(STALE)


def test_direct_caller_of_the_freshness_check_can_name_the_tree(
    tmp_path: Path, other_tree: Path,
) -> None:
    """`check_scheduled_artifacts` — публичная функция; ей тоже нужно знать дерево."""
    _data(other_tree, FRESH)
    prod = _tree(tmp_path / "prod")
    _data(prod, STALE)

    assert {a["artifact"] for a in acc.check_scheduled_artifacts(repo_root=prod)} == set(STALE)


def test_worktree_detection_and_freshness_now_judge_the_same_tree(
    tmp_path: Path, other_tree: Path,
) -> None:
    """Связка, из-за расхождения которой дефект и жил.

    Спросили про WORKTREE: признак срабатывает у `repo_root`, свежесть обязана
    остаться НЕ ИЗМЕРЕНОЙ — а не быть посчитанной по третьему дереву.
    """
    _data(other_tree, STALE)
    wt = _tree(tmp_path / "wt", worktree=True)
    _data(wt, STALE)

    doc = acc.run_acceptance(repo_root=wt, modules=(), write=False)

    assert doc["artifacts_unchecked"], "из worktree свежесть обязана быть НЕ ИЗМЕРЕНА"
    assert doc["artifacts_overdue"] == [], "нельзя утверждать просрочку про чужое дерево"
