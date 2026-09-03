"""Пустая строка в `files` объявления — это НЕ путь и НЕ корень репозитория.

Карточка `inbox-obyavlenie-s-pustym-spiskom-failov-rozhd` (замер цикла #433, 30.08).

**Дефект.** `scripts/log_session_change.py` записывает в `files` то, что ему передали,
не спрашивая, путь ли это. Пустая строка проходит насквозь, а читатель
`scripts/check_undelivered_work.py` разрешает её в `.` (`Path("") == Path(".")`) —
то есть в КОРЕНЬ репозитория. Корень не может «появиться на origin/main под тем же
именем», поэтому находка `[отсутствует] .` **не снимается ничем**, кроме подлога, и
занимает самую читаемую секцию обязательного шага 0a до конца жизни журнала. Верхнего
горизонта у сканера нет по построению (сказано в его собственной шапке).

**Класс растёт сам себя.** Замер карточки (#433, 30.08): такая запись была ОДНА.
Перемер цикла #462 (02.09, тот же живой `data/session_changes.jsonl`): их **три**, и две
приехали за последние сутки —

    2026-08-30T10:58:40Z  cycle-98187  (#432, «полные прогоны выстроены в цепочку»)
    2026-09-02T07:05:50Z  cycle-21873  (#455, «стартовал: читаю STATE/INDEX/BRIEFING…»)
    2026-09-02T18:21:36Z  cycle-88784  (#460, «стартовал: читаю STATE/INDEX/BRIEFING…»)

— обе новые от объявления оркестратора «цикл стартовал», у которого файлов и не бывает.
То есть источник не разовый: пока писатель принимает не-путь, шаг 0a будет копить
неснимаемые строки по одной за цикл.

**Две двери — два вопроса, чинятся обе и не связываются друг с другом.** Писатель
перестаёт ЗАПИСЫВАТЬ не-путь (и говорит об этом вслух — молчаливое отбрасывание было бы
той же болезнью с другого конца); читатель перестаёт ЧИТАТЬ не-путь как корень репозитория
(иначе три уже написанные записи не снимаются: переписать журнал задним числом нельзя).

Обязательные обратные контроли — из тела карточки: настоящий недоставленный файл остаётся
находкой, непустой относительный путь судится ровно как прежде, а форма записи писателя
при непустом `--files` остаётся БАЙТ В БАЙТ прежней (её пиннят чужие тесты
`test_card_claim_guard::TestAnnounceLogField`, `test_durable_session_id::TestWriterEntrySchema`).
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
from contextlib import redirect_stderr
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: читатель сверяет объявленные файлы с базовым ref "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_empty_path_reader", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def writer():
    return _load("_test_empty_path_writer", "scripts/log_session_change.py")


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


def entry(session, files, summary="ход работ"):
    return {"ts": "2026-01-15T12:00:00Z", "session": session,
            "summary": summary, "files": [str(f) for f in files]}


def report(guard, repo, entries):
    return guard.build_report(
        entries=entries, root=repo, base_ref="base", self_session="pid999999",
        ps=lambda pid: (1, ""), now=_NOW, grace_hours=3.0,
    )


def rows_about_root(rep):
    """Все строки отчёта, судящие о пути `.` — в КАКОМ БЫ разделе они ни лежали.

    Раздел спрашивать нельзя: вердикт по несуществующему пути мигрирует между
    `findings` / `nowhere` / `deleted` / `unmeasured` по состоянию репозитория, и тест,
    пришпиленный к одному разделу, замолчал бы ровно тогда, когда строка переехала.
    """
    out = []
    for key, value in rep.items():
        if not isinstance(value, list):
            continue
        for row in value:
            if isinstance(row, dict) and row.get("path") in (".", "", None) \
                    and "state" in row:
                out.append((key, row))
    return out


# ── 1. Положительный контроль: ровно живая авария ────────────────────────────

class TestEmptyDeclaredPathIsNotTheRepoRoot:
    def test_empty_path_produces_no_verdict_about_the_repo_root(self, guard, repo):
        """Ровно запись `cycle-98187` от 2026-08-30T10:58:40Z: `files: [""]`.

        На непочиненном коде здесь `findings == [{"path": ".", "state": "absent", …}]`
        и `exit_code == 1` — находка, которую нельзя снять ничем.

        Ярлык фикстуры — `pid<N>`, а не дословный `cycle-98187` живой записи, и это
        ОБЕСПЕЧЕНИЕ ПРЕДПОСЫЛКИ, а не послабление: у ярлыка без pid активность сессии
        не измеряется по построению (`unmeasured`, код 2), и тест судил бы о ярлыке
        вместо пустого пути. Тот же порядок, по которому соседний файл переименовал
        `pid1` → `pid101`: чинится фикстура, а не проверка.
        """
        rep = report(guard, repo, [entry("pid31439", [""])])
        assert rows_about_root(rep) == [], rows_about_root(rep)
        assert rep["findings"] == []
        assert rep["exit_code"] == 0

    def test_whitespace_only_path_is_judged_the_same(self, guard, repo):
        """Пробел — тоже не путь. Иначе правило чинит одну запись, а не класс."""
        rep = report(guard, repo, [entry("pid31439", ["   "])])
        assert rows_about_root(rep) == [], rows_about_root(rep)
        assert rep["exit_code"] == 0

    def test_entry_is_still_counted_as_checked_not_dropped_in_silence(self, guard, repo):
        """Запись не исчезает: объявление без файлов — законное состояние, а не пропуск.

        Иначе «починка» была бы глушилкой: сессия, объявившая ход работ, перестала бы
        существовать для сторожа вовсе.
        """
        rep = report(guard, repo, [entry("pid31439", [""])])
        assert rep["sessions_checked"] == 1


# ── 2. Обратные контроли из тела карточки ────────────────────────────────────

class TestFixIsNotASilencer:
    def test_real_undelivered_file_is_still_a_finding(self, guard, repo):
        """Главный обратный контроль: настоящая недоставленная работа остаётся находкой."""
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "brand_new.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/brand_new.py"]
        assert rep["findings"][0]["state"] == guard.ABSENT
        assert rep["exit_code"] == 1

    def test_empty_path_next_to_a_real_one_does_not_hide_the_real_one(self, guard, repo):
        """Отбрасывается НЕ-путь, а не запись целиком."""
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo,
                     [entry("pid31439", ["", repo / "scripts" / "brand_new.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/brand_new.py"]
        assert rows_about_root(rep) == [], rows_about_root(rep)
        assert rep["exit_code"] == 1

    def test_nonempty_relative_path_is_judged_exactly_as_before(self, guard, repo):
        """Относительный путь — по-прежнему путь; `declaring_tree`/`cwd` не задеты.

        Правка сужает класс до ПУСТОЙ строки; относительное объявление (замер 24.08,
        сессия `rnd-75-rearm`) продолжает судиться прежним порядком.
        """
        (repo / "scripts" / "brand_new.py").write_text("work\n", encoding="utf-8")
        rep = report(guard, repo, [entry("pid31439", ["scripts/brand_new.py"])])
        assert [f["path"] for f in rep["findings"]] == ["scripts/brand_new.py"]
        assert rep["exit_code"] == 1

    def test_delivered_file_is_still_silent(self, guard, repo):
        rep = report(guard, repo, [entry("pid31439", [repo / "scripts" / "kept.py"])])
        assert rep["findings"] == []
        assert rep["exit_code"] == 0


# ── 3. Писатель: не-путь не записывается, и об этом СКАЗАНО ──────────────────

class TestWriterRefusesToRecordANonPath:
    def _record(self, writer, tmp_path, files):
        log = tmp_path / "announce.jsonl"
        err = io.StringIO()
        with redirect_stderr(err):
            entry = writer.record("ход работ", files, "", log=log)
        written = [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines()]
        return entry, written, err.getvalue()

    def test_empty_path_is_not_written_to_files(self, writer, tmp_path):
        entry, written, _ = self._record(writer, tmp_path, [""])
        assert entry["files"] == []
        assert written[0]["files"] == []

    def test_dropping_a_non_path_is_said_out_loud(self, writer, tmp_path):
        """Молчаливое отбрасывание — та же болезнь с другого конца: сессия обязана
        узнать, что объявила не то, а не обнаружить пропажу через сутки в шаге 0a."""
        _, _, err = self._record(writer, tmp_path, [""])
        assert err.strip(), "писатель отбросил объявленный путь молча"

    def test_announcement_with_no_files_left_carries_no_cwd(self, writer, tmp_path):
        """`cwd` пишется ТОЛЬКО при относительном пути среди объявленных. Пустая строка
        не абсолютна, и до правки она втягивала в запись поле, которое ничего не
        объясняет: файлов-то нет."""
        entry, _, _ = self._record(writer, tmp_path, [""])
        assert "cwd" not in entry

    def test_nonempty_files_are_recorded_byte_for_byte_as_before(self, writer, tmp_path):
        """Форма записи — контракт (её пиннят чужие тесты). Правка её не трогает."""
        paths = ["/abs/one.py", "/abs/two.py"]
        entry, written, err = self._record(writer, tmp_path, paths)
        assert entry["files"] == paths
        assert written[0]["files"] == paths
        assert "cwd" not in entry
        assert err == ""

    def test_nonempty_relative_path_still_reaches_the_record(self, writer, tmp_path):
        """Сужение — до пустой строки. Относительный путь по-прежнему записывается
        (и по-прежнему тянет за собой `cwd`)."""
        entry, _, _ = self._record(writer, tmp_path, ["scripts/x.py"])
        assert entry["files"] == ["scripts/x.py"]
        assert entry.get("cwd")
