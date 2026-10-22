"""Шаг 0a и ВТОРОЙ КЛОН репозитория: объявление, уехавшее в чужой журнал, невидимо.

**Авария, которую воспроизводят эти тесты (замер 22.10, цикл #907).** Цикл #906 построил
свой изолированный worktree от ЗЕРКАЛА (`~/Documents/SPA_mirror`, объявлено ADR-152), а не
от прод-дерева. Объявления `log_session_change.py` легли поэтому в журнал ЗЕРКАЛА: `shared_log`
разрешает «общий» журнал в ГЛАВНОЕ рабочее дерево, и это верно ровно внутри одного клона.
Сессия умерла после объявления полного набора (14 файлов, ADR-785, зелёные батареи) и до
пуша. Один и тот же код, один хост, одна минута:

| откуда запущен шаг 0a | строк про осиротевшую доставку #906 |
|---|---|
| `~/Documents/SPA_Claude` — прод-дерево, так его и зовёт обёртка | **0** |
| `~/Documents/SPA_mirror` — зеркало | **18**, код 2 |

Ноль слева — не «доставлено» и не «не измерено», а МОЛЧАНИЕ: сторож доставки честно ответил
на свой вопрос («что объявлено в МОЁМ журнале») и был прочитан как ответ на нужный («есть ли
осиротевшая работа»). Это fail-OPEN внутри инструмента, который охраняет инв. #17, и нашёлся
он глазами — имя `/tmp/spa_c906` оказалось занято, когда следующий цикл создавал своё дерево.

Поэтому каждый тест ниже — положительный контроль на реальную форму аварии, а не украшение:
две настоящие git-копии в `tmp_path` (вторая — настоящий `git clone`, то есть у неё СВОЙ
`--git-common-dir`), объявление в журнале второй, файл, которого нет на базовом ref.

**Три двери к ХОСТУ закрыты намеренно** (`.claude/rules/deployment.md`):
* **календарь** — отметки относительные (`_freshness.now_utc`), литеральной даты нет ни одной;
* **номер процесса** — живость объявившей сессии приходит ВХОДОМ (`ps=`), а не спрашивается у
  машины; литерального «заведомо мёртвого» pid в файле нет (на Linux `pid_max` по умолчанию
  4 194 304, и «недостижимый» номер там достижим — поправка #453);
* **имя ветки** — `git init -b main`, и базовый ref `base` назван явно.
  Там, где `ps` инъектировать нельзя (прогон через `main()`), предметом утверждения сделан
  исход, который от живости не зависит ВОВСЕ: нечитаемый клон ⇒ код 2, а объявленный файл,
  уже лежащий на базовом ref, находкой не станет ни при какой живости процессов.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: предмет проверки — ДВА клона одного репозитория "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load():
    """Загрузить скрипт по явному пути (`scripts/` — не пакет)."""
    path = ROOT / "scripts" / "check_undelivered_work.py"
    spec = importlib.util.spec_from_file_location("_test_sibling_clones", path)
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


# ── вход «жив ли процесс объявившего» ────────────────────────────────────────

def dead_ps(pid):
    """Процесса нет — на любом хосте, потому что это ВХОД, а не вопрос к машине."""
    return 1, ""


ANNOUNCED_PID = 999_001          # метка, живость которой задаётся входом выше


def _zts(hours_ago: float) -> str:
    """Отметка ровно того формата, которым пишет `log_session_change.py` (`…Z`, без дробей).

    Читатель журнала разбирает СТРОГО `%Y-%m-%dT%H:%M:%SZ`, и `_freshness.ts()` со своим
    `+00:00` и микросекундами даёт «возраст объявления не измерен» — то есть тест мерил бы
    разбор формата вместо предмета. Отметка при этом остаётся ОТНОСИТЕЛЬНОЙ.
    """
    return (now_utc() - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _settle(prod: Path) -> None:
    """Закоммитить дерево прода и подвинуть базовый ref на него.

    **Зачем.** Предмет этих тестов — ЧУЖОЙ клон, а собственное дерево обязано быть чистым:
    иначе своя же правка объявления клонов попадёт в «расхождение без объявления», и
    утверждение «свой журнал даёт верный ноль» измеряло бы фикстуру, а не поведение.
    """
    _git(prod, "add", "-A")
    _git(prod, "commit", "-qm", "declaration")
    _git(prod, "branch", "-f", "base", "HEAD")


def _declare(prod: Path, *paths) -> None:
    """Объявить клоны ровно той формой, которой это объявлено в репозитории (ADR-688)."""
    doc = {"schema_version": 1, "adr": "ADR-688",
           "roots": [{"path": str(p), "kind": "full_clone", "declared_by": "тест"}
                     for p in paths]}
    decl = prod / "architecture" / "history_roots.json"
    decl.parent.mkdir(parents=True, exist_ok=True)
    decl.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _announce(repo: Path, session: str, rel: str, hours_ago: float = 48.0,
              pid: int = ANNOUNCED_PID, pid_start: str | None = None,
              summary: str = "цикл #906: работа начата") -> str:
    """Запись в журнале КЛОНА — в точности той формы, которую пишет `log_session_change.py`
    (включая поля долгоживущего процесса: без них читатель честно говорит «активность не
    измерена», и предметом теста стала бы форма записи, а не чужой журнал)."""
    start = pid_start or (now_utc() - timedelta(hours=hours_ago + 1)).strftime(
        "%a %b %d %H:%M:%S %Y")
    log = repo / "data" / "session_changes.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _zts(hours_ago), "session": session, "summary": summary,
                             "files": [str(repo / rel)],
                             "session_pid": pid, "session_pid_start": start},
                            ensure_ascii=False) + "\n")
    # Отметка старта возвращается, чтобы ВХОД «процесс жив» мог назвать ТО ЖЕ время: расхождение
    # объявленного старта с ответом `ps` читается (верно) как переиспользованный номер.
    return start


@pytest.fixture()
def two_clones(tmp_path):
    """(прод-дерево, зеркало) — две НАСТОЯЩИЕ копии одного репозитория.

    Зеркало создаётся `git clone`, а не копированием каталога: предмет проверки — что у
    второго клона СВОЙ `--git-common-dir` и свой журнал объявлений, и подделать это нельзя.
    Ветка `base` играет роль `origin/main` — так же, как в `test_undelivered_work_guard.py`.
    """
    prod = tmp_path / "prod"
    (prod / "scripts").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main", str(prod))
    (prod / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
    _declare(prod)                                  # объявление есть, клонов пока ноль
    _git(prod, "add", "-A")
    _git(prod, "commit", "-qm", "base")
    _git(prod, "branch", "base")

    mirror = tmp_path / "mirror"
    _git(tmp_path, "clone", "-q", str(prod), str(mirror))
    _git(mirror, "branch", "-f", "base", "main")    # тот же базовый ref в зеркале
    return prod, mirror


def _siblings(guard, prod, ps=dead_ps):
    return guard.sibling_clone_reports(root=prod, base_ref="base",
                                       self_session="pid999999", ps=ps)


# ── 1. ядро: ровно форма #906 ────────────────────────────────────────────────

class TestTheOrphanInTheOtherClone:
    def test_prods_own_log_is_silent_while_the_mirror_holds_undelivered_work(
            self, guard, two_clones):
        """ДВА числа одного замера: свой журнал даёт ноль, чужой — находку.

        Это дословная форма 22.10. Первая половина утверждения — ПРЕЖНЕЕ поведение, и оно
        не ослабляется: шаг 0a о своём журнале отвечает «чисто» верно, потому что в нём
        действительно ничего не объявлено. Дефект был в том, что этот ноль читался как ответ
        на вопрос «есть ли осиротевшая работа», а второго прохода не существовало вовсе.
        """
        prod, mirror = two_clones
        (mirror / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        _announce(mirror, "cycle-40064", "scripts/brand_new.py")
        _declare(prod, mirror)
        _settle(prod)

        own = guard.build_report(entries=[], root=prod, base_ref="base",
                                 self_session="pid999999", ps=dead_ps)
        assert own["findings"] == []
        assert own["exit_code"] == 0, "свой журнал пуст — это верный ноль, он и остаётся"

        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_MEASURED]
        assert [f["path"] for f in rows[0]["findings"]] == ["scripts/brand_new.py"]
        assert rows[0]["findings"][0]["session"] == "cycle-40064"
        assert rows[0]["entries_checked"] == 1
        assert guard.sibling_exit_code(own["exit_code"], rows) == 1

    def test_delivered_work_in_the_other_clone_is_not_a_finding(self, guard, two_clones):
        """Обратная сторона: мера не кричит на доставленном — иначе раздел стал бы шумом."""
        prod, mirror = two_clones
        _announce(mirror, "cycle-40064", "scripts/kept.py")
        _declare(prod, mirror)
        _settle(prod)

        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_MEASURED]
        assert rows[0]["findings"] == []
        assert guard.sibling_exit_code(0, rows) == 0

    def test_live_session_in_the_other_clone_is_not_called_orphaned(self, guard, two_clones):
        """Живой сессии чужого клона подъём не нужен: находки нет, пока процесс жив.

        Живость приходит ВХОДОМ, поэтому утверждение не зависит от того, какой номер сегодня
        свободен на машине прогона.
        """
        prod, mirror = two_clones
        (mirror / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        start = _announce(mirror, "cycle-40064", "scripts/brand_new.py", hours_ago=0.2)
        _declare(prod, mirror)
        _settle(prod)

        def alive(pid):
            return 0, start          # тот же старт, что объявлен ⇒ номер не переиспользован

        rows = _siblings(guard, prod, ps=alive)
        assert [r["state"] for r in rows] == [guard.SIBLING_MEASURED]
        assert rows[0]["findings"] == []
        assert guard.sibling_exit_code(0, rows) == 0

    def test_the_section_is_printed_not_only_counted(self, guard, two_clones):
        """Невидимость и была дефектом: находка обязана попасть в ПЕЧАТНЫЙ отчёт."""
        prod, mirror = two_clones
        (mirror / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        _announce(mirror, "cycle-40064", "scripts/brand_new.py")
        _declare(prod, mirror)
        _settle(prod)

        report = guard.build_report(entries=[], root=prod, base_ref="base",
                                    self_session="pid999999", ps=dead_ps)
        report["sibling_clones"] = _siblings(guard, prod)
        text = guard.render(report)
        assert "ОБЪЯВЛЕНИЯ ИЗ ДРУГИХ ОБЪЯВЛЕННЫХ КЛОНОВ" in text
        assert str(mirror) in text
        assert "scripts/brand_new.py" in text
        assert "cycle-40064" in text


# ── 2. три исхода различимы (инв. #17) ───────────────────────────────────────

class TestThirdOutcomeIsDistinct:
    def test_declared_clone_absent_on_this_machine_is_named_and_not_a_finding(
            self, guard, two_clones):
        """В CI объявленного зеркала нет — и это НЕ находка: объявление само называет путь
        host-specific. Но и не тишина: строка о нём печатается."""
        prod, _ = two_clones
        missing = prod.parent / "no-such-clone"
        _declare(prod, missing)

        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_ABSENT]
        assert guard.sibling_exit_code(0, rows) == 0
        report = {"base_ref": "base", "base_sha": "deadbeef", "grace_hours": 3.0,
                  "entries_checked": 0, "sessions_active": 0, "sessions_checked": 0,
                  "findings": [], "unmeasured": [], "sibling_clones": rows}
        assert str(missing) in guard.render(report)

    def test_clone_without_an_announce_log_is_unmeasured_not_clean(self, guard, two_clones):
        """«Журнала нет» ≠ «ничего не объявлял»: это третий исход и код 2."""
        prod, mirror = two_clones
        _declare(prod, mirror)
        assert not (mirror / "data" / "session_changes.jsonl").exists()

        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_UNMEASURED]
        assert "НЕ ИЗМЕРЕНО" in rows[0]["reason"]
        assert guard.sibling_exit_code(0, rows) == 2

    def test_broken_declaration_is_unmeasured_not_zero_clones(self, guard, two_clones):
        """Нечитаемое объявление — не «клонов не объявлено», а «не измерено»."""
        prod, _ = two_clones
        (prod / "architecture" / "history_roots.json").write_text("{не json", encoding="utf-8")

        clones, err = guard.declared_clone_roots(prod)
        assert clones == []
        assert err and "НЕ ИЗМЕРЕНЫ" in err
        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_UNMEASURED]
        assert guard.sibling_exit_code(0, rows) == 2

    def test_declaration_without_roots_list_is_unmeasured(self, guard, two_clones):
        """Переименуют `roots` — проверка покраснеет, а не замолчит."""
        prod, _ = two_clones
        (prod / "architecture" / "history_roots.json").write_text(
            json.dumps({"schema_version": 1}), encoding="utf-8")
        clones, err = guard.declared_clone_roots(prod)
        assert clones == []
        assert err and "roots" in err

    def test_no_declaration_at_all_is_zero_clones_not_unmeasured(self, guard, two_clones):
        """А вот ОТСУТСТВИЕ объявления — полный ответ «ни одного клона не объявлено», и
        путать его с «не измерено» нельзя: иначе любой репозиторий без этого файла (в том
        числе одноразовое дерево теста) навсегда получил бы код 2."""
        prod, _ = two_clones
        (prod / "architecture" / "history_roots.json").unlink()
        clones, err = guard.declared_clone_roots(prod)
        assert (clones, err) == ([], None)
        assert _siblings(guard, prod) == []

    def test_entry_without_path_is_unmeasured(self, guard, two_clones):
        prod, _ = two_clones
        (prod / "architecture" / "history_roots.json").write_text(
            json.dumps({"roots": [{"kind": "full_clone"}]}), encoding="utf-8")
        clones, err = guard.declared_clone_roots(prod)
        assert err is None
        assert [c["state"] for c in clones] == [guard.SIBLING_UNMEASURED]
        assert "path" in clones[0]["reason"]


# ── 3. не считать свой клон чужим ────────────────────────────────────────────

class TestSameCloneIsNotCountedTwice:
    def test_own_root_declared_is_recognised_as_the_same_clone(self, guard, two_clones):
        """Объявить самого себя — не находка и не двойной счёт: журнал тот же, он прочитан."""
        prod, _ = two_clones
        _declare(prod, prod)
        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_SAME]
        assert guard.sibling_exit_code(0, rows) == 0

    def test_linked_worktree_of_own_clone_is_the_same_clone(self, guard, two_clones, tmp_path):
        """Линкованный worktree — тот же клон (общий `--git-common-dir`), а не второй."""
        prod, _ = two_clones
        wt = tmp_path / "wt"
        _git(prod, "worktree", "add", "-q", "--detach", str(wt), "main")
        _declare(prod, wt)
        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_SAME]

    def test_a_directory_that_is_not_a_repository_is_unmeasured(self, guard, two_clones,
                                                                tmp_path):
        """Каталог есть, а репозитория в нём нет — «не измерено», не «тот же клон»."""
        prod, _ = two_clones
        plain = tmp_path / "plain"
        plain.mkdir()
        _declare(prod, plain)
        rows = _siblings(guard, prod)
        assert [r["state"] for r in rows] == [guard.SIBLING_UNMEASURED]
        assert guard.sibling_exit_code(0, rows) == 2


# ── 4. ПРОВОДКА: проход обязан доходить до CLI ───────────────────────────────

class TestWiringReachesTheCommandLine:
    """Урок #453: «параметр есть, а проводки нет» — та же бомба. Проверка функции отдельно
    от `main()` оставила бы шаг 0a ровно таким же молчаливым, каким он был 22.10.

    `ps` сюда инъектировать нельзя (это CLI), поэтому предметом здесь сделаны исходы, от
    живости процессов не зависящие: нечитаемый клон и ЖИВОЙ собственный процесс.
    """

    def test_main_reads_the_other_clones_log_and_prints_the_section(self, guard, two_clones,
                                                                    capsys, monkeypatch):
        prod, mirror = two_clones
        # Объявлен ДОСТАВЛЕННЫЙ файл: тогда «находки нет» верно при любой живости процессов,
        # а инъектировать `ps` в CLI нельзя. Прочитан чужой журнал или нет — видно по
        # `entries_checked`, и это ровно тот ноль, которого 22.10 не существовало.
        _announce(mirror, "cycle-40064", "scripts/kept.py")
        _declare(prod, mirror)
        own_log = prod / "data" / "session_changes.jsonl"
        own_log.parent.mkdir(parents=True, exist_ok=True)
        own_log.write_text("", encoding="utf-8")
        _settle(prod)
        monkeypatch.delenv("SPA_SESSION_ID", raising=False)

        rc = guard.main(["--root", str(prod), "--log", str(own_log),
                         "--base", "base", "--json"])
        payload = json.loads(capsys.readouterr().out)
        rows = payload["sibling_clones"]
        assert [r["state"] for r in rows] == [guard.SIBLING_MEASURED]
        assert rows[0]["entries_checked"] == 1, "журнал ДРУГОГО клона прочитан через main()"
        assert rows[0]["log"] == str((mirror / "data" / "session_changes.jsonl").resolve())
        assert rows[0]["findings"] == []
        assert rc == 0, "объявленный файл доставлен — находки нет"

    def test_main_returns_two_when_a_declared_clone_cannot_be_measured(self, guard, two_clones,
                                                                      capsys, monkeypatch):
        """Проводка кода возврата: «клон не измерен» обязан доехать до кода 2 из CLI."""
        prod, mirror = two_clones
        _declare(prod, mirror)                     # журнала объявлений в зеркале нет
        own_log = prod / "data" / "session_changes.jsonl"
        own_log.parent.mkdir(parents=True, exist_ok=True)
        own_log.write_text("", encoding="utf-8")
        _settle(prod)
        monkeypatch.delenv("SPA_SESSION_ID", raising=False)

        rc = guard.main(["--root", str(prod), "--log", str(own_log),
                         "--base", "base", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert [r["state"] for r in payload["sibling_clones"]] == [guard.SIBLING_UNMEASURED]
        assert rc == 2

    def test_main_does_not_lower_an_existing_unmeasured_verdict(self, guard, two_clones,
                                                                capsys, monkeypatch):
        """Чужой клон может только ПОДНЯТЬ код возврата. Понижать «не измерено» своего
        отчёта он не вправе — иначе починка стала бы глушилкой."""
        prod, mirror = two_clones
        _announce(mirror, "cycle-40064", "scripts/kept.py")      # доставлено, находок нет
        _declare(prod, mirror)
        own_log = prod / "data" / "session_changes.jsonl"
        own_log.parent.mkdir(parents=True, exist_ok=True)
        own_log.write_text("{битая строка\n", encoding="utf-8")  # ⇒ своё «не измерено»
        _settle(prod)
        monkeypatch.delenv("SPA_SESSION_ID", raising=False)

        rc = guard.main(["--root", str(prod), "--log", str(own_log),
                         "--base", "base", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["unmeasured"], "битая строка журнала — своё «не измерено»"
        assert rc == 2


# ── 5. печать чужого «не измерено» имеет потолок, а находки — нет ────────────

def test_other_clones_unmeasured_rows_are_capped_in_print(guard):
    """Замер #907 на живом зеркале: 18 находок и **83** «не измерено». Печатать все восемьдесят
    три значит получить раздел, который перестанут читать, — поэтому у чужого «не измерено»
    есть потолок и названный остаток, а у НАХОДОК потолка нет: именно их и надо поднимать."""
    many = [{"session": None, "path": f"p{i}.py", "reason": "не измерено"} for i in range(20)]
    rows = [{"root": "/elsewhere", "log": "/elsewhere/data/session_changes.jsonl",
             "state": guard.SIBLING_MEASURED, "reason": None, "entries_checked": 3,
             "findings": [], "unmeasured": many}]
    text = guard.render({"base_ref": "base", "base_sha": "deadbeef", "grace_hours": 3.0,
                         "entries_checked": 0, "sessions_active": 0, "sessions_checked": 0,
                         "findings": [], "unmeasured": [], "sibling_clones": rows})
    shown = sum(1 for line in text.splitlines() if "[не измерено]" in line)
    assert shown == guard.SIBLING_UNMEASURED_SHOWN
    assert f"и ещё {20 - guard.SIBLING_UNMEASURED_SHOWN}" in text


# ── 6. объявление РЕПОЗИТОРИЯ читается, а не только тестовое ─────────────────

def test_the_repositorys_own_declaration_still_parses(guard):
    """Проводка к ДАННЫМ: форма `architecture/history_roots.json` сменится — покраснеет здесь.

    Про состояние клона на машине прогона тест не утверждает ничего (в CI зеркала нет, на
    боевом Маке оно есть — это свойство ХОСТА, и судить о нём значило бы заводить ровно ту
    бомбу, от которой предостерегает `.claude/rules/deployment.md`). Утверждается ровно одно:
    объявление прочитано, список `roots` на месте, и ни одна запись не осталась без разбора.
    """
    clones, err = guard.declared_clone_roots(ROOT)
    assert err is None, f"объявление клонов репозитория не прочитано: {err}"
    assert clones, "в architecture/history_roots.json объявлен хотя бы один клон"
    known = {guard.SIBLING_MEASURED, guard.SIBLING_ABSENT, guard.SIBLING_SAME,
             guard.SIBLING_UNMEASURED}
    assert {c["state"] for c in clones} <= known
