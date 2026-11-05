#!/usr/bin/env python3
"""Контроль ТРЕТЬЕГО вопроса переписи сирот — «в полёте» против «брошена» (ADR-924).

Предмет: :data:`~spa_core.monitoring.orphan_sweep.FLIGHT_STATES` и две двери,
которые его отвечают (объявление сессии · движение дерева с прошлой переписи).
Заказ G911 п. 6 карточки приказа «Portfolio CIO».

**Каждая сцена — настоящая авария или её зеркало.** Сцены с git строятся на
живом `git` (`git init -b main` — имя ветки объявлено ВХОДОМ сцены, а не взято у
хоста: `.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ в тестах»). Сцены с
живостью сессии подменяют РОВНО правило живости (`session_state`), а путь дерева
при этом считает НАСТОЯЩАЯ дверь журнала (`tree_of_path`) — иначе контроль мерил
бы свой же словарь, а не проводку (урок #944/#945).

Часов в приборе нет вовсе, поэтому литеральных дат здесь нет и быть не может:
`generated_at` прошлой переписи участвует как ЯРЛЫК в тексте причины, а не как
срок — ни один вердикт от календаря здесь не зависит.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import orphan_sweep as osw  # noqa: E402

BRANCH = "main"

#: Дословные вершины дерева `~/Documents/SPA_worktrees/yield01` из ДВУХ замеров:
#: #1036 (04.11, 23:34Z) и #1037 (05.11, 01:34Z). Между ними дерево ДВИНУЛОСЬ, и
#: это ровно тот случай, который породил заказ G911 п. 6: цикл #1036 назвал дерево
#: кандидатом и спросить «не в полёте ли она» был НЕЧЕМ.
HEAD_1036 = "7ee20ce01" + "0" * 31
HEAD_1037 = "cf23c2977" + "0" * 31


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} в {repo}: {out.stderr.strip()}")
    return out.stdout.strip()


def commit(repo, name, text="x"):
    (Path(repo) / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def previous_doc(tree, head, *, state="measured", stamp="СЛЕПОК-ПРОШЛОЙ-ПЕРЕПИСИ"):
    """Прошлая перепись как её пишет сам прибор — ровно те поля, что он читает."""
    row = {"tree": str(tree), "verdict": "never_pushed"}
    if head is not None:
        row["head"] = head
    return {"state": state, "generated_at": stamp, "rows": [row]}


class FakeCuw:
    """Подменяется РОВНО правило живости; путь дерева считает настоящая дверь."""

    ACTIVE, NOT_CONFIRMED, UNKNOWN = "active", "not_confirmed", "unknown"

    def __init__(self, states, *, tree_of_path=None, raise_on_parse=False):
        self.states = states                 # session -> verdict
        self._real = osw.load_cuw()[0]
        self._tree_of_path = tree_of_path
        self.raise_on_parse = raise_on_parse

    def tree_of_path(self, path):
        if self._tree_of_path is not None:
            return self._tree_of_path(path)
        return self._real.tree_of_path(path)

    def worktree_of(self, entry):
        if self.raise_on_parse:
            raise RuntimeError("журнал битый")
        return self._real.worktree_of(entry)

    def session_state(self, entry, self_session, **kw):
        s = str(entry.get("session") or "")
        return self.states.get(s, self.NOT_CONFIRMED), f"сцена назвала {s} как {self.states.get(s)}"

    def read_entries(self, path, last):
        rows = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows, 0


def entry(session, tree, name="spa_core/x.py"):
    return {"session": session, "ts": "ЯРЛЫК", "files": [str(Path(tree) / name)]}


# ── 1. Контракт исходов: «брошена» не существует ────────────────────────────────
class FlightContract(unittest.TestCase):
    def test_abandoned_is_not_an_outcome_ever(self):
        """Претензия докстроки — машинная: исходов ДВА, и «брошена» среди них нет.

        Это не стилистика: третий исход «брошена» означал бы, что прибор берётся
        доказать ОТСУТСТВИЕ работы, чего ни одна его дверь не умеет.
        """
        self.assertEqual(osw.FLIGHT_STATES, ("in_flight", "unmeasured"))
        for word in ("abandoned", "брошен", "dead", "мертв"):
            self.assertNotIn(word, " ".join(osw.FLIGHT_STATES).lower())

    def test_a_door_has_exactly_three_states(self):
        """Склеить «молчит» со «слепа» значило бы сделать слепую дверь вердиктом."""
        self.assertEqual(osw.DOOR_STATES, ("affirms", "silent", "blind"))

    def test_flight_tally_keys_are_the_declared_outcomes(self):
        """Учёт объявляется ТЕМ ЖЕ перечнем — вторая копия разошлась бы молча."""
        verdict = osw.flight_verdict([{"door": "d", "state": "silent", "reason": "r"}])
        self.assertIn(verdict["flight"], osw.FLIGHT_STATES)


# ── 2. Дверь ДВИЖЕНИЯ: три состояния, и ни одно не подменяет другое ────────────
class MovementDoor(unittest.TestCase):
    TREE = "/tmp/yield01"

    def test_a_tree_that_moved_since_the_last_census_affirms_flight(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ настоящего случая #1036 → #1037.

        Те самые две вершины `yield01`. Подними его #1036 — он увёз бы на
        `origin/main` половину чужой незаконченной работы под своей подписью.
        """
        door = osw.movement_door(self.TREE, HEAD_1037,
                                 previous_doc(self.TREE, HEAD_1036))
        self.assertEqual(door["state"], "affirms")
        self.assertEqual(door["previous_head"], HEAD_1036)
        self.assertIn("ДВИНУЛОСЬ", door["reason"])

    def test_the_same_head_is_silence_and_never_abandonment(self):
        door = osw.movement_door(self.TREE, HEAD_1037,
                                 previous_doc(self.TREE, HEAD_1037))
        self.assertEqual(door["state"], "silent")
        self.assertIn("НЕ брошенность", door["reason"])

    def test_no_previous_census_is_blindness_not_silence(self):
        """Первый прогон НЕ ИМЕЕТ ПРАВА читаться как «не двинулось»."""
        door = osw.movement_door(self.TREE, HEAD_1037, None, "прошлой переписи нет")
        self.assertEqual(door["state"], "blind")
        self.assertIn("прошлой переписи нет", door["reason"])

    def test_a_tree_absent_from_the_previous_census_is_blindness(self):
        door = osw.movement_door(self.TREE, HEAD_1037,
                                 previous_doc("/tmp/другое", HEAD_1036))
        self.assertEqual(door["state"], "blind")
        self.assertIn("моложе", door["reason"])

    def test_a_previous_row_without_a_head_is_blindness(self):
        door = osw.movement_door(self.TREE, HEAD_1037, previous_doc(self.TREE, None))
        self.assertEqual(door["state"], "blind")

    def test_no_head_now_is_blindness(self):
        door = osw.movement_door(self.TREE, None, previous_doc(self.TREE, HEAD_1036))
        self.assertEqual(door["state"], "blind")


# ── 3. Чтение прошлой переписи: четыре причины слепоты названы раздельно ───────
class LoadPrevious(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "orphan_sweep.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_names_the_first_run(self):
        doc, why = osw.load_previous(self.p)
        self.assertIsNone(doc)
        self.assertIn("первый прогон", why)

    def test_broken_json_is_named_not_swallowed(self):
        self.p.write_text("{не json", encoding="utf-8")
        doc, why = osw.load_previous(self.p)
        self.assertIsNone(doc)
        self.assertIn("НЕ ПРОЧИТАНА", why)

    def test_an_unmeasured_previous_census_is_not_trusted(self):
        """Чужое «не измерено» не имеет права стать нашим «не двинулось»."""
        self.p.write_text(json.dumps({"state": "unmeasured", "rows": []}), encoding="utf-8")
        doc, why = osw.load_previous(self.p)
        self.assertIsNone(doc)
        self.assertIn("НЕ ИЗМЕРЕНА", why)

    def test_a_measured_previous_census_is_returned(self):
        self.p.write_text(json.dumps(previous_doc("/tmp/x", HEAD_1036)), encoding="utf-8")
        doc, why = osw.load_previous(self.p)
        self.assertIsNone(why)
        self.assertEqual(doc["rows"][0]["head"], HEAD_1036)


# ── 4. Дверь ОБЪЯВЛЕНИЯ: живость мерит ЕДИНСТВЕННОЕ правило дома ──────────────
class DeclarationDoor(unittest.TestCase):
    TREE = "/tmp/spa_wt_scene"

    def test_an_active_declared_session_affirms_flight(self):
        cuw = FakeCuw({"cycle-1": FakeCuw.ACTIVE})
        door = osw.declaration_door(self.TREE, [entry("cycle-1", self.TREE)], cuw)
        self.assertEqual(door["state"], "affirms")
        self.assertIn("cycle-1", door["reason"])

    def test_nobody_declared_the_tree_is_silence(self):
        cuw = FakeCuw({})
        door = osw.declaration_door(self.TREE, [entry("cycle-1", "/tmp/чужое")], cuw)
        self.assertEqual(door["state"], "silent")
        self.assertIn("не доказательство брошенности", door["reason"])

    def test_declared_but_not_confirmed_is_silence_not_abandonment(self):
        cuw = FakeCuw({"cycle-1": FakeCuw.NOT_CONFIRMED})
        door = osw.declaration_door(self.TREE, [entry("cycle-1", self.TREE)], cuw)
        self.assertEqual(door["state"], "silent")
        self.assertIn("НЕ доказана", door["reason"])

    def test_one_unmeasurable_liveness_blinds_the_door(self):
        """fail-CLOSED: неизмеренную живость нельзя читать как её отсутствие."""
        cuw = FakeCuw({"cycle-1": FakeCuw.NOT_CONFIRMED, "cycle49": FakeCuw.UNKNOWN})
        door = osw.declaration_door(
            self.TREE, [entry("cycle-1", self.TREE), entry("cycle49", self.TREE)], cuw)
        self.assertEqual(door["state"], "blind")
        self.assertIn("НЕ ИЗМЕРЕНА", door["reason"])

    def test_an_active_session_wins_over_an_unmeasurable_one(self):
        cuw = FakeCuw({"cycle-1": FakeCuw.ACTIVE, "cycle49": FakeCuw.UNKNOWN})
        door = osw.declaration_door(
            self.TREE, [entry("cycle-1", self.TREE), entry("cycle49", self.TREE)], cuw)
        self.assertEqual(door["state"], "affirms")

    def test_no_liveness_rule_is_blindness(self):
        door = osw.declaration_door(self.TREE, [entry("c", self.TREE)], None,
                                    journal_blind_reason="правило живости не загружено")
        self.assertEqual(door["state"], "blind")

    def test_no_journal_is_blindness(self):
        door = osw.declaration_door(self.TREE, None, FakeCuw({}),
                                    journal_blind_reason="журнала нет")
        self.assertEqual(door["state"], "blind")
        self.assertIn("журнала нет", door["reason"])

    def test_a_broken_journal_is_blindness_not_silence(self):
        cuw = FakeCuw({}, raise_on_parse=True)
        door = osw.declaration_door(self.TREE, [entry("c", self.TREE)], cuw)
        self.assertEqual(door["state"], "blind")
        self.assertIn("не разобран", door["reason"])


# ── 5. ИЗМЕРЕННАЯ ловушка: 13 деревьев из 81 сворачиваются в ПРОД-дерево ──────
class TheMeasuredTreeKeyTrap(unittest.TestCase):
    """Авария, найденная замером #1037 на живом хосте — 13 деревьев из 81.

    `tree_of_path` режет путь на ПЕРВОМ компоненте, похожем на каталог репо.
    У `~/Documents/SPA_Claude/.claude/worktrees/<имя>` таким компонентом
    оказывается `.claude` — то есть ключ сворачивается в ПРОД-ДЕРЕВО, которое
    объявляет КАЖДЫЙ цикл. Без проверки дверь утверждала бы «в полёте» для
    тринадцати чужих деревьев, и настоящая сирота в любом из них была бы молча
    укрыта чужим объявлением.
    """

    PROD = "/Users/u/Documents/SPA_Claude"
    NESTED = "/Users/u/Documents/SPA_Claude/.claude/worktrees/beautiful-kilby-e839da"

    def test_the_real_tree_of_path_does_fold_the_nested_tree_into_prod(self):
        """Сначала доказываем, что авария РЕАЛЬНА, а не выдумана этим тестом."""
        real = osw.load_cuw()[0]
        self.assertIsNotNone(real, "правило живости обязано загружаться")
        self.assertEqual(real.tree_of_path(str(Path(self.NESTED) / "spa_core")), self.PROD)

    def test_a_nested_tree_does_not_inherit_the_prod_tree_declaration(self):
        """И только потом — что дверь на ней СЛЕПА, а не утверждает полёт."""
        cuw = FakeCuw({"cycle-prod": FakeCuw.ACTIVE})
        door = osw.declaration_door(self.NESTED, [entry("cycle-prod", self.PROD)], cuw)
        self.assertEqual(door["state"], "blind")
        self.assertIn("ЧУЖОЙ корень", door["reason"])

    def test_the_prod_tree_itself_still_answers(self):
        """ПРОМАХ-половина: проверка не имеет права глушить верный случай."""
        cuw = FakeCuw({"cycle-prod": FakeCuw.ACTIVE})
        door = osw.declaration_door(self.PROD, [entry("cycle-prod", self.PROD)], cuw)
        self.assertEqual(door["state"], "affirms")


# ── 6. Сведение дверей: утверждает любая — значит не поднимать ────────────────
class FlightVerdict(unittest.TestCase):
    AFFIRM = {"door": "movement", "state": "affirms", "reason": "двинулось"}
    SILENT = {"door": "declaration", "state": "silent", "reason": "никто не объявил"}
    BLIND = {"door": "movement", "state": "blind", "reason": "переписи нет"}

    def test_any_affirming_door_makes_it_in_flight(self):
        for doors in ([self.AFFIRM, self.SILENT], [self.SILENT, self.AFFIRM],
                      [self.BLIND, self.AFFIRM]):
            with self.subTest(doors=[d["state"] for d in doors]):
                v = osw.flight_verdict(doors)
                self.assertEqual(v["flight"], "in_flight")
                self.assertIn("movement", v["flight_evidence"])

    def test_both_silent_is_unmeasured_and_names_both_doors(self):
        v = osw.flight_verdict([self.SILENT, {**self.AFFIRM, "state": "silent"}])
        self.assertEqual(v["flight"], "unmeasured")
        self.assertEqual(v["flight_evidence"], [])
        self.assertIn("declaration: silent", v["flight_reason"])
        self.assertIn("movement: silent", v["flight_reason"])

    def test_both_blind_is_unmeasured_too_and_distinguishable_in_the_reason(self):
        v = osw.flight_verdict([{**self.SILENT, "state": "blind"}, self.BLIND])
        self.assertEqual(v["flight"], "unmeasured")
        self.assertIn("blind", v["flight_reason"])


# ── 7. ПРОВОДКА на живом git: прошлый слепок читается ДО записи своего ────────
class WiringOnLiveGit(unittest.TestCase):
    """Сцена: upstream + полный клон + рабочий клон с деревом-сиротой."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.up = base / "upstream"
        self.up.mkdir()
        git(self.up, "init", "-b", BRANCH, "--quiet")
        git(self.up, "config", "user.email", "t@t")
        git(self.up, "config", "user.name", "t")
        commit(self.up, "f0.txt")
        self.full = base / "full"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.full))
        self.work = base / "work"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.work))
        git(self.work, "config", "user.email", "t@t")
        git(self.work, "config", "user.name", "t")
        # дерево-сирота: коммит поверх вершины, никуда не уехавший
        self.orphan = base / "orphan"
        git(self.work, "worktree", "add", "--quiet", "--detach", str(self.orphan),
            f"origin/{BRANCH}")
        git(self.orphan, "config", "user.email", "t@t")
        git(self.orphan, "config", "user.name", "t")
        self.orphan_head = commit(self.orphan, "work.txt")
        (self.work / "data").mkdir(exist_ok=True)
        self.artifact = self.work / "data" / osw.ARTIFACT

    def tearDown(self):
        self.tmp.cleanup()

    def kw(self, **extra):
        return dict(ref=f"origin/{BRANCH}", lineage_candidates=[str(self.full)], **extra)

    def row(self, doc, key="candidates"):
        """Строка дерева-сироты.

        Ищется по БАЗОВОМУ ИМЕНИ, а не по полному пути: на macOS `tempfile` даёт
        `/var/folders/…`, а `git worktree list` регистрирует то же дерево как
        `/private/var/folders/…`. Побайтовое сравнение двух написаний ОДНОГО
        каталога ответило бы «дерева нет» — ровно тот класс, на котором
        споткнулось родство по дереву в замере #301. Прибор сам сравнивает
        написания, пришедшие из ОДНОГО источника (`git worktree list` своего же
        артефакта), поэтому нормализации ему не требуется — а сцене требуется.
        """
        found = [r for r in doc[key] if Path(r["tree"]).name == self.orphan.name]
        self.assertEqual(len(found), 1,
                         f"сцена обязана дать РОВНО одно дерево {self.orphan.name} "
                         f"в {key}, а дала {[r['tree'] for r in doc[key]]}")
        return found[0]

    def test_every_candidate_carries_a_flight_verdict_and_the_tally_balances(self):
        doc = osw.sweep(self.work, **self.kw())
        self.assertEqual(doc["state"], "measured", doc.get("reason"))
        self.assertTrue(doc["candidates"], "сцена обязана дать хотя бы одного кандидата")
        for row in doc["candidates"]:
            self.assertIn(row["flight"], osw.FLIGHT_STATES, row["tree"])
            self.assertTrue(row["flight_reason"])
        self.assertEqual(sum(doc["flight_tally"].values()), len(doc["candidates"]))

    def test_run_reads_the_previous_snapshot_before_overwriting_it(self):
        """Авария класса ADR-774: сверка замера с САМИМ СОБОЙ.

        Артефакт перезаписывается этим же вызовом. Прочитай прибор прошлый слепок
        ПОСЛЕ записи — дверь движения вечно отвечала бы «HEAD тот же», то есть
        молчала бы ровно про те деревья, о которых её и спрашивают.
        """
        # Прошлый слепок пишется ТЕМ ЖЕ написанием пути, которым его пишет сам
        # прибор (`git worktree list`), — спрашиваем его у прибора, а не у
        # `tempfile`: иначе сцена проверяла бы складывание `/var` ≡ `/private/var`,
        # а не чтение слепка.
        spelled = self.row(osw.sweep(self.work, **self.kw()))["tree"]
        osw.atomic_save(previous_doc(spelled, "0" * 40), str(self.artifact))
        osw.run(self.work, **self.kw())
        doc = json.loads(self.artifact.read_text(encoding="utf-8"))
        row = self.row(doc)
        self.assertEqual(row["flight"], "in_flight")
        self.assertIn("movement", row["flight_evidence"])
        self.assertIn("ДВИНУЛОСЬ", row["flight_reason"])
        # и новый слепок несёт УЖЕ новую вершину — иначе следующий прогон
        # сравнивал бы с позапрошлой
        self.assertEqual(row["head"], self.orphan_head)

    def test_a_second_run_in_a_row_honestly_says_the_head_did_not_move(self):
        """ПРОМАХ-половина: «двинулось» не имеет права утверждаться всегда."""
        osw.run(self.work, **self.kw())
        osw.run(self.work, **self.kw())
        doc = json.loads(self.artifact.read_text(encoding="utf-8"))
        row = self.row(doc)
        self.assertEqual(row["flight"], "unmeasured")
        self.assertIn("HEAD тот же", row["flight_reason"])

    def test_the_first_run_ever_is_blind_not_silent_about_movement(self):
        osw.run(self.work, **self.kw())
        doc = json.loads(self.artifact.read_text(encoding="utf-8"))
        row = self.row(doc)
        moved = [d for d in row["flight_doors"] if d["door"] == "movement"][0]
        self.assertEqual(moved["state"], "blind")
        self.assertIn("первый прогон", moved["reason"])

    def test_the_journal_door_is_wired_to_the_measured_clone(self):
        """Живость спрашивается у журнала ПЕРЕПИСЫВАЕМОГО клона, а не своего дерева."""
        doc = osw.sweep(self.work, **self.kw())
        self.assertEqual(doc["journal"], str(self.work / osw.JOURNAL_DEFAULT))

    def test_a_declared_live_session_stops_the_lift_even_without_movement(self):
        """Вторая дверь независима: объявление останавливает подъём само."""
        journal = self.work / "data" / "session_changes.jsonl"
        journal.write_text(json.dumps(entry("cycle-live", self.orphan)) + "\n",
                           encoding="utf-8")
        cuw = FakeCuw({"cycle-live": FakeCuw.ACTIVE})
        doc = osw.sweep(self.work, cuw=cuw, **self.kw())
        row = self.row(doc)
        self.assertEqual(row["flight"], "in_flight")
        self.assertEqual(row["flight_evidence"], ["declaration"])

    def test_the_report_refuses_to_say_lift_about_a_tree_in_flight(self):
        """Читатель обязан видеть запрет СТРОКОЙ, а не полем в json."""
        doc = osw.sweep(self.work, **self.kw())
        row = self.row(doc, "fresh_candidates")
        row.update({"flight": "in_flight", "flight_evidence": ["movement"],
                    "flight_reason": "дерево ДВИНУЛОСЬ"})
        text = "\n".join(osw.report(doc))
        self.assertIn("НЕ ПОДНИМАТЬ (В ПОЛЁТЕ)", text)
        self.assertNotIn("🔶 ПОДНЯТЬ", text)

        row.update({"flight": "unmeasured", "flight_evidence": [],
                    "flight_reason": "улик нет"})
        text2 = "\n".join(osw.report(doc))
        self.assertIn("🔶 ПОДНЯТЬ", text2)
        self.assertIn("полёт НЕ ИЗМЕРЕН", text2)


if __name__ == "__main__":
    unittest.main()
