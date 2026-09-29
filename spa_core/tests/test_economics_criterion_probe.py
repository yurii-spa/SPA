"""ADR-507 — критерий §49 `Economics` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Перепись доминирования KEEP (`spa_core/monitoring/keep_dominance_census.py`, цикл
#702) меряет критерий владельца «Решения используют net expected return, а не raw
APY» с сентября: её артефакт пишется в такте и свеж. А сводный замер §49
(`scripts/cio_acceptance_rollup.py`) про этот критерий отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ в заметке
`architecture/manifest.json`, а сводку читает машина (ADR-504, ADR-506). Заказ
владельца G94 п. 1: перенести привязку в ПОЛЕ, но **по одной пробе**, и каждую со
своим контролем в обе стороны — иначе появится пять объявлений и ни одного
наблюдения.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `economics_net_return_dominates_keep` зелена на целом контуре и красна на
  КАЖДОМ порванном звене — с названным звеном;
* находка `dominated_by_keep` и находка `net_negative_missed_by_gate` — каждая сама
  по себе даёт `not_satisfied` (это положительные контроли: обе воспроизводят
  измеренную на живых журналах породу);
* протухший журнал ⇒ `unmeasured`, **НИКОГДА** не `not_satisfied`;
* пропавшая колонка порогов ADR-060 §3 ⇒ `unmeasured`, а не подставленное умолчание;
* прибор, не объявивший себя мерой `§49 Economics`, ⇒ `unmeasured`; и якорь читается
  как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный статус прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* объявление `s49_criterion` указывает В НАСЕЛЕНИЕ §49, прочитанное из самой карточки
  приказа, а не мимо него.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся и в
фикстуры, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается: журналы
пишутся в одноразовый каталог, живое `data/` не читается.
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import keep_dominance_census as kdc
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "economics_net_return_dominates_keep"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Economics"
#: Модуль, из которого `load_policy` берёт колонку порогов владельца. Порвать эту
#: дверь — единственный способ проверить, что проба НЕ подставляет своё умолчание.
POLICY_MODULE = "spa_core.allocator.rebalance_economics"


class _ProbeBase(unittest.TestCase):
    """Одноразовый каталог с журналами вердиктов. Часы — вход, якорь берётся здесь."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        self.today = self.now.date().isoformat()
        self.long_ago = (self.now - timedelta(days=9)).date().isoformat()

    # ── материал: записи журнала вердиктов ──────────────────────────────────
    #
    # Ни одного записанного `gain_pp`/`book_apy_pp` в фикстурах нет намеренно:
    # перепись — ВТОРОЙ производитель и считает эти числа сама. Подсунуть ей свои
    # значило бы проверить сверку, а не предмет.

    def _record(self, *, cycle_date: str, current: dict, target: dict, apy: dict,
                cost_usd: float, payback_gate: bool | None,
                verdict: str = "REBALANCE") -> dict:
        row = {
            "cycle_date": cycle_date,
            "generated_at": self.now.isoformat(),
            "schema": "shadow-hist-v2",
            "verdict": verdict,
            "capital_usd": 100_000.0,
            "current_positions": dict(current),
            "target_positions": dict(target),
            "apy_evidenced_pct": dict(apy),
            "cost_usd": cost_usd,
        }
        if payback_gate is not None:
            row["gates"] = {"payback_within_horizon": payback_gate}
        return row

    def _clean(self, cycle_date: str | None = None) -> dict:
        """Оптимум ВЫИГРЫВАЕТ у KEEP и отбивает издержки за горизонт: порода `ok`."""
        return self._record(
            cycle_date=cycle_date or self.today,
            current={"aave_v3": 50_000.0},
            target={"aave_v3": 50_000.0, "morpho_blue": 20_000.0},
            apy={"aave_v3": 4.0, "morpho_blue": 8.0},
            cost_usd=10.0, payback_gate=True)

    def _dominated_by_keep(self, cycle_date: str | None = None) -> dict:
        """Цель выводит $15 000 в кэш под 0 % ⇒ `gain_pp < 0` ДО издержек."""
        return self._record(
            cycle_date=cycle_date or self.today,
            current={"aave_v3": 95_000.0},
            target={"aave_v3": 80_000.0},
            apy={"aave_v3": 4.0},
            cost_usd=10.0, payback_gate=True)

    def _net_negative_missed(self, cycle_date: str | None = None) -> dict:
        """Прирост +0,01 пп, издержки $50 ⇒ чистый исход отрицателен, а гейт сказал `True`."""
        return self._record(
            cycle_date=cycle_date or self.today,
            current={"aave_v3": 95_000.0},
            target={"aave_v3": 94_000.0, "morpho_blue": 1_000.0},
            apy={"aave_v3": 4.0, "morpho_blue": 5.0},
            cost_usd=50.0, payback_gate=True)

    def _write(self, rows: list, *, book: str | None = None) -> Path:
        from spa_core.paper_trading.allocation_rationale import history_filename
        path = self.data_dir / history_filename(book)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def _probe(self, **kw):
        return ca._probe_economics_net_return_dominates_keep(
            None, now=kw.pop("now", self.now), data_dir=str(self.data_dir), **kw)


class TestFixturesReproduceTheMeasuredKinds(_ProbeBase):
    """Сначала — что фикстуры дают ИМЕННО те породы. Иначе контроль ниже тавтологичен."""

    def _kind(self, row: dict) -> str:
        policy = kdc.load_policy()
        self.assertTrue(policy["measured"], policy.get("reason"))
        scored = kdc.score_record(row, policy)
        self.assertTrue(scored.get("measured"), scored.get("reason"))
        return scored["kind"]

    def test_clean_record_is_kind_ok(self):
        self.assertEqual(self._kind(self._clean()), "ok")

    def test_dominated_record_is_kind_dominated_by_keep(self):
        self.assertEqual(self._kind(self._dominated_by_keep()), "dominated_by_keep")

    def test_missed_record_is_kind_net_negative_missed_by_gate(self):
        self.assertEqual(self._kind(self._net_negative_missed()),
                         "net_negative_missed_by_gate")

    def test_both_findings_are_material_not_dust(self):
        policy = kdc.load_policy()
        for row in (self._dominated_by_keep(), self._net_negative_missed()):
            scored = kdc.score_record(row, policy)
            self.assertTrue(scored["material"],
                            f"{scored['kind']}: причина ${scored['cause_usd']} "
                            f"ниже пыли ${scored['dust_usd']}")


class TestProbeGreenOnTheWholeContour(_ProbeBase):

    def test_intact_contour_is_satisfied(self):
        self._write([self._clean()])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("находок нет", detail)

    def test_three_books_all_clean_stay_satisfied(self):
        self._write([self._clean()])
        self._write([self._clean()], book="balanced")
        self._write([self._clean()], book="aggressive")
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("книг 3", detail)


class TestProbeRedOnEachBrokenLink(_ProbeBase):

    def test_dominated_by_keep_alone_is_not_satisfied(self):
        """Положительный контроль породы, измеренной на живой книге `conservative`."""
        self._write([self._clean(), self._dominated_by_keep()])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("dominated_by_keep", detail)

    def test_net_negative_missed_by_gate_alone_is_not_satisfied(self):
        """Вторая порода — отдельное звено: гейт окупаемости ПРОМАХНУЛСЯ."""
        self._write([self._clean(), self._net_negative_missed()])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("net_negative_missed_by_gate", detail)

    def test_finding_only_in_history_is_still_not_satisfied_and_says_so(self):
        """Находка не в свежайшем цикле — всё равно «нет», но зазор НАЗВАН."""
        self._write([self._dominated_by_keep(cycle_date=self.long_ago),
                     self._clean()])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("только в истории", detail)

    def test_a_gate_that_caught_the_negative_net_is_not_a_finding(self):
        """Гейт за работой находкой не является — иначе настоящая утонет в шуме."""
        row = self._net_negative_missed()
        row["gates"] = {"payback_within_horizon": False}
        self._write([self._clean(), row])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)


class TestProbeRefusesInsteadOfGuessing(_ProbeBase):

    def test_no_journal_at_all_is_unmeasured_not_satisfied(self):
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("журналов вердиктов не найдено", detail)

    def test_unparsable_journal_is_unmeasured(self):
        from spa_core.paper_trading.allocation_rationale import history_filename
        (self.data_dir / history_filename(None)).write_text(
            "{не json\n", encoding="utf-8")
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_stale_journal_is_unmeasured_never_not_satisfied(self):
        """Замороженный канон `data/` из git — не наблюдение о живой системе."""
        self._write([self._dominated_by_keep(cycle_date=self.long_ago)])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("журнал вердиктов протух", detail)

    def test_the_same_journal_is_judged_when_the_clock_says_it_is_fresh(self):
        """Тот же материал, сдвинуты ТОЛЬКО часы ⇒ вердикт есть. Часы — вход."""
        self._write([self._dominated_by_keep(cycle_date=self.long_ago)])
        moved = self.now - timedelta(days=9)
        verdict, detail = self._probe(now=moved)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_the_freshest_book_decides_the_age_not_the_stalest(self):
        """Одна книга отстала, другая пишется сегодня ⇒ система наблюдаема.

        Мутация `max`→`min` по датам книг делает вердикт «протух» при живом
        журнале — то есть гасит критерий тем, что одна из трёх книг молчит.
        """
        self._write([self._clean(cycle_date=self.long_ago)], book="balanced")
        self._write([self._dominated_by_keep()])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_journal_at_the_window_edge_is_still_judged(self):
        edge = (self.now - timedelta(days=int(ca.DECISION_JOURNAL_MAX_AGE_D))
                ).date().isoformat()
        self._write([self._clean(cycle_date=edge)])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_missing_policy_column_is_unmeasured_not_a_default(self):
        """§22 приказа: «Все значения должны быть config/policy. Не hardcode»."""
        self._write([self._clean()])
        self.assertEqual(self._probe()[0], ca.SATISFIED)
        hollow = types.ModuleType(POLICY_MODULE)  # без `TriggerParams`
        real = sys.modules.get(POLICY_MODULE)
        sys.modules[POLICY_MODULE] = hollow
        try:
            verdict, detail = self._probe()
        finally:
            if real is None:
                sys.modules.pop(POLICY_MODULE, None)
            else:
                sys.modules[POLICY_MODULE] = real
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("колонка порогов", detail)

    def test_missing_data_dir_is_unmeasured(self):
        verdict, detail = ca._probe_economics_net_return_dominates_keep(
            None, now=self.now, data_dir=str(self.data_dir / "нет-такого"))
        self.assertEqual(verdict, ca.UNMEASURED, detail)


class TestProbeReadsTheRealInstrumentNotACopy(_ProbeBase):

    def test_the_probe_goes_through_the_census_module(self):
        """Подменяем модуль переписи — вердикт обязан пойти за ним.

        Проба, несущая собственную копию логики переписи, этот контроль провалит:
        её вердикт не изменится. Так проверяется ПРОВОДКА, а не имя.
        """
        self._write([self._clean()])
        self.assertEqual(self._probe()[0], ca.SATISFIED)

        class _Sabotaged:
            CRITERION = kdc.CRITERION
            STATUS_OK = kdc.STATUS_OK
            STATUS_WARNING = kdc.STATUS_WARNING
            STATUS_CRITICAL = kdc.STATUS_CRITICAL

            @staticmethod
            def run_census(_dir, now=None):
                raise RuntimeError("подменённая перепись оборвалась")

        with patch.object(ca, "_keep_dominance_module", lambda: _Sabotaged):
            verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("подменённая перепись оборвалась", detail)

    def test_the_clock_is_handed_down_to_the_instrument(self):
        """Часы обязаны ДОХОДИТЬ до прибора, а не останавливаться у пробы.

        Сегодня `run_census` кладёт `now` только в `generated_at` доклада, которого
        проба не читает, — то есть по ВЕРДИКТУ мутация «звать перепись без часов»
        эквивалентна. Но это ровно «половина инъекции» из
        `.claude/rules/deployment.md`: у прибора остаётся своя дверь к стенным
        часам, и первая же его проверка свежести стала бы читать не тот сегодня,
        который подал тест. Поэтому проводка закрепляется ОТДЕЛЬНО от вердикта.
        """
        self._write([self._clean()])
        seen: list = []
        real = kdc.run_census

        def _spy(path, now=None, params=None):
            seen.append(now)
            return real(path, now=now, params=params)

        with patch.object(kdc, "run_census", _spy):
            self.assertEqual(self._probe()[0], ca.SATISFIED)
        self.assertEqual(seen, [self.now],
                         "проба не передала свои часы переписи — у прибора осталась "
                         "своя дверь к стенным часам")

    def test_an_instrument_that_measures_another_criterion_is_refused(self):
        self._write([self._clean()])
        with patch.object(kdc, "CRITERION", "§49 Persistence — другой критерий"):
            verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_is_read_as_a_prefix_not_as_a_substring(self):
        """ADR-333: «§49 Economics» где-то в середине заметки — не объявление."""
        self._write([self._clean()])
        with patch.object(kdc, "CRITERION",
                          "прочее, среди которого упомянут §49 Economics и другое"):
            verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)

    def test_an_unknown_instrument_status_is_unmeasured_not_satisfied(self):
        """Fail-CLOSED на статус, которого проба не знает: молчать о нём нельзя."""
        self._write([self._clean()])
        real = kdc.run_census

        def _odd(path, now=None, params=None):
            report = real(path, now=now, params=params)
            report["status"] = "ВСЁ-ХОРОШО"
            return report

        with patch.object(kdc, "run_census", _odd):
            verdict, detail = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не переносится в вердикт", detail)

    def test_a_record_carrying_the_word_ok_does_not_buy_a_green_verdict(self):
        """Вердикт берётся из статуса прибора, а не из текста записи."""
        row = self._dominated_by_keep()
        row["verdict"] = "OK"
        row["note"] = "satisfied · OK · находок нет"
        self._write([row])
        verdict, detail = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)


class TestDeclarationIsWiredIntoTheRollup(_ProbeBase):

    def test_registered_under_its_exact_name(self):
        self.assertIs(ca.PROBES.get(PROBE_NAME),
                      ca._probe_economics_net_return_dominates_keep)

    def test_declaration_validates(self):
        self.assertIsNone(ca.validate_spec(PROBE_NAME))

    def test_a_near_name_is_refused_not_matched_as_a_substring(self):
        self.assertIsNotNone(ca.validate_spec(PROBE_NAME[:-1]))
        self.assertIsNotNone(ca.validate_spec(PROBE_NAME + "_x"))

    def test_the_probe_declares_this_criterion_and_alone(self):
        self.assertEqual(ca.probes_by_s49_criterion().get(CRITERION), [PROBE_NAME])

    def test_data_dir_is_an_announced_input(self):
        """Иначе сводка печатала бы вердикт об ОДНОМ дереве как вердикт о другом."""
        self.assertIn("data_dir", ca.probe_tree_inputs(PROBE_NAME))

    def test_the_declared_criterion_is_in_the_s49_population_of_the_order(self):
        """Объявление МИМО населения приказа — находка, а не измеренный критерий."""
        import importlib.util
        root = Path(ca.REPO_ROOT)
        spec = importlib.util.spec_from_file_location(
            "_rollup_under_test", root / "scripts" / "cio_acceptance_rollup.py")
        rollup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rollup)
        card = (root / "nimbalyst-local" / "tracker"
                / "inbox-task-portfolio-cio-dynamic-capital-alloc.md")
        if not card.exists():
            self.fail(f"карточка приказа не найдена: {card} — население §49 НЕ ПРОЧИТАНО")
        names = rollup.parse_s49_criteria(card.read_text(encoding="utf-8"))
        self.assertIn(CRITERION, names)


if __name__ == "__main__":
    unittest.main()
