"""Шаг 0a: улики квитанции снятого дерева обязаны складываться в ВЕРДИКТ (цикл #292).

Карточка `inbox-shag-0a-u-snyatogo-dereva-kvitantsiya-uz`.

**Что было.** Объявленный путь внутри СНЯТОГО дерева, которого нет в квитанции снятия и нет
на базе, проваливался в раздел «НЕ ДОСТАВЛЕНО». При этом ответ уже печатался в той же строке:
«дерево снято …, путь в квитанции не назван, и на origin/main такого файла нет вовсе». Знания
не хватало не было — не хватало вывода из него.

**Почему вывод верен.** Квитанция (`scripts/reap_stale_worktrees.py::record_reap`) перечисляет
КАЖДЫЙ путь, которым дерево расходилось с базой, и составляется ТОГДА, когда дерево ещё
существует. Путь, которого в ней нет, с базой не расходился; если вдобавок на базе такого файла
нет вовсе — в дереве его не было. Допущение не новое: на нём уже держится ветка `delivered`
(«путь при снятии не расходился с базой»), замер по журналу 18.08 — 741 путь против 3 спорных.

**Почему это не косметика.** Уборка деревьев с #257 — норма (§3.4 велит снимать за собой),
значит доля находок с уже снятым деревом растёт, и раздел «НЕ ДОСТАВЛЕНО» заново набьётся
осадком — тем самым, который #243 сбивал с 42 до 4. Замер 18.08: обе записи раздела (2 из 2)
были ровно этого класса, то есть раздел целиком состоял из ложных находок.

**Ослабления нет, и это проверяется в обе стороны.** Находка не исчезает: она меняет ВЕРДИКТ
и место в отчёте, оставаясь в коде возврата 1 (`nowhere` считается находкой, fail-CLOSED,
инв. #2). Пропуск НЕ даётся, когда вывод сделать нельзя: путь под правилом отсева уборщика
(churn) в квитанцию не попал бы, даже если бы лежал в дереве · путь, встречавшийся в истории
базы, — это удаление на origin, а не «нигде» · правило отсева не прочитано — вердикта нет.
Отдельно закреплено, что СНЯТИЕ ДЕРЕВА НЕ СТАНОВИТСЯ СПОСОБОМ ГАСИТЬ НАХОДКИ: путь, названный
в квитанции недоставленным, по-прежнему даёт код 2, а дерево без квитанции — прежнее
«не измерено».

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
    return _load("_test_reaped_receipt_guard", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def reaper():
    return _load("_test_reaped_receipt_reaper", "scripts/reap_stale_worktrees.py")


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
    """Репозиторий с веткой `base` (роль origin/main)."""
    r = tmp_path / "repo"
    (r / "scripts").mkdir(parents=True)
    _git(r.parent, "init", "-q", "-b", "main", str(r))
    (r / "scripts" / "kept.py").write_text("base content\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    _git(r, "branch", "base")
    return r


# Объявление старше окна ожидания, процесса нет ⇒ сессия молчит и запись меряется.
_NOW = datetime(2026, 1, 20, 12, 0, tzinfo=timezone.utc)


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


def receipt(wt, paths, ts="2026-08-18T13:38:28Z", archive="/arch/spa_c289-20260818T133828Z"):
    return {"ts": ts, "worktree": str(wt), "base": "base", "archive": archive,
            "churn_paths": 89, "paths": dict(paths)}


# ── 1. положительный контроль: настоящая авария 18.08, пути цикла #289 ───────

class TestReceiptSilenceIsAVerdict:
    """Замер 18.08: раздел «НЕ ДОСТАВЛЕНО» состоял ЦЕЛИКОМ из этих двух путей."""

    C289 = ("spa_core/tests/test_acceptance_serialization.py",
            "scripts/measure_parallel_acceptance.py")

    def test_both_paths_of_cycle_289_are_judged_nowhere_not_undelivered(self, guard, repo,
                                                                        tmp_path):
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"spa_core/monitoring/stalled_run_diagnosis.py": "delivered",
                                   "spa_core/tests/test_stalled_run_diagnosis.py": "delivered",
                                   "spa_core/tests/acceptance_plateau_baseline.json": "delivered"})])
        rep = report(guard, repo, [entry("pid21014", [wt / p for p in self.C289])])

        assert rep["findings"] == [], rep["findings"]
        assert rep["unmeasured"] == [], rep["unmeasured"]
        assert len(rep["nowhere"]) == 2
        assert {Path(n["path"]).name for n in rep["nowhere"]} == {Path(p).name for p in self.C289}
        assert all(n["state"] == guard.NOWHERE for n in rep["nowhere"])

    def test_the_verdict_names_the_receipt_as_its_evidence(self, guard, repo, tmp_path):
        """Вывод обязан быть объяснён уликой, а не объявлен: читатель должен видеть, ПОЧЕМУ."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])])

        detail = rep["nowhere"][0]["detail"]
        assert "дерево снято 2026-08-18T13:38:28Z" in detail
        assert "/arch/spa_c289-20260818T133828Z" in detail
        assert "путь в квитанции не назван" in detail
        assert "НЕ БЫЛО" in detail

    def test_the_finding_is_not_hidden_the_exit_code_stays_one(self, guard, repo, tmp_path):
        """Главная граница: меняется ВЕРДИКТ и место в отчёте, а не видимость.

        Путь «нигде → ✅ всё доставлено» здесь не заводится намеренно (инв. #2), иначе
        снятие дерева стало бы способом красить сторожа зелёным."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])])
        assert rep["exit_code"] == 1

    def test_render_prints_it_in_the_nowhere_section(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        text = guard.render(report(guard, repo,
                                   [entry("pid31439", [wt / "scripts" / "brand_new.py"])]))
        assert "ПОДНИМАТЬ НЕЧЕГО" in text
        assert "brand_new.py" in text
        assert "НЕ ДОСТАВЛЕНО" not in text

    def test_one_path_declared_twice_is_one_verdict_with_both_sessions(self, guard, repo,
                                                                       tmp_path):
        """Тот же приём, что у остальных разделов: находка одна, объявившие перечислены."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        p = wt / "scripts" / "brand_new.py"
        rep = report(guard, repo, [entry("pid31439", [p]), entry("pid44444", [p])])
        assert len(rep["nowhere"]) == 1
        assert rep["nowhere"][0]["also_declared_by"] == ["pid44444"]


# ── 2. обратные контроли: где вывода НЕТ, там и вердикта нет ────────────────

class TestReapingNeverBecomesAWayToSilence:
    """Карточка, п.4: иначе снятие дерева станет способом гасить находки."""

    def test_path_named_in_the_receipt_as_undelivered_still_fails_closed(self, guard, repo,
                                                                        tmp_path):
        """Настоящая потеря: квитанция НАЗЫВАЕТ путь и говорит «расходится с базой»."""
        wt = tmp_path / "spa_wt_rnd49"
        ledger(repo, [receipt(wt, {"scripts/edge_criterion_consensus.py": "unique"})])
        rep = report(guard, repo,
                     [entry("pid31439", [wt / "scripts" / "edge_criterion_consensus.py"])])
        assert rep["exit_code"] == 2
        assert rep["nowhere"] == []
        assert "'unique'" in rep["unmeasured"][0]["reason"]

    def test_path_named_delivered_stays_delivered(self, guard, repo, tmp_path):
        wt = tmp_path / "spa_wt_c191"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "superseded"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "docs" / "STATE.md"])])
        assert rep["exit_code"] == 0 and rep["nowhere"] == [] and len(rep["reaped"]) == 1

    def test_a_tree_reaped_without_a_receipt_is_still_unmeasured(self, guard, repo, tmp_path):
        """Пропуск даёт КВИТАНЦИЯ, а не сам факт пропажи дерева."""
        ledger(repo, [receipt(tmp_path / "other", {})])
        rep = report(guard, repo,
                     [entry("pid31439", [tmp_path / "spa_wt_gone" / "scripts" / "new.py"])])
        assert rep["exit_code"] == 2 and rep["nowhere"] == []
        assert "рабочее дерево удалено" in rep["unmeasured"][0]["reason"]

    def test_churn_path_gets_no_verdict_because_the_receipt_drops_it_by_rule(self, guard, repo,
                                                                            tmp_path):
        """Граница: уборщик отсеивает `data/` ДО записи квитанции.

        Такой путь в квитанцию не попал бы, даже если бы в дереве лежал, — значит «его там
        не было» из тишины квитанции не следует. Замер 18.08: 69 квитанций из 142 отсеяли
        хотя бы один путь, максимум 92 за раз."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "data" / "alpha_candidates.json"])])
        assert rep["nowhere"] == []
        assert rep["findings"][0]["state"] == guard.ABSENT
        assert "НЕ ИЗМЕРЕНО" in rep["findings"][0]["detail"]
        assert "churn" in rep["findings"][0]["detail"]

    def test_named_churn_fixture_gets_no_verdict_either(self, guard, repo, tmp_path):
        """Точечные churn-пути (перезаписываются прогоном тестов) — тот же отказ."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo,
                     [entry("pid31439", [wt / "spa_core" / "database" / "spa.db"])])
        assert rep["nowhere"] == []
        assert rep["findings"][0]["state"] == guard.ABSENT

    def test_path_that_lived_on_base_before_is_a_deletion_not_nowhere(self, guard, repo,
                                                                      tmp_path):
        """«Нигде» ложно, если имя в истории базы встречалось: это удаление на origin."""
        (repo / "scripts" / "gone.py").write_text("жил\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "add gone")
        _git(repo, "rm", "-q", "scripts/gone.py")
        _git(repo, "commit", "-qm", "remove gone")
        _git(repo, "branch", "-f", "base", "HEAD")

        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "gone.py"])])
        assert rep["nowhere"] == []
        assert rep["findings"][0]["state"] == guard.ABSENT
        assert "удаление/переименование" in rep["findings"][0]["detail"]

    def test_unreadable_churn_rule_yields_no_verdict(self, guard, repo, tmp_path, monkeypatch):
        """fail-CLOSED: не прочитали правило — вердикта нет (класс #226)."""
        monkeypatch.setattr(guard, "churn_rule",
                            lambda: (None, "правило отсева уборщика (churn) прочитать не удалось"))
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])])
        assert rep["nowhere"] == []
        assert rep["findings"][0]["state"] == guard.ABSENT

    def test_unreadable_history_yields_no_verdict(self, guard, repo, tmp_path):
        """Историю базы прочитать не вышло — «нигде» утверждать нечем."""
        wt = tmp_path / "spa_c289"
        ledger(repo, [receipt(wt, {"docs/STATE.md": "delivered"})])
        real = guard._git

        def flaky(cwd, *args):
            if args[:1] == ("log",):
                return 128, "", "fatal: подделано"
            return real(cwd, *args)

        rep = report(guard, repo, [entry("pid31439", [wt / "scripts" / "brand_new.py"])],
                     git=flaky)
        assert rep["nowhere"] == []
        assert rep["findings"][0]["state"] == guard.ABSENT
        assert "НЕ ИЗМЕРЕНО" in rep["findings"][0]["detail"]


# ── 3. правило отсева живёт в ОДНОМ месте ───────────────────────────────────

class TestChurnRuleHasOneDefinition:
    """Копия правила разошлась бы молча, а от неё зависит вердикт «поднимать нечего»."""

    def test_predicate_agrees_with_the_reaper_constants(self, guard, reaper):
        is_churn, why = guard.churn_rule()
        assert why is None and is_churn is not None
        for prefix in reaper.CHURN_PREFIXES:
            assert is_churn(f"{prefix}whatever.json")
        for named in reaper.CHURN_PATHS:
            assert is_churn(named)
        assert not is_churn("scripts/measure_parallel_acceptance.py")
        assert not is_churn("spa_core/tests/test_acceptance_serialization.py")

    def test_the_rule_is_imported_not_copied(self, guard):
        """Храповик: если правило скопируют сюда литералом, тест обязан покраснеть."""
        source = (ROOT / "scripts" / "check_undelivered_work.py").read_text(encoding="utf-8")
        assert "from reap_stale_worktrees import" in source
        assert "reward_harvesting_log" not in source, \
            "правило отсева скопировано литералом — оно обязано читаться импортом"
