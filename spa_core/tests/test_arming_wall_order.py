"""Приёмка прибора «порядок снятия стен к взводу» (заказ #545, ADR-305).

Каждый тест — положительный контроль на свойство, на котором прибор такого рода
врёт молча. Набор писался так, чтобы мутация по координате в
`spa_core/monitoring/arming_wall_order.py` красила хотя бы один тест.

Свойства, закрытые отдельно и намеренно:

1. **освобождение считается СОВМЕСТНО, а не по краевым долям** — гейты отказывают
   пачками, и сумма «сколько раз отказал каждый» на вопрос «сколько дней
   освободится» не отвечает. Контроль ОТРИЦАТЕЛЬНЫЙ: сцена, где недельный гейт
   отказал на всех днях, а снятие его одного не освобождает НИЧЕГО;
2. **недельный потолок и потолок на ход считаются ПОРОЗНЬ** — карточка владельцу
   спрашивает про недельный, и «0 дн. от него одного» обязано быть измеримым, а
   не тонуть в объединённом наборе;
3. **потолок стены «запись» — НЕ обещание** (граница №3 ADR-300). Пара «нога вне
   книг дня» лежит внутри того, что расширение писателя способно затронуть, но
   существовала ли тогда живая ставка — не решается ничем; исход обязан быть
   третьим, а не «да»;
4. **пара «нога в книгах, провенанс не живой» расширением НЕ закрывается** — и
   это должно быть отделено от предыдущего класса, иначе прибор пообещал бы
   починку, которой нет;
5. **правило закрытия ветки — конъюнкция** («ни в одном из двух порядков»), а не
   дизъюнкция: ровно на этой подмене заказ #545 велел не закрывать ветку;
6. **fail-CLOSED на неизмеренных гейтах** — день без `gates` и без `reasons` не
   читается как «гейты прошли»;
7. **прибор не предсказывает вердикты** — ни `hit_rate`, ни `hit`/`miss` в
   артефакте нет вовсе (та же граница, что у ADR-300/305);
8. **правила берутся у НАСТОЯЩИХ функций** — `classify_pair` и
   `_evaluate_verdict` зовутся из своих модулей, своей копии правила нет.

FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром
`now=` в `measure`/`run` (константа `FIXED_NOW` ниже и второй литерал в
`test_clock_is_an_input` передаются туда же), поэтому ни одно утверждение набора
не зависит от календаря. Даты в фикстурах (`2026-08-01` и соседи) — ИМЕНА строк
журнала решений: по ним `load_history` сортирует и разрешает повтор дня,
свойством свежести они не являются.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — единственные часы прибора приходят параметром:
# FIXED_NOW (и второй литерал в ClockIsAnInput) передаются в measure(..., now=) и
# run(..., now=), поэтому ни одно утверждение набора не зависит от календаря.
# Даты в фикстурах — ИМЕНА строк журнала решений, а не свойство свежести.
from __future__ import annotations

import ast
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import arming_wall_order as awo

FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)

_MODULE = Path(awo.__file__)


def _line(date: str, *, gates: dict, current: dict, target: dict,
          apy: dict, unevidenced=None, cost: float = 1.0,
          verdict: str = "HOLD") -> dict:
    """Одна строка журнала решений схемы ``shadow-hist-v2``."""
    rec = {
        "cycle_date": date,
        "verdict": verdict,
        "gates": gates,
        "current_positions": current,
        "target_positions": target,
        "apy_evidenced_pct": apy,
        "cost_usd": cost,
    }
    if unevidenced is not None:
        rec["apy_unevidenced"] = list(unevidenced)
    if apy is None:
        rec.pop("apy_evidenced_pct")     # строка, молчащая о ставках (ADR-344)
    return rec


def _forward(date: str, **kw) -> dict:
    """Forward-день фикстуры: несёт ставки, но САМ ACT-пригодным не является.

    Гейты forward-дня к оценке отношения не имеют — оценщик читает у него только
    ``apy_evidenced_pct``. Но `measure` судит КАЖДЫЙ существенный день, и день со
    всеми пройденными гейтами освобождён уже без снятия бюджета: сцена тогда
    проверяла бы не заявленное. В живых данных таких дней ноль (замер 10.09:
    0 из 22), и фикстура воспроизводит именно эту форму.
    """
    return _line(date, gates=_all_pass(cooldown_ok=False), **kw)


def _all_pass(**overrides) -> dict:
    """Все гейты проходят, кроме перечисленных."""
    from spa_core.paper_trading.shadow_trigger_eval import _ALL_GATES

    g = {name: True for name in _ALL_GATES}
    g["has_legs"] = True
    g.update(overrides)
    return g


def _write(data_dir: Path, records) -> None:
    from spa_core.paper_trading.allocation_rationale import history_filename

    path = Path(data_dir) / history_filename(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                    encoding="utf-8")


class ReleaseIsJoint(unittest.TestCase):
    """Свойство 1 + 2 — и главный ОТРИЦАТЕЛЬНЫЙ контроль набора."""

    def test_week_gate_alone_releases_nothing_when_a_second_gate_also_refuses(self):
        """Недельный гейт отказал на ВСЕХ днях, а снятие его одного даёт НОЛЬ.

        Это ровно форма живого замера (22 дн. отказа недельного, 0 освобождённых)
        и одновременно контроль на подмену «краевая доля ⇒ освобождение».
        """
        with TemporaryDirectory() as td:
            d = Path(td)
            recs = [
                _line("2026-08-01",
                      gates=_all_pass(week_turnover_ok=False,
                                      move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
                _line("2026-08-02",
                      gates=_all_pass(week_turnover_ok=False,
                                      move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
            ]
            _write(d, recs)
            doc = awo.measure(d, now=FIXED_NOW)
            a = doc["orders"][0]

            self.assertEqual(a["released_by_week_budget_alone"], 0,
                             "недельный гейт снят, но второй гейт оборота ещё "
                             "отказывает — освобождать нечего")
            self.assertEqual(a["released_by_both_turnover_budgets"], 2)

    def test_week_gate_alone_DOES_release_when_it_is_the_only_refusal(self):
        """Положительный контроль к предыдущему: ноль не истинен по построению.

        Без этого теста «0 дн. от недельного потолка» был бы неотличим от
        прибора, который всегда печатает ноль.
        """
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            a = doc["orders"][0]
            self.assertEqual(a["released_by_week_budget_alone"], 1)


class TrivialHoldsStayOutOfTheDenominator(unittest.TestCase):
    """Пробел, найденный батареей мутаций: снятие фильтра `has_legs` выживало.

    День, где решать было нечего, — не отказ гейтов, и в знаменатель он не идёт:
    иначе тихий рынок надувал бы «сколько дней связывает бюджет» ровно теми
    днями, на которых бюджет не высказывался вовсе. Мерка та же, что у
    `arming_blockade`.
    """

    def test_a_day_without_material_legs_is_not_counted_as_material(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(has_legs=False),
                      current={"a": 50_000.0}, target={"a": 50_000.0},
                      apy={"a": 5.0}),
                _line("2026-08-02",
                      gates=_all_pass(week_turnover_ok=False,
                                      move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            self.assertEqual(doc["material_days"], 1,
                             "тривиальный HOLD не есть существенный день")
            self.assertIn("1 существенных", " ".join(doc["findings"]))

    def test_a_trivial_day_is_not_reported_as_released_either(self):
        """И освобождать его нечем: гейты на нём ничего не решали."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(has_legs=False),
                      current={"a": 50_000.0}, target={"a": 50_000.0},
                      apy={"a": 5.0}),
                _line("2026-08-02",
                      gates=_all_pass(week_turnover_ok=False,
                                      move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
            ])
            a = awo.measure(d, now=FIXED_NOW)["orders"][0]
            self.assertNotIn("2026-08-01", a["released_dates"])


class ExpansionCeilingIsNotAPromise(unittest.TestCase):
    """Свойства 3 и 4 — потолок расширения и то, что вне него."""

    def test_leg_outside_the_books_is_UNDETERMINED_not_yes(self):
        """Нога вне книг forward-дня ⇒ внутри потолка, но исход ТРЕТИЙ."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={}),
                # forward-день: ноги `a`/`b` вне книг дня вовсе
                _forward("2026-08-02",
                         current={"z": 10.0}, target={"z": 10.0},
                         apy={"z": 1.0}),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            prof = doc["orders"][0]["profiles"][0]

            self.assertFalse(prof["scorable"])
            self.assertGreater(prof["unpriced_pairs_within_expansion_ceiling"], 0)
            self.assertEqual(prof["expansion_effect"],
                             "UNDETERMINED_WITHIN_CEILING",
                             "внутри потолка ≠ «расширение откроет»")
            self.assertIn("НЕ ОПРЕДЕЛЕНО", prof["expansion_effect_note"])

    def test_leg_in_books_with_dead_provenance_is_BEYOND_expansion(self):
        """Нога В КНИГАХ и провенанс не живой ⇒ записывать было нечего."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={}, unevidenced=["a", "b"]),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            prof = doc["orders"][0]["profiles"][0]

            self.assertEqual(prof["unpriced_pairs_within_expansion_ceiling"], 0)
            self.assertGreater(prof["unpriced_pairs_beyond_expansion"], 0)
            self.assertEqual(prof["expansion_effect"], "BEYOND_EXPANSION")
            self.assertTrue(
                any("НЕ закрывает" in f for f in doc["findings"]),
                "прибор обязан СКАЗАТЬ, что расширение этих пар не закрывает")

    def test_the_two_classes_are_counted_separately(self):
        """Слипание классов и было бы обещанием починки, которой нет."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={}),
                # `a` в книгах и неэвиденсна (вне потолка), `b` вне книг (внутри)
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"a": 50_000.0},
                         apy={}, unevidenced=["a"]),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            prof = doc["orders"][0]["profiles"][0]
            self.assertEqual(prof["unpriced_pairs_within_expansion_ceiling"], 1)
            self.assertEqual(prof["unpriced_pairs_beyond_expansion"], 1)


class ASilentForwardRowIsNotAnUnpricedDay(unittest.TestCase):
    """ADR-344 (инвариант #17): строка БЕЗ поля ставок не говорит о ногах ничего.

    Прежнее чтение `frec.get("apy_evidenced_pct") or {}` объявляло НЕОЦЕНЁННЫМИ все
    ноги такого дня — молчание записи шло уликой против каждой. Пустая карта при
    этом остаётся ответом писателя и по-прежнему даёт неоценённые пары.
    """

    def _measure(self, forward_apy):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0}, apy={}),
                _forward("2026-08-02", current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy=forward_apy),
            ])
            return awo.measure(d, now=FIXED_NOW)["orders"][0]["profiles"][0]

    def test_a_silent_row_is_counted_apart_and_yields_no_pairs(self):
        prof = self._measure(None)
        self.assertEqual(prof["forward_rows_without_evidenced_field"], 1)
        self.assertEqual(prof["unpriced_pairs_total"], 0,
                         "молчание строки записано неоценёнными парами")

    def test_an_empty_map_still_yields_unpriced_pairs(self):
        prof = self._measure({})
        self.assertEqual(prof["forward_rows_without_evidenced_field"], 0)
        self.assertGreater(prof["unpriced_pairs_total"], 0)

    def test_an_evaluator_without_the_unpriced_field_reports_null_not_empty(self):
        """`None` ≠ `[]`: «оценщик не сказал» и «неоценённых нет» — разные ответы."""
        row = {"verdict": "HOLD", "forward_days_checked": 0}
        self.assertIsNone(awo.observed(row, "unpriced_protocols", kind=(list, tuple)))
        self.assertEqual(awo.observed({"unpriced_protocols": []},
                                      "unpriced_protocols", kind=(list, tuple)), [])


class BranchClosureRule(unittest.TestCase):
    """Свойство 5 — ветка закрывается только конъюнкцией."""

    def test_branch_is_OPEN_when_the_record_hole_binds_in_order_A(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={}, unevidenced=["a", "b"]),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            self.assertEqual(doc["branch_verdict"], awo.BRANCH_OPEN)
            self.assertIn("budget_then_record", doc["expansion_adds_in_orders"])
            self.assertNotIn("record_then_budget",
                             doc["expansion_adds_in_orders"],
                             "во втором порядке расширение не добавляет ничего")

    def test_branch_CLOSES_when_every_released_day_is_fully_priced(self):
        """Положительный контроль: BRANCH_CLOSED достижим, а не мёртвая ветка."""
        with TemporaryDirectory() as td:
            d = Path(td)
            horizon = 2
            recs = [_line("2026-08-01",
                          gates=_all_pass(week_turnover_ok=False,
                                          move_turnover_ok=False),
                          current={"a": 50_000.0}, target={"b": 50_000.0},
                          apy={"a": 5.0, "b": 9.0})]
            for i in (2, 3):
                recs.append(_forward(f"2026-08-0{i}",
                                     current={"a": 50_000.0},
                                     target={"b": 50_000.0},
                                     apy={"a": 5.0, "b": 9.0}))
            _write(d, recs)
            doc = awo.measure(d, now=FIXED_NOW, horizon_days=horizon)
            self.assertEqual(doc["orders"][0]["record_blocked_days"], 0)
            self.assertEqual(doc["orders"][0]["partially_priced_days"], 0)
            self.assertEqual(doc["branch_verdict"], awo.BRANCH_CLOSED)
            self.assertEqual(doc["expansion_adds_in_orders"], [])


class FailClosed(unittest.TestCase):
    """Свойство 6 — молчание строки не читается как согласие гейтов."""

    def test_a_day_without_gates_and_without_reasons_is_UNMEASURED(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                {"cycle_date": "2026-08-01", "verdict": "HOLD",
                 "current_positions": {"a": 50_000.0},
                 "target_positions": {"b": 50_000.0},
                 "apy_evidenced_pct": {"a": 5.0, "b": 9.0}},
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            self.assertEqual(doc["status"], awo.STATUS_UNMEASURED)
            self.assertEqual(doc["branch_verdict"], awo.BRANCH_UNMEASURED)
            self.assertNotIn("orders", doc,
                             "по неполной переписи порядок стен не судится")

    def test_empty_history_is_UNMEASURED_not_a_closed_branch(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [])
            doc = awo.measure(d, now=FIXED_NOW)
            self.assertEqual(doc["branch_verdict"], awo.BRANCH_UNMEASURED)
            self.assertNotEqual(doc["branch_verdict"], awo.BRANCH_CLOSED)


class DoesNotPredictVerdicts(unittest.TestCase):
    """Свойство 7 — граница ADR-300/305 соблюдена."""

    def test_no_hit_rate_and_no_outcome_anywhere_in_the_artifact(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={"a": 5.0, "b": 9.0}),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            blob = json.dumps(doc, ensure_ascii=False)
            for forbidden in ('"hit_rate"', '"outcome"', '"hit"', '"miss"'):
                self.assertNotIn(forbidden, blob,
                                 f"прибор не смеет предсказывать вердикты ({forbidden})")

    def test_adapter_status_is_never_read(self):
        """Ловушка ADR-302: провенанс принадлежит значению, а не дороге.

        Проверка ПОВЕДЕНЧЕСКАЯ, а не по подстроке: имя файла законно стои́т в
        прозе `what_it_does_not_prove` («прибор его не читает вовсе»), поэтому
        текстовый запрет краснел бы на честном объяснении границы. Сцена вместо
        этого подкладывает файл с содержимым, которое ЛЮБОЕ чтение изменило бы,
        и требует побайтового совпадения вердикта.
        """
        def build(with_trap: bool) -> str:
            with TemporaryDirectory() as td:
                d = Path(td)
                _write(d, [
                    _line("2026-08-01",
                          gates=_all_pass(week_turnover_ok=False,
                                          move_turnover_ok=False),
                          current={"a": 50_000.0}, target={"b": 50_000.0},
                          apy={}),
                    _forward("2026-08-02",
                             current={"a": 50_000.0}, target={"b": 50_000.0},
                             apy={}, unevidenced=["a", "b"]),
                ])
                if with_trap:
                    (d / "adapter_status.json").write_text(
                        json.dumps({"adapters": {
                            "a": {"live_apy": 99.0, "apy": 99.0},
                            "b": {"live_apy": 99.0, "apy": 99.0}}}),
                        encoding="utf-8")
                return json.dumps(awo.measure(d, now=FIXED_NOW),
                                  ensure_ascii=False, sort_keys=True)

        self.assertEqual(build(False), build(True),
                         "вердикт изменился от подложенного adapter_status.json "
                         "— значит файл читается, и ловушка ADR-302 не соблюдена")


class RulesComeFromTheRealFunctions(unittest.TestCase):
    """Свойство 8 — проверяется ФОРМОЙ вызова, а не подстрокой в тексте.

    Тест на подстроку пережил бы любое расплетение: имя осталось бы в импорте,
    а вызов ушёл бы к своей копии правила.
    """

    def _calls_in(self, func_name: str):
        tree = ast.parse(_MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                return {n.func.id for n in ast.walk(node)
                        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.fail(f"функция {func_name} не найдена")

    def test_pricing_profile_calls_the_real_classifier_and_evaluator(self):
        calls = self._calls_in("pricing_profile")
        self.assertIn("classify_pair", calls,
                      "класс пары обязан браться у настоящего classify_pair")
        self.assertIn("_evaluate_verdict", calls,
                      "оценимость обязана браться у настоящего оценщика")

    def test_material_days_uses_the_real_gate_state(self):
        self.assertIn("gate_state", self._calls_in("material_days"))

    def test_the_real_classifier_is_imported_from_its_owner(self):
        src = _MODULE.read_text(encoding="utf-8")
        self.assertIn(
            "from spa_core.monitoring.unevidenced_leg_causes import", src)
        self.assertIn(
            "from spa_core.paper_trading.shadow_trigger_eval import", src)


class ClockIsAnInput(unittest.TestCase):
    """Часы — вход, а не окружение (правило `.claude/rules/deployment.md`)."""

    def test_generated_at_is_exactly_what_the_caller_passed(self):
        other = datetime(2027, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [])
            self.assertEqual(awo.measure(d, now=FIXED_NOW)["generated_at"],
                             FIXED_NOW.isoformat())
            self.assertEqual(awo.measure(d, now=other)["generated_at"],
                             other.isoformat())


class RunShape(unittest.TestCase):
    """Форма, которую ждут ступень переписей и шаг 0-офис."""

    def test_run_writes_the_artifact_and_carries_counts(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            _write(root / "data", [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={}, unevidenced=["a", "b"]),
            ])
            doc = awo.run(root=str(root), now=FIXED_NOW)
            out = root / "data" / awo.OUTPUT_FILENAME
            self.assertTrue(out.exists())
            on_disk = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["version"], awo.VERSION)
            self.assertEqual(doc["overall"], doc["status"])
            self.assertIn("counts", doc)
            self.assertGreater(doc["counts"]["critical"], 0)

    def test_unmeasured_is_counted_apart_from_zero(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            _write(root / "data", [])
            doc = awo.run(root=str(root), now=FIXED_NOW, write=False)
            self.assertEqual(doc["status"], awo.STATUS_UNMEASURED)
            self.assertGreaterEqual(doc["counts"]["unchecked"], 1)

    def test_format_report_names_both_orders(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0},
                      apy={"a": 5.0, "b": 9.0}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={"a": 5.0, "b": 9.0}),
            ])
            lines = awo.format_report(awo.measure(d, now=FIXED_NOW))
            joined = "\n".join(lines)
            self.assertIn("A бюджет→запись", joined)
            self.assertIn("B запись→бюджет", joined)
            self.assertIn("ADVISORY", joined)


class NetSignSensitivityIsNamedAsAnAssumption(unittest.TestCase):
    """Граница №3 прибора: короткий оценённый горизонт смещает знак."""

    def test_partial_day_carries_both_the_scored_net_and_the_full_rate_bound(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            recs = [_line("2026-08-01",
                          gates=_all_pass(week_turnover_ok=False,
                                          move_turnover_ok=False),
                          current={"a": 50_000.0}, target={"b": 50_000.0},
                          apy={"a": 5.0, "b": 9.0}, cost=100.0)]
            recs.append(_forward("2026-08-02",
                                 current={"a": 50_000.0},
                                 target={"b": 50_000.0},
                                 apy={"a": 5.0, "b": 9.0}))
            recs.append(_forward("2026-08-03",
                                 current={"a": 50_000.0},
                                 target={"b": 50_000.0},
                                 apy={}, unevidenced=["a", "b"]))
            _write(d, recs)
            doc = awo.measure(d, now=FIXED_NOW, horizon_days=7)
            prof = doc["orders"][0]["profiles"][0]
            self.assertTrue(prof["scorable"])
            self.assertIn("net_usd_as_scored", prof)
            self.assertIn("net_usd_if_full_horizon_at_same_rate", prof)
            self.assertIn("ДОПУЩЕНИ", " ".join(doc["what_it_does_not_prove"]))

    def test_unpriceable_day_carries_NO_net_at_all(self):
        """Знака нет ⇒ его не печатают. Ноль тут читался бы как замер."""
        with TemporaryDirectory() as td:
            d = Path(td)
            _write(d, [
                _line("2026-08-01", gates=_all_pass(week_turnover_ok=False,
                                                    move_turnover_ok=False),
                      current={"a": 50_000.0}, target={"b": 50_000.0}, apy={}),
                _forward("2026-08-02",
                         current={"a": 50_000.0}, target={"b": 50_000.0},
                         apy={}, unevidenced=["a", "b"]),
            ])
            doc = awo.measure(d, now=FIXED_NOW)
            prof = doc["orders"][0]["profiles"][0]
            self.assertFalse(prof["scorable"])
            self.assertNotIn("net_usd_as_scored", prof)
            self.assertNotIn("net_usd_if_full_horizon_at_same_rate", prof)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
