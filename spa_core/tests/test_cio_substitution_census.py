"""Сцены к :mod:`spa_core.monitoring.cio_substitution_census`.

Каждая сцена нарушает ТОЛЬКО СВОЁ ограничение (урок приёмки #519: отказ соседнего
порога записывается измеряемому в актив, и ложный вердикт тогда не краснеет).
Сцены-двойники идут парами «должно поймать / не должно поймать» — у каждого
различения замера ДВА направления ошибки, и закрывать одно, не закрывая другое,
значит повторить дефект, ради которого замер написан.

# FROZEN-DATE-OK: injected-clock — единственная отметка времени в отчёте приходит
# параметром ``now=`` функции :func:`run`; литеральных дат в фикстурах нет.
"""
from __future__ import annotations

import ast
import json
import unittest
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import cio_substitution_census as M

FakeStage = namedtuple("FakeStage", "key module product")
FIXED_NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)   # только источник строки


def fn_of(src: str) -> ast.AST:
    return ast.parse(src).body[0]


def forms(src: str) -> list[str]:
    return [f for f, _, _ in M.absence_sites(fn_of(src))]


def subs(src: str) -> list[str]:
    """Формы, у которых значение признано ПОДСТАНОВКОЙ."""
    tree = ast.parse(src)
    consts = M.module_constants(tree)
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for form, value, _ in M.absence_sites(fn):
                if M.plausible_value(value, consts)[0]:
                    out.append(form)
    return out


# ─────────────────── ловушка 1: метка отсутствия ≠ подстановка ───────────────

class AbsenceMarkerIsNotSubstitution(unittest.TestCase):
    """`None`/`0`/пустое заставляют вызывающего проверить — это НЕ подстановка."""

    def test_none_is_not_a_substitution(self):
        self.assertEqual([], subs("def f(x):\n"
                                  "    if x is None:\n        return None\n"
                                  "    return x\n"))

    def test_zero_is_not_a_substitution(self):
        self.assertEqual([], subs("def f(x):\n"
                                  "    if x is None:\n        return 0\n"
                                  "    return x\n"))

    def test_empty_container_is_not_a_substitution(self):
        self.assertEqual([], subs("def f(x):\n"
                                  "    if not x:\n        return {}\n"
                                  "    return x\n"))

    def test_false_is_not_a_substitution(self):
        self.assertEqual([], subs("def f(x):\n"
                                  "    if not x:\n        return False\n"
                                  "    return x\n"))

    def test_empty_string_is_not_a_substitution(self):
        self.assertEqual([], subs("def f(x):\n"
                                  "    if not x:\n        return ''\n"
                                  "    return x\n"))

    # ── обратное направление: правдоподобное значение ПОЙМАНО ────────────────

    def test_a_plausible_number_is_a_substitution(self):
        self.assertEqual([M.FORM_IS_NONE], subs("def f(x):\n"
                                                "    if x is None:\n        return 4.2\n"
                                                "    return x\n"))

    def test_a_container_of_numbers_is_a_substitution(self):
        self.assertEqual([M.FORM_NOT], subs("def f(x):\n"
                                            "    if not x:\n        return {'a': 22000.0}\n"
                                            "    return x\n"))

    def test_a_class_constant_is_resolved(self):
        """`self.FALLBACK_APY` — самая частая форма подстановки у адаптеров."""
        self.assertEqual([M.FORM_EXCEPT], subs(
            "class A:\n"
            "    FALLBACK_APY = 0.04\n"
            "    def safe(self):\n"
            "        try:\n            return self.fetch()\n"
            "        except Exception:\n            return self.FALLBACK_APY\n"))

    def test_a_class_constant_that_is_zero_is_not(self):
        self.assertEqual([], subs(
            "class A:\n"
            "    FALLBACK_APY = 0\n"
            "    def safe(self):\n"
            "        try:\n            return self.fetch()\n"
            "        except Exception:\n            return self.FALLBACK_APY\n"))


class OptionalParameterDefaultIsNotSubstitution(unittest.TestCase):
    """Вход не спрашивали ⇒ и не потеряли. До этого исключения 4 из 10
    достижимых «находок» были ровно им."""

    def test_none_defaulted_parameter_is_skipped(self):
        self.assertEqual([], forms(
            "def f(timeout=None):\n    return timeout if timeout is not None else 30\n"))

    def test_kwonly_none_defaulted_parameter_is_skipped(self):
        self.assertEqual([], forms(
            "def f(*, timeout=None):\n"
            "    return timeout if timeout is not None else 30\n"))

    def test_or_form_on_a_defaulted_parameter_is_skipped(self):
        self.assertEqual([], forms("def f(now=None):\n    return now or 30\n"))

    # ── обратное направление: НЕ параметр — ловится ──────────────────────────

    def test_the_same_shape_on_a_local_is_a_substitution(self):
        self.assertEqual([M.FORM_IFEXP_NOT_NONE], forms(
            "def f():\n    v = fetch()\n"
            "    return v if v is not None else 30\n"))

    def test_a_parameter_without_a_none_default_is_not_skipped(self):
        self.assertEqual([M.FORM_IFEXP_NOT_NONE], forms(
            "def f(v):\n    return v if v is not None else 30\n"))

    def test_a_parameter_with_a_non_none_default_is_not_skipped(self):
        """Исключается ТОЛЬКО `None`-часовой: он и означает «аргумент не
        передан». Дефолт `30` такого смысла не несёт, и объявить пропуск по
        одному лишь НАЛИЧИЮ дефолта значило бы ослепить замер на всех
        параметрах разом."""
        self.assertEqual([M.FORM_IFEXP_NOT_NONE], forms(
            "def f(v=30):\n    return v if v is not None else 40\n"))

    def test_a_kwonly_parameter_with_a_non_none_default_is_not_skipped(self):
        self.assertEqual([M.FORM_IFEXP_NOT_NONE], forms(
            "def f(*, v=30):\n    return v if v is not None else 40\n"))


# ─────────────── ловушка 2: ветка НАЛИЧИЯ исключена ЯВНО ────────────────────

class PresenceBranchIsNotAnAbsenceBranch(unittest.TestCase):
    """Порог-лестница — не отсутствие входа. Первая редакция считала её и дала
    609 «подстановок» там, где их 211."""

    def test_threshold_ladder_is_not_counted(self):
        self.assertEqual([], forms(
            "def f(x):\n"
            "    if x > 0.5:\n        return 22.0\n"
            "    if x > 0.2:\n        return 15.0\n"
            "    return 8.0\n"))

    def test_membership_test_is_not_counted(self):
        self.assertEqual([], forms(
            "def f(x, s):\n    if x in s:\n        return 4.2\n    return 0.0\n"))

    def test_the_else_of_a_threshold_is_not_counted(self):
        self.assertEqual([], forms(
            "def f(x):\n    return 22.0 if x > 0.5 else 15.0\n"))

    def test_in_a_truthy_ifexp_the_absence_arm_is_the_else_not_the_body(self):
        """`22.0 if v else v` — при наличии `v` возвращается 22.0, при
        отсутствии сам `v`, то есть МЕТКА отсутствия. Перепутать руки значит
        объявить подстановкой ветку НАЛИЧИЯ — ровно ошибка, на которой прибор
        #518 дал ложную находку в `golive_preflight`."""
        self.assertEqual([], subs("def f(v):\n    return 22.0 if v else v\n"))
        self.assertEqual([M.FORM_IFEXP_TRUTHY],
                         subs("def f(v):\n    return v if v else 22.0\n"))

    def test_a_negated_comparison_is_validation_not_absence(self):
        """`if not (a > b)` — проверка ПРАВИЛА, а не отсутствия входа.
        Разрешить тесту быть сравнением значит впустить в предмет весь
        валидационный код дерева."""
        self.assertEqual([], forms(
            "def f(a, b):\n    if not (a > b):\n        return 4.2\n    return a\n"))
        self.assertEqual([M.FORM_NOT], forms(
            "def f(a):\n    if not a:\n        return 4.2\n    return a\n"))

    # ── обратное направление: каждая объявленная форма отсутствия ловится ────

    def test_except_branch_is_counted(self):
        self.assertIn(M.FORM_EXCEPT, forms(
            "def f():\n    try:\n        return fetch()\n"
            "    except Exception:\n        return 4.2\n"))

    def test_not_value_branch_is_counted(self):
        self.assertIn(M.FORM_NOT, forms(
            "def f():\n    v = fetch()\n    if not v:\n        return 4.2\n    return v\n"))

    def test_is_none_branch_is_counted(self):
        self.assertIn(M.FORM_IS_NONE, forms(
            "def f():\n    v = fetch()\n    if v is None:\n        return 4.2\n    return v\n"))

    def test_else_of_is_not_none_is_counted(self):
        self.assertIn(M.FORM_ELSE_NOT_NONE, forms(
            "def f():\n    v = fetch()\n    if v is not None:\n        return v\n"
            "    else:\n        return 4.2\n"))

    def test_or_form_is_counted(self):
        self.assertIn(M.FORM_OR, forms("def f():\n    return fetch() or 4.2\n"))

    def test_fallthrough_past_every_attempt_is_counted(self):
        """«Ни одна попытка не сработала — вот вам число»: форма
        `yield_aggregator_v2`, которую ни одна ветвевая проверка не видит."""
        self.assertIn(M.FORM_FALLTHROUGH, forms(
            "def f(sources):\n"
            "    for s in sources:\n"
            "        v = s()\n"
            "        if v:\n            return v\n"
            "    return 0.04\n"))

    def test_a_function_without_a_loop_has_no_fallthrough(self):
        self.assertNotIn(M.FORM_FALLTHROUGH, forms(
            "def f():\n    x = compute()\n    return 0.04\n"))


# ─────────── обратная сторона: КУДА подстановка двигает решение ──────────────

class DirectionSeparatesTheClassFromItsOpposite(unittest.TestCase):

    def test_cost_axis_moves_toward_refusal(self):
        self.assertEqual(M.DIR_REFUSAL, M.direction_of("_move_cost_usd")[0])

    def test_gas_axis_moves_toward_refusal(self):
        self.assertEqual(M.DIR_REFUSAL, M.direction_of("estimate_gas_price")[0])

    def test_apy_axis_moves_toward_entry(self):
        self.assertEqual(M.DIR_ENTRY, M.direction_of("fallback_apy")[0])

    def test_tvl_axis_moves_toward_entry(self):
        self.assertEqual(M.DIR_ENTRY, M.direction_of("FALLBACK_TVL_USD")[0])

    def test_an_unknown_axis_is_the_third_outcome_not_safety(self):
        verdict, why = M.direction_of("zzz_quux")
        self.assertEqual(M.DIR_UNCHECKED, verdict)
        self.assertIn("не измерено", why)

    def test_two_axes_at_once_is_also_the_third_outcome(self):
        self.assertEqual(M.DIR_UNCHECKED, M.direction_of("apy_cost_ratio")[0])

    def test_the_axis_is_a_word_not_a_substring(self):
        """`portfolio_rebalancer` НЕ несёт оси `balance`: первая редакция мерила
        подстрокой, и код возврата `main()` уехал в находки."""
        self.assertEqual(M.DIR_UNCHECKED, M.direction_of("portfolio_rebalancer")[0])
        self.assertEqual(M.DIR_ENTRY, M.direction_of("get_supply_balance")[0])

    def test_a_qualified_name_is_read_by_its_qualifier_not_its_tail(self):
        """ЗАМЕР приёмки #521: `name.rsplit(".", 1)[0]` не держал ни один тест.

        У КВАЛИФИЦИРОВАННОГО имени ось берётся с квалификатора, а хвост
        отбрасывается. Ось от этого может не опознаться — и тогда исход
        ТРЕТИЙ, сказанный вслух, а не тихий вердикт: `cfg.apy` даёт UNCHECKED,
        а не «двигает ко входу». Поведение закреплено СЦЕНОЙ, чтобы быть
        решением, а не остатком: мутация «читать имя целиком» выживала.
        """
        self.assertEqual({"cfg"}, M._tokens("cfg.apy"))
        self.assertEqual(M.DIR_UNCHECKED, M.direction_of("cfg.apy")[0])

    def test_an_unqualified_name_keeps_every_word(self):
        """Обратное направление той же пары: без точки не теряется ничего."""
        self.assertEqual({"cfg", "apy"}, M._tokens("cfg_apy"))
        self.assertEqual(M.DIR_ENTRY, M.direction_of("cfg_apy")[0])

    def test_camel_case_is_split_into_words(self):
        self.assertEqual(M.DIR_ENTRY, M.direction_of("fallbackApy")[0])


# ─────────────────── различимость: помечена или неотличима ───────────────────

class LabelDecidesWhetherTheConsumerCanRefuse(unittest.TestCase):

    def test_a_labelled_substitution_is_recognised(self):
        node = ast.parse("{'apy': 4.2, 'source': 'fallback'}", mode="eval").body
        self.assertIn("source", M._label_keys_in(node))

    def test_an_unlabelled_substitution_carries_no_label(self):
        node = ast.parse("{'apy': 4.2}", mode="eval").body
        self.assertEqual([], M._label_keys_in(node))

    def test_tvl_source_counts_as_a_label(self):
        node = ast.parse("{'tvl_usd': 5e7, 'tvl_source': 'static'}", mode="eval").body
        self.assertIn("tvl_source", M._label_keys_in(node))


# ──────────── ловушка 3: провенанс, и КАНАЛОВ ДВА, а не один ────────────────

class ReachabilityMeasuresTwoChannels(unittest.TestCase):
    """Замер только импортом ответил бы «до решения не доходит ничего» — верный
    ответ не на тот вопрос. Сцена строит дерево, где подстановка достижима
    ИСКЛЮЧИТЕЛЬНО через артефакт."""

    def _tree(self, tmp: Path) -> tuple[Path, tuple]:
        (tmp / "spa_core" / "decide").mkdir(parents=True)
        (tmp / "spa_core" / "feed").mkdir(parents=True)
        (tmp / "spa_core" / "__init__.py").write_text("")
        (tmp / "spa_core" / "decide" / "__init__.py").write_text("")
        (tmp / "spa_core" / "feed" / "__init__.py").write_text("")
        (tmp / "spa_core" / "decide" / "book.py").write_text(
            "def rebalance():\n"
            "    raw = open('data/feed_snapshot.json').read()\n"
            "    return raw\n", encoding="utf-8")
        (tmp / "spa_core" / "feed" / "poller.py").write_text(
            "def run_feed():\n"
            "    v = fetch()\n"
            "    if v is None:\n"
            "        return {'apy': 4.5}\n"
            "    return v\n", encoding="utf-8")
        stages = (
            FakeStage("portfolio_state", "spa_core/decide/book.py", "book.json"),
            FakeStage("portfolio_optimizer", "spa_core/decide/book.py", "book.json"),
            FakeStage("target_allocation", "spa_core/decide/book.py", "book.json"),
            FakeStage("rebalance_evaluator", "spa_core/decide/book.py", "book.json"),
            FakeStage("risk_gate", "spa_core/decide/book.py", "book.json"),
            FakeStage("opportunity_data", "spa_core/feed/poller.py",
                      "feed_snapshot.json"),
        )
        return tmp, stages

    def test_the_artifact_channel_finds_what_imports_alone_cannot(self):
        with TemporaryDirectory() as td:
            root, stages = self._tree(Path(td))
            meas = M.measure(root, stages)
            self.assertEqual("MEASURED", meas["status"])
            reached = {r["file"] for r in meas["reachable"]["substitutions"]}
            self.assertIn("spa_core/feed/poller.py", reached)
            # и это НЕ канал импорта: книга поллер не импортирует
            row = next(r for r in meas["reachable"]["substitutions"]
                       if r["file"] == "spa_core/feed/poller.py")
            self.assertEqual(["артефакт"], row["channels"])

    def test_without_the_artifact_edge_nothing_is_reachable(self):
        """Положительный контроль на сам канал: уберём чтение продукта — и
        подстановка перестаёт быть достижимой."""
        with TemporaryDirectory() as td:
            root, stages = self._tree(Path(td))
            (root / "spa_core" / "decide" / "book.py").write_text(
                "def rebalance():\n    return 1\n", encoding="utf-8")
            meas = M.measure(root, stages)
            reached = {r["file"] for r in meas["reachable"]["substitutions"]}
            self.assertNotIn("spa_core/feed/poller.py", reached)

    def test_the_import_channel_still_works(self):
        with TemporaryDirectory() as td:
            root, stages = self._tree(Path(td))
            (root / "spa_core" / "decide" / "book.py").write_text(
                "from spa_core.feed.poller import run_feed\n"
                "def rebalance():\n    return run_feed()\n", encoding="utf-8")
            meas = M.measure(root, stages)
            row = next(r for r in meas["reachable"]["substitutions"]
                       if r["file"] == "spa_core/feed/poller.py")
            self.assertEqual(["импорт"], row["channels"])

    def test_a_substitution_outside_the_closure_is_not_reachable(self):
        with TemporaryDirectory() as td:
            root, stages = self._tree(Path(td))
            (root / "spa_core" / "feed" / "unrelated.py").write_text(
                "def g():\n    v = fetch()\n    if v is None:\n"
                "        return 9.9\n    return v\n", encoding="utf-8")
            meas = M.measure(root, stages)
            reached = {r["file"] for r in meas["reachable"]["substitutions"]}
            self.assertIn("spa_core/feed/poller.py", reached)
            self.assertNotIn("spa_core/feed/unrelated.py", reached)
            # но перепись видит ОБЕ: население шире достижимости
            self.assertGreaterEqual(meas["census"]["substitutions"], 2)


# ─────────── поле-спутник, ПЕРЕЖИВШЕЕ подстановку своей величины ─────────────

class StaleCompanionSurvivesTheSubstitution(unittest.TestCase):

    BASE = ("def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "{extra}"
            "    doc = {{'positions': positions,\n"
            "           'expected_apy': result.expected_apy}}\n"
            "    return doc\n")

    def test_a_companion_of_the_rejected_value_is_found(self):
        rows = M.stale_companions(ast.parse(self.BASE.format(extra="")))
        self.assertEqual(["expected_apy"], [r["stale_field"] for r in rows])
        self.assertEqual(["result"], [r["reads"] for r in rows])

    def test_a_companion_that_is_replaced_too_is_not_a_finding(self):
        rows = M.stale_companions(ast.parse(
            self.BASE.format(extra="        result = describe(positions)\n")))
        self.assertEqual([], rows)

    def test_a_parameter_is_not_a_stale_companion(self):
        """Капитал на обеих ветвях один ПО ПОСТРОЕНИЮ."""
        rows = M.stale_companions(ast.parse(
            "def w(capital):\n"
            "    positions = to_usd(capital)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return {'positions': positions, 'capital': capital}\n"))
        self.assertEqual([], rows)

    def test_a_name_the_substitution_itself_reads_is_not_stale(self):
        """Имя, читаемое обеими ветвями, входом обеих и является."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    key = pick()\n"
            "    apy = observe(key)\n"
            "    if apy is None:\n"
            "        apy = guess(key)\n"
            "    return {'apy': apy, 'key': key}\n"))
        self.assertEqual([], rows)

    def test_a_dict_written_before_the_branch_is_not_a_finding(self):
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    doc = {'positions': positions, 'expected_apy': result.expected_apy}\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return doc\n"))
        self.assertEqual([], rows)

    def test_the_source_is_read_through_a_wrapping_call(self):
        """`round(result.expected_apy, 4)` читает `result` — первая редакция
        брала «корневое имя» и получала `round`."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return {'positions': positions,\n"
            "            'apy': round(result.expected_apy, 4)}\n"))
        self.assertEqual(["result"], [r["reads"] for r in rows])

    def test_a_second_substituted_name_is_not_its_own_stale_companion(self):
        """Величина, ЗАМЕНЁННАЯ той же подстановкой, спутником не является:
        она описывает записанное состояние, а не отвергнутое."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions = to_usd(result)\n"
            "    cash = rest(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "        cash = safe_cash()\n"
            "    return {'positions': positions, 'cash': cash}\n"))
        self.assertEqual([], rows)

    def test_a_source_that_was_itself_replaced_is_not_stale(self):
        """`base` — источник заменённой книги, но подстановка заменила и ЕГО.
        Значит поле, читающее `base`, описывает записанное состояние, а не
        отвергнутое, и находкой не является."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "        base = new_base()\n"
            "    return {'positions': positions, 'base_id': base.id}\n"))
        self.assertEqual([], rows)

    def test_the_same_scene_without_replacing_the_source_is_a_finding(self):
        """Обратное направление той же сцены: не заменили источник — находка
        есть. Пара доказывает, что вердикт решает ЗАМЕНА, а не форма кода."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "    return {'positions': positions, 'base_id': base.id}\n"))
        self.assertEqual(["base"], [r["reads"] for r in rows])

    def test_an_annotated_binding_of_the_substituted_value_is_seen(self):
        """Аннотация может стоять и у ЗАМЕНЯЕМОЙ величины, а не только у
        источника. Прибор, знающий только `Assign`, теряет тогда сам источник
        подстановки — и находка исчезает МОЛЧА."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result = tune()\n"
            "    positions: dict = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return {'positions': positions, 'apy': result.expected_apy}\n"))
        self.assertEqual(["result"], [r["reads"] for r in rows])

    def test_the_annotated_source_binding_is_seen(self):
        """`result: TunerResult = tuner.optimize(...)` — `AnnAssign`. Живой
        источник находки объявлен именно так, и прибор, знающий только
        `Assign`, терял находку МОЛЧА."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result: R = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return {'positions': positions, 'apy': result.expected_apy}\n"))
        self.assertEqual(["result"], [r["reads"] for r in rows])

    def test_two_fields_reading_a_replaced_source_are_both_clean(self):
        """ЗАМЕР приёмки #521: сцену «источник заменён» держал НЕ тот охранник.

        Прежняя сцена давала по одному полю на источник, и при ОДНОМ поле
        вердикт «чисто» получался раньше — на пропуске поля, которое само несёт
        подставленную величину. Вычитание `- rebound` при этом не работало
        ни в одном тесте, и мутация, снимающая его, ВЫЖИВАЛА.

        Здесь источник `base` читают ДВА поля. Словарь `carried` хранит по
        имени ОДИН ключ (последний), поэтому второе поле до вычитания доходит —
        и «чисто» тут может сказать только `- rebound`.
        """
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "        base = new_base()\n"
            "    return {'positions': positions, 'a': base.x, 'b': base.y}\n"))
        self.assertEqual([], rows)

    def test_two_fields_reading_a_source_left_in_place_are_both_findings(self):
        """Обратное направление той же сцены: не заменили источник — находки
        ОБЕ. Пара доказывает, что вердикт решает ЗАМЕНА, а не число полей."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "    return {'positions': positions, 'a': base.x, 'b': base.y}\n"))
        self.assertEqual([("a", "base"), ("b", "base")],
                         [(r["stale_field"], r["reads"]) for r in rows])

    def test_a_field_that_carries_the_substitution_is_skipped_even_reading_a_source(self):
        """ЗАМЕР приёмки #521: пропуск поля-носителя тоже не был закреплён.

        Поле `positions` НЕСЁТ подставленную величину и вместе с ней читает её
        прежний источник `base`. Оно описывает записанное состояние, а не
        отвергнутое, и находкой не является — сказать это может только пропуск
        `key in carried.values()`. Мутация, снимавшая пропуск, выживала: во
        всех прежних сценах поле-носитель читало ТОЛЬКО подставленное имя, и
        вычитание `- rebound` закрывало сцену вместо пропуска.
        """
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "    return {'positions': merge(positions, base)}\n"))
        self.assertEqual([], rows)

    def test_the_same_source_in_a_field_of_its_own_is_a_finding(self):
        """Обратное направление: тот же источник, вынесенный в ОТДЕЛЬНОЕ поле,
        подстановку переживает — и находкой является. Пара доказывает, что
        решает НОСИТЕЛЬСТВО поля, а не присутствие имени в словаре."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    base = load()\n"
            "    positions = to_usd(base)\n"
            "    if not ok(positions):\n"
            "        positions = fallback()\n"
            "    return {'positions': positions, 'base_id': base.id}\n"))
        self.assertEqual([("base_id", "base")],
                         [(r["stale_field"], r["reads"]) for r in rows])

    def test_an_annotated_binding_is_seen(self):
        """`result: TunerResult = tuner.optimize(...)` — AnnAssign, и первая
        редакция его не видела, отчего находка исчезала молча."""
        rows = M.stale_companions(ast.parse(
            "def w():\n"
            "    result: R = tune()\n"
            "    positions = to_usd(result)\n"
            "    if not ok(positions):\n"
            "        positions = safe_fallback()\n"
            "    return {'positions': positions, 'apy': result.expected_apy}\n"))
        self.assertEqual(1, len(rows))


# ─────────────────────── третий исход и форма отчёта ─────────────────────────

class UnmeasurableRefusesLoudly(unittest.TestCase):

    def test_a_missing_decision_stage_is_unchecked_not_ok(self):
        with TemporaryDirectory() as td:
            meas = M.measure(Path(td), (FakeStage("reporting", "x.py", "y.json"),))
        self.assertEqual("UNCHECKED", meas["status"])
        self.assertIn("portfolio_state", meas["unchecked_reason"])

    def test_unchecked_status_is_not_silently_ok(self):
        self.assertEqual("UNCHECKED", M.status_of(
            [{"severity": "UNCHECKED", "text": "x"}, {"severity": "INFO", "text": "y"}]))

    def test_critical_outranks_unchecked(self):
        self.assertEqual("CRITICAL", M.status_of(
            [{"severity": "UNCHECKED", "text": "x"}, {"severity": "CRITICAL", "text": "y"}]))

    def test_only_info_is_ok(self):
        self.assertEqual("OK", M.status_of([{"severity": "INFO", "text": "y"}]))


class ReportShape(unittest.TestCase):

    def test_the_clock_is_an_input(self):
        with TemporaryDirectory() as td:
            doc = M.run(Path(td), write=False, now=FIXED_NOW)
        self.assertEqual(FIXED_NOW.isoformat(), doc["generated_at"])

    def test_the_report_is_json_serialisable_and_advisory(self):
        with TemporaryDirectory() as td:
            doc = M.run(Path(td), write=False, now=FIXED_NOW)
        json.dumps(doc)
        self.assertIn("ADVISORY", doc["advisory"])

    def test_the_report_declares_the_schema_the_office_reader_asserts(self):
        """Шаг 0-офис читает отчёт по объявленной схеме; расхождение имён
        превращает поставленный замер в «❌ НЕ ПРОЧИТАН» молча."""
        with TemporaryDirectory() as td:
            doc = M.run(Path(td), write=False, now=FIXED_NOW)
        for key in ("overall", "positive_control", "counts", "measurement",
                    "findings"):
            self.assertIn(key, doc)
        for key in ("critical", "warn", "info", "unchecked"):
            self.assertIn(key, doc["counts"])
        self.assertTrue(doc["positive_control"]["passed"])

    def test_positive_control_passes(self):
        control = M.positive_control()
        self.assertTrue(control["passed"],
                        [k for k, v in control["cases"].items() if not v])


# ───── решения замера, у которых сцены НЕ БЫЛО (приёмка цикла #523) ─────────

class DecisionsThatHadNoScene(unittest.TestCase):
    """Шесть решений прибора, которые СНИМАЛИСЬ, не покрасив ни одного теста.

    Батарея #521 (23 мутации) закрыла те различения, вокруг которых сама и
    строилась, — и ни одно из перечисленных ниже в неё не входило. Это ровно тот
    урок, который #519 записал этажом ниже («найдя форму контроля, применять её
    ко ВСЕМУ классу, а не к её поводу»), повторённый на уровне САМОЙ БАТАРЕИ:
    населением проверки на украшения был круг рассуждений автора.

    Отдельная оговорка про «отчёт не изменился». Три из шести мутаций оставляли
    отчёт байт-в-байт тем же, и первый прогон записал это как невиновность. Он
    ошибался ДВАЖДЫ: у двух хешировался только срез ``measurement`` (тяжесть
    находки и положительный контроль живут РЯДОМ с ним и в срез не попадали), а
    у оставшейся отчёт совпадает потому, что на ЗДОРОВОМ дереве проверяемая
    ветка не срабатывает — а она затем и написана, чтобы говорить, когда дерево
    больное. «Не меняет ответ сегодня» и «не может изменить ответ» — разные
    утверждения, и второе сценой не проверяется, а доказывается.
    """

    # ── 1. положительный контроль ВЫЧИСЛЯЕТСЯ, а не проштампован ────────────

    def test_the_positive_control_reports_a_BROKEN_instrument(self):
        """Мутация ``"passed": True`` пережила обе батареи. Ломаем прибор в
        точке, которую контроль обязан заметить, и требуем, чтобы он это
        СКАЗАЛ — иначе контроль украшение по определению."""
        real = M.plausible_value
        try:
            M.plausible_value = lambda node, consts, depth=0: (True, "прибор сломан")
            control = M.positive_control()
        finally:
            M.plausible_value = real
        self.assertFalse(control["passed"],
                         "сломанный прибор обязан быть назван, а не проштампован")
        failed = [k for k, v in control["cases"].items() if not v]
        self.assertIn("absence_marker_is_not_substitution", failed)

    def test_the_healthy_instrument_still_passes(self):
        """Двойник предыдущей: контроль не краснеет просто так."""
        self.assertTrue(M.positive_control()["passed"])

    # ── 2. РАЗЛИЧИМОСТЬ доходит до находки, а не только до поля ─────────────

    def _labelled_tree(self, tmp: Path, label: str) -> tuple[Path, tuple]:
        """Дерево из :class:`ReachabilityMeasuresTwoChannels`, где подстановка
        достижима каналом артефакта и НЕСЁТ (или не несёт) метку."""
        (tmp / "spa_core" / "decide").mkdir(parents=True)
        (tmp / "spa_core" / "feed").mkdir(parents=True)
        (tmp / "spa_core" / "__init__.py").write_text("")
        (tmp / "spa_core" / "decide" / "__init__.py").write_text("")
        (tmp / "spa_core" / "feed" / "__init__.py").write_text("")
        (tmp / "spa_core" / "decide" / "book.py").write_text(
            "def rebalance():\n"
            "    raw = open('data/feed_snapshot.json').read()\n"
            "    return raw\n", encoding="utf-8")
        (tmp / "spa_core" / "feed" / "poller.py").write_text(
            "def run_feed():\n"
            "    v = fetch()\n"
            "    if v is None:\n"
            f"        return {{'apy': 4.5{label}}}\n"
            "    return v\n", encoding="utf-8")
        stages = tuple(
            FakeStage(k, "spa_core/decide/book.py", "book.json")
            for k in M.DECISION_STAGE_KEYS
        ) + (FakeStage("opportunity_data", "spa_core/feed/poller.py",
                       "feed_snapshot.json"),)
        return tmp, stages

    def test_an_unlabelled_reachable_substitution_is_a_finding(self):
        with TemporaryDirectory() as td:
            root, stages = self._labelled_tree(Path(td), "")
            meas = M.measure(root, stages)
        self.assertEqual(
            ["spa_core/feed/poller.py"],
            [r["file"] for r in meas["reachable"]["unlabelled_toward_entry"]])

    def test_a_LABELLED_reachable_substitution_is_NOT_a_finding(self):
        """Обратное направление той же ошибки. Помеченная подстановка —
        здоровый код (ADR-053: `tvl_source="static"`, и гейт по ней
        отказывает); объявить её находкой значило бы краснеть на работающей
        различимости."""
        with TemporaryDirectory() as td:
            root, stages = self._labelled_tree(Path(td), ", 'apy_source': 'fallback'")
            meas = M.measure(root, stages)
        reached = [r["file"] for r in meas["reachable"]["substitutions"]]
        self.assertIn("spa_core/feed/poller.py", reached,
                      "достижимость от метки не зависит — зависит вердикт")
        self.assertEqual([], meas["reachable"]["unlabelled_toward_entry"])

    # ── 3. тяжесть находки-спутника ─────────────────────────────────────────

    def test_a_stale_companion_is_CRITICAL_not_a_remark(self):
        """Понижение до INFO меняло отчёт и не красило ни одного теста: статус
        замера падал с CRITICAL, а владелец видел бы примечание вместо находки."""
        meas = {
            "status": "MEASURED",
            "census": {"substitutions": 0, "files": 0, "constants": 0,
                       "constant_files": 0},
            "closure": {"import_modules": 1, "artifact_modules": 0, "modules": 1,
                        "artifact_edges": []},
            "reachable": {"substitutions": [], "constants": [],
                          "unlabelled_toward_entry": []},
            "stale_companions": [{
                "file": "spa_core/tuner/portfolio_rebalancer.py", "stage": "portfolio_state",
                "branch_line": 405, "dict_line": 521, "substituted": ["positions_usd"],
                "stale_field": "tuner_expected_apy", "reads": "result"}],
        }
        sev = [f["severity"] for f in M._findings(meas)
               if "tuner_expected_apy" in f["text"]]
        self.assertEqual(["CRITICAL"], sev)
        self.assertEqual("CRITICAL", M.status_of(M._findings(meas)))

    # ── 4. состав ОБЪЯВЛЯЮЩИХ имён ──────────────────────────────────────────

    def _consts_of(self, body: str) -> list[str]:
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core").mkdir()
            (root / "spa_core" / "__init__.py").write_text("")
            (root / "spa_core" / "m.py").write_text(body, encoding="utf-8")
            return [c["name"] for c in M.substitution_constants(root)]

    def test_a_name_that_declares_itself_a_replacement_is_counted(self):
        self.assertEqual(["FALLBACK_APY"], self._consts_of("FALLBACK_APY = 4.5\n"))

    def test_DEFAULT_is_not_a_declaring_name(self):
        """Решение с причиной, а не недосмотр: дефолт применяется, когда вход
        НЕ СПРАШИВАЛИ, подстановка — когда спросили и не получили. Впустить
        сюда `DEFAULT` значит утопить класс в конфигурационных умолчаниях
        (замер: население 598 против 114), то есть отвечать верно не на тот
        вопрос."""
        self.assertNotIn("DEFAULT", M.SUBSTITUTION_TOKENS)
        self.assertEqual([], self._consts_of("DEFAULT_TIMEOUT_SEC = 30\n"))

    # ── 5. поверхность обхода ───────────────────────────────────────────────

    def test_a_standalone_script_is_scanned_too(self):
        """`scripts/` в корнях обхода НАМЕРЕННО: подставлять число умеет и
        отдельный скрипт, а не только модуль пакета. Сужение корня меняло
        ответ и не красило ни одного теста."""
        with TemporaryDirectory() as td:
            root = Path(td)
            for sub in ("spa_core", "scripts"):
                (root / sub).mkdir()
            (root / "spa_core" / "__init__.py").write_text("")
            body = ("def f():\n    v = fetch()\n    if v is None:\n"
                    "        return 4.5\n    return v\n")
            (root / "spa_core" / "m.py").write_text(body, encoding="utf-8")
            (root / "scripts" / "s.py").write_text(body, encoding="utf-8")
            (root / "elsewhere").mkdir()
            (root / "elsewhere" / "x.py").write_text(body, encoding="utf-8")
            files = {r["file"] for r in M.census(root)}
        self.assertEqual({"spa_core/m.py", "scripts/s.py"}, files,
                         "оба корня обходятся, и только они")

    # ── 6. спутники ищутся ТОЛЬКО у ступеней решения ────────────────────────

    def _companion_tree(self, tmp: Path, stage_key: str) -> tuple[Path, tuple]:
        (tmp / "spa_core").mkdir(parents=True)
        (tmp / "spa_core" / "__init__.py").write_text("")
        (tmp / "spa_core" / "book.py").write_text(
            "def w():\n"
            "    result = optimize()\n"
            "    positions = derive(result)\n"
            "    if not positions:\n"
            "        positions = {'a': 1.0}\n"
            "    doc = {'positions': positions, 'apy': result}\n"
            "    return doc\n", encoding="utf-8")
        (tmp / "spa_core" / "other.py").write_text(
            "def w():\n    return 1\n", encoding="utf-8")
        stages = tuple(
            FakeStage(k, "spa_core/book.py" if k == stage_key else "spa_core/other.py",
                      "book.json")
            for k in M.DECISION_STAGE_KEYS
        )
        return tmp, stages

    def test_a_companion_at_a_decision_stage_is_reported(self):
        with TemporaryDirectory() as td:
            root, stages = self._companion_tree(Path(td), "portfolio_state")
            meas = M.measure(root, stages)
        self.assertEqual(["portfolio_state"],
                         [c["stage"] for c in meas["stale_companions"]])

    def test_a_companion_outside_the_decision_stages_is_NOT_reported(self):
        """Двойник: тот же файл, но ступень не решает о капитале. Расширение
        населения на ВСЕ ступени меняло ответ и не красило ни одного теста —
        а «спутник» имеет смысл лишь там, где артефакт И ЕСТЬ ход."""
        with TemporaryDirectory() as td:
            root, stages = self._companion_tree(Path(td), "portfolio_state")
            # ВСЕ ступени решения смотрят в пустой файл, а спутник живёт у
            # ступени `reporting`, решением о капитале не являющейся.
            stages = tuple(
                FakeStage(st.key, "spa_core/other.py", st.product) for st in stages
            ) + (FakeStage("reporting", "spa_core/book.py", "r.json"),)
            meas = M.measure(root, stages)
        self.assertEqual([], meas["stale_companions"])


# ───────────────────── головная находка на ЖИВОМ дереве ─────────────────────

class TheHeadFindingIsAnchoredToTheRealTree(unittest.TestCase):
    """Замер, никогда не видевший настоящей поломки, — украшение. Эта сцена
    привязана к живому файлу: пропадёт находка — тест обязан покраснеть и
    сказать об этом, а не позеленеть молча."""

    def test_the_rebalancer_publishes_numbers_of_a_rejected_allocation(self):
        root = Path(__file__).resolve().parents[2]
        target = root / "spa_core" / "tuner" / "portfolio_rebalancer.py"
        if not target.is_file():                      # pragma: no cover
            self.fail(f"предмет замера отсутствует: {target} — "
                      f"это НЕ «нечего проверять», а необеспеченная предпосылка")
        rows = M.stale_companions(ast.parse(target.read_text(encoding="utf-8")))
        fields = sorted({r["stale_field"] for r in rows})
        self.assertEqual(
            ["tuner_expected_apy", "tuner_expected_sharpe", "tuner_objective_score"],
            fields,
            "поля-спутники отвергнутой аллокации в current_positions.json")
        self.assertEqual({"result"}, {r["reads"] for r in rows})


if __name__ == "__main__":                                        # pragma: no cover
    unittest.main()
