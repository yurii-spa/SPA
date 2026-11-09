#!/usr/bin/env python3
"""Сторож прибора §18 «Asset allocation boundary» (заказ G949 п. 1, ADR-961).

У каждой претензии прибора здесь есть контроль В ОБЕ СТОРОНЫ: проверка зелена на
целом контуре и красна на порванном звене — с НАЗВАННЫМ звеном
(`.claude/rules/acceptance.md`, п. 3). Проверки «прибор напечатал слово» тут нет
намеренно: совпадение подстроки не есть замер.

Главный контроль файла — :class:`RoleNormaliserControl`. Он воспроизводит ОШИБКУ
ЗАМЕРА, найденную в первой редакции прибора: два пункта назначения §18 обязаны
быть разными ключами (иначе у них не было бы разных активов), отпечаток двери
допуска несёт имя ключа, и прямое сравнение объявило РАЗЛИЧЕНИЕ там, где дверь
лишь назвала, куда ушли деньги.
"""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.analytics import asset_boundary_census as abc


REPO_ROOT = Path(__file__).resolve().parents[2]


class VocabularyIsImportedNotReprinted(unittest.TestCase):
    """Словари ВВЕЗЕНЫ. Вторая копия означала бы две шкалы, расходящиеся молча."""

    def test_express_kinds_is_the_same_object_as_in_section_17(self):
        from spa_core.analytics import correlated_dependency_census as c17
        self.assertIs(abc.EXPRESS_KINDS, c17.EXPRESS_KINDS)
        self.assertIs(abc.OBSERVE_KINDS, c17.OBSERVE_KINDS)
        self.assertIs(abc.money_path_axis_call_forms, c17.money_path_axis_call_forms)

    def test_unmeasured_token_comes_from_section_13(self):
        from spa_core.analytics import transaction_economics as c13
        self.assertEqual(abc.UNMEASURED, c13.UNMEASURED)

    def test_surfaces_extend_section_41_and_the_extension_is_named(self):
        from spa_core.monitoring import cio_auto_execution_limits as c41
        self.assertEqual(abc.SURFACES_18[:len(c41.SURFACES)], tuple(c41.SURFACES),
                         "поверхности §41 обязаны войти в §18 БЕЗ переписывания")
        self.assertEqual(abc.SURFACES_18[len(c41.SURFACES):], ("book",),
                         "расширение обязано быть ровно одним и названным")

    def test_no_vocabulary_import_errors_on_this_tree(self):
        self.assertEqual(abc._VOCAB_ERRORS, [],
                         "ввоз словаря упал — прибор обязан ответить кодом 2, "
                         "а не считать на пустых словарях")


class RoleNormaliserControl(unittest.TestCase):
    """Нормализатор обязан снимать ЛИЧНОСТЬ и НЕ снимать СУТЬ."""

    SCENE = {"source": "aave_v3", "same_asset": "compound_v3",
             "other_asset": "spark_susds"}

    def test_role_normaliser_removes_the_identity_confound(self):
        """Положительный контроль: без нормализации отпечатки РАЗНЫЕ."""
        raw_same = "approved=True|err=False|book={'compound_v3': 15000.0}"
        raw_other = "approved=True|err=False|book={'spark_susds': 15000.0}"
        self.assertNotEqual(raw_same, raw_other,
                            "предпосылка контроля: сырые отпечатки различаются "
                            "именем — именно этим ошиблась первая редакция")
        self.assertEqual(abc.role_normalised(raw_same, self.SCENE),
                         abc.role_normalised(raw_other, self.SCENE))

    def test_role_normaliser_keeps_a_real_difference(self):
        """Обратная сторона: разную СУММУ нормализатор обязан сохранить."""
        a = abc.role_normalised("approved=True|book={'compound_v3': 15000.0}", self.SCENE)
        b = abc.role_normalised("approved=True|book={'spark_susds': 40000.0}", self.SCENE)
        self.assertNotEqual(a, b)

    def test_role_normaliser_keeps_the_approval_difference(self):
        a = abc.role_normalised("approved=True|book={'compound_v3': 1.0}", self.SCENE)
        b = abc.role_normalised("approved=False|book={'spark_susds': 1.0}", self.SCENE)
        self.assertNotEqual(a, b)

    def test_role_normaliser_restores_key_order_after_renaming(self):
        """Переименование не должно оставлять отпечаток зависящим от порядка."""
        one = abc.role_normalised(
            "book={'aave_v3': 1.0, 'compound_v3': 2.0}", self.SCENE)
        two = abc.role_normalised(
            "book={'compound_v3': 2.0, 'aave_v3': 1.0}", self.SCENE)
        self.assertEqual(one, two)


class ProducerClaimIsCheckedAgainstTheTree(unittest.TestCase):
    """«Актив до двери не доезжает» — претензия о ДЕРЕВЕ, и она сверяется."""

    def _tree(self, body: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="abc_prod_"))
        target = root / abc.GATE_RECORD_PRODUCER_REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return root

    def test_producer_without_asset_key_answers_false(self):
        root = self._tree("def f():\n    return {'protocol': 'x', 'tier': 'T1'}\n")
        builds, why = abc._producer_builds_asset(root)
        self.assertIsNone(why)
        self.assertFalse(builds)

    def test_producer_with_asset_key_answers_true(self):
        """Положительный контроль: прибор УВИДИТ ключ, если он появится."""
        root = self._tree("def f():\n    return {'protocol': 'x', 'asset': 'USDC'}\n")
        builds, why = abc._producer_builds_asset(root)
        self.assertIsNone(why)
        self.assertTrue(builds)

    def test_missing_producer_is_a_third_outcome_not_false(self):
        root = Path(tempfile.mkdtemp(prefix="abc_prod_none_"))
        builds, why = abc._producer_builds_asset(root)
        self.assertIsNone(builds, "«файла нет» обязано быть НЕ ИЗМЕРЕНО, а не «не несёт»")
        self.assertIn("файла нет", why or "")

    def test_unparsable_producer_is_a_third_outcome(self):
        root = self._tree("def f(:\n")
        builds, why = abc._producer_builds_asset(root)
        self.assertIsNone(builds)
        self.assertIn("не разобран", why or "")


class AllocatorRecordReaderControl(unittest.TestCase):
    """Поля записи кандидата читаются AST'ом, и читатель проверен в обе стороны."""

    def _tree(self, body: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="abc_alloc_"))
        target = root / "spa_core/allocator/allocator.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return root

    def test_reader_finds_asset_when_the_record_carries_it(self):
        root = self._tree(
            "def _load_adapters(self):\n"
            "    return [{'protocol': 'x', 'tier': 'T1', 'asset': 'USDC'}]\n")
        fields, why = abc._allocator_record_fields(root)
        self.assertIsNone(why)
        self.assertIn("asset", fields or [])

    def test_reader_reports_absence_when_the_record_has_no_asset(self):
        root = self._tree(
            "def _load_adapters(self):\n"
            "    return [{'protocol': 'x', 'tier': 'T1'}]\n")
        fields, why = abc._allocator_record_fields(root)
        self.assertIsNone(why)
        self.assertNotIn("asset", fields or [])

    def test_missing_loader_is_a_third_outcome(self):
        root = self._tree("def something_else():\n    return []\n")
        fields, why = abc._allocator_record_fields(root)
        self.assertIsNone(fields)
        self.assertIn("_load_adapters", why or "")

    def test_live_tree_record_has_no_asset(self):
        """Замер на ЖИВОМ дереве: поверхность предложения актива не несёт."""
        fields, why = abc._allocator_record_fields(REPO_ROOT)
        self.assertIsNone(why)
        self.assertNotIn("asset", fields or [])
        self.assertIn("tier", fields or [], "предпосылка: запись вообще прочитана")


class ScenePickerRefusesInsteadOfInventing(unittest.TestCase):
    """Сцены нет ⇒ названная причина, а не сцена на выдуманных ключах."""

    def test_no_pair_of_the_same_asset_refuses_with_a_reason(self):
        reach = {"fundable": {
            "a": {"asset": "USDC", "tier": 2, "chain": "ethereum"},
            "b": {"asset": "sDAI", "tier": 2, "chain": "ethereum"},
        }}
        scene, why = abc.pick_scene(reach)
        self.assertIsNone(scene)
        self.assertIn("сцены нет", why or "")

    def test_scene_holds_tier_and_chain_constant(self):
        """Положительный контроль: сцена находится и ТОЛЬКО внутри тира+сети."""
        reach = {"fundable": {
            "a": {"asset": "USDC", "tier": 2, "chain": "ethereum"},
            "b": {"asset": "USDC", "tier": 2, "chain": "ethereum"},
            "c": {"asset": "sDAI", "tier": 2, "chain": "ethereum"},
            "d": {"asset": "wUSDM", "tier": 3, "chain": "arbitrum"},
        }}
        scene, why = abc.pick_scene(reach)
        self.assertIsNone(why)
        self.assertEqual(scene["tier"], 2)
        self.assertEqual(scene["chain"], "ethereum")
        self.assertEqual({scene["source"], scene["same_asset"]}, {"a", "b"})
        self.assertEqual(scene["other_asset"], "c")
        self.assertNotEqual(scene["source_asset"], scene["other_asset_asset"])

    def test_keys_without_a_named_asset_never_enter_the_scene(self):
        """Ключ без актива сценой быть не может: возмущать было бы нечего."""
        reach = {"fundable": {
            "a": {"asset": "USDC", "tier": 2, "chain": "ethereum"},
            "b": {"asset": "USDC", "tier": 2, "chain": "ethereum"},
            "x": {"asset": None, "tier": 2, "chain": "ethereum"},
        }}
        scene, why = abc.pick_scene(reach)
        self.assertIsNone(scene, "актив пункта назначения не назван ⇒ сцены нет")
        self.assertIn("сцены нет", why or "")


class ProbesWouldSeeADoorThatDoesDistinguish(unittest.TestCase):
    """Самый сильный контроль файла: подсадить дверь, которая актив СПРАШИВАЕТ.

    Без него «switch_invisible» означал бы лишь, что проба не возмущает актив —
    и мутация «оба пункта назначения берутся одним и тем же» выжила бы молча.
    Здесь дверь подменяется на такую, что реагирует РОВНО на актив, и проба
    обязана ответить ``switch_charged``.
    """

    SCENE = {"tier": 2, "chain": "ethereum",
             "source": "src_key", "source_asset": "USDC",
             "same_asset": "same_key", "same_asset_asset": "USDC",
             "other_asset": "other_key", "other_asset_asset": "sDAI"}

    def test_gate_probe_reports_charged_when_the_door_reads_asset(self):
        def fake_verdict(target, spec, *, held=None, **kw):
            dest = spec[1]
            total = sum(target.values())
            # дверь, которая СПРАШИВАЕТ актив — и сумму тоже (для контроля)
            return (f"approved={dest['asset'] == 'USDC'}"
                    f"|cap={total <= 0.4 * abc.SCENE_CAPITAL_USD}"
                    f"|book={{{dest['protocol']!r}: {total}}}")

        row = abc.probe_gate(self.SCENE, {"gate_verdict": fake_verdict})
        self.assertEqual(row["kind"], "switch_charged",
                         f"проба не увидела реагирующую дверь: {row}")

    def test_gate_probe_reports_invisible_when_the_door_ignores_asset(self):
        def blind_verdict(target, spec, *, held=None, **kw):
            dest = spec[1]
            total = sum(target.values())
            return (f"approved={total <= 0.4 * abc.SCENE_CAPITAL_USD}"
                    f"|book={{{dest['protocol']!r}: {total}}}")

        row = abc.probe_gate(self.SCENE, {"gate_verdict": blind_verdict})
        self.assertEqual(row["kind"], "switch_invisible", row)

    def test_gate_probe_refuses_when_its_own_control_is_silent(self):
        """Дверь, слепая и к активу, и к СУММЕ ⇒ ответ НЕ ВЫДАЁТСЯ.

        Эту проверку нашла мутационная проба цикла #1079: снятие ветки отказа у
        двери допуска ВЫЖИЛО, потому что у близнеца (`book`) такой контроль был,
        а здесь — нет. Контроль СЧИТАЛСЯ и печатался, но его молчание ни к чему
        не обязывало, то есть ответ об активе выдавался бы и на мёртвом приборе.
        """
        def deaf_verdict(target, spec, *, held=None, **kw):
            return "approved=True|book={}"

        row = abc.probe_gate(self.SCENE, {"gate_verdict": deaf_verdict})
        self.assertEqual(row["kind"], abc.UNMEASURED)
        self.assertIn("контроль МОЛЧИТ", row["detail"])

    def test_book_probe_reports_charged_when_the_policy_reads_asset(self):
        import dataclasses as dc

        @dc.dataclass
        class _Pos:
            protocol_key: str
            tier: str
            asset: str
            amount_usd: float
            apy_at_open: float
            current_apy: float
            days_held: float = 0.0
            chain: str = "ethereum"

        @dc.dataclass
        class _State:
            total_capital_usd: float
            positions: list

        class _Result:
            def __init__(self, approved, violations, warnings):
                self.approved, self.violations, self.warnings = approved, violations, warnings

        class _Policy:
            def check_portfolio_health(self, state):
                assets = {p.asset for p in state.positions}
                biggest = max(p.amount_usd for p in state.positions)
                # реагирует и на актив (находка), и на долю (контроль)
                viol = ["чужой актив"] if assets - {"USDC"} else []
                if biggest > 0.4 * state.total_capital_usd:
                    viol = viol + ["концентрация"]
                return _Result(not viol, viol, [])

        row = abc.probe_book(self.SCENE, {"Position": _Pos, "PortfolioState": _State,
                                          "RiskPolicy": _Policy})
        self.assertEqual(row["kind"], "switch_charged",
                         f"проба не увидела политику, читающую актив: {row}")

    def test_book_probe_refuses_when_its_own_control_is_silent(self):
        """Дверь, слепая и к активу, и к доле ⇒ ответ НЕ ВЫДАЁТСЯ."""
        import dataclasses as dc

        @dc.dataclass
        class _Pos:
            protocol_key: str
            tier: str
            asset: str
            amount_usd: float
            apy_at_open: float
            current_apy: float
            days_held: float = 0.0
            chain: str = "ethereum"

        @dc.dataclass
        class _State:
            total_capital_usd: float
            positions: list

        class _Deaf:
            def check_portfolio_health(self, state):
                class _R:
                    approved, violations, warnings = True, [], []
                return _R()

        row = abc.probe_book(self.SCENE, {"Position": _Pos, "PortfolioState": _State,
                                          "RiskPolicy": _Deaf})
        self.assertEqual(row["kind"], abc.UNMEASURED)
        self.assertIn("контроль МОЛЧИТ", row["detail"])


class ReachabilityIsMeasuredNotAssumed(unittest.TestCase):

    def test_missing_live_registry_is_a_third_outcome(self):
        root = Path(tempfile.mkdtemp(prefix="abc_reach_"))
        reach, why = abc.reachability(root, {})
        self.assertEqual(reach, {})
        self.assertIn("НЕ ИЗМЕРЕНА", why or "")

    def test_advisory_keys_are_excluded_from_the_fundable_set(self):
        """Советательный ключ сценой быть не может — его закрыл бы флаг, не актив."""
        root = Path(tempfile.mkdtemp(prefix="abc_reach2_"))
        (root / "data").mkdir(parents=True)
        (root / abc.LIVE_REGISTRY_REL).write_text(json.dumps({"adapters": {
            "live": {"status": "active", "tier": 2, "chain": "ethereum"},
            "adv": {"status": "active", "tier": 2, "chain": "ethereum",
                    "research_only": True},
            "off": {"status": "retired", "tier": 2, "chain": "ethereum"},
        }}), encoding="utf-8")
        reach, why = abc.reachability(
            root, {"live": {"asset": "USDC", "state": "resolved"},
                   "adv": {"asset": "BTC", "state": "resolved"}})
        self.assertIsNone(why)
        self.assertEqual(reach["fundable_keys"], 1)
        self.assertEqual(reach["advisory_keys"], 1)
        self.assertEqual(reach["assets_named"], {"USDC": ["live"]})

    def test_live_tree_reachability_names_the_owner_example(self):
        """На живом дереве BTC-ключи ЕСТЬ в каноне и НЕ фондируемы — это и печатается."""
        amap, _ctx, why = abc.load_asset_map()
        self.assertIsNone(why, f"карта активов не измерена: {why}")
        reach, why = abc.reachability(REPO_ROOT, amap)
        self.assertIsNone(why)
        self.assertGreaterEqual(len(reach["owner_example_keys"]), 1,
                                "предпосылка: BTC-ключи в каноническом реестре есть")
        self.assertEqual(reach["owner_example_reachable"], [],
                         "пример владельца сегодня НЕ фондируем — и сцена поэтому "
                         "строится НЕ на нём")
        self.assertGreater(reach["distinct_named_assets"], 1,
                           "вопрос §18 имеет смысл только если активов больше одного")


class DepegInputsOnMoneyPath(unittest.TestCase):
    """Заказ G949 п. 4: подаёт ли денежный путь двери книги цены стейблов."""

    def _tree(self, call: str) -> Path:
        from spa_core.analytics.correlated_dependency_census import MONEY_PATH_FILES
        root = Path(tempfile.mkdtemp(prefix="abc_depeg_"))
        target = root / MONEY_PATH_FILES[0]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"def f(self, state):\n    return {call}\n", encoding="utf-8")
        return root

    def test_call_without_prices_is_a_finding(self):
        root = self._tree("self.policy.check_portfolio_health(state)")
        out = abc.depeg_inputs_on_money_path(root)
        self.assertEqual(out["kind"], "finding")
        self.assertIn("не запускается НИ РАЗУ", out["detail"])

    def test_call_with_both_inputs_is_clean(self):
        """Положительный контроль: прибор УВИДИТ починку, если она произойдёт."""
        root = self._tree("self.policy.check_portfolio_health("
                          "state, stablecoin_prices=px, exit_latency_map=lat)")
        out = abc.depeg_inputs_on_money_path(root)
        self.assertEqual(out["kind"], "ok")

    def test_missing_money_path_file_is_a_third_outcome(self):
        root = Path(tempfile.mkdtemp(prefix="abc_depeg_none_"))
        out = abc.depeg_inputs_on_money_path(root)
        self.assertEqual(out["kind"], abc.UNMEASURED)

    def test_live_tree_money_path_supplies_neither_input(self):
        out = abc.depeg_inputs_on_money_path(REPO_ROOT)
        self.assertEqual(out["kind"], "finding")
        self.assertGreaterEqual(len(out["calls"]), 1,
                                "предпосылка: зов двери книги на денежном пути найден")
        for call in out["calls"]:
            self.assertNotIn("stablecoin_prices", call["keywords"])


class VerdictCodeIsReachableInEveryKind(unittest.TestCase):
    """Род обязан быть ДОСТИЖИМ до того, как печатать его ноль."""

    def test_unmeasured_gives_two(self):
        self.assertEqual(abc.verdict_code({"unmeasured": "дверь не ввезена"}), 2)
        self.assertEqual(abc.verdict_code({"vocab_errors": ["§17"]}), 2)
        self.assertEqual(abc.verdict_code(
            {"distinction": [{"kind": abc.UNMEASURED}]}), 2)

    def test_no_input_door_gives_one(self):
        """«Возмутить нечем» — тоже находка: границы там нет ВОВСЕ."""
        self.assertEqual(abc.verdict_code({
            "distinction": [{"kind": "no_input_door"}],
            "authority": {"kind": "owner_only"},
            "expressibility": [{"kind": "door_input"}],
            "depeg_inputs": {"kind": "ok"}}), 1)

    def test_switch_invisible_gives_one(self):
        self.assertEqual(abc.verdict_code({
            "distinction": [{"kind": "switch_invisible"}],
            "authority": {"kind": "owner_only"},
            "expressibility": [{"kind": "door_input"}],
            "depeg_inputs": {"kind": "ok"}}), 1)

    def test_no_subject_authority_alone_gives_one(self):
        self.assertEqual(abc.verdict_code({
            "distinction": [{"kind": "switch_refused"}],
            "authority": {"kind": "no_subject"},
            "expressibility": [{"kind": "door_input"}],
            "depeg_inputs": {"kind": "ok"}}), 1)

    def test_a_fully_clean_report_gives_zero(self):
        """Ноль ДОСТИЖИМ — иначе код 1 был бы свойством прибора, не мира."""
        self.assertEqual(abc.verdict_code({
            "distinction": [{"kind": "switch_refused"}],
            "authority": {"kind": "owner_only"},
            "expressibility": [{"kind": "door_input"}],
            "depeg_inputs": {"kind": "ok"}}), 0)


class LiveTreeCensus(unittest.TestCase):
    """Замер на живом дереве: все четыре поверхности отвечают, ни одна не молчит."""

    @classmethod
    def setUpClass(cls):
        cls.report = abc.census(REPO_ROOT)

    def test_every_declared_surface_is_answered(self):
        answered = {row["surface"] for row in self.report["distinction"]}
        self.assertEqual(answered, set(abc.SURFACES_18))

    def test_no_surface_is_unmeasured(self):
        for row in self.report["distinction"]:
            self.assertNotEqual(
                row["kind"], abc.UNMEASURED,
                f"поверхность {row['surface']} не измерена: {row['detail']}")

    def test_every_kind_belongs_to_its_declared_vocabulary(self):
        for row in self.report["distinction"]:
            self.assertIn(row["kind"], abc.DISTINCTION_KINDS)
        for row in self.report["expressibility"]:
            self.assertIn(row["kind"], tuple(abc.EXPRESS_KINDS) + (abc.UNMEASURED,))
        self.assertIn(self.report["authority"]["kind"],
                      tuple(abc.AUTHORITY_KINDS) + (abc.UNMEASURED,))

    def test_both_asset_bearing_doors_have_a_live_positive_control(self):
        """Контроль каждой двери СРАБОТАЛ — иначе ответ об активе не выдаётся."""
        for name in ("gate", "book"):
            row = next(r for r in self.report["distinction"] if r["surface"] == name)
            control = row.get("control") or {}
            self.assertNotEqual(
                control.get("base"), control.get("oversized"),
                f"{name}: положительный контроль молчит — ответ об активе был бы "
                f"свойством прибора, а не мира")

    def test_the_verdict_is_a_finding_today(self):
        self.assertEqual(abc.verdict_code(self.report), 1)

    def test_tripwire_the_asset_still_has_no_subject_in_the_system(self):
        """РАСТЯЖКА, а не проверка кода (образец — `test_t3_total_cap_...` §41).

        Замер 2026-11-09: объекта «разрешённая asset exposure» нет. Появится
        поле политики, класс владельческого гейта или потолок аллокатора по
        активу — этот тест покраснеет, и узнать об этом надо ЗДЕСЬ, а не из
        отчёта полугодом позже.
        """
        self.assertEqual(self.report["authority"]["kind"], "no_subject",
                         "граница актива обрела субъекта — перемерить §18 "
                         "и обновить ADR-961, а не править тест")
        self.assertEqual(self.report["authority"]["dials"], [])

    def test_tripwire_asset_does_not_reach_the_admission_door(self):
        """РАСТЯЖКА: актив не доезжает до двери допуска даже данными."""
        row = next(r for r in self.report["expressibility"] if r["surface"] == "gate")
        self.assertEqual(row["kind"], "absent",
                         "актив начал доезжать до двери допуска — перемерить §18")
        self.assertNotIn("asset", row["door_params"])

    def test_render_does_not_crash_and_names_the_order(self):
        text = abc.render(self.report)
        self.assertIn("G949", text)
        self.assertIn("ДОСТИЖИМОСТЬ", text)


class InstrumentOnlyReads(unittest.TestCase):
    """§18 просит ПРЕДЛОЖЕНИЯ: прибор не вправе ничего записать."""

    def test_module_opens_nothing_for_writing(self):
        src = (REPO_ROOT / "spa_core/analytics/asset_boundary_census.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                self.assertNotIn(name, {"write_text", "atomic_save", "mkdir", "dump"},
                                 "прибор §18 обязан только ЧИТАТЬ")
                if name == "open":
                    mode = [a for a in node.args[1:2]]
                    self.assertFalse(
                        mode and isinstance(mode[0], ast.Constant)
                        and "w" in str(mode[0].value), "запись запрещена")

    def test_census_writes_no_artifact(self):
        before = {p.name for p in (REPO_ROOT / "data").glob("asset_boundary*")}
        abc.census(REPO_ROOT)
        after = {p.name for p in (REPO_ROOT / "data").glob("asset_boundary*")}
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
