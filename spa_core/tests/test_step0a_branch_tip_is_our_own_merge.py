"""Шаг 0a: свежесть ВЕРШИНЫ ветки — не ответ о судьбе лежащих на ней решений владельца.

**Авария, которую воспроизводит каждый тест этого файла (21.08, цикл #328).** Карточка
`inbox-vtoraya-vetka-s-resheniem-i-kartochkami` поставила прямую развилку по ветке
`origin/claude/unreadable-description-ltyucb`, на которой лежат `ADR-102` и три карточки,
отсутствующие на `main` целиком: **работа идёт — не трогать; работа брошена — разобрать.**
Единственным входом этой развилки была строка шага 0a «последний коммит 2026-08-21».

Строка верна и отвечает не на тот вопрос. `remote_branch_refs` датирует ветку
`committerdate` ВЕРШИНЫ, а вершину двигает и merge НАШЕЙ ЖЕ базы: облачная сессия
подмерживает `origin/main` сама. Живой замер 21.08 06:04Z: вершина — 05:40Z, и это merge
нашего main; последний коммит автора — 23:56Z накануне. Ветка, которую мержат с базой
несколько раз в сутки, выглядит **вечно живой**, и потерянные на ней решения владельца не
поднимаются НИКОГДА. Это fail-OPEN внутри fail-CLOSED-сторожа (класс #226), и цена его —
не формулировка, а выбор ПРОТИВОПОЛОЖНОГО действия над чужой работой.

**Почему признак — пути, а не `--no-merges`** (обратный контроль ниже держит именно это).
Дешёвый рецепт «не считать merge-коммиты» на этой же ветке даёт НЕВЕРНЫЙ ответ, и в опасную
сторону. Замер 21.08: merge `099c8f396` добавил **25 строк** в карточку
`inbox-progon-testov-perepisyvaet-sorok-otslezhivaemyh-failov-data` — раздел «СВЕДЕНИЕ
ИСТОЧНИКОВ (дописано 21.08 после переноса на свежий `main`)»; файла на main-стороне merge'а
нет вовсе, то есть содержимое **авторское**. `--no-merges` объявил бы карточки замороженными
с 23:56 и позвал бы разбирать ДВИЖУЩУЮСЯ работу — ровно та разрушительная сторона, от которой
предостерегает сама карточка. Поэтому спрашивается не «какой природы коммит», а «трогал ли он
предмет находки»: решения и карточки, которых на базе нет ВООБЩЕ. Этот ответ ТОЧЕН.

Все тесты герметичны: настоящий git в ``tmp_path``, `refs/remotes/*` заводятся плумбингом
(`update-ref`), сети нет.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: проверка датирует коммиты ветки и считает их",
)

CARD = "nimbalyst-local/tracker/own-btc-dvizhok-ne-vlezaet-pod-stop-kran.md"
ADR = "docs/decisions/ADR-102-btc-cycle-backtest-archived-not-built.md"
CODE = "scripts/build_maturity_register.py"


def _load():
    path = ROOT / "scripts" / "check_undelivered_work.py"
    spec = importlib.util.spec_from_file_location("_test_step0a_branch_tip", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


def _git(cwd, *args, when=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    if when:                       # время — ВХОД, а не окружение (правило .claude/rules/deployment.md)
        env["GIT_AUTHOR_DATE"] = when
        env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


def _write(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с веткой `base` в роли origin/main."""
    r = tmp_path / "repo"
    r.mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    _write(r, "README.md", "база\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "база", when="2026-08-20T10:00:00+0000")
    _git(r, "branch", "base")
    return r


def _publish(repo, ref_name):
    """Опубликовать текущий HEAD как `refs/remotes/<ref_name>` и вернуться на базу."""
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", f"refs/remotes/{ref_name}", sha)
    _git(repo, "checkout", "-q", "base")
    return sha


REF = "origin/claude/unreadable-description-ltyucb"


def _branch_frozen_cards_then_merges(repo, merges=2):
    """Ветка 21.08: карточка и решение, сверху работа автора, сверху merge'и БАЗЫ.

    Возвращает (sha коммита с карточками, sha вершины).
    """
    _git(repo, "checkout", "-q", "-b", "work", "base")
    _write(repo, CARD, "развилка владельцу\n")
    _write(repo, ADR, "ADR-102\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "решение и карточка владельца",
         when="2026-08-20T23:00:00+0000")
    cards_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()

    _write(repo, CODE, "реестр зрелости\n")     # работа автора, предмета находки НЕ касается
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "реестр зрелости", when="2026-08-20T23:56:00+0000")

    for i in range(merges):                      # именно то, чем облачная сессия двигает вершину
        _git(repo, "checkout", "-q", "base")
        _write(repo, "README.md", f"база двинулась {i}\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"наш цикл {i}", when=f"2026-08-21T0{1 + i}:50:00+0000")
        _git(repo, "checkout", "-q", "work")
        _git(repo, "merge", "-q", "--no-ff", "-m", "Merge remote-tracking branch 'origin/main'",
             "base", when=f"2026-08-21T0{1 + i}:56:00+0000")

    tip = _publish(repo, REF)
    _git(repo, "branch", "-qD", "work")
    return cards_sha, tip


def _touch(guard, repo, owner_work=(CARD, ADR)):
    return guard.owner_work_last_touch(repo, "base", REF, list(owner_work))


# ── 1. сама авария 21.08 ─────────────────────────────────────────────────────

class TestTipIsOurOwnMerge:
    def test_measurement_names_the_authors_date_not_the_merge_date(self, guard, repo):
        """Положительный контроль: до правки у ветки была ОДНА дата — merge нашей же базы."""
        cards_sha, tip = _branch_frozen_cards_then_merges(repo)
        touch, unmeasured = _touch(guard, repo)
        assert unmeasured is None
        assert touch["sha"] == cards_sha, "предмет находки последний раз трогал коммит карточек"
        assert touch["date"].startswith("2026-08-20T23:00"), touch["date"]

        tip_date = _git(repo, "log", "-1", "--format=%cI", tip).stdout.strip()
        assert tip_date.startswith("2026-08-21T02:56"), "вершина — merge базы, и она СВЕЖЕЕ"
        assert touch["date"] < tip_date, "разрыв вершины и предмета находки обязан быть виден"

    def test_the_report_prints_both_numbers(self, guard, repo):
        """Отчёт обязан НАЗВАТЬ разрыв: одной свежей даты достаточно, чтобы выбрать не то действие."""
        _branch_frozen_cards_then_merges(repo)
        rep = guard.build_report(entries=[], root=repo, base_ref="base",
                                 self_session="pid999999", ps=lambda pid: (1, ""), now=None,
                                 grace_hours=3.0)
        text = guard.render(rep)
        assert "решения и карточки этой ветки не трогали с 2026-08-20 23:00" in text, text
        assert "свежесть ВЕРШИНЫ про предмет находки НЕ ГОВОРИТ" in text
        assert "последний коммит 2026-08-21 02:56" in text, "вершина тоже названа, а не подменена"

    def test_commits_above_counts_the_author_not_our_base(self, guard, repo):
        """`sha..ref` втянул бы коммиты НАШЕГО main (живой замер: 16 против 2)."""
        _branch_frozen_cards_then_merges(repo, merges=2)
        touch, _ = _touch(guard, repo)
        # автор: коммит реестра + два merge'а = 3; коммиты базы (2 штуки) сюда НЕ входят
        assert touch["commits_above"] == 3, touch
        naive = _git(repo, "rev-list", "--count", f"{touch['sha']}..{REF}").stdout.strip()
        assert int(naive) > touch["commits_above"], (
            "наивный счёт обязан быть больше — иначе тест не про то")


# ── 2. обратный контроль: почему НЕ `--no-merges` ────────────────────────────

class TestAMergeMayCarryTheAuthorsOwnContent:
    """Замер 21.08: merge дописал в карточку 25 строк, которых на main-стороне нет вовсе.

    Значит `--no-merges` объявил бы карточку замороженной и позвал бы разбирать ЖИВУЮ работу.
    Этот тест краснеет ровно на такой «дешёвой» реализации.
    """

    def _branch_where_the_merge_edits_the_card(self, repo):
        _git(repo, "checkout", "-q", "-b", "work", "base")
        _write(repo, CARD, "развилка владельцу\n")
        _write(repo, ADR, "ADR-102\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "решение и карточка", when="2026-08-20T23:00:00+0000")
        frozen = _git(repo, "rev-parse", "HEAD").stdout.strip()

        _git(repo, "checkout", "-q", "base")
        _write(repo, "README.md", "база двинулась\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "наш цикл", when="2026-08-21T01:50:00+0000")

        _git(repo, "checkout", "-q", "work")
        _git(repo, "merge", "-q", "--no-commit", "--no-ff", "base")
        # автор сводит источники ПРЯМО в merge — это и произошло 21.08
        _write(repo, CARD, "развилка владельцу\n\n## СВЕДЕНИЕ ИСТОЧНИКОВ (дописано 21.08)\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "Merge remote-tracking branch 'origin/main'",
             when="2026-08-21T01:56:00+0000")
        merge_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _publish(repo, REF)
        _git(repo, "branch", "-qD", "work")
        return frozen, merge_sha

    def test_the_merge_that_edits_a_card_counts_as_a_touch(self, guard, repo):
        frozen, merge_sha = self._branch_where_the_merge_edits_the_card(repo)
        touch, unmeasured = _touch(guard, repo)
        assert unmeasured is None
        assert touch["sha"] == merge_sha, (
            "merge изменил карточку — значит предмет находки ДВИГАЛСЯ; пропустить его "
            "значит объявить живую работу брошенной")
        assert touch["sha"] != frozen
        assert touch["date"].startswith("2026-08-21T01:56")
        assert touch["commits_above"] == 0, "выше касания на стороне ветки ничего нет"

    def test_no_merges_would_have_given_the_dangerous_answer(self, guard, repo):
        """Замер самой альтернативы: она даёт СТАРУЮ дату. Тест удерживает выбор признака."""
        frozen, merge_sha = self._branch_where_the_merge_edits_the_card(repo)
        cheap = _git(repo, "rev-list", "--max-count=1", "--no-merges", f"base..{REF}",
                     "--", CARD, ADR).stdout.strip()
        assert cheap == frozen, "альтернатива и правда указывает на замороженный коммит"
        touch, _ = _touch(guard, repo)
        assert touch["sha"] != cheap, "реализация не должна совпасть с опасной альтернативой"


# ── 3. отсутствие шума и границы ─────────────────────────────────────────────

class TestItStaysQuietWhereThereIsNothingToSay:
    def test_no_extra_line_when_the_tip_itself_touches_the_cards(self, guard, repo):
        """Вершина и есть касание ⇒ разъяснять нечего, лишней строки быть не должно."""
        _git(repo, "checkout", "-q", "-b", "work", "base")
        _write(repo, CARD, "развилка владельцу\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "карточка владельца", when="2026-08-21T05:40:00+0000")
        _publish(repo, REF)
        _git(repo, "branch", "-qD", "work")

        touch, _ = _touch(guard, repo, owner_work=(CARD,))
        assert touch["commits_above"] == 0
        rep = guard.build_report(entries=[], root=repo, base_ref="base",
                                 self_session="pid999999", ps=lambda pid: (1, ""), now=None,
                                 grace_hours=3.0)
        assert "не трогали с" not in guard.render(rep)

    def test_a_branch_without_owner_work_is_not_dated(self, guard, repo):
        """Предмета нет — нечего и датировать; ветки с одним кодом эта правка не касается."""
        assert guard.owner_work_last_touch(repo, "base", REF, []) == (None, None)


class TestFailClosed:
    def test_unreadable_git_says_not_measured_rather_than_going_silent(self, guard, repo):
        _branch_frozen_cards_then_merges(repo)

        def broken(root, *args):
            if args and args[0] == "rev-list":
                return 128, "", "fatal: bad revision"
            return guard._git(root, *args)

        touch, unmeasured = guard.owner_work_last_touch(repo, "base", REF, [CARD, ADR],
                                                        git=broken)
        assert touch is None
        assert unmeasured and "НЕ ИЗМЕРЕНО" in unmeasured
        assert REF in unmeasured

    def test_the_unmeasured_reason_reaches_the_report(self, guard, repo):
        """«Не измерено» обязано ДОЕХАТЬ до отчёта, а не остаться внутри функции."""
        _branch_frozen_cards_then_merges(repo)

        real = guard._git

        def broken(root, *args):
            if args and args[0] == "rev-list" and "--max-count=1" in args:
                return 128, "", "fatal: bad revision"
            return real(root, *args)

        rep = guard.build_report(entries=[], root=repo, base_ref="base",
                                 self_session="pid999999", ps=lambda pid: (1, ""), now=None,
                                 grace_hours=3.0, git=broken)
        reasons = " ".join(u["reason"] for u in rep["unmeasured"] if u.get("reason"))
        assert "решения и карточки" in reasons and "НЕ ИЗМЕРЕНО" in reasons, reasons
        assert rep["exit_code"] == 2, "непрочитанное измерение — код 2, а не мягкая единица"


class TestStampKeepsMinutes:
    """Обрезка до дня стёрла бы ровно тот разрыв, ради которого правка и делалась."""

    def test_minutes_survive(self, guard):
        assert guard._stamp("2026-08-21T01:56:09Z") == "2026-08-21 01:56"

    def test_same_day_gap_is_visible(self, guard):
        assert guard._stamp("2026-08-21T05:40:49Z") != guard._stamp("2026-08-21T01:56:09Z")

    def test_odd_input_is_passed_through_rather_than_mangled(self, guard):
        assert guard._stamp("") == ""
        assert guard._stamp(None) == ""
        assert guard._stamp("2026-08-21") == "2026-08-21"
