"""Шаг 0a и ТРЕТЬЕ вместилище недоставленной работы — удалённая ветка.

**Авария, которую воспроизводит каждый тест этого файла (20.08, циклы #321/#322).** На
`origin/claude/work-status-check-xfnbew` за 17–19.08 легли 133 коммита, а на `main` их не
привозил никто. Замер цикла #322: **178 путей, которых на `main` нет вообще** — восемь файлов
решений (`ADR-088`…`ADR-095`), **52 карточки** (из них два десятка — вопросы ВЛАДЕЛЬЦУ, которых
он не видел ни разу) и 110 файлов кода и тестов. Шаг 0a смотрел в рабочие деревья и в историю
базы — и ни одной строкой не смотрел в `refs/remotes/*`.

Хуже, чем «не смотрел»: объявленный путь, уехавший на ветку, попадал в раздел «ОБЪЯВЛЕНО, НО НЕ
СУЩЕСТВУЕТ НИГДЕ» с вердиктом **«ПОДНИМАТЬ НЕЧЕГО»** — то есть сторож не молчал, а утверждал
неправду о работе, которая лежала в двух командах git от него. Это fail-OPEN внутри
fail-CLOSED-сторожа (класс #226), а не неточность формулировки.

**Почему находкой считается не всякая ветка** (карточка
`inbox-shag-0a-slep-k-udalennym-vetkam-rabota-u` прямо требовала это решить: «безадресный список
веток каждый цикл — это шум, который научатся пролистывать»). Признак выбран ЗАМЕРОМ 14 веток
репозитория: уникальный код есть у 13 из них, а уникальные решения или карточки владельца — ровно
у ОДНОЙ. Код на ветке — обычная параллельная работа, для того ветки и существуют. Решение или
карточка на ветке означают, что очередь ВЛАДЕЛЬЦА потеряла пункт, и восстановить его нечем, кроме
самой ветки. Поэтому:

* ветка с решениями/карточками — находка, код возврата 1;
* ветка с одним лишь кодом — НЕ находка, но названа строкой с числами: разница между «не
  считаем» и «не видим» обязана быть видна в самом отчёте (обратный контроль ниже).

Все тесты герметичны: настоящий git в ``tmp_path``, `refs/remotes/*` заводятся плумбингом
(`update-ref`), сети нет.
"""
import importlib.util
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: проверка читает refs/remotes/ и деревья веток",
)

_NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)


def _load():
    path = ROOT / "scripts" / "check_undelivered_work.py"
    spec = importlib.util.spec_from_file_location("_test_step0a_branches", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load()


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с веткой `base` (роль origin/main) и рабочим деревом поверх неё."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    (r / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "branch", "base")
    return r


def branch_with(repo, ref_name, files: dict, message="работа сессии в облаке"):
    """Завести `refs/remotes/<ref_name>` с указанными файлами поверх базы.

    Плумбинг вместо `git push`: удалённый ref — это обычная ссылка, и подделывать сеть, чтобы
    её получить, значило бы проверять не то. Рабочее дерево после этого возвращается на базу —
    файлы ветки НЕ должны лежать на диске, иначе тест мерил бы дерево, а не ветку.
    """
    _git(repo, "checkout", "-q", "-b", f"_tmp_{ref_name.replace('/', '_')}", "base")
    for rel, text in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-ref", f"refs/remotes/{ref_name}", sha)
    _git(repo, "checkout", "-q", "base")
    _git(repo, "branch", "-qD", f"_tmp_{ref_name.replace('/', '_')}")
    for rel in files:
        p = repo / rel
        if p.exists():
            p.unlink()
    return sha


def entry(session, files, ts="2026-08-19T02:27:00Z", summary="работа"):
    return {"ts": ts, "session": session, "summary": summary, "files": [str(f) for f in files]}


def report(guard, repo, entries=(), now=_NOW, git=None):
    kw = {}
    if git is not None:
        kw["git"] = git
    return guard.build_report(
        entries=list(entries), root=repo, base_ref="base", self_session="pid999999",
        ps=lambda pid: (1, ""), now=now, grace_hours=3.0, **kw,
    )


# ── 1. объявленный путь, уехавший на ветку ───────────────────────────────────

class TestDeclaredPathOnABranch:
    def test_path_on_a_branch_is_not_judged_nowhere(self, guard, repo):
        """Положительный контроль аварии: до правки этот путь получал «ПОДНИМАТЬ НЕЧЕГО»."""
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"scripts/adr_number.py": "работа облачной сессии\n"})
        rep = report(guard, repo, [entry("pid36055", [repo / "scripts" / "adr_number.py"])])
        assert rep["nowhere"] == [], "путь лежит на ветке — «нигде» это неправда"
        assert [f["path"] for f in rep["on_branch"]] == ["scripts/adr_number.py"]
        assert rep["on_branch"][0]["state"] == guard.ON_BRANCH
        assert rep["on_branch"][0]["branches"] == ["origin/claude/work-status-check-xfnbew"]

    def test_the_finding_names_the_branch_and_says_there_is_something_to_raise(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"scripts/adr_number.py": "работа облачной сессии\n"})
        rep = report(guard, repo, [entry("pid36055", [repo / "scripts" / "adr_number.py"])])
        detail = rep["on_branch"][0]["detail"]
        assert "origin/claude/work-status-check-xfnbew" in detail
        assert "ПОДНИМАТЬ ЕСТЬ ЧТО" in detail
        assert "НЕЧЕГО" not in detail

    def test_it_still_holds_a_non_zero_exit_code(self, guard, repo):
        """Работы нет на базе — значит она не доставлена. Место назвали, вердикт не смягчили.

        ЕДИНСТВЕННЫЙ тест этого файла, зелёный и ДО правки, и после, — намеренно: до правки
        код 1 давал раздел «нигде», после — раздел «на ветке». Он утверждает не починку, а то,
        что починка НЕ смягчила вердикт; красным ему быть не с чего, и притворяться иначе
        (например, сверяя код возврата с числом разделов) значило бы украшать приёмку.
        """
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"scripts/adr_number.py": "работа облачной сессии\n"})
        rep = report(guard, repo, [entry("pid36055", [repo / "scripts" / "adr_number.py"])])
        assert rep["exit_code"] == 1

    def test_a_name_that_exists_nowhere_at_all_is_still_nowhere(self, guard, repo):
        """ОБРАТНЫЙ контроль: ветка не превращает «нигде» в «где-то» вообще всегда.

        Зелёный по обе стороны правки НАМЕРЕННО — он утверждает НЕизменённое поведение.
        Поэтому раздел читается через `.get`: иначе тест краснел бы на старом коде из-за
        отсутствующего ключа, то есть из-за ПОДГОТОВКИ, а не из-за поведения, и приёмка
        считала бы его положительным контролем, которым он не является.
        """
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"scripts/adr_number.py": "работа облачной сессии\n"})
        rep = report(guard, repo, [entry("pid36055", [repo / "scripts" / "never_written.py"])])
        assert [f["path"] for f in rep["nowhere"]] == ["scripts/never_written.py"]
        assert (rep.get("on_branch") or []) == []

    def test_a_delivered_path_is_not_turned_into_a_branch_finding(self, guard, repo):
        """Второй обратный контроль: то, что на базе ЕСТЬ, веткой не переосмысливается."""
        branch_with(repo, "origin/feature/x", {"scripts/other.py": "код ветки\n"})
        rep = report(guard, repo, [entry("pid1", [repo / "scripts" / "kept.py"])])
        assert (rep.get("on_branch") or []) == []          # `.get` — см. соседний тест выше
        assert rep["findings"] == []


# ── 2. сама ветка как находка: решения и карточки владельца ──────────────────

class TestBranchHoldingOwnerWork:
    def test_branch_with_decisions_absent_from_base_is_a_finding(self, guard, repo):
        """Дословно состояние 20.08: восемь файлов решений на ветке, база о них не знает."""
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {f"docs/decisions/ADR-{n}-x.md": f"решение {n}\n"
                     for n in range(88, 96)})
        rep = report(guard, repo)
        rows = rep["branches_with_owner_work"]
        assert [b["ref"] for b in rows] == ["origin/claude/work-status-check-xfnbew"]
        assert len(rows[0]["decisions"]) == 8
        assert rep["exit_code"] == 1

    def test_branch_with_owner_cards_is_a_finding(self, guard, repo):
        """Карточка владельца на ветке = вопрос, который он не увидит никогда."""
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"nimbalyst-local/tracker/own-55-vtoroi-chitatel.md": "вопрос владельцу\n",
                     "nimbalyst-local/tracker/inbox-sem-skriptov.md": "задание\n"})
        rows = report(guard, repo)["branches_with_owner_work"]
        assert len(rows) == 1 and len(rows[0]["cards"]) == 2

    def test_the_row_states_how_much_is_there(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"docs/decisions/ADR-088-x.md": "решение\n",
                     "nimbalyst-local/tracker/own-55.md": "вопрос\n",
                     "spa_core/tuner/allocation_tuner.py": "код\n"})
        row = report(guard, repo)["branches_with_owner_work"][0]
        assert (row["unique"], len(row["decisions"]), len(row["cards"]), row["code"]) == (3, 1, 1, 1)
        assert row["ahead"] == 1
        assert row["tip"].startswith("20")          # дата последнего коммита названа

    def test_a_branch_with_only_code_is_named_but_is_not_a_finding(self, guard, repo):
        """Признак выбран замером (13 веток из 14 — только код). Обратный контроль на шум."""
        branch_with(repo, "origin/novel-edge-daily",
                    {"spa_core/strategy_lab/x.py": "код\n", "tests/test_x.py": "тест\n"})
        rep = report(guard, repo)
        assert rep["branches_with_owner_work"] == []
        assert [b["ref"] for b in rep["branches_code_only"]] == ["origin/novel-edge-daily"]
        assert rep["exit_code"] == 0, "код на ветке — обычная работа, а не авария"

    def test_a_branch_fully_merged_into_base_is_not_reported(self, guard, repo):
        """Влитая ветка отсеивается ИЗМЕРЕНИЕМ (`merge-base --is-ancestor`), а не по имени."""
        sha = _git(repo, "rev-parse", "base").stdout.strip()
        _git(repo, "update-ref", "refs/remotes/origin/main", sha)
        rep = report(guard, repo)
        # `.get` по той же причине, что у обратных контролей выше: тест утверждает ОТСУТСТВИЕ
        # находки, и на старом коде он обязан быть зелёным — красным его сделал бы только
        # отсутствующий ключ.
        assert (rep.get("branches_with_owner_work") or []) == []
        assert (rep.get("branches_code_only") or []) == []
        assert rep["exit_code"] == 0

    def test_two_branches_are_two_rows(self, guard, repo):
        branch_with(repo, "origin/a", {"docs/decisions/ADR-088-x.md": "решение\n"})
        branch_with(repo, "origin/b", {"nimbalyst-local/tracker/own-1.md": "вопрос\n"})
        rows = report(guard, repo)["branches_with_owner_work"]
        assert sorted(b["ref"] for b in rows) == ["origin/a", "origin/b"]


# ── 3. fail-CLOSED: не измерено ≠ в порядке ──────────────────────────────────

class TestUnmeasured:
    def test_unreadable_branch_list_is_unmeasured_not_silence(self, guard, repo):
        real = guard._git

        def broken(cwd, *args):
            if args[:1] == ("for-each-ref",):
                return 128, "", "fatal: not a git repository"
            return real(cwd, *args)

        rep = report(guard, repo, git=broken)
        assert rep["exit_code"] == 2
        assert any("удалённых веток НЕ ПРОЧИТАН" in u["reason"] for u in rep["unmeasured"])

    def test_unreadable_branch_tree_is_unmeasured(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"docs/decisions/ADR-088-x.md": "решение\n"})
        real = guard._git

        def broken(cwd, *args):
            if args[:1] == ("ls-tree",) and args[-1] == "origin/claude/work-status-check-xfnbew":
                return 128, "", "fatal: not a tree object"
            return real(cwd, *args)

        rep = report(guard, repo, git=broken)
        assert rep["exit_code"] == 2
        assert any("дерево НЕ ПРОЧИТАНО" in u["reason"] for u in rep["unmeasured"])

    def test_unmeasurable_merge_state_is_named(self, guard, repo):
        branch_with(repo, "origin/x", {"docs/decisions/ADR-088-x.md": "решение\n"})
        real = guard._git

        def broken(cwd, *args):
            if args[:2] == ("merge-base", "--is-ancestor"):
                return 128, "", "fatal: bad object"
            return real(cwd, *args)

        rep = report(guard, repo, git=broken)
        assert rep["exit_code"] == 2
        assert any("влита ли она" in u["reason"] for u in rep["unmeasured"])


# ── 4. отчёт: сказанное вслух ────────────────────────────────────────────────

class TestRender:
    def test_branch_section_is_printed_with_the_branch_name(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"docs/decisions/ADR-088-x.md": "решение\n"})
        text = guard.render(report(guard, repo))
        assert "РЕШЕНИЯ И КАРТОЧКИ ВЛАДЕЛЬЦА" in text
        assert "origin/claude/work-status-check-xfnbew" in text
        assert "docs/decisions/ADR-088-x.md" in text

    def test_code_only_branches_are_named_aloud(self, guard, repo):
        """«Не считаем находкой» не должно читаться как «не видим»."""
        branch_with(repo, "origin/novel-edge-daily", {"spa_core/x.py": "код\n"})
        text = guard.render(report(guard, repo))
        assert "origin/novel-edge-daily" in text
        assert "НЕ находки" in text

    def test_all_green_line_is_not_printed_while_a_branch_holds_owner_work(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"nimbalyst-local/tracker/own-55.md": "вопрос владельцу\n"})
        text = guard.render(report(guard, repo))
        assert "всё доставлено" not in text

    def test_the_path_on_a_branch_is_printed_with_its_branch(self, guard, repo):
        branch_with(repo, "origin/claude/work-status-check-xfnbew",
                    {"scripts/adr_number.py": "работа\n"})
        text = guard.render(report(guard, repo,
                                   [entry("pid36055", [repo / "scripts" / "adr_number.py"])]))
        assert "ЛЕЖИТ НА ВЕТКЕ" in text
        assert "scripts/adr_number.py → origin/claude/work-status-check-xfnbew" in text
