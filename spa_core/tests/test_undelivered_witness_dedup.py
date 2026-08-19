"""«Кто ещё объявлял» обязано быть ИЗМЕРЕНИЕМ, а не эхом журнала (цикл #308).

Карточка `inbox-razdel-nahodok-shaga-0a-nazyvaet-avtora`, замер #307 герметичным прогоном
на чистом `origin`: одна сессия `pid31439` объявила ОДИН путь ТРИЖДЫ — штатное поведение
(§3.4: объявление до работы, потом уточняющие) — и в записи получилось

    also_declared_by = ['pid31439', 'pid31439']

то есть шаг 0a печатал «тот же путь объявляли ещё: pid31439, pid31439» про сессию, которая
и есть автор записи. Двух «ещё объявлявших» не существовало ни одной.

**Почему это не косметика.** Раздел находок — тот, ради которого сторож существует, и тот,
который читают, когда ищут потерянную работу. Именно по списку «кто ещё объявлял» сессия
решает, две ли сессии взяли одну карточку — вопрос, ради которого заводили шаг 0b (#230).
«Объявляли трое» и «объявляла одна сессия трижды» — разные ответы.

Правило теперь ОДНО на все разделы (`add_witness`): в свидетели попадает сессия, которая
отличается от автора записи и там ещё не названа. Второй источник правды разошёлся бы молча
и выключил бы свёртку там, где её не поправили (урок `reap_where`, #307) — поэтому ниже
стоит и структурная проверка проводки: сырых `append` в скрипте не остаётся.

**Обратные контроли объявлены и обязательны:** ДВЕ разные сессии по-прежнему обе названы —
иначе свернём ровно то, ради чего поле заведено. Они зелены и до правки, и после; красными
на неисправленном `origin` обязаны быть положительные контроли.

Все тесты герметичны: настоящие git-репозитории в ``tmp_path``, `ps` подменён, сети нет.
"""
import ast
import importlib.util
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_undelivered_work.py"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: проверка сверяет объявленные файлы с базовым ref "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load():
    spec = importlib.util.spec_from_file_location("_test_undelivered_witness", SCRIPT)
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


_NOW = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)   # объявления старше окна ожидания
_LSTART_OLD = "Wed Jan 14 10:00:00 2026"


def entry(session, files, ts="2026-01-15T12:00:00Z", summary="работа", **extra):
    e = {"ts": ts, "session": session, "summary": summary, "files": [str(f) for f in files]}
    e.update(extra)
    return e


def durable_entry(session, files, pid, **kw):
    e = entry(session, files, **kw)
    e["session_pid"], e["session_pid_start"] = pid, _LSTART_OLD
    return e


def report(guard, repo, entries, ps=None):
    return guard.build_report(
        entries=entries, root=repo, base_ref="base", self_session="pid999999",
        ps=ps if ps is not None else (lambda pid: (1, "")), now=_NOW, grace_hours=3.0,
    )


def thrice(make, session="pid31439"):
    """Ровно форма замера #307: ОДНА сессия объявляет один и тот же путь три раза."""
    return [make(session, ts) for ts in ("2026-01-15T12:00:00Z",
                                         "2026-01-15T13:00:00Z",
                                         "2026-01-15T14:00:00Z")]


# ── подготовка каждого раздела ───────────────────────────────────────────────

def _absent_path(repo):
    """`findings`/ABSENT: байты лежат в дереве, на базе их нет."""
    p = repo / "scripts" / "brand_new.py"
    p.write_text("работа\n", encoding="utf-8")
    return p


def _phantom_path(repo):
    """`nowhere`: имя объявлено авансом, файла нет нигде и не было на базе."""
    return repo / "scripts" / "edge_rsb.py"


def _deleted_path(repo, rel="scripts/gone.py"):
    """`deleted_on_origin`: путь жил на базе, попал в её историю и был удалён."""
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text("жил на базе\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"add {rel}")
    _git(repo, "branch", "-f", "base", "HEAD")
    _git(repo, "rm", "-q", rel)
    _git(repo, "commit", "-qm", f"rm {rel}")
    _git(repo, "branch", "-f", "base", "HEAD")
    return repo / rel


def _by_design_path(repo):
    """`by_design`: путь, который репозиторий не берёт по правилу (`.gitignore`)."""
    (repo / ".gitignore").write_text("data/**/*.jsonl\n", encoding="utf-8")
    (repo / "data").mkdir(exist_ok=True)
    p = repo / "data" / "worktree_reap_log.jsonl"
    p.write_text("{}\n", encoding="utf-8")
    return p


CARD = "inbox-u-outcomes-jsonl-sprashivayut-vozrast-fa"


def _card_closed_path(repo):
    """`card_closed`: карточка объявления закрыта на базе, в дереве промежуточная копия."""
    d = repo / "nimbalyst-local" / "tracker"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{CARD}.md").write_text(
        "---\ntrackerStatus:\n  type: inbox\n"
        "title: карточка объявления\nstatus: done\n---\n\nтело\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "карточка закрыта")
    _git(repo, "branch", "-f", "base", "HEAD")
    p = repo / "scripts" / "kept.py"
    p.write_text(p.read_text(encoding="utf-8") + "промежуточная копия\n", encoding="utf-8")
    return p


# ── 1. положительные контроли: одна сессия себе не свидетель ─────────────────

class TestOneSessionIsNotItsOwnWitness:
    """Каждый тест — точная форма замера #307, и каждый краснеет на неисправленном стороже
    (`also_declared_by == ['pid31439', 'pid31439']`)."""

    def test_findings_section(self, guard, repo):
        p = _absent_path(repo)
        rep = report(guard, repo, thrice(lambda s, ts: entry(s, [p], ts=ts)))
        assert len(rep["findings"]) == 1
        assert rep["findings"][0]["session"] == "pid31439"
        assert rep["findings"][0]["also_declared_by"] == []

    def test_nowhere_section(self, guard, repo):
        p = _phantom_path(repo)
        rep = report(guard, repo, thrice(lambda s, ts: entry(s, [p], ts=ts)))
        assert len(rep["nowhere"]) == 1
        assert rep["nowhere"][0]["also_declared_by"] == []

    def test_deleted_on_origin_section(self, guard, repo):
        p = _deleted_path(repo)
        rep = report(guard, repo, thrice(lambda s, ts: entry(s, [p], ts=ts)))
        assert len(rep["deleted_on_origin"]) == 1
        assert rep["deleted_on_origin"][0]["also_declared_by"] == []

    def test_by_design_section(self, guard, repo):
        p = _by_design_path(repo)
        rep = report(guard, repo,
                     thrice(lambda s, ts: durable_entry(s, [p], pid=22392, ts=ts),
                            session="cycle-257"))
        assert len(rep["by_design"]) == 1
        assert rep["by_design"][0]["also_declared_by"] == []

    def test_card_closed_section(self, guard, repo):
        p = _card_closed_path(repo)
        rep = report(guard, repo,
                     thrice(lambda s, ts: durable_entry(s, [p], pid=73796, ts=ts,
                                                        card=CARD, card_state="claim"),
                            session="cycle-258"))
        assert len(rep["card_closed"]) == 1
        assert rep["card_closed"][0]["also_declared_by"] == []

    def test_the_false_witness_does_not_reach_the_reader(self, guard, repo):
        """Читателя интересует ТЕКСТ отчёта: строки «объявляли ещё» о самой себе быть не должно,
        а сама находка обязана остаться на месте (тишиной дефект не покупается)."""
        p = _absent_path(repo)
        text = guard.render(report(guard, repo, thrice(lambda s, ts: entry(s, [p], ts=ts))))
        assert "объявляли ещё" not in text
        assert "scripts/brand_new.py" in text
        assert "pid31439" in text


# ── 2. смешанный случай: повторы своей сессии не топят чужую ─────────────────

class TestRepeatsDoNotDrownTheOtherSession:
    def test_second_session_is_named_once_among_repeats(self, guard, repo):
        """Живая форма: своя сессия объявила путь дважды, чужая — один раз (и тоже дважды).
        Свидетель обязан быть ровно один и назван ровно один раз."""
        p = _absent_path(repo)
        rep = report(guard, repo, [
            entry("pid31439", [p], ts="2026-01-15T12:00:00Z"),
            entry("pid50691", [p], ts="2026-01-15T12:30:00Z"),
            entry("pid31439", [p], ts="2026-01-15T13:00:00Z"),
            entry("pid50691", [p], ts="2026-01-15T13:30:00Z"),
        ])
        assert len(rep["findings"]) == 1
        assert rep["findings"][0]["also_declared_by"] == ["pid50691"]
        assert "тот же файл объявляли ещё: pid50691" in guard.render(rep)


# ── 3. обратные контроли: видимость не сужена ни в одном разделе ─────────────

class TestTwoSessionsAreStillBothNamed:
    """ОБРАТНЫЕ КОНТРОЛИ (зелены и до правки, и после). Ради этого поле и заведено: если
    одну карточку взяли ДВЕ сессии, отчёт обязан назвать обе."""

    def test_findings_section(self, guard, repo):
        p = _absent_path(repo)
        rep = report(guard, repo, [entry("pid1", [p]), entry("pid2", [p]), entry("pid3", [p])])
        assert rep["findings"][0]["also_declared_by"] == ["pid2", "pid3"]

    def test_nowhere_section(self, guard, repo):
        p = _phantom_path(repo)
        rep = report(guard, repo, [entry("pid1", [p]), entry("pid2", [p])])
        assert rep["nowhere"][0]["also_declared_by"] == ["pid2"]

    def test_deleted_on_origin_section(self, guard, repo):
        p = _deleted_path(repo)
        rep = report(guard, repo, [entry("pid1", [p]), entry("pid2", [p])])
        assert rep["deleted_on_origin"][0]["also_declared_by"] == ["pid2"]

    def test_by_design_section(self, guard, repo):
        p = _by_design_path(repo)
        rep = report(guard, repo, [durable_entry("cycle-257", [p], pid=22392),
                                   durable_entry("cycle-15316", [p], pid=15316)])
        assert rep["by_design"][0]["also_declared_by"] == ["cycle-15316"]

    def test_card_closed_section(self, guard, repo):
        p = _card_closed_path(repo)
        rep = report(guard, repo,
                     [durable_entry("cycle-258", [p], pid=73796, card=CARD, card_state="claim"),
                      durable_entry("cycle-15316", [p], pid=15316, card=CARD,
                                    card_state="claim")])
        assert rep["card_closed"][0]["also_declared_by"] == ["cycle-15316"]


# ── 4. само правило и его проводка ──────────────────────────────────────────

class TestTheRuleItself:
    def test_add_witness_answers_each_case(self, guard):
        rec = {"session": "pid1", "also_declared_by": []}
        assert guard.add_witness(rec, "pid1") is False        # автор записи себе не свидетель
        assert guard.add_witness(rec, None) is False          # имени нет — судить нечем
        assert guard.add_witness(rec, "") is False
        assert guard.add_witness(rec, "pid2") is True         # другая сессия — свидетель
        assert guard.add_witness(rec, "pid2") is False        # и ровно один раз
        assert rec["also_declared_by"] == ["pid2"]

    def test_every_section_goes_through_the_one_rule(self, guard):
        """Проводка, а не деталь: сырой `…["also_declared_by"].append(…)` в скрипте не
        остаётся ни одного. Иначе следующий раздел заведёт второй источник правды и
        разойдётся с этим молча — ровно так и появился разбираемый дефект."""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        raw = [n for n in ast.walk(tree)
               if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
               and isinstance(n.func.value, ast.Subscript)
               and isinstance(getattr(n.func.value, "slice", None), ast.Constant)
               and n.func.value.slice.value == "also_declared_by"]
        assert raw == [], f"сырых append осталось {len(raw)} — свести к add_witness"
