"""Шаг 0a: раздел квитанций перестаёт быть осадком — свёртка по деревьям (цикл #307).

**Что измерено (2026-08-19, прод-дерево, база origin/main e3bcc6a0d).** Обязательный к прочтению
отчёт шага 0a — 101 строка, из них **87 — раздел «снятые деревья с квитанцией»**, а уникальных
путей в нём **48**. То есть 39 строк (45 %) — чистый повтор, и каждая несёт ~120 символов
одинаковой шапки «дерево снято …, архив: …».

**Откуда повтор — измерено, а не предположено.** Раздел `reaped` был ЕДИНСТВЕННЫМ из пяти без
свёртки, которая у соседей (`nowhere`, `deleted`, `findings`) стоит с самого начала: путь,
объявленный несколько раз (объявление до работы, потом уточняющее), давал столько же записей.
Второй источник — `/tmp` ≡ `/private/tmp`: на macOS это один каталог, один файл объявляется то
одной формой, то другой, и по сырой строке пара выглядит как два разных пути (тот же класс,
который #303 закрыл в шаге 0b). Таких «двойников по ярлыку» в замере 5 из 53.

**Почему это не косметика.** Механизм, которым сторожа глохнут, в этом репозитории назван и
разобран трижды (#243 сбивал раздел с 42 до 4, #291 добавил вердикт квитанции, карточка
`inbox-shag-0a-povtoryaet-odni-i-te-zhe-6-nahod`): следующая сессия учится ЛИСТАТЬ раздел
целиком, и настоящая потеря уезжает вместе с осадком. Уборка деревьев с #257 — норма (§3.4),
значит раздел будет только расти.

**Ослабления нет, и это проверяется в обе стороны.** Свёртка — рендер и дедупликация записи,
вердикты и код возврата не тронуты ни одной строкой. Ни один путь не исчезает: шапка выносится
на дерево, пути перечисляются под своим вердиктом, повторившая сессия называется в
`also_declared_by` (ровно как у соседних разделов). Обратные контроли обязательны и стоят ниже:
настоящая находка НЕ сворачивается и держит код 2 · два РАЗНЫХ вердикта в одном дереве не
свариваются в один · снятие дерева не становится способом гасить находки.

Тесты герметичны: настоящие git-репозитории в ``tmp_path``, `ps` подменён, сети нет.
"""
import importlib.util
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: сверка объявленных путей с базовым ref "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_receipt_render_guard", "scripts/check_undelivered_work.py")


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env,
    )


# Пути, которые в замере #307 повторялись чаще всего. На базе они ОБЯЗАНЫ существовать: вердикт
# `delivered` («путь при снятии не расходился с базой») выдаётся именно тогда, когда квитанция
# путь не называет, а на базе он есть. Не будь их на базе — ветка увела бы в `nowhere`, и тест
# мерил бы не тот раздел.
ON_BASE = ("docs/STATE.md", "docs/journal/2026-W34.md", "scripts/check_card_claim.py",
           "nimbalyst-local/tracker/_BOARD.md")


@pytest.fixture()
def repo(tmp_path):
    """Репозиторий с веткой `base` (роль origin/main)."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    (r / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
    for rel in ON_BASE:
        f = r / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("base content\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "branch", "base")
    return r


# Объявление старше окна ожидания, процесса нет ⇒ сессия молчит и запись меряется.
_NOW = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)

ARCHIVE = "/arch/spa_c303-20260819T124837Z"
REAP_TS = "2026-08-19T12:48:37Z"


def entry(session, files, ts="2026-01-15T12:00:00Z", summary="работа"):
    return {"ts": ts, "session": session, "summary": summary, "files": [str(f) for f in files]}


def report(guard, repo, entries, **kw):
    kw.setdefault("ps", lambda pid: (1, ""))
    return guard.build_report(entries=entries, root=repo, base_ref="base",
                              self_session="pid999999", now=_NOW, grace_hours=3.0, **kw)


def ledger(repo, rows):
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / "worktree_reap_log.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def receipt(wt, paths, ts=REAP_TS, archive=ARCHIVE):
    return {"ts": ts, "worktree": str(wt), "base": "base", "archive": archive,
            "churn_paths": 89, "paths": dict(paths)}


# ── 1. положительный контроль: повтор объявления даёт ОДНУ запись ────────────

class TestRepeatedDeclarationCollapses:
    """Замер #307: 78 объявлений на 48 путей — раздел был единственным без свёртки."""

    def test_one_path_declared_twice_is_one_receipt_record(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        p = wt / "docs" / "STATE.md"
        rep = report(guard, repo, [entry("pid26813", [p]), entry("pid26813", [p])])

        assert len(rep["reaped"]) == 1, rep["reaped"]

    def test_a_second_session_is_named_not_dropped(self, guard, repo, tmp_path):
        """Видимость не сужается: у соседних разделов это ровно тот же `also_declared_by`."""
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        p = wt / "docs" / "STATE.md"
        rep = report(guard, repo, [entry("pid26813", [p]), entry("pid99001", [p])])

        assert len(rep["reaped"]) == 1
        assert rep["reaped"][0]["also_declared_by"] == ["pid99001"]
        assert "pid99001" in guard.render(rep)

    def test_the_same_session_is_not_listed_twice_as_its_own_witness(self, guard, repo,
                                                                    tmp_path):
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        p = wt / "docs" / "STATE.md"
        rep = report(guard, repo, [entry("pid26813", [p])] * 3)

        assert rep["reaped"][0]["also_declared_by"] == []


# ── 2. положительный контроль: /tmp ≡ /private/tmp (класс #303) ──────────────

class TestSymlinkTwinsCollapse:
    """5 из 53 путей замера #307 были одним файлом под двумя формами одного каталога."""

    TREE = "/tmp/spa_c307_receipt_render_fixture"

    def test_tmp_and_private_tmp_declarations_are_one_path(self, guard, repo):
        assert not Path(self.TREE).exists(), "фикстура ожидает несуществующее дерево"
        ledger(repo, [receipt(self.TREE, {})])
        rep = report(guard, repo, [
            entry("pid26813", [f"{self.TREE}/docs/STATE.md"]),
            entry("pid26813", [f"/private{self.TREE}/docs/STATE.md"]),
        ])

        assert len(rep["reaped"]) == 1, rep["reaped"]
        assert rep["reaped"][0]["rel"] == "docs/STATE.md"

    def test_the_collapsed_twin_is_still_printed_once(self, guard, repo):
        ledger(repo, [receipt(self.TREE, {})])
        text = guard.render(report(guard, repo, [
            entry("pid26813", [f"{self.TREE}/docs/STATE.md"]),
            entry("pid26813", [f"/private{self.TREE}/docs/STATE.md"]),
        ]))
        assert text.count("docs/STATE.md") == 1, text


# ── 3. положительный контроль: шапка квитанции — один раз на дерево ──────────

class TestReceiptHeaderIsPrintedOncePerTree:
    """~120 символов одинаковой шапки у каждого пути и есть тот самый осадок."""

    PATHS = ("docs/STATE.md", "docs/journal/2026-W34.md", "scripts/check_card_claim.py")

    def _rep(self, guard, repo, wt):
        ledger(repo, [receipt(wt, {})])
        return report(guard, repo, [entry("pid26813", [wt / p for p in self.PATHS])])

    def test_archive_and_timestamp_appear_exactly_once(self, guard, repo, tmp_path):
        text = guard.render(self._rep(guard, repo, tmp_path / "spa_c303"))
        assert text.count(ARCHIVE) == 1, text
        assert text.count(REAP_TS) == 1, text

    def test_every_declared_path_survives_the_collapse(self, guard, repo, tmp_path):
        """Граница свёртки: короче — да, беднее — нет."""
        text = guard.render(self._rep(guard, repo, tmp_path / "spa_c303"))
        for p in self.PATHS:
            assert p in text, (p, text)

    def test_a_single_verdict_tree_costs_exactly_two_lines_not_one_per_path(self, guard, repo,
                                                                           tmp_path):
        """Точный якорь длины: дерево + вердикт, сколько бы путей под ним ни лежало.

        Проверяется ПОВЕДЕНИЕ, а не «стало покороче»: до свёртки раздел стоил ровно строку на
        путь (3 строки на эти 3 пути) и рос линейно с числом снятых деревьев."""
        rep = self._rep(guard, repo, tmp_path / "spa_c303")
        body = guard.render(rep).split("🧾", 1)[1].splitlines()[1:]
        body = [ln for ln in body if ln.strip() and not ln.startswith("✅")]
        assert len(body) == 2, body

    def test_two_trees_get_two_headers(self, guard, repo, tmp_path):
        """Свёртка идёт ПО ДЕРЕВЬЯМ: слипнись они, читатель потеряет, что откуда."""
        a, b = tmp_path / "spa_c303", tmp_path / "spa_c304"
        ledger(repo, [receipt(a, {}, archive="/arch/a"), receipt(b, {}, archive="/arch/b")])
        text = guard.render(report(guard, repo, [
            entry("pid26813", [a / "docs" / "STATE.md"]),
            entry("pid66226", [b / "docs" / "STATE.md"]),
        ]))
        assert text.count("/arch/a") == 1 and text.count("/arch/b") == 1, text
        assert text.count("  ▪ ") == 2, text


# ── 4. обратные контроли: свёртка ничего не гасит и не сваривает ─────────────

class TestCollapseNeverHidesAnything:
    """Иначе снятие дерева стало бы способом красить сторожа зелёным (карточка #291, п.4)."""

    def test_two_different_verdicts_in_one_tree_stay_two_lines(self, guard, repo, tmp_path):
        """`delivered` и «не расходился с базой» — РАЗНЫЕ утверждения о работе."""
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {"spa_core/tests/test_new.py": "delivered"})])
        rep = report(guard, repo, [entry("pid26813", [
            wt / "spa_core" / "tests" / "test_new.py",   # назван в квитанции: delivered
            wt / "docs" / "STATE.md",                     # не назван: не расходился с базой
        ])])

        assert len(rep["reaped"]) == 2
        verdicts = {r["verdict"] for r in rep["reaped"]}
        assert len(verdicts) == 2, verdicts
        text = guard.render(rep)
        assert "delivered" in text
        assert "не расходился" in text

    def test_a_real_loss_is_never_folded_into_the_receipt_section(self, guard, repo, tmp_path):
        """Квитанция НАЗЫВАЕТ путь недоставленным ⇒ прежний код 2, мимо свёртки."""
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {"scripts/edge_criterion_consensus.py": "unique"})])
        rep = report(guard, repo,
                     [entry("pid26813", [wt / "scripts" / "edge_criterion_consensus.py"])])

        assert rep["reaped"] == []
        assert rep["exit_code"] == 2
        assert "'unique'" in rep["unmeasured"][0]["reason"]
        assert "edge_criterion_consensus.py" in guard.render(rep)

    def test_a_finding_declared_twice_still_reaches_the_reader(self, guard, repo, tmp_path):
        """Повтор объявления не должен «съедать» находку — сворачивается только осадок."""
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {"scripts/lost.py": "unique"})])
        p = wt / "scripts" / "lost.py"
        rep = report(guard, repo, [entry("pid26813", [p]), entry("pid99001", [p])])

        assert rep["exit_code"] == 2
        assert "lost.py" in guard.render(rep)

    def test_exit_code_of_a_pure_receipt_section_is_unchanged(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        rep = report(guard, repo, [entry("pid26813", [wt / "docs" / "STATE.md"])] * 4)

        assert rep["exit_code"] == 0
        assert rep["findings"] == [] and rep["unmeasured"] == []

    def test_machine_output_keeps_the_tree_so_the_collapse_is_reproducible(self, guard, repo,
                                                                          tmp_path):
        """`--json` обязан нести всё, чем рендер группирует, — иначе свёртку не перепроверить."""
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        rec = report(guard, repo, [entry("pid26813", [wt / "docs" / "STATE.md"])])["reaped"][0]

        assert rec["tree"] == str(wt)
        assert rec["rel"] == "docs/STATE.md"
        assert rec["reap_ts"] == REAP_TS and rec["archive"] == ARCHIVE
        assert rec["path"].endswith("docs/STATE.md")
        assert json.dumps(rec, ensure_ascii=False)   # запись сериализуема целиком


# ── 5. шапка раздела честно называет, что свёрнуто ──────────────────────────

class TestHeadlineTellsTheTruthAboutTheCollapse:
    """Молча сократить отчёт — то же, что молча ослабить проверку: читатель обязан знать."""

    def test_headline_counts_paths_and_declarations_separately(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        p = wt / "docs" / "STATE.md"
        head = [ln for ln in guard.render(
            report(guard, repo, [entry("pid26813", [p]), entry("pid99001", [p])])
        ).splitlines() if ln.startswith("🧾")][0]

        assert "путей 1" in head, head
        assert "объявлений 2" in head, head

    def test_without_repeats_the_headline_does_not_invent_a_second_number(self, guard, repo,
                                                                         tmp_path):
        wt = tmp_path / "spa_c303"
        ledger(repo, [receipt(wt, {})])
        head = [ln for ln in guard.render(
            report(guard, repo, [entry("pid26813", [wt / "docs" / "STATE.md"])])
        ).splitlines() if ln.startswith("🧾")][0]

        assert "путей 1" in head, head
        assert "объявлений" not in head, head
