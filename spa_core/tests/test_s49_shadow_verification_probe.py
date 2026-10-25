"""ADR-809 — последний критерий §49 приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Замер 25.10 (`data/s49_tally_tact.json`, ADR-808): из тринадцати критериев §49
приказа «Portfolio CIO» у `Shadow verification` в графе пробы стоял **`null`**,
вердикт — **`unmeasured`**, такт входа — **`unbound`**, а цена по
`s49_criterion_price` — **`DECISION`** («конституция не называет мерой этого
критерия НИ ОДНОГО артефакта»).

При этом прибор, отвечающий на дословный вопрос владельца, работает с 06.09:
`cio_shadow_replay` (§38) гоняет три руки по накопителю ADR-060, объявлен в
конституции со сроком годности 7 ч, свеж, читается шагом 0-офис и печатает
`CRITICAL` каждым тактом. Живой замер 25.10: сверенных во ВСЕХ трёх руках дней
**7** (ранее 7 из 31, теперь из 157 пар), чистая APY живой книги −5.29 % против
+5.41 % у НЕсделанной перекладки, 12 из 13 проверяемых перекладок не окупаются.

То есть критерий был ИЗМЕРЕН и не имел читателя ровно там, где считается его
вердикт, — последний такой случай в §49.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `shadow_verification_replay_was_conducted` зелена на целом контуре и
  красна на КАЖДОМ порванном звене — с НАЗВАННЫМ звеном;
* **вердикт переносится, а не считается заново.** Правило живёт у производителя
  чисел (`criterion_verdict`, ADR-220); проба читает поле `criterion.status`;
* **переносится НЕ `overall`.** У этого прибора `overall` есть лестница ТЯЖЕСТИ
  находок, и на живом замере он `CRITICAL` именно потому, что прогон СОСТОЯЛСЯ
  и нашёл дефект. Перенеси пробу на `overall` — критерий «прогон проведён»
  оказался бы невыполненным ровно тогда, когда он выполняется. Класс
  `TestTheSeverityLadderIsNotTheVerdict` держит эту сторону отдельно;
* **предмет критерия — ПРОВЕДЁННОСТЬ, а не победитель.** Отчёт, нашедший, что
  живая книга проигрывает тени, обязан давать `satisfied`: кто победил — предмет
  §38 и money-path, решение владельца;
* **ноль сверенных дней — третий исход, а не зелёный.** «Тень сверена с фактом»
  при нуле сверенных дней верно ПО ПОСТРОЕНИЮ и ответом не является;
* **одноколоночное сравнение — третий исход.** Вывод, живущий только на
  ЗАРЯЖЕННОМ газе, ADR-243 опроверг на этом же прогоне (9 из 13 против 12 из 13);
* **у порога узости ОДИН дом.** И находка прогона, и вердикт критерия зовут
  `population_too_thin`; второго сравнения с числом в дереве нет, и это
  измеряется AST, а не глазами (`TestTheThinnessRuleHasExactlyOneHome`);
* своего порога свежести у пробы НЕТ: срок годности читается из
  `architecture/manifest.json` одним читателем (`declared_slo_hours`);
* прибор, не объявивший себя мерой критерия, ⇒ `unmeasured`; якорь читается как
  НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный вердикт прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `repo_root`, `data_dir` и `now` ДОХОДЯТ до исхода пробы — ВСЕ двери, а не одна
  («половина инъекции», `.claude/rules/deployment.md`);
* проба НЕ ПИШЕТ ни одного артефакта.

Порядок контроля не произволен: сначала доказывается, что НАСТОЯЩИЙ прибор
несёт вердикт в своём отчёте и что сцена даёт именно его породу
(`TestTheRealInstrumentCarriesTheVerdict`), и только потом — что проба на нём
отвечает. Без первого шага «красно на порванном звене» тавтологично.

Утверждения-носители claim стоят ОТДЕЛЬНЫМИ пробами, а не под `subTest`:
падение под `subTest` несёт имя `SUBFAILED`, которого прибор мутаций по дельте
не видит (ADR-761, замер #876), и носитель оказался бы невидим.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся
и в сцену, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается,
живое `data/` не читается: материал пишется в одноразовый каталог.
"""
from __future__ import annotations

import ast
import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import cio_shadow_replay as R
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "shadow_verification_replay_was_conducted"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Shadow verification"

#: Живой замер 25.10, породивший ADR-809: сверено 7 дней — ниже порога прогона.
_LIVE_COMMON_DAYS = 7
#: Знаменатель того же замера.
_LIVE_PAIRS = 157


class _Scene(unittest.TestCase):
    """Одноразовое дерево: конституция в `architecture/`, артефакт в `data/`.

    Сцена — это АРТЕФАКТ; правило вердикта берётся у НАСТОЯЩЕГО прибора
    (`criterion_verdict`). Подменять правило было бы бессмысленно: проверялась
    бы копия, а не мера.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()
        (self.root / "architecture").mkdir()
        # Якорь считается ЗДЕСЬ, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.build()

    # ── сцена ───────────────────────────────────────────────────────────────

    def _ts(self, hours_ago: float) -> str:
        return (self.now - timedelta(hours=hours_ago)).isoformat()

    def build(self, *, days: int | None = None, pairs: int = _LIVE_PAIRS,
              columns: tuple[str, ...] = R.COST_COLUMNS,
              unchecked_columns: tuple[str, ...] = (),
              blank_arms: tuple[str, ...] = (),
              drop_rates_in: tuple[str, ...] = (),
              overall: str = "OK", age_h: float = 1.0,
              slo: float | None = 7.0, stamp: str | None = None,
              drop: tuple[str, ...] = (), unchecked: list | None = None,
              unpriced: dict | None = None) -> None:
        """Целый контур по умолчанию; каждый аргумент рвёт ОДНО звено.

        По умолчанию `days` = порог прогона, то есть ПРОВЕДЁННЫЙ и утверждаемый
        прогон: целый контур обязан быть зелёным, иначе «красно на порванном
        звене» ничего не значит.
        """
        days = R.MIN_COMMON_DAYS_FOR_CLAIM if days is None else days

        arts = []
        if slo is not None:
            arts.append({"path": R.REPORT_REL, "slo_hours": slo,
                         "status": "active"})
        self._write(self.root / "architecture" / "manifest.json",
                    {"artifacts": arts, "agents": []})

        # Сцена ПЕРЕСОБИРАЕТСЯ, а не дописывается: `build` зовётся повторно, и
        # оставленный прошлым зовом файл сделал бы «звено порвано» ложью.
        stale = self.data_dir / Path(R.REPORT_REL).name
        if stale.exists():
            stale.unlink()
        if "artifact" in drop:
            return

        comparison: dict = {}
        for column in columns:
            if column in unchecked_columns:
                comparison[column] = {"verdict": "UNCHECKED",
                                      "reason": f"колонка {column} не посчитана"}
                continue
            block: dict = {
                "hold_minus_current_pp": 1.0,
                "opt_minus_current_pp": -1.0,
                "gross_spread_pp": 0.2,
                "best_net_arm": R.ARM_CIO_HOLD,
            }
            if column not in drop_rates_in:
                block["net_apy_pct"] = {
                    arm: (None if arm in blank_arms else
                          {R.ARM_CURRENT: -5.29, R.ARM_CIO_HOLD: 5.41,
                           R.ARM_CIO_OPT: -4.86}[arm])
                    for arm in R.ARMS}
            comparison[column] = block

        doc: dict = {
            "generated_at": stamp if stamp is not None else self._ts(age_h),
            "overall": overall,
            "counts": {"critical": 0, "warn": 0, "info": 0, "unchecked": 0},
            "comparison": comparison,
            "findings": [],
            "unchecked": [] if unchecked is None else unchecked,
        }
        if "population" not in drop:
            population: dict = {"days_observed": pairs + 1, "day_pairs": pairs,
                                "common_scored_days": days,
                                "scored_per_arm": {arm: days for arm in R.ARMS}}
            if "pairs_number" in drop:
                population["day_pairs"] = "много"
            if "days_number" in drop:
                population["common_scored_days"] = None
            if unpriced is not None:
                population["unpriced_per_arm"] = unpriced
            doc["population"] = population
        if "comparison" in drop:
            doc.pop("comparison")
        self._write(self.data_dir / Path(R.REPORT_REL).name, doc)

    @staticmethod
    def _write(path: Path, doc) -> None:
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # ── прогон ──────────────────────────────────────────────────────────────

    def probe(self, *, now=None, data_dir=None, repo_root=None) -> tuple:
        """Проба зовётся ПО ИМЕНИ ИЗ РЕЕСТРА — иначе контроль проверял бы
        функцию, а не то, что реестр отдаёт именно её."""
        fn = ca.PROBES[PROBE_NAME]
        return fn(None, now=now or self.now,
                  data_dir=data_dir or str(self.data_dir),
                  repo_root=repo_root or str(self.root))


class TestTheRealInstrumentCarriesTheVerdict(unittest.TestCase):
    """СНАЧАЛА — что настоящий прибор вообще выносит вердикт критерия.

    Без этого шага всё остальное тавтологично: проба могла бы быть красной от
    чего угодно, а не от того, что критерий владельца не выполнен.
    """

    def test_the_instrument_declares_the_criterion_as_the_START_of_its_claim(self):
        self.assertTrue(R.CRITERION.startswith("§49 Shadow verification"),
                        R.CRITERION[:80])

    def test_the_anchor_is_an_anchor_and_not_a_substring(self):
        """ADR-333: упоминание критерия в СЕРЕДИНЕ текста — ссылка, не объявление.

        Утверждение о СТРОКЕ, и только о ней: что так же читает её ПРОБА,
        проверяет `TestTheProbeRefusesAnUndeclaredOrStrangeInstrument`. Первый
        прогон мутаций по дельте оставил «читать подстрокой» ВЫЖИВШИМ ровно
        потому, что здесь стояло одно это утверждение — строка была закреплена,
        а её читатель нет.
        """
        self.assertFalse(
            ("прочее; " + R.CRITERION).startswith(ca.SHADOW_REPLAY_ANCHOR))

    def test_run_puts_the_verdict_INTO_the_report(self):
        """Вердикт обязан жить в САМОМ отчёте: читатель его переносит (ADR-220).

        Дерево одноразовое и ПУСТОЕ — живое `data/` не открывается. Прибор на нём
        честно отвечает «не измерено», и это ровно тот исход, который
        проверяется: блок есть, и он не притворяется зелёным.
        """
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            doc = R.run(root=tmp, write=False)
        self.assertIn("criterion", doc, "вердикта критерия нет в отчёте прибора")
        self.assertEqual(doc["criterion"]["status"], R.CRITERION_UNMEASURED,
                         doc["criterion"]["reason"])

    def test_the_verdict_of_an_empty_run_names_its_reason(self):
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "data").mkdir()
            doc = R.run(root=tmp, write=False)
        self.assertTrue(doc["criterion"]["reason"].strip())

    def test_zero_common_days_is_UNMEASURED_by_construction(self):
        """Ноль сверенных дней — третий исход, а не зелёное."""
        verdict = R.criterion_verdict(
            {"population": {"common_scored_days": 0, "day_pairs": 31}})
        self.assertEqual(verdict["status"], R.CRITERION_UNMEASURED)
        self.assertIn("ПО ПОСТРОЕНИЮ", verdict["reason"])

    def test_the_registry_returns_THIS_probe_under_THIS_name(self):
        self.assertIn(PROBE_NAME, ca.PROBES)
        self.assertIs(ca.PROBES[PROBE_NAME],
                      ca._probe_shadow_verification_replay_was_conducted)

    def test_the_probe_declares_WHICH_s49_criterion_it_answers(self):
        self.assertEqual(
            ca.PROBES[PROBE_NAME].s49_criterion, CRITERION)

    def test_the_criterion_is_reachable_through_the_s49_index(self):
        self.assertEqual(ca.probes_by_s49_criterion().get(CRITERION),
                         [PROBE_NAME])


class TestTheWholeContourIsGreen(_Scene):
    """Целый контур. Без этого «красно на порванном звене» не значит ничего."""

    def test_a_conducted_and_assertable_run_is_satisfied(self):
        status, why = self.probe()
        self.assertEqual(status, ca.SATISFIED, why)

    def test_the_green_answer_names_both_cost_columns(self):
        _status, why = self.probe()
        for column in R.COST_COLUMNS:
            self.assertIn(column, why)

    def test_the_green_answer_names_what_the_measure_does_NOT_report(self):
        """Назвать слепоту — часть замера, а не вежливость."""
        _status, why = self.probe()
        self.assertIn("money-path", why)


class TestTheSubjectIsConductNotTheWinner(_Scene):
    """Предмет критерия — ПРОВЕДЁННОСТЬ прогона, а не кто в нём победил."""

    def test_a_run_that_found_the_live_book_losing_is_still_conducted(self):
        """Находки §38 — money-path и решение владельца, а не вердикт §49."""
        self.build(overall="CRITICAL")
        status, why = self.probe()
        self.assertEqual(status, ca.SATISFIED, why)


class TestTheSeverityLadderIsNotTheVerdict(_Scene):
    """`overall` прибора в вердикт критерия НЕ переносится — ни в одну сторону."""

    def test_a_CRITICAL_overall_does_not_make_the_criterion_unsatisfied(self):
        self.build(overall="CRITICAL")
        status, _why = self.probe()
        self.assertNotEqual(status, ca.NOT_SATISFIED)

    def test_an_OK_overall_does_not_make_a_thin_run_satisfied(self):
        """Обратная сторона: зелёная лестница не красит узкую популяцию."""
        self.build(days=_LIVE_COMMON_DAYS, overall="OK")
        status, _why = self.probe()
        self.assertEqual(status, ca.NOT_SATISFIED)


class TestTheThinPopulationIsMeasuredNotSatisfied(_Scene):
    """Живой замер 25.10: прогон состоялся и САМ отозвал свой вывод."""

    def test_the_live_measurement_is_not_satisfied(self):
        self.build(days=_LIVE_COMMON_DAYS)
        status, _why = self.probe()
        self.assertEqual(status, ca.NOT_SATISFIED)

    def test_the_answer_carries_BOTH_numbers(self):
        """«Не выполнено» обязано нести числа — иначе его нечем починить."""
        self.build(days=_LIVE_COMMON_DAYS)
        _status, why = self.probe()
        self.assertIn(str(_LIVE_COMMON_DAYS), why)
        self.assertIn(str(_LIVE_PAIRS), why)

    def test_the_answer_names_the_ADDRESS_of_the_fix(self):
        """Протоколы без цен вперёд — это и есть адрес починки."""
        self.build(days=_LIVE_COMMON_DAYS,
                   unpriced={R.ARM_CURRENT: ["aave_v3"],
                             R.ARM_CIO_HOLD: ["pendle"],
                             R.ARM_CIO_OPT: ["pendle", "morpho_blue"]})
        _status, why = self.probe()
        self.assertIn("aave_v3", why)
        self.assertIn("morpho_blue", why)

    def test_a_missing_unpriced_section_is_NOT_an_empty_address(self):
        """«Раздела нет» и «протоколов ноль» чинятся разным (инв. #17)."""
        self.build(days=_LIVE_COMMON_DAYS, unpriced=None)
        _status, why = self.probe()
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_exactly_at_the_threshold_the_run_is_assertable(self):
        """Граница названа явно: порог прогона — НЕ строгое «больше»."""
        self.build(days=R.MIN_COMMON_DAYS_FOR_CLAIM)
        status, why = self.probe()
        self.assertEqual(status, ca.SATISFIED, why)

    def test_one_day_below_the_threshold_is_not_satisfied(self):
        self.build(days=R.MIN_COMMON_DAYS_FOR_CLAIM - 1)
        status, _why = self.probe()
        self.assertEqual(status, ca.NOT_SATISFIED)


class TestTheThinnessRuleHasExactlyOneHome(unittest.TestCase):
    """Порог узости сравнивается ровно в ОДНОМ месте — меряется AST, не глазами."""

    def test_the_predicate_is_the_only_comparison_against_the_threshold(self):
        source = Path(R.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        sites = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                names = [n.id for n in ast.walk(node)
                         if isinstance(n, ast.Name)]
                if "MIN_COMMON_DAYS_FOR_CLAIM" in names:
                    sites.append(node.lineno)
        self.assertEqual(len(sites), 1,
                         f"порог сравнивается в {len(sites)} местах "
                         f"(строки {sites}) — вторая копия правила")

    def test_the_column_list_is_read_by_the_collector_too(self):
        """`COST_COLUMNS` спрашивают ОБА читателя, и это не комментарий.

        Разойдись перечень со сборщиком колонок — вердикт критерия требовал бы
        колонку, которой прогон не делает, и критерий был бы НЕИЗМЕРИМ навсегда
        по построению. Меряется AST: в `run` имена колонок не набираются
        литералами, а берутся из перечня.
        """
        source = Path(R.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        reads = [n for n in ast.walk(run)
                 if isinstance(n, ast.Name) and n.id == "COST_COLUMNS"]
        self.assertTrue(reads, "`run` не читает `COST_COLUMNS` — перечень разошёлся")

    def test_both_readers_go_through_the_predicate(self):
        """И находка прогона, и вердикт критерия зовут один предикат."""
        source = Path(R.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        callers = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == "population_too_thin"):
                    callers.add(node.name)
        self.assertEqual(callers, {"_findings", "criterion_verdict"}, callers)


class TestEveryBrokenLinkIsRedAndNamed(_Scene):
    """Красно на КАЖДОМ порванном звене, и звено НАЗВАНО."""

    def _unmeasured(self, needle: str) -> str:
        status, why = self.probe()
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn(needle, why)
        return why

    def test_a_missing_artifact_is_unmeasured(self):
        self.build(drop=("artifact",))
        self._unmeasured("не прочитан")

    def test_a_missing_population_section_is_unmeasured(self):
        self.build(drop=("population",))
        self._unmeasured("`population`")

    def test_an_unreadable_day_count_is_unmeasured(self):
        self.build(drop=("days_number",))
        self._unmeasured("common_scored_days")

    def test_an_unreadable_denominator_is_unmeasured(self):
        self.build(drop=("pairs_number",))
        self._unmeasured("day_pairs")

    def test_zero_common_days_is_unmeasured_through_the_probe(self):
        self.build(days=0)
        self._unmeasured("ПО ПОСТРОЕНИЮ")

    def test_a_missing_comparison_section_is_unmeasured(self):
        self.build(drop=("comparison",))
        self._unmeasured("`comparison`")

    def test_a_missing_cost_column_is_unmeasured_and_the_column_is_named(self):
        """Одноколоночный вывод ADR-243 опроверг на этом же прогоне."""
        self.build(columns=("charged",))
        self._unmeasured("observed")

    def test_an_unchecked_cost_column_is_unmeasured(self):
        self.build(unchecked_columns=("observed",))
        self._unmeasured("НЕ ВЫНЕСЕНО")

    def test_a_missing_rate_block_is_unmeasured(self):
        self.build(drop_rates_in=("charged",))
        self._unmeasured("net_apy_pct")

    def test_an_arm_without_a_rate_is_unmeasured_and_the_arm_is_named(self):
        self.build(blank_arms=(R.ARM_CIO_HOLD,))
        self._unmeasured(R.ARM_CIO_HOLD)

    def test_a_stale_artifact_is_unmeasured(self):
        self.build(age_h=9.0, slo=7.0)
        self._unmeasured("протух")

    def test_an_undeclared_slo_is_unmeasured_not_fresh(self):
        """Своего «24 часа» проба не назначает: порог — решение, дом его — конституция."""
        self.build(slo=None)
        self._unmeasured("срок годности")

    def test_an_unparseable_stamp_is_unmeasured(self):
        self.build(stamp="вчера")
        self._unmeasured("НЕ ИЗМЕРЕН")

    def test_an_argument_is_refused(self):
        status, why = ca.PROBES[PROBE_NAME]("spa_core/x.py")
        self.assertEqual(status, ca.UNMEASURED)
        self.assertIn("не принимает аргумента", why)


class TestTheProbeRefusesAnUndeclaredOrStrangeInstrument(_Scene):
    """Объявление читается ДО артефакта, а незнакомый вердикт fail-CLOSED."""

    class _Silent:
        CRITERION = ""
        REPORT_REL = R.REPORT_REL

        @staticmethod
        def criterion_verdict(_doc):
            return {"status": "SATISFIED", "reason": "врёт"}

    class _Strange:
        CRITERION = R.CRITERION
        REPORT_REL = R.REPORT_REL
        CRITERION_SATISFIED = "SATISFIED"
        CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
        CRITERION_UNMEASURED = "UNMEASURED"

        @staticmethod
        def criterion_verdict(_doc):
            return {"status": "ПОЧТИ", "reason": "вердикт не из набора"}

    class _Mentioning:
        """Критерий назван, но НЕ первым словом: это ссылка, а не объявление.

        Прибор при этом возвращает `SATISFIED` — то есть ошибка чтения якоря
        подстрокой стоила бы зелёного вердикта на чужом приборе.
        """

        CRITERION = ("Смотри также " + R.CRITERION)
        REPORT_REL = R.REPORT_REL
        CRITERION_SATISFIED = "SATISFIED"
        CRITERION_NOT_SATISFIED = "NOT_SATISFIED"
        CRITERION_UNMEASURED = "UNMEASURED"

        @staticmethod
        def criterion_verdict(_doc):
            return {"status": "SATISFIED", "reason": "подписался чужой мерой"}

    class _Exploding:
        CRITERION = R.CRITERION
        REPORT_REL = R.REPORT_REL

        @staticmethod
        def criterion_verdict(_doc):
            raise RuntimeError("прибор сломан")

    def _with_instrument(self, stub) -> tuple:
        import importlib
        real = importlib.import_module
        try:
            importlib.import_module = (
                lambda name, *a, **k: stub
                if name == ca.SHADOW_REPLAY_MODULE else real(name, *a, **k))
            return self.probe()
        finally:
            importlib.import_module = real

    def test_an_instrument_that_does_not_declare_itself_is_unmeasured(self):
        status, why = self._with_instrument(self._Silent)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не объявляет себя мерой", why)

    def test_an_instrument_that_only_MENTIONS_the_criterion_is_unmeasured(self):
        """Якорь читается как НАЧАЛО строки, и спрашивается это у ПРОБЫ."""
        status, why = self._with_instrument(self._Mentioning)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не объявляет себя мерой", why)

    def test_an_unknown_verdict_is_unmeasured_not_satisfied(self):
        status, why = self._with_instrument(self._Strange)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не переносится", why)

    def test_an_exploding_instrument_is_unmeasured_with_the_exception_named(self):
        status, why = self._with_instrument(self._Exploding)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("RuntimeError", why)


class TestEveryInjectionDoorReachesTheOutcome(_Scene):
    """ВСЕ двери, а не одна: «половина инъекции» — та же бомба."""

    def test_the_clock_door_reaches_the_outcome(self):
        self.build(age_h=1.0, slo=7.0)
        status, why = self.probe(now=self.now + timedelta(hours=12))
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("протух", why)

    def test_the_data_dir_door_reaches_the_outcome(self):
        with TemporaryDirectory() as empty:
            status, why = self.probe(data_dir=empty)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("не прочитан", why)

    def test_the_repo_root_door_reaches_the_outcome(self):
        """Конституция берётся из ОБЪЯВЛЕННОГО корня, а не из прод-дерева."""
        with TemporaryDirectory() as bare:
            (Path(bare) / "architecture").mkdir()
            status, why = self.probe(repo_root=bare)
        self.assertEqual(status, ca.UNMEASURED, why)
        self.assertIn("срок годности", why)


class TestTheProbeWritesNothing(_Scene):
    """Проба ЧИТАЕТ. Любая правка по её итогам — money-path и решение владельца."""

    def test_no_file_in_the_scene_changes(self):
        before = {p: p.read_bytes()
                  for p in sorted(self.root.rglob("*")) if p.is_file()}
        self.probe()
        after = {p: p.read_bytes()
                 for p in sorted(self.root.rglob("*")) if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
