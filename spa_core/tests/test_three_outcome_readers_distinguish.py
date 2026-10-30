"""Четыре читателя трёхисходных дверей РАЗЛИЧАЮТ «не измерено» от «отказано» (ADR-871).

Предмет — карточка `inbox-chetyre-chitatelya-svodyat-ne-izmereno-s`, проба
`three_outcome_readers_distinguish_by_code`. ADR-870 ИЗМЕРИЛ население класса ADR-869
(дверей 14, читателей 6, сводят 4, различают кодом 0) и решением №4 объявил ПОЧИНКУ
отдельной работой со своей пробой. Эта батарея — приёмка той починки.

**Контроль в ОБЕ стороны, и обе стороны — на ЖИВОМ коде.** Батарея, построенная на
словаре, собранном руками, мерила бы свой словарь (урок памяти
«hand-built-doc-tests-your-dict-not-the-wiring», мутанты #944/#945). Поэтому:

* прямая сторона — НАСТОЯЩИЙ читатель, поднятый на сцене, где подменена РОВНО ОДНА
  вещь: код, которым отвечает дверь;
* обратная сторона — тот же НАСТОЯЩИЙ файл, в котором починка МЕХАНИЧЕСКИ ОТКАЧЕНА
  (сторожа `== k` заменены на «ненулевое»), и перепись обязана назвать читателя
  сводящим. Сцена отличается от живого файла РОВНО этими строками, и это проверяется
  отдельным тестом: сцена, отличающаяся не тем, доказывала бы не то.

Литеральных дат здесь нет вовсе; живость процесса сцены измеряется у той же двери,
которой отвечает проверяемый код (`.claude/rules/deployment.md`, § «ЛИЧНОСТЬ ПРОЦЕССА»).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from spa_core.monitoring import card_acceptance as ca                      # noqa: E402
from spa_core.monitoring import three_outcome_reader_census as c           # noqa: E402

PUSHER = REPO_ROOT / "push_to_github.py"
BATCH = REPO_ROOT / "push_to_github_batch.py"
ACCEPTANCE = REPO_ROOT / "spa_core" / "monitoring" / "card_acceptance.py"

#: Механическая откатка починки: сторож `== k` над НЕНУЛЕВЫМ кодом снимается, и у
#: читателя снова остаётся ровно два ответа — «ноль» и «не ноль». Это ДОСЛОВНАЯ форма
#: находок 1–4 переписи ADR-870, а не выдуманная поломка.
#: Якорь каждой пары обязан быть ОДНОЗНАЧНЫМ: в `push_to_github.py` строка
#: `    if rc == 1:` встречается у ДВУХ читателей, и первая редакция этой откатки
#: попала в соседнего — контроль честно покраснел и назвал чужой ключ.
_REVERT_PUBLICATION = [
    ("    if rc == 1:\n        out.update(kind=PUB_GATE_REFUSED",
     "    if rc:\n        out.update(kind=PUB_GATE_REFUSED"),
    ("    if rc == 2:\n        out.update(kind=PUB_GATE_UNMEASURED",
     "    if rc:\n        out.update(kind=PUB_GATE_UNMEASURED")]
_REVERT_OWNER_CHOICE = [("    if rc == 1:\n        msg =", "    if rc:\n        msg ="),
                        ('    if rc == 2:\n        why =', '    if rc:\n        why =')]
_REVERT_PROBE = [("    if rc_live == 2:", "    if rc_live:"),
                 ("    if rc_live == 3:", "    if rc_live:"),
                 ("    if rc_live == 1:", "    if rc_live:")]


def _apply(text: str, pairs: "list[tuple[str, str]]") -> "tuple[str, int]":
    """Подставить и ПОСЧИТАТЬ, сколько подстановок состоялось.

    Число возвращается наружу намеренно: откатка, не нашедшая своей строки, сделала бы
    сцену равной живому файлу — и обратный контроль молча превратился бы в прямой.
    Такая сцена не краснеет и не проходит, она ИСЧЕЗАЕТ (урок #465), поэтому её
    предпосылка проверяется числом.
    """
    hits = 0
    for old, new in pairs:
        if old in text:
            text = text.replace(old, new, 1)
            hits += 1
    return text, hits


def _door_copies(scene: Path) -> None:
    """Положить в сцену сами ДВЕРИ: их словарь объявлен в коде, и перепись читает его."""
    (scene / "scripts").mkdir(parents=True, exist_ok=True)
    for rel in ("scripts/verify_publication.py",
                "scripts/check_owner_choice_authorship.py",
                "scripts/delta_mutation_run.py"):
        shutil.copy2(REPO_ROOT / rel, scene / rel)


class LiveReaderOfThePublicationGateDistinguishes(unittest.TestCase):
    """Прямая сторона: НАСТОЯЩИЙ читатель ворот публикации на подменённой двери."""

    def test_the_fixed_reader_tells_refused_from_did_not_answer(self):
        drive = c.drive_publication_gate(REPO_ROOT)
        self.assertEqual(drive["kind"], c.DRIVE_DISTINGUISHES, drive.get("reason"))
        self.assertEqual(drive["scenes"]["door_refused"]["kind"], "refused")
        self.assertEqual(drive["scenes"]["door_did_not_answer"]["kind"], "unmeasured")

    def test_the_two_scenes_differ_in_exactly_the_doors_code(self):
        """Сцены обязаны отличаться РОВНО кодом двери — иначе доказано не то."""
        a = c._STUB_DOOR.format(code=1).splitlines()
        b = c._STUB_DOOR.format(code=2).splitlines()
        self.assertEqual(len(a), len(b))
        differ = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        self.assertEqual([a[i].strip() for i in differ], ["CODE = 1"])
        self.assertEqual([b[i].strip() for i in differ], ["CODE = 2"])

    def test_every_code_of_the_doors_vocabulary_gets_its_own_kind(self):
        """Словарь двери — 0/1/2; код вне словаря тоже «не измерено», со своей причиной."""
        import importlib.util as u
        spec = u.spec_from_file_location("_p2g_vocab", PUSHER)
        mod = u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seen = {}
        with tempfile.TemporaryDirectory(prefix="pubgate_vocab_") as tmp:
            for code in (0, 1, 2, 99):
                scene = Path(tmp) / f"c{code}"
                (scene / "scripts").mkdir(parents=True)
                (scene / "landing" / "src" / "data").mkdir(parents=True)
                (scene / "scripts" / "verify_publication.py").write_text(
                    c._STUB_DOOR.format(code=code), encoding="utf-8")
                shelf = scene / "landing" / "src" / "data" / "site_numbers.json"
                shelf.write_text("{}\n", encoding="utf-8")
                runner = scene / "push_to_github.py"
                runner.write_text("# адрес дерева\n", encoding="utf-8")
                out = mod.publication_gate_verdict([str(shelf)], runner_file=str(runner))
                seen[code] = out["kind"]
        self.assertEqual(seen, {0: "clean", 1: "refused", 2: "unmeasured",
                                99: "unmeasured"})

    def test_a_set_without_the_shelf_does_not_wake_the_gate(self):
        """Триггер остаётся узким: пуш без витрины ворота не трогает."""
        import importlib.util as u
        spec = u.spec_from_file_location("_p2g_trigger", PUSHER)
        mod = u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out = mod.publication_gate_verdict(["spa_core/risk/policy.py"])
        self.assertEqual(out["kind"], "clean")
        self.assertIsNone(out["rc"], "ворота спрошены там, где витрины нет")

    def test_a_missing_gate_is_unmeasured_not_clean(self):
        """Двери нет ни в одном дереве ⇒ ТРЕТИЙ исход, а не тихий пропуск.

        **Эта сцена переписана по выжившему мутанту** (замер #988, мутация 4/18
        «двери нет на диске — объявлено чистым»). Первая редакция грузила модуль из
        РЕПОЗИТОРИЯ, поэтому его `MODULE_FILE` указывал в репозиторий — а это ВТОРОЙ
        кандидат поиска двери, и дверь там есть. Ветка «двери нет» не исполнялась ни
        разу: живой гейт отвечал на витрину-заглушку своим кодом 2, и проба видела
        «unmeasured» по ДРУГОЙ причине. Два признака подменяли друг друга — ровно
        форма, которую память называет настоящей дырой батареи. Теперь модуль
        грузится ИЗ СЦЕНЫ (оба кандидата указывают в сцену), а утверждение
        спрашивает строку ИМЕННО этой ветки, а не общее «НЕ ИЗМЕРЕНО».
        """
        import importlib.util as u
        with tempfile.TemporaryDirectory(prefix="pubgate_nogate_") as tmp:
            scene = Path(tmp) / "scene"
            (scene / "landing" / "src" / "data").mkdir(parents=True)
            shelf = scene / "landing" / "src" / "data" / "site_numbers.json"
            shelf.write_text("{}\n", encoding="utf-8")
            runner = scene / "push_to_github.py"
            shutil.copy2(PUSHER, runner)
            spec = u.spec_from_file_location("_p2g_nogate", runner)
            mod = u.module_from_spec(spec)
            sys.modules[spec.name] = mod
            try:
                spec.loader.exec_module(mod)
            finally:
                sys.modules.pop(spec.name, None)
            self.assertEqual(os.path.dirname(mod.MODULE_FILE), str(scene),
                             "сцена НЕ ПОДНЯТА: модуль всё ещё видит репозиторий, и "
                             "ветка «двери нет» не исполнится")
            self.assertFalse((scene / "scripts" / "verify_publication.py").exists())
            out = mod.publication_gate_verdict([str(shelf)], runner_file=str(runner))
        self.assertEqual(out["kind"], "unmeasured")
        self.assertIn("ворот публикации нет ни в одном из деревьев", out["detail"])
        self.assertIn("НЕ ИЗМЕРЕНО", out["detail"])


class TheSceneVerdictIsCheckableWithoutATree(unittest.TestCase):
    """Шов вердикта — иначе подмена всей проверки на «ok = True» переживает мутацию.

    Урок ADR-870 дословно: живые сцены отвечают верно, поэтому утверждение о ЧИСЛАХ
    держится, а утверждение о РОДЕ исхода не держит ничего. Сцену со СВОДЯЩИМ читателем
    в живом дереве взять негде — его только что починили.
    """

    def test_opposite_kinds_are_called_distinguishing(self):
        v = c.publication_scenes_verdict({"kind": "refused"}, {"kind": "unmeasured"})
        self.assertEqual(v["kind"], c.DRIVE_DISTINGUISHES)

    def test_the_same_kind_on_both_scenes_is_conflation(self):
        v = c.publication_scenes_verdict({"kind": "refused"}, {"kind": "refused"})
        self.assertEqual(v["kind"], c.DRIVE_CONFLATES)

    def test_kinds_differing_the_wrong_way_are_unmeasured(self):
        """Различны, но не в ту сторону — это НЕ «различает» и НЕ «сводит»."""
        v = c.publication_scenes_verdict({"kind": "unmeasured"}, {"kind": "refused"})
        self.assertEqual(v["kind"], c.DRIVE_UNMEASURED)
        v = c.publication_scenes_verdict({"kind": "clean"}, {"kind": "unmeasured"})
        self.assertEqual(v["kind"], c.DRIVE_UNMEASURED)


class OwnerChoiceAuthorshipTellsForgeryFromUnmeasured(unittest.TestCase):
    """Прямая сторона находки 3: подменена РОВНО дверь, читатель настоящий."""

    GUARD_STUB = ('#!/usr/bin/env python3\nimport sys\n'
                  'CODE = {code}\nsys.exit(CODE)\n')

    def _drive(self, code: int):
        import importlib.util as u
        spec = u.spec_from_file_location(f"_p2g_oc{code}", PUSHER)
        mod = u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory(prefix="owner_choice_") as tmp:
            scene = Path(tmp) / "scene"
            (scene / "scripts").mkdir(parents=True)
            (scene / "nimbalyst-local" / "tracker").mkdir(parents=True)
            (scene / "scripts" / "check_owner_choice_authorship.py").write_text(
                self.GUARD_STUB.format(code=code), encoding="utf-8")
            card = scene / "nimbalyst-local" / "tracker" / "own-scene.md"
            card.write_text("---\nstatus: ingested\n---\n", encoding="utf-8")
            runner = scene / "push_to_github.py"
            runner.write_text("# адрес дерева\n", encoding="utf-8")
            try:
                return ("ok", mod.enforce_owner_choice_authorship(
                    [str(card)], runner_file=str(runner)))
            except mod.OwnerChoiceUnmeasured as exc:
                return ("unmeasured", str(exc))
            except mod.OwnerChoiceUnattributed as exc:
                return ("finding", str(exc))

    def test_a_clean_guard_passes(self):
        kind, _ = self._drive(0)
        self.assertEqual(kind, "ok")

    def test_a_finding_is_called_a_forgery(self):
        kind, msg = self._drive(1)
        self.assertEqual(kind, "finding")
        self.assertIn("НАХОДКА", msg)
        self.assertIn("ТОЛЬКО владелец", msg)

    def test_an_unmeasured_guard_is_not_called_a_forgery(self):
        """Предмет находки 3: отказ остаётся, а ПРИЧИНА больше не врёт."""
        kind, msg = self._drive(2)
        self.assertEqual(kind, "unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНО", msg)
        self.assertNotIn("НАХОДКА", msg)

    def test_a_code_outside_the_vocabulary_is_unmeasured_with_its_own_reason(self):
        kind, msg = self._drive(99)
        self.assertEqual(kind, "unmeasured")
        self.assertIn("которого нет в его словаре", msg)

    def test_both_refusals_stay_fail_closed(self):
        """Инвариант #2 цел: отказ отказывает в ОБОИХ исходах, различается причина."""
        self.assertEqual(self._drive(1)[0], "finding")
        self.assertEqual(self._drive(2)[0], "unmeasured")

    def test_the_unmeasured_exception_is_a_subclass_so_old_callers_still_refuse(self):
        import importlib.util as u
        spec = u.spec_from_file_location("_p2g_subclass", PUSHER)
        mod = u.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(issubclass(mod.OwnerChoiceUnmeasured,
                                   mod.OwnerChoiceUnattributed))
        self.assertNotEqual(mod.OWNER_CHOICE_INTERLOCK_EXIT,
                            mod.OWNER_CHOICE_UNMEASURED_EXIT)
        self.assertNotEqual(mod.PUBLICATION_GATE_EXIT,
                            mod.PUBLICATION_GATE_UNMEASURED_EXIT)


class SubclassHandlersComeFirstInBothCLIs(unittest.TestCase):
    """`OwnerChoiceUnmeasured` — ПОДКЛАСС, и порядок обработчиков решает исход.

    Поймай сперва базовый — и «не измерено» навсегда уедет под кодом находки, то есть
    класс ADR-869 вернётся на ВЫХОДЕ из той же функции, из которой его убрали. Мера
    читает НАСТОЯЩИЙ файл (AST), а обратный контроль переставляет обработчики в копии и
    требует, чтобы мера покраснела.
    """

    @staticmethod
    def _order(source: str) -> "list[list[str]]":
        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            names = [h.type.id for h in node.handlers
                     if isinstance(h.type, ast.Name)
                     and h.type.id.startswith("OwnerChoice")]
            if len(names) >= 2:
                found.append(names)
        return found

    def test_the_subclass_is_caught_before_its_base_in_the_real_files(self):
        for path in (PUSHER, BATCH):
            with self.subTest(path=path.name):
                orders = self._order(path.read_text(encoding="utf-8"))
                self.assertEqual(len(orders), 1,
                                 f"{path.name}: ожидалась ровно одна пара обработчиков")
                self.assertEqual(orders[0],
                                 ["OwnerChoiceUnmeasured", "OwnerChoiceUnattributed"])

    def test_swapping_the_handlers_turns_the_measure_red(self):
        """Обратный контроль: мера, не видящая переставленный порядок, бесполезна."""
        for path in (PUSHER, BATCH):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                swapped, hits = _apply(text, [
                    ("    except OwnerChoiceUnmeasured:", "    except __TMP__:"),
                    ("    except OwnerChoiceUnattributed:",
                     "    except OwnerChoiceUnmeasured:"),
                    ("    except __TMP__:", "    except OwnerChoiceUnattributed:")])
                self.assertEqual(hits, 3, "сцена не поднята: строк обработчиков нет")
                self.assertEqual(self._order(swapped)[0],
                                 ["OwnerChoiceUnattributed", "OwnerChoiceUnmeasured"])


class TheProbeJudgesTheLiveSceneByTheDoorsVocabulary(unittest.TestCase):
    """Прямая и обратная сторона находки 4 — на НАСТОЯЩЕЙ пробе.

    Подменяется РОВНО дверь: `scripts/delta_mutation_run.py` заменён заглушкой, которая
    ведёт себя как настоящая (открывает окно, кладёт мутанта, спрашивает живость
    ВЛАДЕЛЬЦА записи у ОС через `kill -0`), но отвечает ОБЪЯВЛЕННЫМ кодом на зов
    `--window-restore` при живом владельце. Проба, её ожидание мутанта, её слепки и её
    классификация берутся из дерева как есть.
    """

    STUB = '''#!/usr/bin/env python3
"""Заглушка ДВЕРИ мутационного прибора: ведёт себя как настоящая, отвечает ОБЪЯВЛЕННЫМ
кодом на возврат при ЖИВОМ владельце окна."""
import json, os, sys, time
from pathlib import Path

RC_WINDOW_OWNER_ALIVE = {alive_rc}
LIVE_RC = {live_rc}

def _args():
    a = sys.argv[1:]
    root = a[a.index("--repo-root") + 1] if "--repo-root" in a else "."
    return a, Path(root)

def _record(root):
    return root / ".mutation_window" / "window.json"

def main():
    a, root = _args()
    rel = "pkg/mod.py"
    target = root / rel
    rec = _record(root)
    if "--window-restore" in a:
        if not rec.exists():
            print("окна нет", file=sys.stderr)
            return 0
        doc = json.loads(rec.read_text(encoding="utf-8"))
        alive = False
        try:
            os.kill(int(doc["pid"]), 0)
            alive = int(doc["pid"]) != os.getpid()
        except OSError:
            alive = False
        if alive:
            print("ОТКАЗ: владелец окна ЖИВ. Осознанный обход: --allow-live-owner",
                  file=sys.stderr)
            return LIVE_RC
        target.write_text(doc["pristine"], encoding="utf-8")
        rec.unlink()
        print(json.dumps({{"restored": True}}))
        return 0
    # режим прогона: открыть окно, положить мутанта, жить до SIGKILL
    pristine = target.read_text(encoding="utf-8")
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({{"pid": os.getpid(), "pristine": pristine,
                               "files": [rel]}}), encoding="utf-8")
    target.write_text(pristine.replace("VALUE = 1", "VALUE = 777"), encoding="utf-8")
    while True:
        time.sleep(0.2)

if __name__ == "__main__":
    sys.exit(main())
'''

    def _run_probe(self, live_rc: int, alive_rc: int = 4):
        with tempfile.TemporaryDirectory(prefix="probe_door_") as tmp:
            root = Path(tmp) / "repo"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "delta_mutation_run.py").write_text(
                self.STUB.format(alive_rc=alive_rc, live_rc=live_rc), encoding="utf-8")
            return ca._probe_mutation_window_restore_refuses_a_live_owner(
                None, repo_root=str(root))

    def test_the_declared_refusal_code_satisfies_the_probe(self):
        verdict, detail = self._run_probe(live_rc=4)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("RC_WINDOW_OWNER_ALIVE", detail)

    def test_the_doors_unmeasured_code_is_not_proof_of_a_refusal(self):
        """ПРЕДМЕТ находки 4: код 2 означает «живость НЕ ИЗМЕРЕНА», а не «владелец жив»."""
        verdict, detail = self._run_probe(live_rc=2)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("НЕ ИЗМЕРЕНО", detail)

    def test_a_partially_unmeasured_code_is_unmeasured_too(self):
        verdict, detail = self._run_probe(live_rc=3)
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_a_finding_about_the_tree_is_an_answer_to_another_question(self):
        verdict, detail = self._run_probe(live_rc=1)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не на тот вопрос", detail)

    def test_a_successful_restore_under_a_live_owner_is_the_2026_10_22_accident(self):
        verdict, detail = self._run_probe(live_rc=0)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_a_code_outside_the_vocabulary_is_unmeasured(self):
        verdict, detail = self._run_probe(live_rc=97)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("которого нет в его словаре", detail)

    def test_a_renumbered_door_is_followed_not_remembered(self):
        """Словарь берётся У ДВЕРИ: перенумеруй её — проба пойдёт за ней, а не за памятью."""
        verdict, detail = self._run_probe(live_rc=7, alive_rc=7)
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_a_door_that_declares_no_code_is_unmeasured(self):
        """Объявления нет ⇒ ТРЕТИЙ исход, а не подставленное число."""
        with tempfile.TemporaryDirectory(prefix="probe_nodict_") as tmp:
            root = Path(tmp) / "repo"
            (root / "scripts").mkdir(parents=True)
            (root / "scripts" / "delta_mutation_run.py").write_text(
                "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n", encoding="utf-8")
            verdict, detail = ca._probe_mutation_window_restore_refuses_a_live_owner(
                None, repo_root=str(root))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("RC_WINDOW_OWNER_ALIVE", detail)

    def test_the_vocabulary_is_read_from_the_live_door(self):
        rc = ca._door_rc_for_live_owner(str(REPO_ROOT / "scripts" / "delta_mutation_run.py"))
        self.assertIsInstance(rc, int)
        self.assertEqual(rc, 4, "живая дверь объявляет RC_WINDOW_OWNER_ALIVE = 4")
        self.assertIsNone(ca._door_rc_for_live_owner(str(REPO_ROOT / "README.md")),
                          "файл без объявления обязан дать None, а не число")


class RevertingTheFixTurnsTheCensusRed(unittest.TestCase):
    """Обратная сторона ВСЕХ четырёх починок — на НАСТОЯЩИХ файлах.

    Сцена — копия живого файла, в которой сторожа `== k` над ненулевыми кодами сняты,
    то есть ДОСЛОВНО восстановлена форма находок ADR-870. Перепись обязана назвать
    такого читателя сводящим. Батарея, у которой этой стороны нет, зелена и на
    починке, и на её откатке.
    """

    def _census_of_scene(self, rel: str, pairs: "list[tuple[str, str]]",
                         extra: "list[tuple[str, list]]" = ()):
        with tempfile.TemporaryDirectory(prefix="revert_scene_") as tmp:
            scene = Path(tmp) / "tree"
            scene.mkdir()
            _door_copies(scene)
            targets = [(rel, pairs)] + list(extra)
            for path_rel, path_pairs in targets:
                dst = scene / path_rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                text = (REPO_ROOT / path_rel).read_text(encoding="utf-8")
                reverted, hits = _apply(text, path_pairs)
                self.assertEqual(hits, len(path_pairs), (
                    f"сцена НЕ ПОДНЯТА: в {path_rel} не нашлось строк починки — "
                    f"сцена равна живому файлу, и контроль измерил бы не то"))
                self.assertNotEqual(reverted, text)
                dst.write_text(reverted, encoding="utf-8")
                ast.parse(reverted)        # откатка обязана оставаться разбираемой
            return c.run_census(scene)

    def test_the_publication_gate_reader_collapses_again_when_reverted(self):
        report = self._census_of_scene("push_to_github.py", _REVERT_PUBLICATION)
        keys = [c.finding_key(r) for r in report["findings"]]
        self.assertIn("push_to_github.py::publication_gate_verdict::"
                      "scripts/verify_publication.py", keys, report["counts"])

    def test_the_owner_choice_reader_collapses_again_when_reverted(self):
        report = self._census_of_scene("push_to_github.py", _REVERT_OWNER_CHOICE)
        keys = [c.finding_key(r) for r in report["findings"]]
        self.assertIn("push_to_github.py::enforce_owner_choice_authorship::"
                      "scripts/check_owner_choice_authorship.py", keys, report["counts"])

    def test_the_acceptance_probe_collapses_again_when_reverted(self):
        report = self._census_of_scene(
            "spa_core/monitoring/card_acceptance.py", _REVERT_PROBE)
        keys = [c.finding_key(r) for r in report["findings"]]
        self.assertIn("spa_core/monitoring/card_acceptance.py::"
                      "_probe_mutation_window_restore_refuses_a_live_owner::"
                      "scripts/delta_mutation_run.py", keys, report["counts"])

    def test_the_scene_differs_from_the_live_file_in_exactly_the_guard_lines(self):
        """Сцена, отличающаяся не тем, доказывала бы не то (урок ADR-870)."""
        for rel, pairs in (("push_to_github.py", _REVERT_PUBLICATION),
                           ("push_to_github.py", _REVERT_OWNER_CHOICE),
                           ("spa_core/monitoring/card_acceptance.py", _REVERT_PROBE)):
            with self.subTest(rel=rel, pairs=len(pairs)):
                live = (REPO_ROOT / rel).read_text(encoding="utf-8")
                reverted, hits = _apply(live, pairs)
                self.assertEqual(hits, len(pairs))
                a, b = live.splitlines(), reverted.splitlines()
                self.assertEqual(len(a), len(b), "откатка не должна менять число строк")
                differ = [(x.strip(), y.strip())
                          for x, y in zip(a, b) if x != y]
                expected = {(old.strip().splitlines()[0], new.strip().splitlines()[0])
                            for old, new in pairs}
                self.assertEqual(set(differ), expected)


class TheLiveTreeIsClean(unittest.TestCase):
    """Исход починки — ЧИСЛОМ, и проба приёмки обязана его подтверждать."""

    def test_the_census_finds_no_collapsing_reader_in_the_live_tree(self):
        report = c.run_census(REPO_ROOT)
        self.assertEqual(report["findings"], [],
                         [c.finding_key(r) for r in report["findings"]])
        self.assertEqual(report["counts"][c.COLLAPSED], 0)
        self.assertEqual(report["counts"][c.FAIL_OPEN], 0)
        self.assertGreaterEqual(report["counts"][c.DISTINGUISHES], 3)

    def test_the_four_named_readers_of_adr_870_are_gone_from_the_baseline(self):
        baseline = c.load_baseline(REPO_ROOT)
        self.assertEqual(baseline.get("collapsing_readers"), [],
                         "база обязана опустеть ПОЧИНКОЙ — дописывать в неё запрещено")

    def test_the_batch_cli_no_longer_carries_its_own_copy_of_the_gate(self):
        """Вторая дословная копия ветки — находка 2; её не должно быть вовсе."""
        text = BATCH.read_text(encoding="utf-8")
        self.assertNotIn("verify_publication.py\")", text,
                         "batch-CLI снова собирает путь к двери сам — это вторая копия")
        self.assertIn("publication_gate_verdict = _root_push.publication_gate_verdict",
                      text)

    def test_the_declared_probe_is_registered_and_satisfied(self):
        self.assertIn("three_outcome_readers_distinguish_by_code", ca.PROBES)
        verdict, detail = ca.PROBES["three_outcome_readers_distinguish_by_code"](None)
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_the_probe_is_not_satisfied_by_a_substring(self):
        """ADR-333: ярлык переименовать можно, род исхода переписи — нет."""
        source = ACCEPTANCE.read_text(encoding="utf-8")
        body = source.split(
            "def _probe_three_outcome_readers_distinguish_by_code")[1].split(
            "\ndef ")[0]
        self.assertNotIn("in detail", body)
        self.assertIn("run_census", body)
        self.assertIn("drive_publication_gate", body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
