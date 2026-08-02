"""Гарантия шага 0c протокола: «память лежит в git?» (инвариант #13).

Дефект процесса (найден циклом #86, 2026-08-02): решения владельца живой сессии **2026-07-23**
существовали ТОЛЬКО в рабочем дереве хоста и не были закоммичены ни в одну ветку —
одиннадцать дней. Не доехали: `docs/decisions/ADR-054-kill-switch-authority.md`,
`ADR-055-head-of-investment-agent-layer.md`, оба `docs/rfcs/RFC-054-*.md`, идея-источник,
девять карточек бэклога и ответы «Вариант X» в десяти карточках `owner-decision` (на origin
те же карточки стояли `needs-owner` без ответа). Радиус: автономные циклы читают решения и
очередь ИЗ GIT — одиннадцать циклов подряд видели вопросы, на которые владелец уже ответил, а
TOP-приоритетную директиву владельца (Head of Investment) не видели вовсе.

Шаг 0a (`check_undelivered_work.py`) на этот вопрос не отвечает **по построению**: он сверяет
работу, ОБЪЯВЛЕННУЮ в `session_changes.jsonl`. Живая сессия с владельцем ничего не объявляет.

`scripts/check_memory_in_git.py` меряет это двумя независимыми способами:
1. `--tree` — домены памяти рабочего дерева против `origin/main` (host-side, как шаг 0a);
2. `--links` — ссылочная целостность `docs/decisions/INDEX.md`; работает в ЧИСТОМ чекауте,
   поэтому видна в CI. Именно она краснеет на состоянии origin, которое одиннадцать дней
   держало строку ADR-054 со ссылкой на несуществующий файл.

Тесты герметичны: свои временные git-репозитории в ``tmp_path`` (свой ref
`refs/remotes/origin/main`), git-вызовы подменяются там, где проверяется fail-CLOSED. Сети нет.
Отдельно — контроли против ЖИВОГО репозитория (ратчет: реестр решений обязан быть цел).
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


mem = _load("check_memory_in_git_under_test", "scripts/check_memory_in_git.py")


# ── герметичный git-репозиторий ──────────────────────────────────────────────

def _run(cwd, *args):
    return subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с веткой, играющей роль origin/main."""
    r = tmp_path / "repo"
    (r / "docs" / "decisions").mkdir(parents=True)
    (r / "nimbalyst-local" / "tracker").mkdir(parents=True)
    _run(r, "git", "init", "-q")
    _run(r, "git", "config", "user.email", "t@t")
    _run(r, "git", "config", "user.name", "t")
    return r


def _commit_as_origin(repo, msg="c"):
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "-m", msg)
    head = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    _run(repo, "git", "update-ref", "refs/remotes/origin/main", head)
    return head


# ── classify: пять состояний ────────────────────────────────────────────────

def test_classify_ok_when_tree_matches_base(repo):
    p = repo / "docs" / "decisions" / "ADR-900-x.md"
    p.write_text("решение\n", encoding="utf-8")
    _commit_as_origin(repo)
    state, why = mem.classify(repo, "origin/main", "docs/decisions/ADR-900-x.md")
    assert state == mem.OK, why


def test_classify_absent_is_a_finding_when_content_never_existed(repo):
    """Ровно случай ADR-055: файл есть в дереве, на origin его нет и не было."""
    (repo / "docs" / "decisions" / "seed.md").write_text("seed\n", encoding="utf-8")
    _commit_as_origin(repo)
    p = repo / "docs" / "decisions" / "ADR-055-head-of-investment.md"
    p.write_text("решение владельца 2026-07-23\n", encoding="utf-8")
    state, why = mem.classify(repo, "origin/main", "docs/decisions/ADR-055-head-of-investment.md")
    assert state == mem.ABSENT, why
    assert state in mem.FINDING_STATES


def test_classify_diverged_is_a_finding_when_edit_never_reached_origin(repo):
    """Ровно случай `.claude/rules/risk-engine.md`: путь на origin есть, правка — нет."""
    p = repo / "docs" / "decisions" / "INDEX.md"
    p.write_text("строка 1\n", encoding="utf-8")
    _commit_as_origin(repo)
    p.write_text("строка 1\nстрока про ADR-055\n", encoding="utf-8")
    state, why = mem.classify(repo, "origin/main", "docs/decisions/INDEX.md")
    assert state == mem.DIVERGED, why
    assert state in mem.FINDING_STATES


def test_classify_stale_local_is_not_a_finding(repo):
    """ГЛАВНЫЙ ложноположительный: дерево ОТСТАЛО от origin — это не потеря памяти.

    Без этого различения проверка утонула бы в шуме ровно так же, как сырое «отличается»
    в шаге 0a (45 находок на 12 записей, почти все ложные).
    """
    p = repo / "docs" / "decisions" / "ADR-900-x.md"
    p.write_text("версия 1\n", encoding="utf-8")
    _commit_as_origin(repo, "v1")
    p.write_text("версия 2\n", encoding="utf-8")
    _commit_as_origin(repo, "v2")
    p.write_text("версия 1\n", encoding="utf-8")  # рабочее дерево откатилось назад
    state, why = mem.classify(repo, "origin/main", "docs/decisions/ADR-900-x.md")
    assert state == mem.STALE_LOCAL, why
    assert state not in mem.FINDING_STATES


def test_classify_deleted_on_origin_but_known_content_is_not_a_finding(repo):
    p = repo / "docs" / "decisions" / "ADR-900-x.md"
    p.write_text("версия 1\n", encoding="utf-8")
    _commit_as_origin(repo, "v1")
    p.unlink()
    _commit_as_origin(repo, "удалено")
    p.write_text("версия 1\n", encoding="utf-8")  # осталось локально
    state, why = mem.classify(repo, "origin/main", "docs/decisions/ADR-900-x.md")
    assert state == mem.STALE_LOCAL, why


# ── fail-CLOSED: «не измерено» никогда не сворачивается в «в порядке» ────────

def test_classify_unreadable_file_is_unchecked_not_ok(repo):
    _commit_as_origin(repo)
    state, why = mem.classify(repo, "origin/main", "docs/decisions/nope.md")
    assert state == mem.UNCHECKED
    assert "не измерено" in why or "не читается" in why


def test_classify_broken_git_history_is_unchecked_not_ok(repo):
    p = repo / "docs" / "decisions" / "ADR-900-x.md"
    p.write_text("x\n", encoding="utf-8")
    _commit_as_origin(repo)

    def failing_git(cwd, *args):
        if args and args[0] == "log":
            return 128, "", "boom"
        return mem._git(cwd, *args)

    state, why = mem.classify(repo, "origin/main", "docs/decisions/ADR-900-x.md",
                              git=failing_git)
    assert state == mem.UNCHECKED, why


def test_unresolvable_base_ref_does_not_report_tree_as_clean(repo):
    p = repo / "docs" / "decisions" / "ADR-900-x.md"
    p.write_text("x\n", encoding="utf-8")
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "-m", "c")  # ref origin/main НЕ создаём
    report = mem.build_report(root=repo, base_ref="origin/main", do_links=False)
    assert report["unchecked"], "нет base ref ⇒ обязано быть «не измерено», а не пустой отчёт"
    assert mem.exit_code(report) == 2


def test_exit_code_unchecked_dominates_findings():
    assert mem.exit_code({"unchecked": ["x"], "findings": [], "link_findings": []}) == 2
    assert mem.exit_code({"unchecked": ["x"], "findings": [1], "link_findings": []}) == 2
    assert mem.exit_code({"unchecked": [], "findings": [1], "link_findings": []}) == 1
    assert mem.exit_code({"unchecked": [], "findings": [], "link_findings": ["y"]}) == 1
    assert mem.exit_code({"unchecked": [], "findings": [], "link_findings": []}) == 0


# ── обход доменов памяти ────────────────────────────────────────────────────

def test_iter_memory_paths_collects_domains_and_named_files(repo):
    (repo / "docs" / "decisions" / "ADR-900-x.md").write_text("a", encoding="utf-8")
    (repo / "nimbalyst-local" / "tracker" / "own-1.md").write_text("b", encoding="utf-8")
    (repo / "nimbalyst-local" / "tracker" / "notes.txt").write_text("c", encoding="utf-8")
    (repo / "docs" / "POST_PAPER_TEST_PLAN.md").write_text("d", encoding="utf-8")
    got = mem.iter_memory_paths(repo)
    assert "docs/decisions/ADR-900-x.md" in got
    assert "nimbalyst-local/tracker/own-1.md" in got
    assert "docs/POST_PAPER_TEST_PLAN.md" in got, "именованный файл-решение обязан попадать"
    assert "nimbalyst-local/tracker/notes.txt" not in got, "не-markdown не обходим"


def test_iter_memory_paths_honours_exclusions(repo):
    (repo / "nimbalyst-local" / "tracker" / "_BOARD.md").write_text("доска", encoding="utf-8")
    (repo / "nimbalyst-local" / "tracker" / "own-1.md").write_text("b", encoding="utf-8")
    got = mem.iter_memory_paths(repo)
    assert "nimbalyst-local/tracker/_BOARD.md" not in got
    assert "nimbalyst-local/tracker/own-1.md" in got


def test_exclusion_registry_is_traceable_and_not_stale():
    """Исключение обязано иметь обоснование И существовать — протухшие записи краснят."""
    assert mem.EXCLUSIONS, "пустой реестр исключений допустим, но тогда убрать и проверку"
    for path, reason in mem.EXCLUSIONS.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 30, (
            f"исключение {path} без прослеживаемого обоснования")
        assert (ROOT / path).exists(), (
            f"исключение {path} протухло — такого пути в репозитории уже нет")


# ── ссылочная целостность реестра решений ───────────────────────────────────

def _index(repo, text):
    (repo / "docs" / "decisions" / "INDEX.md").write_text(text, encoding="utf-8")


def test_index_links_flags_dangling_adr_reference(repo):
    """Ровно состояние origin/main 22.07–02.08: строка ADR-054 есть, файла нет."""
    _index(repo, "| ADR-054 | Kill-switch authority | Accepted | "
                 "[ADR-054](ADR-054-kill-switch-authority.md) |\n")
    findings, unchecked = mem.check_index_links(repo)
    assert not unchecked
    assert any("ADR-054-kill-switch-authority.md" in f for f in findings)


def test_index_links_flags_backticked_repo_relative_reference(repo):
    """RFC в реестре указан бэктиками, а не ссылкой — тоже обязан проверяться."""
    _index(repo, "| ADR-054 | x | Accepted | (RFC `docs/rfcs/RFC-054-kill-switch-authority.md`) |\n")
    findings, _ = mem.check_index_links(repo)
    assert any("RFC-054-kill-switch-authority.md" in f for f in findings)


def test_index_links_flags_adr_file_missing_from_registry(repo):
    _index(repo, "реестр без строк\n")
    (repo / "docs" / "decisions" / "ADR-055-head-of-investment.md").write_text("x", encoding="utf-8")
    findings, _ = mem.check_index_links(repo)
    assert any("ADR-055-head-of-investment.md" in f and "не упомянут" in f for f in findings)


def test_index_links_clean_when_registry_and_files_agree(repo):
    (repo / "docs" / "decisions" / "ADR-055-x.md").write_text("x", encoding="utf-8")
    _index(repo, "| ADR-055 | x | Accepted | [ADR-055](ADR-055-x.md) |\n")
    findings, unchecked = mem.check_index_links(repo)
    assert findings == [] and unchecked == []


def test_index_links_ignores_template_and_index_itself(repo):
    (repo / "docs" / "decisions" / "_TEMPLATE.md").write_text("шаблон", encoding="utf-8")
    _index(repo, "пустой реестр\n")
    findings, _ = mem.check_index_links(repo)
    assert findings == [], "шаблон и сам реестр — не решения"


def test_missing_index_is_unchecked_not_clean(repo):
    findings, unchecked = mem.check_index_links(repo)
    assert findings == []
    assert unchecked, "нет реестра ⇒ «не измерено», а не «реестр цел»"


# ── без сети, без копипасты ─────────────────────────────────────────────────

def test_guard_never_fetches(  ):
    """Как и шаг 0a: проверка read-only и не ходит в сеть."""
    src = (ROOT / "scripts" / "check_memory_in_git.py").read_text(encoding="utf-8")
    assert '"fetch"' not in src and "'fetch'" not in src
    for banned in ("urllib", "requests", "socket", "http.client"):
        assert f"import {banned}" not in src


def test_activity_measurement_is_reused_not_copied():
    """Измерение «содержимое было на origin» переиспользовано из шага 0a, а не скопировано.

    Сверяем с КАНОНИЧЕСКИМ модулем шага 0a (тем, что импортировал сам продукт), а не с
    повторно загруженной копией: копия — другой объект по построению, и такой ассерт
    краснел бы даже при честном переиспользовании.
    """
    step0a = sys.modules["check_undelivered_work"]
    assert Path(step0a.__file__).resolve() == (ROOT / "scripts" / "check_undelivered_work.py")
    assert mem.origin_blob_history is step0a.origin_blob_history
    assert mem._blob_sha is step0a._blob_sha
    # и в самом сторожe нет второй реализации того же измерения
    src = (ROOT / "scripts" / "check_memory_in_git.py").read_text(encoding="utf-8")
    assert "def origin_blob_history" not in src and "def _blob_sha" not in src


# ── ратчет по ЖИВОМУ репозиторию ────────────────────────────────────────────

def test_live_registry_of_decisions_is_intact():
    """CI-видимый гейт: каждая ссылка реестра разрешается, каждый ADR в реестре.

    Красный здесь = решение существует только на чьём-то диске (случай ADR-054/055) либо
    строка реестра указывает в пустоту. Это и есть инвариант #13, ставший измерением.
    """
    findings, unchecked = mem.check_index_links(ROOT)
    assert not unchecked, unchecked
    assert findings == [], "\n".join(findings)


def test_live_memory_scan_is_not_silently_empty():
    """Сканер, не нашедший НИ ОДНОГО файла памяти, считается красным (fail-CLOSED).

    Зеркало гейта исключений CI: «ничего не нашёл» не должно читаться как «всё в порядке».
    """
    paths = mem.iter_memory_paths(ROOT)
    assert len(paths) > 50, f"домены памяти почти пусты ({len(paths)}) — сканер сломан"
    assert any(p.startswith("docs/decisions/") for p in paths)
    assert any(p.startswith("nimbalyst-local/tracker/") for p in paths)
