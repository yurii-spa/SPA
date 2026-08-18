"""Состояние аварийной остановки обязано ПЕРЕЖИВАТЬ восстановление дерева из git.

ЗАМЕР (2026-08-18, карточка `inbox-snyataya-ostanovka-zhivet-v-git-vosstano`).

Аварийный выключатель — это файл `data/kill_switch_active.json`, и читает его
`KillSwitchChecker.check_manual_trigger` (`spa_core/governance/kill_switch.py:522`)
по трёхзначному контракту, а НЕ по «есть файл — стоим»:

    файла нет                       → (False, "not found")
    файл есть, active is False      → (False, "present but active=False")   ← строка 534
    файл есть, любое другое содержимое → (True, ...)                         ← строка 547

Файл при этом ЛЕЖИТ В git (`git ls-files data/kill_switch_active.json`), хотя
`.gitignore` его правилом `data/*.json` исключает: правило не действует на файл,
уже попавший в индекс. Отсюда две ПРОТИВОПОЛОЖНЫЕ опасности, и проверять надо обе.

  (а) ВОСКРЕШЕНИЕ снятой остановки. Владелец снял остановку 10.08 (файл удалён),
      а восстановление из резерва принесёт версию из git обратно. Сегодня это
      безвредно ровно потому, что в git лежит запись с `active: false` от
      2026-06-20 — реальной остановки она не поднимает. Держится это на
      СОДЕРЖИМОМ коммита, а не на замысле: коммит с `active: true` вернул бы
      прод в остановку по решению, которое владелец уже отменил.

  (б) ПОТЕРЯ настоящей остановки — опаснее, и она РЕАЛЬНА СЕГОДНЯ. Пока файл
      отслеживается, `git checkout -- data/` / `git reset --hard` / развёртывание
      из резерва ЗАТИРАЮТ живую остановку версией из коммита: `active: true`
      молча становится `active: false`, и торговля идёт дальше. Аварийный
      выключатель обязан переживать восстановление — иначе путь ВНИЗ есть,
      а удержаться внизу нельзя.

Разница между (а) и (б) и fail-CLOSED. Инвариант «в сомнении — останавливаться»
НЕ означает «хранить остановку в git на всякий случай». Восстановленный файл —
не свидетельство о сегодняшнем риске, а окаменелость июньского решения; его
воспроизведение — это не осторожность, а подмена отменённого решения владельца.
Честный fail-CLOSED здесь: восстановление НЕ приносит никакого состояния
остановки вовсе, а живой писатель (`threat_reactor` / risk-слой) заново судит
о риске по свежим данным — и то, что он записал, восстановление не стирает.

Тесты герметичны и офлайн: одноразовый git-репозиторий под `tmp_path`, реальные
`data/` репозитория не читаются и не пишутся. Проверяются ОБЕ стороны, и каждая
имеет положительный контроль — противоположный режим отслеживания, на котором
ассерт краснеет:

  ОТСЛЕЖИВАЕТСЯ    живая остановка после restore ПОТЕРЯНА  (воспроизводит аварию)
  НЕ ОТСЛЕЖИВАЕТСЯ живая остановка после restore НА МЕСТЕ  (требуемое поведение)

Ничего в money-path эти тесты не меняют: `kill_switch.py`, пороги RiskPolicy v1.0
и ADR-034/048 не затрагиваются — предмет проверки только СОСТАВ git.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spa_core.governance.kill_switch import KillSwitchChecker

_REPO = Path(__file__).resolve().parents[2]
_HALT_FILE = "data/kill_switch_active.json"

# Дословно то, что пишет `threat_reactor` при аварийной остановке
# (`spa_core/monitoring/threat_reactor.py:191`).
_LIVE_HALT = {
    "active": True,
    "reason": "threat_reactor: emergency breaker: HALT",
    "activated_at": "2026-08-18T00:52:40+00:00",
}
# Дословно то, что лежит в коммите сегодня (запись о СНЯТИИ от 2026-06-20).
_COMMITTED_DEACTIVATION = {
    "active": False,
    "deactivated_at": "2026-06-20T15:00:00+00:00",
    "reason": "deactivated: P0-1175 fix applied",
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_repo(tmp_path: Path, *, halt_file_tracked: bool) -> Path:
    """Одноразовый репозиторий, повторяющий состав реального дерева.

    `halt_file_tracked` — единственная переменная опыта: попал ли файл
    остановки в индекс. `.gitignore` в обоих случаях ОДИНАКОВ и файл
    исключает — это и воспроизводит реальность, где правило игнорирования
    бессильно против уже отслеживаемого файла.
    """
    repo = tmp_path / ("tracked" if halt_file_tracked else "untracked")
    (repo / "data").mkdir(parents=True)
    _git(repo.parent, "init", "--quiet", repo.name)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    (repo / ".gitignore").write_text("data/*.json\n")
    (repo / "data" / "keep.txt").write_text("нормальный отслеживаемый файл\n")
    if halt_file_tracked:
        (repo / _HALT_FILE).write_text(json.dumps(_COMMITTED_DEACTIVATION))
        _git(repo, "add", "--force", _HALT_FILE)
    _git(repo, "add", ".gitignore", "data/keep.txt")
    _git(repo, "commit", "--quiet", "-m", "baseline")
    return repo


def _restore_tree(repo: Path) -> None:
    """Восстановление рабочего дерева из git — ровно то, что делает развёртывание
    из резерва, свежий клон или `git reset --hard` на прод-дереве."""
    _git(repo, "checkout", "--", "data/")


def _halted(repo: Path) -> bool:
    triggered, _ = KillSwitchChecker(data_dir=repo / "data").check_manual_trigger()
    return triggered


# ─────────────────────────── сторона (б): остановка обязана выжить ───────────

def test_live_halt_survives_tree_restore_when_file_is_not_tracked(tmp_path: Path) -> None:
    """ТРЕБУЕМОЕ ПОВЕДЕНИЕ: файл остановки вне git → восстановление его не трогает."""
    repo = _make_repo(tmp_path, halt_file_tracked=False)
    (repo / _HALT_FILE).write_text(json.dumps(_LIVE_HALT))
    assert _halted(repo), "предусловие: живая остановка должна читаться как остановка"

    _restore_tree(repo)

    assert _halted(repo), (
        "аварийная остановка ПОТЕРЯНА при восстановлении дерева — "
        "торговля пойдёт дальше вопреки сработавшему выключателю"
    )


def test_live_halt_is_erased_by_tree_restore_when_file_is_tracked(tmp_path: Path) -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к тесту выше: воспроизводит аварию.

    Пока файл отслеживается, восстановление затирает живую остановку версией из
    коммита. Тест краснеет, если состав git перестанет влиять на живое состояние —
    то есть если проверка выше станет бессодержательной.
    """
    repo = _make_repo(tmp_path, halt_file_tracked=True)
    (repo / _HALT_FILE).write_text(json.dumps(_LIVE_HALT))
    assert _halted(repo), "предусловие: живая остановка должна читаться как остановка"

    _restore_tree(repo)

    assert not _halted(repo), (
        "ожидалась воспроизведённая авария: отслеживаемый файл затирается "
        "версией из коммита"
    )
    assert json.loads((repo / _HALT_FILE).read_text())["active"] is False


# ─────────────────── сторона (а): снятая остановка не воскресает ─────────────

def test_restore_does_not_resurrect_a_lifted_halt_when_file_is_not_tracked(
    tmp_path: Path,
) -> None:
    """ТРЕБУЕМОЕ ПОВЕДЕНИЕ: владелец снял остановку (файл удалён) → восстановление
    не приносит НИКАКОГО состояния остановки, и прод поднимается работающим."""
    repo = _make_repo(tmp_path, halt_file_tracked=False)
    (repo / _HALT_FILE).write_text(json.dumps(_LIVE_HALT))
    (repo / _HALT_FILE).unlink()  # решение владельца 10.08: снять остановку
    assert not _halted(repo)

    _restore_tree(repo)

    assert not (repo / _HALT_FILE).exists(), (
        "восстановление вернуло файл остановки, отменённой владельцем"
    )
    assert not _halted(repo), "снятая владельцем остановка воскресла из резерва"


def test_restore_resurrects_the_file_when_it_is_tracked(tmp_path: Path) -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к тесту выше: отслеживаемый файл ВОЗВРАЩАЕТСЯ.

    Сегодня он безвреден только потому, что в коммите лежит `active: false`.
    Тест закрепляет, что защита держится на содержимом коммита, а не на замысле.
    """
    repo = _make_repo(tmp_path, halt_file_tracked=True)
    (repo / _HALT_FILE).unlink()
    assert not (repo / _HALT_FILE).exists()

    _restore_tree(repo)

    assert (repo / _HALT_FILE).exists(), "отслеживаемый файл обязан вернуться из git"
    assert not _halted(repo), (
        "в git лежит запись со СНЯТИЕМ (active=false); остановку она поднимать не должна"
    )


def test_tracked_halt_record_with_active_true_would_resurrect_the_halt(
    tmp_path: Path,
) -> None:
    """Именно то, чего допустить нельзя: коммит с `active: true`.

    Восстановление поднимает прод УЖЕ ОСТАНОВЛЕННЫМ по отменённому решению.
    Тест называет этот режим явно, чтобы он не мог появиться незамеченным.
    """
    repo = _make_repo(tmp_path, halt_file_tracked=True)
    (repo / _HALT_FILE).write_text(json.dumps(_LIVE_HALT))
    _git(repo, "add", "--force", _HALT_FILE)
    _git(repo, "commit", "--quiet", "-m", "остановка попала в коммит")
    (repo / _HALT_FILE).unlink()  # владелец снял остановку

    _restore_tree(repo)

    assert _halted(repo), (
        "контроль: коммит с active=true при восстановлении обязан "
        "воспроизводить остановку — ради этого он и запрещён"
    )


# ─────────────────────────── храповик по реальному репозиторию ───────────────

def test_halt_state_file_is_not_tracked_in_this_repository() -> None:
    """ХРАПОВИК. Файл живого состояния остановки не должен лежать в git.

    КРАСНЫЙ НА СЕГОДНЯШНЕМ СОСТОЯНИИ (2026-08-18) — это и есть находка карточки,
    а не поломка теста: `data/kill_switch_active.json` отслеживается, поэтому
    любое восстановление дерева стирает живую остановку (сторона «б»).

    Снятие с отслеживания — `git rm --cached` + доставка; у `push_to_github.py`
    удаления файлов НЕТ, поэтому способ доставки решает владелец
    (карточка `own-*`). Гасить этот тест, добавляя файл в исключения, ЗАПРЕЩЕНО
    (инвариант 16) — чинить надо состав git.
    """
    out = subprocess.run(
        ["git", "ls-files", "--error-unmatch", _HALT_FILE],
        cwd=_REPO, capture_output=True, text=True,
    )
    assert out.returncode != 0, (
        f"{_HALT_FILE} отслеживается в git — восстановление дерева затрёт "
        f"живую аварийную остановку (замер: kill_switch.py:534 читает active=false "
        f"как снятие). Снять с отслеживания: git rm --cached {_HALT_FILE}"
    )
