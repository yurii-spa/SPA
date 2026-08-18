"""Сторож КЛАССА: что из `data/` можно возить в git, а что откат сделает опасным.

ПРЕДЫСТОРИЯ. `spa_core/tests/test_halt_state_survives_tree_restore.py` закрыл ОДИН
файл: `data/kill_switch_active.json` лежал в индексе, и `git checkout -- data/`
затирал живую аварийную остановку версией из коммита. Замер того же дня показал,
что остановка была не одна такая: мимо разрешающего списка `.gitignore:151-154`
отслеживается 322 файла состояния (296 в корне `data/`, 26 в подкаталогах).
Сторож на один файл такую аварию не закрывает — здесь сторож на КЛАСС.

Предмет проверки — `spa_core/monitoring/data_git_policy.py`: закрытый список
«что можно возить» + разбор состава git по риску отката. Money-path не
затрагивается: `kill_switch.py`, пороги RiskPolicy v1.0, ADR-034/048, дашборд и
деплой не читаются и не меняются. Живой трек `data/equity_curve_daily.json`
здесь только ИМЯ в списке — файл не открывается ни на чтение, ни на запись.

ТЕСТЫ ГЕРМЕТИЧНЫ: одноразовые git-репозитории под `tmp_path`, никакой сети и
никаких реальных `data/` — кроме трёх ХРАПОВИКОВ в конце, которые по замыслу
судят состав именно этого репозитория.

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ В ОБЕ СТОРОНЫ (правило `.claude/rules/deployment.md`:
проверка, не видевшая настоящей поломки, — украшение):

  сторона (а) ВРЕДНО  отслеживается  → живая остановка ПОТЕРЯНА при откате  ← авария
                      не отслеживается → живая остановка НА МЕСТЕ            ← норма
  сторона (в) КАНОН   отслеживается   → канон приезжает в свежий клон        ← норма
                      не отслеживается → канон в клоне ОТСУТСТВУЕТ           ← авария
"""
# FROZEN-DATE-OK: даты здесь — САМ ПРЕДМЕТ, а не фикстура свежести. Это дословные
# значения, лежащие в коммитах на 2026-08-18: offset getUpdates от 2026-06-18
# (`data/tg_bot_v2_offset.json`) и запись о снятии остановки от 2026-06-20
# (`data/kill_switch_active.json`). Ни один ассерт не судит о возрасте и не
# сравнивает с сегодняшним днём — сравниваются ЗНАЧЕНИЯ до и после отката, —
# поэтому сдвиг календаря эти тесты не трогает.
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from spa_core.governance.kill_switch import KillSwitchChecker
from spa_core.monitoring import data_git_policy as policy

_REPO = Path(__file__).resolve().parents[2]
_HALT = "data/kill_switch_active.json"
_CANON_SAMPLE = "data/equity_curve_daily.json"   # только имя, файл не читается

# Дословно то, что пишет threat_reactor при аварийной остановке
# (`spa_core/monitoring/threat_reactor.py:191`).
_LIVE_HALT = {"active": True, "reason": "threat_reactor: emergency breaker: HALT"}
_COMMITTED_LIFTED = {"active": False, "reason": "deactivated: P0-1175 fix applied"}
# Канон трека — то, что ОБЯЗАНО быть проверяемо из репозитория.
_CANON_PAYLOAD = {"days": 53, "note": "канон трека, публикуется сайтом"}


# ────────────────────────────── герметичный репозиторий ──────────────────────

def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_repo(tmp_path: Path, name: str, tracked: dict, untracked: dict) -> Path:
    """Репозиторий, повторяющий устройство реального: `.gitignore` исключает
    `data/*.json`, но на уже добавленные в индекс файлы это правило не действует."""
    repo = tmp_path / name
    (repo / "data").mkdir(parents=True)
    _git(repo.parent, "init", "--quiet", repo.name)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text("data/*.json\n")
    # обычный отслеживаемый файл в data/ — иначе `git checkout -- data/` не имеет
    # чего восстанавливать и падает pathspec'ом, подменяя предмет опыта
    (repo / "data" / "keep.txt").write_text("нормальный отслеживаемый файл\n")
    _git(repo, "add", ".gitignore", "data/keep.txt")
    for rel, doc in tracked.items():
        (repo / rel).write_text(json.dumps(doc))
        _git(repo, "add", "--force", rel)
    _git(repo, "commit", "--quiet", "-m", "baseline")
    for rel, doc in untracked.items():
        (repo / rel).write_text(json.dumps(doc))
    return repo


def _restore_tree(repo: Path) -> None:
    """Ровно то, что делает развёртывание из резерва / `git reset --hard`."""
    _git(repo, "checkout", "--", "data/")


def _halted(repo: Path) -> bool:
    triggered, _ = KillSwitchChecker(data_dir=repo / "data").check_manual_trigger()
    return triggered


# ══════════════ сторона (а): ВРЕДНО — откат возвращает опасное значение ══════

def test_harmful_file_tracked_loses_live_halt_on_restore(tmp_path: Path) -> None:
    """ВОСПРОИЗВЕДЕНИЕ АВАРИИ 2026-08-18 (образец класса H-SAFETY).

    Пока файл состояния остановки отслеживается, откат подменяет живую
    остановку версией из коммета `active: false` — торговля идёт дальше.
    """
    repo = _make_repo(tmp_path, "tracked", {_HALT: _COMMITTED_LIFTED}, {})
    (repo / _HALT).write_text(json.dumps(_LIVE_HALT))
    assert _halted(repo), "предусловие: живая остановка должна читаться как остановка"

    _restore_tree(repo)

    assert not _halted(repo), (
        "ожидалась воспроизведённая авария: отслеживаемый файл затирается версией из коммита"
    )
    assert json.loads((repo / _HALT).read_text())["active"] is False


def test_harmful_file_untracked_keeps_live_halt_on_restore(tmp_path: Path) -> None:
    """ТРЕБУЕМОЕ ПОВЕДЕНИЕ — вторая сторона того же опыта."""
    repo = _make_repo(tmp_path, "untracked", {}, {_HALT: _LIVE_HALT})
    assert _halted(repo)

    _restore_tree(repo)

    assert _halted(repo), (
        "аварийная остановка ПОТЕРЯНА при восстановлении дерева — "
        "путь вниз есть, а удержаться внизу нельзя"
    )


def test_replay_state_tracked_rewinds_the_telegram_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ВТОРОЙ ЗАМЕР ТОГО ЖЕ КЛАССА, механизм H-REPLAY (авария ещё не случившаяся).

    `data/tg_bot_v2_offset.json` — позиция `getUpdates`. В коммите лежит offset
    от 2026-06-18. Пока файл отслеживается, откат отматывает бота на два месяца
    назад, и он ЗАНОВО обрабатывает уже исполненные команды владельца.
    Читатель настоящий — `TelegramBot._read_offset` (`telegram/bot.py:363`).
    """
    from spa_core.telegram import bot as tg

    rel = "data/tg_bot_v2_offset.json"
    committed = {"offset": 815192365, "updated_at": "2026-06-18T20:11:43+00:00"}
    live = {"offset": 900000000, "updated_at": "2026-08-18T09:00:00+00:00"}

    repo = _make_repo(tmp_path, "replay_tracked", {rel: committed}, {})
    (repo / rel).write_text(json.dumps(live))
    monkeypatch.setattr(tg, "OFFSET_FILE", repo / rel)
    assert tg.TelegramBot._read_offset(None) == 900000000

    _restore_tree(repo)

    assert tg.TelegramBot._read_offset(None) == 815192365, (
        "ожидалась воспроизведённая перемотка: отслеживаемый offset откатывается к июню"
    )


def test_replay_state_untracked_keeps_the_telegram_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ТРЕБУЕМОЕ ПОВЕДЕНИЕ — вторая сторона: вне git offset переживает откат."""
    from spa_core.telegram import bot as tg

    rel = "data/tg_bot_v2_offset.json"
    repo = _make_repo(tmp_path, "replay_untracked", {}, {rel: {"offset": 900000000}})
    monkeypatch.setattr(tg, "OFFSET_FILE", repo / rel)

    _restore_tree(repo)

    assert tg.TelegramBot._read_offset(None) == 900000000, (
        "позиция getUpdates ПОТЕРЯНА при восстановлении дерева — "
        "бот переисполнит уже обработанные команды владельца"
    )


def test_policy_calls_the_halt_file_harmful() -> None:
    """Сторож обязан УЗНАВАТЬ эталон класса, а не просто иметь его в тексте."""
    assert policy.classify(_HALT) == policy.HARMFUL
    assert policy.harm_class(_HALT) == "H-SAFETY"


# ══════════════ сторона (в): КАНОН — файл ОБЯЗАН быть в git ══════════════════

def _clone(repo: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", "--quiet", str(repo), str(dest)],
                   check=True, capture_output=True)
    return dest


def test_canon_file_tracked_arrives_in_a_fresh_clone(tmp_path: Path) -> None:
    """ТРЕБУЕМОЕ ПОВЕДЕНИЕ: канон трека приезжает в свежий клон — числа сайта
    проверяемы из репозитория."""
    repo = _make_repo(tmp_path, "canon_tracked", {_CANON_SAMPLE: _CANON_PAYLOAD}, {})
    clone = _clone(repo, tmp_path / "clone_ok")

    assert (clone / _CANON_SAMPLE).exists(), "канон обязан приезжать в клон"
    assert json.loads((clone / _CANON_SAMPLE).read_text())["days"] == 53


def test_canon_file_untracked_is_absent_in_a_fresh_clone(tmp_path: Path) -> None:
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к тесту выше: воспроизводит вторую аварию карточки.

    Канон трека, оставшийся вне git, существует ТОЛЬКО на живом хосте: свежий
    клон/аудит его не видит, и опубликованное сайтом число нечем подтвердить.
    """
    repo = _make_repo(tmp_path, "canon_untracked", {}, {_CANON_SAMPLE: _CANON_PAYLOAD})
    clone = _clone(repo, tmp_path / "clone_bad")

    assert not (clone / _CANON_SAMPLE).exists(), (
        "контроль: нетслеживаемый канон обязан отсутствовать в клоне — "
        "ради этого он и обязан быть в git"
    )


def test_policy_calls_the_track_canon_canon() -> None:
    assert policy.classify(_CANON_SAMPLE) == policy.CANON
    assert policy.harm_class(_CANON_SAMPLE) is None


# ══════════════ разбор состава: обе стороны и закрытость списка ══════════════

def test_audit_flags_a_harmful_file_that_is_tracked() -> None:
    """Инъекция состава — реальный репозиторий не читается.

    Взят именно файл остановки: он снят с отслеживания сегодня, и сторож обязан
    покраснеть, если тот вернётся в индекс. Уже известный долг (25 файлов из
    `data_git_baseline.json`) здесь не сработал бы — он подавлен храповиком,
    и на нём проверка была бы бессодержательной.
    """
    viol = policy.audit(tracked=[_HALT])
    kinds = {(v.path, v.kind) for v in viol}
    assert (_HALT, "TRACKED_HARMFUL") in kinds


def test_audit_is_silent_when_the_same_harmful_file_is_absent() -> None:
    """Вторая сторона: без вредного файла тот же вход нарушений не даёт."""
    viol = policy.audit(tracked=[])
    assert not [v for v in viol if v.kind == "TRACKED_HARMFUL"]


def test_audit_flags_canon_that_is_missing_from_git() -> None:
    viol = policy.audit(tracked=[])
    missing = {v.path for v in viol if v.kind == "CANON_NOT_TRACKED"}
    assert _CANON_SAMPLE in missing
    assert "data/paper_evidence.json" in missing


def test_audit_is_silent_when_canon_is_tracked() -> None:
    viol = policy.audit(tracked=sorted(policy._CANON))
    assert not [v for v in viol if v.kind == "CANON_NOT_TRACKED"]


def test_allowlist_is_CLOSED_unknown_state_file_is_a_violation() -> None:
    """Список «что можно возить» ЗАКРЫТ.

    Новый файл состояния, не названный ни в одном из трёх списков, обязан
    краснеть — иначе сторож ловил бы только уже известное, а следующая
    `kill_switch_active.json` приехала бы молча.
    """
    viol = policy.audit(tracked=sorted(policy._CANON) + ["data/brand_new_state.json"])
    unknown = {v.path for v in viol if v.kind == "UNCLASSIFIED"}
    assert unknown == {"data/brand_new_state.json"}


def test_canon_directories_are_allowed_wholesale_but_only_the_named_ones() -> None:
    """Негации-каталоги разрешены целиком; посторонний каталог — нет."""
    viol = policy.audit(tracked=sorted(policy._CANON) + [
        "data/strategy_cards/new_card.json",
        "data/some_other_dir/state.json",
    ])
    flagged = {v.path for v in viol}
    assert "data/strategy_cards/new_card.json" not in flagged
    assert "data/some_other_dir/state.json" in flagged


def test_every_harmful_entry_names_its_mechanism_and_its_evidence() -> None:
    """Отнесение к «вредно» обязано быть обосновано потребителем в коде, а не мнением."""
    allowed = {"H-SAFETY", "H-CAPITAL", "H-LEDGER", "H-REPLAY", "H-JUNK"}
    for path, (mech, why) in policy._HARMFUL.items():
        assert mech in allowed, f"{path}: неизвестный механизм вреда {mech}"
        assert len(why) > 40, f"{path}: обоснование слишком короткое, чтобы быть замером"


def test_classes_do_not_overlap() -> None:
    assert not (set(policy._CANON) & set(policy._HARMFUL))
    base = policy.load_baseline()
    assert not (set(base["derived_tolerated"]) & set(policy._HARMFUL))
    assert not (set(base["derived_tolerated"]) & set(policy._CANON))


# ══════════════ ХРАПОВИКИ по РЕАЛЬНОМУ репозиторию ══════════════════════════

# Замер 2026-08-18 на HEAD. Обе величины могут ТОЛЬКО УМЕНЬШАТЬСЯ.
# Поднять число, чтобы погасить падение, ЗАПРЕЩЕНО (инвариант 16 CLAUDE.md):
# красный здесь означает, что в git приехал новый файл состояния.
_HARMFUL_DEBT_BASELINE = 24
_DERIVED_TOLERATED_BASELINE = 283


def test_no_unclassified_data_file_is_tracked_in_this_repository() -> None:
    """Всякий отслеживаемый `data/**` назван в одном из трёх списков."""
    unknown = [v for v in policy.audit(_REPO) if v.kind == "UNCLASSIFIED"]
    assert not unknown, (
        "в git приехали файлы data/**, не разобранные по риску отката:\n"
        + "\n".join(f"  {v.path}" for v in unknown)
        + "\nКлассифицировать в spa_core/monitoring/data_git_policy.py "
          "(CANON / HARMFUL / derived_tolerated), а не добавлять в базу ради зелёного."
    )


def test_no_NEW_rollback_harmful_file_is_tracked() -> None:
    """Ни один вредный файл СВЕРХ известного долга не отслеживается."""
    new = [v for v in policy.audit(_REPO) if v.kind == "TRACKED_HARMFUL"]
    assert not new, (
        "новый файл состояния с ВРЕДНЫМ откатом попал в git:\n"
        + "\n".join(f"  {v.path} — {v.detail}" for v in new)
    )


def test_known_debt_can_only_shrink() -> None:
    """ХРАПОВИК долга: список снимаемых с отслеживания только сокращается.

    Каждая строка базы обязана всё ещё быть в индексе — как только файл снят,
    строку УДАЛЯЮТ, и потолок опускается. Это и есть механизм, которым долг
    не может вернуться незамеченным.
    """
    base = policy.load_baseline()
    tracked = set(policy.tracked_data_files(_REPO))
    debt = base["harmful_debt"]
    assert len(debt) <= _HARMFUL_DEBT_BASELINE, (
        f"известный долг вырос: {len(debt)} > {_HARMFUL_DEBT_BASELINE}"
    )
    assert len(base["derived_tolerated"]) <= _DERIVED_TOLERATED_BASELINE
    stale = [p for p in debt if p not in tracked]
    assert not stale, (
        "эти файлы уже сняты с отслеживания — удалить их строки из "
        f"data_git_baseline.json, чтобы потолок опустился: {stale}"
    )


def test_gitignore_negations_and_the_canon_list_say_the_same_thing() -> None:
    """Закрытый список обязан быть ОДИН — в двух местах он разъедется.

    `.gitignore` негациями решает, что переживёт переклон; `_CANON` решает, что
    сторож считает каноном. Если файл назван только в одном из двух, кто-то из
    них молчит не о том: канон без негации выпадет при переносе дерева, а
    негация без канона протащит в git состояние, которое туда не относится.
    """
    negated = {
        line[1:].strip()
        for line in (_REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.startswith("!data/") and line.rstrip().endswith(".json")
    }
    canon_files = set(policy._CANON)
    assert canon_files - negated == set(), (
        "канон без негации в .gitignore (выпадет при переклоне): "
        f"{sorted(canon_files - negated)}"
    )
    assert negated - canon_files == set(), (
        "негация без записи в _CANON (сторож о таком файле ничего не знает): "
        f"{sorted(negated - canon_files)}"
    )


def test_the_lifted_halt_file_is_still_out_of_git() -> None:
    """Эталон класса не должен вернуться в индекс.

    Дублирует храповик из `test_halt_state_survives_tree_restore.py` намеренно:
    там он про один файл, здесь — про то, что сторож класса реально смотрит
    в этот репозиторий, а не только в свои списки.
    """
    assert _HALT not in set(policy.tracked_data_files(_REPO)), (
        f"{_HALT} снова отслеживается — откат опять затрёт живую остановку"
    )


def test_track_canon_is_actually_present_in_git() -> None:
    """КАНОН обязан быть в git — иначе числа сайта нечем подтвердить из репозитория.

    КРАСНЫЙ НА СЕГОДНЯШНЕМ СОСТОЯНИИ (2026-08-18) — это находка, а не поломка
    теста: `data/tier1_packages.json` перечислен в разрешающем списке
    `.gitignore:151-154` как канон ADR-093 п.3 (net-APY и worst-DD карточек
    тиров на главной), но в индексе git его НЕТ и в дереве файла тоже нет —
    то есть сторож сайта его не возит, и owner-gate не может пересчитать
    owner-gated число «доходность тира» из репозитория. Гасить этот тест
    исключением ЗАПРЕЩЕНО (инвариант 16) — чинить состав git.
    """
    missing = [v.path for v in policy.audit(_REPO) if v.kind == "CANON_NOT_TRACKED"]
    assert not missing, (
        "канон трека отсутствует в git: " + ", ".join(missing)
        + " — проверяемость публикуемых чисел из репозитория сломана"
    )
