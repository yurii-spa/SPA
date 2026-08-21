"""Шаг 0a обязан видеть работу, которой НИКТО не объявлял.

Карточка `inbox-shag-0a-ne-vidit-neobyavlennyi-kod-v-osi`, замер цикла #334.

**Авария.** Сессия `cycle-72429` умерла между работой и пушем, оставив два рабочих дерева.
Шаг 0a показал из них ТОЛЬКО карточку: сторож сверяет с origin ОБЪЯВЛЕННЫЕ пути, а
`spa_core/telegram/buttonless_reason.py` (211 строк, новый модуль) и правки двух прод-модулей
объявлены не были — прямой замер полного вывода дал слово `buttonless_reason` **0 раз при 144
строках отчёта**. Работа нашлась не сторожем: следующая сессия руками открыла `git status` в
осиротевшем дереве. Спасло случайное соседство карточки, которую сторож ищет ДРУГИМ механизмом.

Каждый тест здесь — либо ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ над этой аварией (правило
`.claude/rules/deployment.md`: проверка, никогда не видевшая настоящей поломки, — украшение),
либо ОБРАТНЫЙ контроль над её лечением. Обратные здесь не менее важны: сторож, краснеющий на
дереве живой сессии или на состоянии, которое пишет сам прогон тестов, станет фоном за неделю —
и его перестанут читать, а это тот же класс дефекта, только медленнее.

Второй положительный контроль — авария, найденная уже ЭТОЙ починкой на живом прогоне (#335):
удалённый в дереве путь ронял `git hash-object` (`rc=128`), и ВСЁ прод-дерево уходило в
«НЕ ИЗМЕРЕНО» навсегда — необратимое «не измерено» внутри сторожа, заведённого против него же.

Время входом не является намеренно: разбор про СОДЕРЖИМОЕ, а не про свежесть, литеральных дат
в фикстурах нет вовсе (правило «фиксированная дата — бомба замедленного действия» соблюдено
отсутствием предмета).
"""

import importlib.util
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_undelivered_work.py"

# Настоящее имя модуля из аварии 21.08 — тест обязан требовать именно его (критерий приёмки
# карточки: «шаг 0a называет `spa_core/telegram/buttonless_reason.py` поимённо»).
CYCLE_72429_MODULE = "spa_core/telegram/buttonless_reason.py"


def _load():
    spec = importlib.util.spec_from_file_location("cuw_unannounced", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cuw = _load()


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        capture_output=True, text=True, check=True, env=env)


class TreeBase(unittest.TestCase):
    """Настоящий git с настоящим worktree: проверка живёт на плумбинге, подделка её не проверит."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        home = Path(self._tmp.name)
        self.root = home / "repo"
        (self.root / "spa_core" / "telegram").mkdir(parents=True)
        _git(home, "init", "-q", "-b", "main", str(self.root))
        (self.root / "spa_core" / "telegram" / "owner_decisions.py").write_text("на базе\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "base")
        _git(self.root, "branch", "base")
        self.base = "base"
        self.tree = home / "spa_c72429"
        _git(self.root, "worktree", "add", "-q", str(self.tree), "base")

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, rel, text):
        p = self.tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def scan(self, declared=(), active=(), trees=None, **kw):
        """Скан по ОДНОМУ дереву-фикстуре; `diff_sets` считается настоящим git-ом."""
        checkouts = [self.tree] if trees is None else trees
        diff_sets, failed = cuw.collect_diff_sets(self.base, checkouts)
        self.assertEqual(failed, [], "фикстура: дерево не сверилось с базой")
        rows = cuw.unannounced_divergence_scan(
            self.root, self.base, checkouts, set(declared), set(active), diff_sets, **kw)
        self.assertEqual(len(rows), len(checkouts))
        return rows[0]

    def names(self, row):
        return [f["path"] for f in row["undelivered"]]


# ── 1. положительный контроль: ровно авария 21.08 ────────────────────────────

class UnannouncedWorkIsNamed(TreeBase):
    """Замер #334: 144 строки отчёта, слово `buttonless_reason` — 0 раз."""

    def test_new_module_nobody_announced_is_named_by_name(self):
        self.put(CYCLE_72429_MODULE, "211 строк нового модуля\n")
        row = self.scan()
        self.assertEqual(self.names(row), [CYCLE_72429_MODULE])
        self.assertEqual(row["unchecked"], [])
        self.assertFalse(row["undelivered"][0]["on_base"],
                         "имени модуля на базе не было — строка обязана это сказать")

    def test_edit_of_a_tracked_module_nobody_announced_is_named_too(self):
        """`cycle-72429` правила и существующие модули — их сторож не видел ровно так же."""
        (self.tree / "spa_core" / "telegram" / "owner_decisions.py").write_text("правка\n")
        row = self.scan()
        self.assertEqual(self.names(row), ["spa_core/telegram/owner_decisions.py"])
        self.assertTrue(row["undelivered"][0]["on_base"])

    def test_the_finding_holds_exit_code_one_through_build_report(self):
        """Критерий приёмки карточки: это видно В ОТЧЁТЕ, а не только в структуре."""
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        rep = cuw.build_report(entries=[], root=self.root, base_ref=self.base,
                               self_session="pid999999", ps=lambda pid: (1, ""))
        self.assertEqual(rep["unmeasured"], [])
        self.assertEqual(rep["exit_code"], 1)
        text = cuw.render(rep)
        self.assertIn(CYCLE_72429_MODULE, text)
        self.assertIn("НИКТО НЕ ОБЪЯВЛЯЛ", text)


# ── 2. обратные контроли: молчать сторож обязан по ДОКАЗАТЕЛЬСТВУ ────────────

class LiveSessionTreeIsSilent(TreeBase):
    """Дерево живой сессии: расхождение там — норма, а не находка (п. 2 карточки)."""

    def test_same_tree_with_a_confirmed_active_session_is_not_a_finding(self):
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        row = self.scan(active=[cuw._normalize_tree(str(self.tree))])
        self.assertTrue(row["active"])
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["unchecked"], [])

    def test_activity_comes_from_the_same_measure_the_report_uses(self):
        """Живость берётся ИЗ ОТЧЁТА (`ACTIVE`), а не из второго определения живости.

        Запись объявляет долгоживущий процесс, `ps` подтверждает его личность ⇒ сессия активна ⇒
        её дерево молчит. Тот же вход с мёртвым процессом обязан дать находку — иначе тест
        проверял бы не признак, а его отсутствие."""
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        entry = {"ts": "2026-01-15T12:00:00Z", "session": "cycle-72429", "summary": "работа",
                 "files": [str(self.tree / "docs" / "STATE.md")],
                 "session_pid": 4242, "session_pid_start": "Thu Jan 15 12:00:00 2026"}

        alive = cuw.build_report(entries=[entry], root=self.root, base_ref=self.base,
                                 self_session="pid999999",
                                 ps=lambda pid: (0, "Thu Jan 15 12:00:00 2026"))
        self.assertEqual(alive["sessions_active"], 1)
        self.assertEqual([f for r in alive["unannounced"] for f in r["undelivered"]], [])

        dead = cuw.build_report(entries=[entry], root=self.root, base_ref=self.base,
                                self_session="pid999999", ps=lambda pid: (1, ""))
        self.assertIn(CYCLE_72429_MODULE,
                      [f["path"] for r in dead["unannounced"] for f in r["undelivered"]])


class AlreadyAnsweredElsewhereIsSilent(TreeBase):
    """Путь, которым занят ДРУГОЙ раздел, второй раз не называется: эхо, а не находка."""

    def test_declared_path_is_left_to_the_main_report(self):
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        row = self.scan(declared=[CYCLE_72429_MODULE])
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["declared"], 1)

    def test_declaration_of_any_session_counts_not_only_the_tree_owner(self):
        """Объявление СЧИТАЕТСЯ по имени пути, кто бы его ни сделал — так строит `declared_rel_paths`."""
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        declared = cuw.declared_rel_paths([
            {"files": [f"/tmp/spa_c999/{CYCLE_72429_MODULE}"]}])
        self.assertEqual(declared, {CYCLE_72429_MODULE})
        self.assertEqual(self.scan(declared=declared)["undelivered"], [])

    def test_tracker_card_is_left_to_its_own_section(self):
        """Замер #335: без этой ступени прод-дерево дало бы 77 строк о карточках из 115."""
        self.put("nimbalyst-local/tracker/inbox-nedostavlennaya.md", "status: new\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["by_card_scan"], 1)

    def test_churn_and_test_state_are_not_work(self):
        """`data/` — правило уборщика; `spa_core/data/` — то, что пишет сам прогон тестов."""
        self.put("data/current_positions.json", "{}\n")
        self.put("spa_core/data/whale_impact_log.json", "{}\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual((row["churn"], row["test_state"]), (1, 1))

    def test_content_the_repository_remembers_is_not_a_finding(self):
        """Старая копия / локальный коммит: байты не в одном экземпляре, поднимать нечего."""
        (self.root / "spa_core" / "telegram" / "owner_decisions.py").write_text("вторая версия\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "вторая версия живёт в объектной базе")
        (self.tree / "spa_core" / "telegram" / "owner_decisions.py").write_text("вторая версия\n")
        row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(row["known"], 1)


# ── 3. положительный контроль #335: удаление роняло ВСЁ дерево в «не измерено» ─

class DeletionDoesNotBlindTheWholeTree(TreeBase):
    """Живой замер #335: `hash-object` падал на первом удалённом пути прод-дерева.

    Вердикт по 477 кандидатам превращался в одну строку «НЕ ИЗМЕРЕНО» и код 2 — навсегда,
    потому что удалённые файлы в прод-дереве никуда не денутся."""

    def test_deleted_path_is_counted_and_the_real_finding_survives(self):
        (self.tree / "spa_core" / "telegram" / "owner_decisions.py").unlink()
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        row = self.scan()
        self.assertEqual(row["gone"], 1)
        self.assertEqual(row["unchecked"], [], "удаление не смеет ослеплять всё дерево")
        self.assertEqual(self.names(row), [CYCLE_72429_MODULE])

    def test_deletion_alone_is_not_a_finding(self):
        """У удаления нет байтов, которые существовали бы только здесь: содержимое на базе."""
        (self.tree / "spa_core" / "telegram" / "owner_decisions.py").unlink()
        row = self.scan()
        self.assertEqual((row["gone"], row["undelivered"], row["unchecked"]), (1, [], []))


class OversizedIsAnsweredNotHashed(TreeBase):
    """Потолок хеширования не тихий: ответ даётся, просто из более дешёвого источника.

    Замер #335: три архива резерва (0.2 + 0.6 + 1.26 ГБ) стоили шагу 0a +29 с процессорного
    времени КАЖДЫЙ прогон ради вывода, известного заранее.

    Проверяется МЕХАНИЗМ, а не число: потолок опускается до горсти байт, иначе фикстура сама
    стоила бы гигабайт. Само число проверено отдельно — оно обязано быть положительным, иначе
    «дешёвый источник» стал бы единственным и содержимое не сверялось бы НИКОГДА."""

    SMALL = 8

    def _scan_counting_git(self):
        """Скан с подсчётом вызовов `hash-object`: потолок обязан их ИЗБЕГАТЬ, а не переживать."""
        calls = []

        def counting(cwd, *args, stdin=None):
            calls.append(args[0] if args else "")
            return cuw._git(cwd, *args, stdin=stdin)

        diff_sets, _ = cuw.collect_diff_sets(self.base, [self.tree])
        with mock.patch.object(cuw, "HASH_SIZE_CEILING", self.SMALL):
            rows = cuw.unannounced_divergence_scan(self.root, self.base, [self.tree], set(),
                                                   set(), diff_sets, git=counting)
        return rows[0], calls

    def test_the_ceiling_is_a_positive_number(self):
        self.assertGreater(cuw.HASH_SIZE_CEILING, 0)

    def test_big_file_absent_on_base_is_a_finding_without_hashing(self):
        self.put("backups/dump.tar.gz", "x" * (self.SMALL + 1))
        row, calls = self._scan_counting_git()
        self.assertEqual(self.names(row), ["backups/dump.tar.gz"])
        self.assertIsNone(row["undelivered"][0]["sha"])
        self.assertEqual(row["unchecked"], [])
        self.assertNotIn("hash-object", calls,
                         "крупный файл не смеет хешироваться — ради этого и потолок")

    def test_big_file_present_on_base_is_unchecked_not_a_verdict(self):
        """Имя на базе есть, содержимое не сверялось ⇒ честное «не измерено» (код 2)."""
        (self.root / "big.bin").write_text("x" * (self.SMALL + 1))
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "крупный файл на базе")
        _git(self.root, "branch", "with-big")
        self.base = "with-big"
        self.put("big.bin", "y" * (self.SMALL + 1))
        row, _calls = self._scan_counting_git()
        self.assertEqual(row["undelivered"], [])
        self.assertEqual(len(row["unchecked"]), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", row["unchecked"][0])


# ── 4. fail-CLOSED: не смог измерить ≠ поднимать нечего ──────────────────────

class UnmeasuredIsNeverSilence(TreeBase):
    """Любая неотработавшая ступень даёт `unchecked` и код 2 — молчания не появляется нигде."""

    def test_ls_files_failure_is_unchecked(self):
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        diff_sets, _ = cuw.collect_diff_sets(self.base, [self.tree])

        def broken(cwd, *args, stdin=None):
            if "ls-files" in args:
                return 128, "", "fatal: не отработал"
            return cuw._git(cwd, *args, stdin=stdin)

        rows = cuw.unannounced_divergence_scan(self.root, self.base, [self.tree], set(), set(),
                                               diff_sets, git=broken)
        self.assertEqual(rows[0]["undelivered"], [])
        self.assertEqual(len(rows[0]["unchecked"]), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", rows[0]["unchecked"][0])

    def test_unreadable_churn_rule_is_unchecked(self):
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        with mock.patch.object(cuw, "churn_rule", return_value=(None, "правило не прочитано")):
            row = self.scan()
        self.assertEqual(row["undelivered"], [])
        self.assertIn("правило не прочитано", row["unchecked"][0])

    def test_tree_that_never_reached_diff_sets_is_unchecked(self):
        """`collect_diff_sets` не сверил дерево ⇒ отсутствие находок не выдаётся за их отсутствие."""
        rows = cuw.unannounced_divergence_scan(self.root, self.base, [self.tree], set(), set(),
                                               {})
        self.assertEqual(rows[0]["undelivered"], [])
        self.assertIn("НЕ ИЗМЕРЕНО", rows[0]["unchecked"][0])

    def test_unchecked_reaches_exit_code_two_through_build_report(self):
        self.put(CYCLE_72429_MODULE, "211 строк\n")
        with mock.patch.object(cuw, "churn_rule", return_value=(None, "правило не прочитано")):
            rep = cuw.build_report(entries=[], root=self.root, base_ref=self.base,
                                   self_session="pid999999", ps=lambda pid: (1, ""))
        self.assertEqual(rep["exit_code"], 2)
        self.assertTrue(any("правило не прочитано" in u["reason"] for u in rep["unmeasured"]))




if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
