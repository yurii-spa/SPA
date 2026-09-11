"""Цикл #525 — ОДИН вердикт об отсутствующем артефакте на ВСЕХ его читателей.

Каждая сцена здесь — воспроизведение НАСТОЯЩЕЙ поломки, измеренной 2026-09-08,
а не выдуманный случай. Проверка, никогда не видевшая живой аварии, —
украшение (`.claude/rules/deployment.md`).

Три замера, каждый дифференциальный (прежний код против нового, одна и та же
сцена):

**(A) Ложная находка во ВТОРОМ читателе.** `architecture_conformance.B2` печатал
«активный артефакт отсутствует на диске» БЕЗУСЛОВНО. Живой прогон 10:17Z назвал
находкой `data/cio_substitution_census.json` — исправный модуль цикла #523,
чей бегун `com.spa.decision_loop` (такт 6 ч) последний раз отработал в 07:03Z,
ДО прихода кода. Соседний ключ того же вида (`B2:missing:data/
cio_outcome_independence.json`) уже доехал до КАРТОЧКИ владельцу, то есть класс
не теоретический. ADR-261 закрыл ровно это — но у ОДНОГО читателя, того, на
котором нашлось.

**(Б) fail-OPEN в самой форме контроля.** Имя ступени ВЫВОДИЛОСЬ из имени файла
модуля, а мост её ОБЪЯВЛЯЕТ, и у двух переписей из 25 эти имена разные
(`evidence_staleness` ← `evidence_staleness_monitor.py`, `outcomes` ←
`outcomes_archive.py`). Ветка «названа бегуном ⇒ находка» для них не срабатывала
НИКОГДА: провалившаяся перепись С ЗАПИСАННОЙ ПРИЧИНОЙ уходила в ветку дат и при
недавно правленом модуле объявлялась «ещё не производился». Измерено прогоном
кода `origin/main` 99ab793ab: `находка=False`, причина `KeyError: 'positions'`
до читателя не доезжает.

**(В) Чужой бегун.** Ветки дат сравнивали отчёт МОСТА с датой модуля для любого
артефакта карты офиса, включая пять, которых мост не запускает вовсе. Измерено
тем же способом: `data/architecture_conformance.json` объявлялся «ещё не
производился» со ссылкой на бегуна, который его не пишет.

Время — ВХОД: ни одной литеральной даты в роли «сейчас», все отметки производны
от инъектированного якоря, `os.utime` выставляется явно.
FROZEN-DATE-OK: injected-clock — якорь `NOW` уходит параметром `now=` во все
вызовы `verdict()` / `_absent_verdict()` / `run_checks()`, а обе отметки сцены
(mtime модуля через `os.utime`, `generated_at` отчёта бегуна) строятся
вычитанием от него же. Ни одна проба не спрашивает стенных часов.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import artifact_absence as aa
from spa_core.monitoring import architecture_conformance as ac
from spa_core.monitoring.findings_bridge import CENSUS_PRODUCT, CENSUS_STAGE

REPO = Path(__file__).resolve().parents[2]
_OFFICE = REPO / "scripts" / "consume_office_reports.py"

#: Единственный якорь времени всего файла.
# FROZEN-DATE-OK: injected-clock — якорь NOW уходит параметром now= в verdict()/run();
# стенных часов тест не спрашивает (маркер в докстринге храповик не считает — он ищет «#»).
NOW = dt.datetime(2031, 1, 1, 12, 0, tzinfo=dt.timezone.utc)

#: Настоящая пара живого замера #525 — сцена обязана быть тем случаем, на
#: котором прибор соврал.
ARTIFACT = "data/cio_substitution_census.json"
MODULE = "spa_core/monitoring/cio_substitution_census.py"
STAGE = "cio_substitution_census"

#: Пара, у которой ОБЪЯВЛЕННОЕ имя ступени не совпадает с именем файла — на ней
#: и держался fail-OPEN (Б).
MISMATCH_ARTIFACT = "data/evidence_staleness.json"
MISMATCH_MODULE = "spa_core/monitoring/evidence_staleness_monitor.py"
MISMATCH_STAGE = "evidence_staleness"


def _load_office():
    """Шаг 0-офис — СКРИПТ, а не модуль пакета: грузим по пути."""
    spec = importlib.util.spec_from_file_location("_office_c525", _OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


office = _load_office()


class _Tree(unittest.TestCase):
    """Одноразовое дерево: живое `data/` не трогается ни одной сценой."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data").mkdir()
        (self.root / "spa_core" / "monitoring").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def module(self, rel: str = MODULE, *, born_hours_ago: float) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# производитель\n", encoding="utf-8")
        born = NOW - dt.timedelta(hours=born_hours_ago)
        os.utime(p, (born.timestamp(), born.timestamp()))

    def runner(self, *, ran_hours_ago: float | None = None, censuses=None,
               broken: bool = False, no_clock: bool = False) -> None:
        p = self.root / "data" / "findings_bridge_report.json"
        if broken:
            p.write_text("{ это не json", encoding="utf-8")
            return
        doc: dict = {}
        if not no_clock and ran_hours_ago is not None:
            doc["generated_at"] = (
                NOW - dt.timedelta(hours=ran_hours_ago)).isoformat()
        if censuses is not None:
            doc["censuses"] = censuses
        p.write_text(json.dumps(doc), encoding="utf-8")

    def verdict(self, artifact: str = ARTIFACT):
        return aa.verdict(artifact, root=str(self.root), now=NOW)


class LiveReplayOfTheFalseFinding(_Tree):
    """(A) Замер 2026-09-08 10:17Z: исправный контур объявлялся находкой."""

    def test_producer_arrived_after_its_runner_last_ran_is_not_a_finding(self):
        self.module(born_hours_ago=2.66)     # ровно живой замер
        self.runner(ran_hours_ago=3.2)
        v = self.verdict()
        self.assertTrue(v.not_yet, "исправный контур снова объявлен находкой — "
                                   "это и есть авария, ради которой правка")
        self.assertFalse(v.is_finding)
        self.assertEqual(v.stage, STAGE)

    def test_inverse_runner_ran_after_the_code_arrived_is_a_finding(self):
        """Обратный контроль: правка не смеет стать глушилкой."""
        self.module(born_hours_ago=5.0)
        self.runner(ran_hours_ago=1.0)
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.DECLARED_WITHOUT_CALL)
        self.assertIn("ADR-259", v.reason)

    def test_declared_attempt_beats_the_file_date(self):
        """Названа бегуном ⇒ находка, даже когда код «моложе» отчёта."""
        self.module(born_hours_ago=0.5)
        self.runner(ran_hours_ago=3.0,
                    censuses={"attempted": [STAGE], "skipped": {}})
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.ATTEMPTED_AND_ABSENT)

    def test_third_outcome_closes_itself_on_the_next_run(self):
        """«Ещё не производился» — состояние с выходом, не вечный UNCHECKED."""
        self.module(born_hours_ago=1.0)
        self.runner(ran_hours_ago=3.0)
        self.assertTrue(self.verdict().not_yet)
        self.runner(ran_hours_ago=0.1)       # в коде НИЧЕГО не менялось
        self.assertTrue(self.verdict().is_finding,
                        "состояние не закрывается следующим прогоном ⇒ это "
                        "UNCHECKED, который не станет CHECKED никогда")


class FailOpenOfTheDerivedStageName(_Tree):
    """(Б) Провалившаяся перепись молчала, потому что имя ступины ВЫВОДИЛОСЬ.

    Самое опасное направление класса: не ложная находка, а ЗАГЛУШЕННАЯ
    настоящая. Причина пропуска у бегуна уже записана — и не доезжала.
    """

    def test_declared_stage_is_found_even_when_module_filename_differs(self):
        self.module(MISMATCH_MODULE, born_hours_ago=0.5)   # модуль МОЛОЖЕ отчёта
        self.runner(ran_hours_ago=3.0,
                    censuses={"attempted": [MISMATCH_STAGE],
                              "skipped": {MISMATCH_STAGE: "KeyError: 'positions'"}})
        v = self.verdict(MISMATCH_ARTIFACT)
        self.assertTrue(v.is_finding,
                        "провалившаяся перепись снова объявлена «ещё не "
                        "производился» — fail-OPEN вернулся")
        self.assertEqual(v.kind, aa.ATTEMPTED_AND_ABSENT)
        self.assertEqual(v.skip_reason, "KeyError: 'positions'")

    def test_the_recorded_reason_reaches_the_office_reader(self):
        """Причина едет ЧИТАТЕЛЮ, а не только в /tmp-лог агента."""
        self.module(MISMATCH_MODULE, born_hours_ago=0.5)
        self.runner(ran_hours_ago=3.0,
                    censuses={"attempted": [MISMATCH_STAGE],
                              "skipped": {MISMATCH_STAGE: "KeyError: 'positions'"}})
        is_finding, lines = office._absent_verdict(
            MISMATCH_ARTIFACT, root=str(self.root), data_dir=None, now=NOW)
        self.assertTrue(is_finding)
        self.assertIn("KeyError: 'positions'", "\n".join(lines))

    def test_lookup_is_keyed_by_the_declared_artifact_string(self):
        """Ступень ищется по ОБЪЯВЛЕННОЙ строке, а не по имени файла артефакта.

        Замер батареи мутаций #525: подмена ключа на `basename(артефакт)`
        ВЫЖИЛА — и была права, что выжила: у всех 25 переписей имя артефакта
        сегодня совпадает с именем ступени, то есть подмена эквивалентна ПО
        ПОСТРОЕНИЮ. Эквивалентна СЕГОДНЯ — не значит «не может изменить ответ»:
        первая же перепись, чей продукт назван иначе, молча выпала бы из
        различения и вернулась к безусловной находке. Сцена делает подмену
        неэквивалентной, задавая объявление ВХОДОМ.
        """
        products = {"стороннее_имя_ступени": {
            "module": MODULE, "artifact": "data/совсем_другое_имя.json"}}
        self.module(born_hours_ago=1.0)
        self.runner(ran_hours_ago=3.0)
        v = aa.verdict("data/совсем_другое_имя.json", root=str(self.root),
                       now=NOW, products=products)
        self.assertEqual(v.stage, "стороннее_имя_ступени",
                         "поиск ступени вернулся к выводу из имени файла — "
                         "объявление снова не спрашивают")
        self.assertTrue(v.not_yet)

    def test_the_other_mismatched_pair_is_covered_too(self):
        """`outcomes` ← `outcomes_archive.py` — вторая пара того же вида.

        Форма контроля применяется ко ВСЕМУ классу, а не к его поводу
        (урок #519): вторая пара — не повод, а тот же класс.
        """
        spec = CENSUS_PRODUCT["outcomes"]
        self.module(spec["module"], born_hours_ago=0.5)
        self.runner(ran_hours_ago=3.0,
                    censuses={"attempted": ["outcomes"],
                              "skipped": {"outcomes": "OSError: disk full"}})
        v = self.verdict(spec["artifact"])
        self.assertTrue(v.is_finding)
        self.assertEqual(v.skip_reason, "OSError: disk full")


class WrongRunnerIsRefusedNotSubstituted(_Tree):
    """(В) Чужому бегуну не место: «не измерено» вместо подставного ответа."""

    def test_artifact_no_census_declares_never_becomes_not_yet(self):
        self.module("spa_core/monitoring/architecture_conformance.py",
                    born_hours_ago=0.5)
        self.runner(ran_hours_ago=3.0, censuses={"attempted": [], "skipped": {}})
        v = self.verdict("data/architecture_conformance.json")
        self.assertFalse(v.not_yet,
                         "артефакт чужого бегуна снова получил ответ моста — "
                         "верный ответ не на тот вопрос")
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.UNMEASURED_NOT_DECLARED)
        self.assertIn(aa.UNMEASURED, v.reason)


class NothingIsSilenced(_Tree):
    """Все четыре двери незнания остаются находкой. «Не смог измерить» ≠ «ок»."""

    def test_module_absent_from_the_tree(self):
        self.runner(ran_hours_ago=3.0)          # модуля не создаём вовсе
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.UNMEASURED_MODULE_ABSENT)

    def test_runner_report_unreadable(self):
        self.module(born_hours_ago=1.0)
        self.runner(broken=True)
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.UNMEASURED_REPORT_UNREADABLE)

    def test_runner_report_without_its_own_clock(self):
        self.module(born_hours_ago=1.0)
        self.runner(ran_hours_ago=3.0, no_clock=True)
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.UNMEASURED_REPORT_HAS_NO_CLOCK)

    def test_runner_report_absent_entirely(self):
        self.module(born_hours_ago=1.0)         # отчёта бегуна нет на диске
        v = self.verdict()
        self.assertTrue(v.is_finding)
        self.assertEqual(v.kind, aa.UNMEASURED_REPORT_UNREADABLE)

    def test_not_yet_is_the_only_non_finding(self):
        """Ровно ОДИН исход из пяти не обязывает действовать."""
        kinds = (aa.ATTEMPTED_AND_ABSENT, aa.DECLARED_WITHOUT_CALL, aa.NOT_YET,
                 aa.UNMEASURED_NOT_DECLARED, aa.UNMEASURED_MODULE_ABSENT,
                 aa.UNMEASURED_REPORT_UNREADABLE,
                 aa.UNMEASURED_REPORT_HAS_NO_CLOCK)
        self.assertEqual(len(set(kinds)), 7, "исходы задвоены по значению")
        self.assertEqual(aa.Absence("x", aa.NOT_YET, False, "").not_yet, True)
        for k in kinds:
            if k != aa.NOT_YET:
                self.assertFalse(aa.Absence("x", k, True, "").not_yet)


class ConformanceUsesTheVerdictAndCountsItApart(_Tree):
    """Проводка во ВТОРОМ читателе + третий исход как ОТДЕЛЬНОЕ слагаемое."""

    def _manifest(self):
        return {"agents": [{"label": "com.spa.decision_loop", "intent": "active",
                            "schedule": "interval:21600s", "reboot_safe": True,
                            "plist_source": "launch_agents"}],
                "artifacts": [{"path": ARTIFACT, "status": "active",
                               "producer": "com.spa.decision_loop",
                               "slo_hours": 7}]}

    def _run(self, absence_of):
        return ac.run_checks(self._manifest(), fleet=None,
                             ts_of=lambda rel: None,     # артефакта нет на диске
                             receipts={}, now=NOW, absence_of=absence_of)

    def test_healthy_contour_is_not_a_finding_and_is_named_aloud(self):
        self.module(born_hours_ago=2.66)
        self.runner(ran_hours_ago=3.2)
        r = self._run(lambda path, *, now: aa.verdict(path, root=str(self.root),
                                                      now=now))
        self.assertEqual([f["key"] for f in r["findings"]
                          if f["key"].startswith("B2:missing")], [])
        self.assertEqual(r["counts"]["b2_not_yet"], 1)
        self.assertEqual(r["b2_not_yet"][0]["path"], ARTIFACT)
        self.assertEqual(r["b2_not_yet"][0]["stage"], STAGE)

    def test_positive_control_the_old_behaviour_is_a_finding(self):
        """Со снятым различением сцена КРАСНЕЕТ — контроль не украшение."""
        class _Always:
            not_yet = False
            stage = module = runner_ran_at = skip_reason = None
            module_age_h = None
            reason = "(прежнее безусловное поведение)"
        r = self._run(lambda path, *, now: _Always())
        self.assertEqual([f["key"] for f in r["findings"]],
                         [f"B2:missing:{ARTIFACT}"])
        self.assertEqual(r["counts"]["b2_not_yet"], 0)

    def test_third_outcome_is_a_separate_summand(self):
        """Не в `warn`, не в `unchecked` — иначе один из двух дефектов вернётся.

        Мера ДИФФЕРЕНЦИАЛЬНАЯ: сравниваются два прогона ОДНОЙ сцены, у которых
        различается ровно наличие «ещё не производился». Абсолютные числа сюда
        не годятся — в них попадают чужие исходы той же сцены (`fleet=None`
        честно даёт свой `unchecked`), и утверждение о них было бы утверждением
        о соседнем ограничении, а не о своём.
        """
        self.module(born_hours_ago=2.66)
        self.runner(ran_hours_ago=3.2)
        probe = lambda path, *, now: aa.verdict(path, root=str(self.root),  # noqa: E731
                                                now=now)
        # артефакт НА МЕСТЕ и свеж — третьего исхода нет
        present = ac.run_checks(self._manifest(), fleet=None,
                                ts_of=lambda rel: NOW - dt.timedelta(hours=1),
                                receipts={}, now=NOW, absence_of=probe)
        absent = self._run(probe)          # тот же прогон, артефакта нет

        self.assertEqual(present["counts"]["b2_not_yet"], 0)
        self.assertEqual(absent["counts"]["b2_not_yet"], 1)
        for k in ("critical", "warn", "aged", "unchecked"):
            self.assertEqual(present["counts"][k], absent["counts"][k],
                             f"третий исход просочился в `{k}` — он снова "
                             f"неотличим либо от находки, либо от тишины")
        self.assertEqual(present["overall"], absent["overall"],
                         "третий исход изменил ВЕРДИКТ — значит он всё-таки "
                         "сложился с находками")

    def test_the_finding_carries_the_measured_reason(self):
        """Строка находки объясняет ПОЧЕМУ, а не только «нет на диске»."""
        self.module(born_hours_ago=5.0)
        self.runner(ran_hours_ago=1.0)
        r = self._run(lambda path, *, now: aa.verdict(path, root=str(self.root),
                                                      now=now))
        msg = r["findings"][0]["message"]
        self.assertIn("активный артефакт отсутствует на диске", msg)
        self.assertIn("ADR-259", msg)

    def test_skip_reason_reaches_the_conformance_reader(self):
        self.module(born_hours_ago=0.5)
        self.runner(ran_hours_ago=3.0,
                    censuses={"attempted": [STAGE],
                              "skipped": {STAGE: "KeyError: 'positions'"}})
        r = self._run(lambda path, *, now: aa.verdict(path, root=str(self.root),
                                                      now=now))
        self.assertIn("KeyError: 'positions'", r["findings"][0]["message"])

    def test_third_outcome_is_printed_not_only_stored(self):
        """Блок в JSON, который не звучит, — тот же немой исход (урок #426)."""
        report = {"overall": "OK", "counts": {"critical": 0, "warn": 0,
                                              "aged": 0, "unchecked": 0},
                  "fleet_size": 1, "manifest_agents": 1, "findings": [],
                  "b2_not_yet": [{"path": ARTIFACT, "stage": STAGE,
                                  "module": MODULE, "module_age_h": 2.66,
                                  "runner_ran_at": "2026-09-08T07:05:12+00:00",
                                  "reason": "приехал ПОСЛЕ прогона бегуна"}]}
        buf = io.StringIO()
        with redirect_stdout(buf):
            ac._print_report(report, {"source": "test"})
        out = buf.getvalue()
        self.assertIn("ЕЩЁ НЕ ПРОИЗВОДИЛСЯ", out)
        self.assertIn(ARTIFACT, out)
        self.assertIn("НЕ находка", out)


class WiringIsMeasuredNotAssumed(unittest.TestCase):
    """Безупречный вердикт, который никто не зовёт, — мёртвая правка.

    Меряется ФОРМА вызова в теле `run_checks`, а не наличие функции рядом.
    """

    def test_conformance_calls_the_verdict_in_the_missing_branch(self):
        src = Path(ac.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "run_checks")
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "absence_of"]
        self.assertEqual(len(calls), 1,
                         "проба об отсутствии не вызывается из run_checks ровно "
                         "один раз — правка мертва либо задвоена")
        self.assertIn("b2_not_yet", src,
                      "третий исход не имеет своего слагаемого ⇒ он "
                      "складывается либо с находками, либо с тишиной")

    def test_office_delegates_to_the_shared_verdict(self):
        """Второй читатель обязан звать ТУ ЖЕ функцию, а не свою копию."""
        src = _OFFICE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_absent_verdict")
        called = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "verdict"]
        self.assertEqual(len(called), 1,
                         "шаг 0-офис снова решает сам — две реализации одного "
                         "вопроса и есть тот дефект, ради которого правка")

    def test_both_readers_agree_on_the_same_input(self):
        """Согласие ИЗМЕРЯЕТСЯ на общей сцене, а не утверждается чтением."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            (root / "spa_core" / "monitoring").mkdir(parents=True)
            p = root / MODULE
            p.write_text("#\n", encoding="utf-8")
            born = NOW - dt.timedelta(hours=1)
            os.utime(p, (born.timestamp(), born.timestamp()))
            (root / "data" / "findings_bridge_report.json").write_text(
                json.dumps({"generated_at":
                            (NOW - dt.timedelta(hours=3)).isoformat()}),
                encoding="utf-8")
            shared = aa.verdict(ARTIFACT, root=str(root), now=NOW)
            is_finding, _ = office._absent_verdict(ARTIFACT, root=str(root),
                                                   data_dir=None, now=NOW)
            self.assertEqual(shared.is_finding, is_finding)
            self.assertFalse(is_finding)


class DeclarationIsRatcheted(unittest.TestCase):
    """Состав переписи ОБЪЯВЛЕН и сверяется с ДВУМЯ независимыми объявлениями.

    Ручной список отказывает ровно тогда, когда кто-то забыл в него дописать —
    поэтому его держат перекрёстные сверки, а не внимательность.
    """

    def test_keys_match_the_declared_stage(self):
        self.assertEqual(set(CENSUS_PRODUCT), set(CENSUS_STAGE),
                         "состав продуктов разошёлся с составом ступени")

    def test_every_declared_module_exists_in_the_tree(self):
        missing = [s for s, v in CENSUS_PRODUCT.items()
                   if not (REPO / v["module"]).exists()]
        self.assertEqual(missing, [], "объявлен производитель, которого нет")

    def test_every_declared_artifact_is_active_in_the_manifest(self):
        manifest = json.loads((REPO / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        active = {a["path"]: a for a in manifest.get("artifacts", [])
                  if a.get("status") == "active"}
        for stage, spec in sorted(CENSUS_PRODUCT.items()):
            with self.subTest(stage=stage):
                self.assertIn(spec["artifact"], active,
                              "продукт переписи не объявлен активным в манифесте")
                self.assertEqual(active[spec["artifact"]].get("producer"),
                                 "com.spa.decision_loop",
                                 "манифест приписывает продукт ДРУГОМУ бегуну")

    def test_no_two_stages_declare_the_same_artifact(self):
        arts = [v["artifact"] for v in CENSUS_PRODUCT.values()]
        self.assertEqual(len(arts), len(set(arts)),
                         "один артефакт объявлен двумя ступенями — вердикт "
                         "перестал быть однозначным")

    def test_the_two_known_name_mismatches_are_declared_not_derived(self):
        """Именно эти две пары и держали fail-OPEN (Б). Замер, не память."""
        for stage in ("evidence_staleness", "outcomes"):
            derived = os.path.splitext(
                os.path.basename(CENSUS_PRODUCT[stage]["module"]))[0]
            self.assertNotEqual(
                derived, stage,
                f"пара {stage} перестала быть расхождением — сцена (Б) "
                f"потеряла свой предмет и больше ничего не меряет")


if __name__ == "__main__":
    unittest.main()
