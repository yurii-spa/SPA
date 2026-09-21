"""Досягаемость двуязычия — заказ G60 пп. 1–2.

ADR-437 нашёл одноязычие У ОДНОЙ координаты: латинский канал имени в
двуязычном репозитории отвечал «никто не называет» О СЕБЕ. Заказ спрашивает
шире: свойство это одной меры или ВСЕХ свидетелей имени. Ответ обязан быть
замером, и у каждого нуля обязан ехать свой знаменатель — «карта ничего не
сдвинула» и «карту ни разу не спросили» суть разные ответы.

Сцены строятся из ``tmp_path``; карта синонимов почти везде ПОДАЁТСЯ
аргументом, а не берётся у модуля: тест, завязанный на живую карту, менял бы
вердикт от чужой правки словаря и отвечал бы о словаре вместо кода. Ровно один
тест проверяет, что умолчание берёт карту модуля, — иначе инъекция закрыла бы
проводку от проверки.

Литеральных дат-якорей и литеральных pid в файле нет ни одного.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import rule_second_copy_census as census
# Имена, существовавшие на `origin` ДО этой правки, берутся ввозом; всё НОВОЕ
# зовётся через модуль (`census.X`), иначе ввоз упал бы на сборе и один ERROR
# подменил бы вердикты всего файла.
from spa_core.monitoring.rule_second_copy_census import (
    EV_NAME_BILINGUAL, EV_NAME_TOKEN, EV_NAME_VERBATIM, NAME_ABSENT,
    NAME_RESOLVED, RISK_POLICY_MODULE, RULE_DIR, RULE_TEXT,
)

#: Карта сцены. Своя, а не живая: предмет теста — ПРАВИЛО сверки, а не
#: содержимое словаря репозитория.
MAP = {"cash": ("кэш",), "kill": ("стоп-кран",), "switch": ("кран",),
       "drawdown": ("просадк",)}

#: Маркер права изменения берётся У МОДУЛЯ, а не перепечатывается: вторая
#: копия правила в сцене пережила бы смену правила молча.
AUTHORITY = census.AUTHORITY_MARKS[0]


class TokenEvidence(unittest.TestCase):
    """Общая половина правила имени — та, которой пользуются ОБА свидетеля."""

    def test_latin_token_alone_is_not_bilingual(self):
        self.assertEqual(
            census._token_evidence("порог cash проверяется", {"cash"}, MAP),
            EV_NAME_TOKEN)

    def test_russian_synonym_alone_is_bilingual(self):
        self.assertEqual(
            census._token_evidence("буфер кэша обязателен", {"cash"}, MAP),
            EV_NAME_BILINGUAL)

    def test_one_missing_token_refuses_the_whole_name(self):
        self.assertIsNone(
            census._token_evidence("буфер кэша обязателен",
                                   {"cash", "drawdown"}, MAP))

    def test_empty_token_set_is_not_a_name(self):
        self.assertIsNone(census._token_evidence("что угодно", set(), MAP))

    def test_empty_map_is_the_monolingual_control(self):
        self.assertIsNone(
            census._token_evidence("буфер кэша обязателен", {"cash"}, {}))

    def test_injected_map_is_used_instead_of_the_module_one(self):
        self.assertEqual(
            census._token_evidence("порог слова-которого-нет", {"cash"},
                                   {"cash": ("слова-которого-нет",)}),
            EV_NAME_BILINGUAL)

    def test_latin_token_requires_word_boundaries(self):
        self.assertIsNone(census._token_evidence("предел t10 задан",
                                                 {"t1"}, MAP))

    def test_name_evidence_still_prefers_the_verbatim_channel(self):
        # Делегирование не имеет права понизить канал ADR-437: дословное имя
        # обязано остаться сильнейшим, иначе прежний вердикт переписи поедет.
        self.assertEqual(
            census._name_evidence("порог `min_cash_pct` объявлен",
                                  "RiskPolicy:min_cash_pct"),
            EV_NAME_VERBATIM)

    def test_name_evidence_reads_the_module_map_by_default(self):
        # Единственный тест, зависящий от живой карты: без него инъекция
        # закрыла бы от проверки саму проводку умолчания.
        token = next(iter(census._TOKEN_SYNONYMS["cash"]))
        self.assertEqual(
            census._name_evidence(f"буфер {token}а обязателен",
                                  "RiskPolicy:min_cash_pct"),
            EV_NAME_BILINGUAL)


class ModuleNaming(unittest.TestCase):
    """Свидетель ПРЕДМЕТА: называет ли текст чужой модуль русским словом."""

    def test_non_python_target_has_no_tokens(self):
        self.assertEqual(census._module_tokens("docs/readme.md"), set())

    def test_directories_are_not_distinguishing_tokens(self):
        self.assertEqual(
            census._module_tokens("spa_core/governance/kill_switch.py"),
            {"kill", "switch"})

    def test_latin_witness_takes_precedence_and_bilingual_stays_silent(self):
        # Иначе «сколько ПРИБАВИЛО двуязычие» включало бы пары, у которых
        # свидетель и так есть, — то есть отвечало бы о населении.
        text = "проверяем kill_switch.py и стоп-кран заодно"
        self.assertIsNotNone(
            census.subject_witness(text, "spa_core/governance/kill_switch.py"))
        self.assertIsNone(
            census._module_named_bilingually(
                text, "spa_core/governance/kill_switch.py", MAP))

    def test_the_precedence_guard_is_provably_redundant_today(self):
        """Батарея мутаций сняла этот сторож и НЕ покраснела — измеряю почему.

        Свидетель предмета срабатывает только на ДОСЛОВНОМ имени файла или
        точечном хвосте, а значит все различающие токены основы стои́т в тексте
        латиницей — и канал токенов отвечает `name_token`, а не
        `name_token_bilingual`, каким бы русским словом текст ни сопровождался.
        Сцены, где сторож кусается, не существует, и это ЗАМЕР по формам, а не
        уверенность: сторож оставлен ремнём поверх подтяжек, а редундантность
        закреплена тестом, чтобы её потеря стала видимой.
        """
        modules = ("spa_core/governance/kill_switch.py",
                   "spa_core/governance/cash.py",
                   "spa_core/x/y/kill_switch.py")
        shapes = ("{name}", "смотри {name} рядом", "{name} и кэш и стоп-кран",
                  "русский текст про стоп-кран и {name}")
        checked = 0
        for module in modules:
            stem = module[:-3].split("/")[-1]
            parts = module[:-3].split("/")
            for verbatim in (f"{stem}.py", ".".join(parts[-2:]),
                             ".".join(parts)):
                for shape in shapes:
                    text = shape.format(name=verbatim)
                    if census.subject_witness(text, module) is None:
                        continue
                    checked += 1
                    self.assertNotEqual(
                        census._token_evidence(text.lower(),
                                               census._module_tokens(module),
                                               MAP),
                        EV_NAME_BILINGUAL)
        # Пустой обход доказал бы не редундантность, а отсутствие сцен.
        self.assertGreater(checked, 0)

    def test_latin_tokens_alone_are_not_a_bilingual_gain(self):
        # Прибавка двуязычия — только та пара, которой БЕЗ русского слова не
        # было бы. Латиница врозь («kill и switch») свидетелем предмета не
        # является и прибавкой становиться не вправе.
        self.assertIsNone(
            census._module_named_bilingually(
                "kill и switch упомянуты порознь",
                "spa_core/governance/kill_switch.py", MAP))

    def test_russian_only_mention_is_the_gain(self):
        self.assertEqual(
            census._module_named_bilingually(
                "стоп-кран срабатывает первым",
                "spa_core/governance/kill_switch.py", MAP),
            "kill_switch")

    def test_one_token_without_russian_refuses(self):
        self.assertIsNone(
            census._module_named_bilingually(
                "стоп-кран срабатывает первым",
                "spa_core/governance/kill_switch_drawdown.py", MAP))


class RowSides(unittest.TestCase):
    """Стороны строки у ВСЕХ трёх осей переписи, а не у одной."""

    def test_guard_executor_row(self):
        self.assertEqual(
            census._row_sides({"guard": "g.py", "executor": "e.py"}),
            [("g.py", "e.py")])

    def test_peer_row(self):
        self.assertEqual(census._row_sides({"left": "l.py", "right": "r.py"}),
                         [("l.py", "r.py")])

    def test_triple_row_has_three_sides(self):
        self.assertEqual(
            census._row_sides({"guard": "g.py", "left": "l.py",
                               "right": "r.py"}),
            [("l.py", "r.py"), ("g.py", "l.py"), ("g.py", "r.py")])

    def test_row_without_sides_is_not_invented(self):
        self.assertEqual(census._row_sides({"name": "SEED"}), [])


class ParagraphValues(unittest.TestCase):
    """Две единицы одного порога — иначе ответ решала бы единица автора."""

    def test_percent_is_read_both_ways(self):
        values = census._paragraph_values("потолок 20 % на протокол")
        self.assertIn(census.value_key("20.0"), values)
        self.assertIn(census.value_key("0.2"), values)

    def test_digit_groups_are_separators_not_values(self):
        self.assertIn(census.value_key("5000000.0"),
                      census._paragraph_values("floor 5_000_000 USD"))

    def test_text_without_numbers_yields_nothing(self):
        self.assertEqual(census._paragraph_values("без чисел вовсе"), set())


class Enrichment(unittest.TestCase):
    """Отношение частот — и три отказа вместо сочинённого числа."""

    def test_ratio_is_reported(self):
        rate, why = census._rate_enrichment(4, 2, 2, 4)
        self.assertIsNone(why)
        self.assertAlmostEqual(rate, 4.0)

    def test_no_control_population_is_not_measured(self):
        rate, why = census._rate_enrichment(4, 2, 0, 0)
        self.assertIsNone(rate)
        self.assertIn("контрол", why)

    def test_no_population_is_not_measured(self):
        rate, why = census._rate_enrichment(0, 0, 2, 4)
        self.assertIsNone(rate)
        self.assertIsNotNone(why)

    def test_zero_control_hits_refuses_instead_of_infinity(self):
        rate, why = census._rate_enrichment(4, 2, 0, 4)
        self.assertIsNone(rate)
        self.assertIn("бесконечность", why)


class _Tree:
    """Дерево с обеими поверхностями решения — иначе полнота карты «не измерена»."""

    def __init__(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        policy = self.root / RISK_POLICY_MODULE
        policy.parent.mkdir(parents=True, exist_ok=True)
        policy.write_text("class RiskConfig:\n"
                          "    min_cash_pct: float = 0.05\n"
                          "    max_drawdown_stop: float = 0.10\n"
                          "    cash_horizon_pct: float = 0.30\n"
                          "    var_horizon_days: int = 7\n",
                          encoding="utf-8")

    def write(self, rel, body):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return rel

    def rule(self, body, rel=RULE_TEXT):
        return self.write(rel, body)

    def close(self):
        self._tmp.cleanup()


class SubjectReach(unittest.TestCase):

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    def test_russian_only_mention_changes_the_verdict(self):
        guard = self.tree.write("spa_core/tests/test_x.py",
                                "# стоп-кран проверяется здесь\nSEED = 42\n")
        executor = self.tree.write("spa_core/governance/kill_switch.py",
                                   "SEED = 42\n")
        out = census.bilingual_subject_reach(
            self.tree.root, [{"guard": guard, "executor": executor,
                              "name": "SEED", "value": "42"}], MAP)
        self.assertEqual(out["changed"], 1)
        self.assertEqual(out["pairs_read"], 1)

    def test_the_same_scene_is_inert_under_the_monolingual_control(self):
        guard = self.tree.write("spa_core/tests/test_x.py",
                                "# стоп-кран проверяется здесь\nSEED = 42\n")
        executor = self.tree.write("spa_core/governance/kill_switch.py",
                                   "SEED = 42\n")
        out = census.bilingual_subject_reach(
            self.tree.root, [{"guard": guard, "executor": executor,
                              "name": "SEED", "value": "42"}], {})
        self.assertEqual(out["changed"], 0)

    def test_zero_travels_with_its_denominators(self):
        guard = self.tree.write("spa_core/tests/test_x.py",
                                "# по-русски, но не про предмет\nSEED = 42\n")
        executor = self.tree.write("spa_core/paper_trading/ledger.py",
                                   "SEED = 42\n")
        out = census.bilingual_subject_reach(
            self.tree.root, [{"guard": guard, "executor": executor,
                              "name": "SEED"}], MAP)
        self.assertEqual(out["changed"], 0)
        # Ноль без этих трёх чисел был бы утверждением о приборе.
        self.assertEqual(out["askable"], 0)
        self.assertEqual(out["modules"], 2)
        self.assertEqual(out["cyrillic_sides"], 1)

    def test_latin_witness_on_any_side_cancels_the_gain(self):
        # Сторож называет исполнителя ДОСЛОВНО, исполнитель сторожа — только
        # по-русски. Пара уже имеет свидетеля, и прибавкой двуязычия она не
        # является: иначе число отвечало бы о населении, а не о прибавке.
        # Основа имени сторожа несёт РОВНО один различающий токен, и он в
        # карте: иначе двуязычный свидетель не сработал бы вовсе, сцена
        # ответила бы о своём имени файла, а мутация «считать прибавкой и
        # пару со свидетелем» пережила бы тест.
        guard = self.tree.write(
            "spa_core/tests/cash.py",
            "# сверяем kill_switch.py\nSEED = 42\n")
        executor = self.tree.write("spa_core/governance/kill_switch.py",
                                   "# буфер кэша считается тут\nSEED = 42\n")
        out = census.bilingual_subject_reach(
            self.tree.root, [{"guard": guard, "executor": executor}], MAP)
        self.assertEqual(out["changed"], 0)

    def test_askable_demands_full_coverage_not_mere_overlap(self):
        # Частично закрытая основа назваться по-русски НЕ может: канал требует
        # каждого токена. Считать её спрошенной значило бы завысить
        # знаменатель и выдать ноль карты за ноль дерева.
        guard = self.tree.write("spa_core/tests/test_x.py", "SEED = 42\n")
        executor = self.tree.write("spa_core/governance/kill_ratio.py",
                                   "SEED = 42\n")
        out = census.bilingual_subject_reach(
            self.tree.root, [{"guard": guard, "executor": executor}], MAP)
        self.assertEqual(out["askable"], 0)
        self.assertEqual(out["token_overlap"], 1)

    def test_unreadable_population_is_not_measured(self):
        out = census.bilingual_subject_reach(
            self.tree.root,
            [{"guard": "нет/такого.py", "executor": "и/такого.py"}], MAP)
        self.assertEqual(out["status"], census.BILINGUAL_UNMEASURED)
        self.assertIn("не прочитана", out["reason"])


class NameReach(unittest.TestCase):

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)
        self.holder = self.tree.write("spa_core/governance/damper.py",
                                      "_MIN_CASH_PCT = 0.05\n")
        self.index = {"_MIN_CASH_PCT": [self.holder]}

    def test_value_in_the_same_paragraph_corroborates_the_pair(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["authority_raw"], 1)
        self.assertEqual(out["authority_corroborated"], 1)
        self.assertEqual(out["pairs"][0]["resolved"], self.holder)

    def test_named_without_a_matching_value_stays_uncorroborated(self):
        self.tree.rule(f"- Кэш обязателен всегда: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["authority_raw"], 1)
        self.assertEqual(out["authority_numeric"], 1)
        self.assertEqual(out["authority_corroborated"], 0)
        self.assertEqual(out["pairs"], [])

    def test_control_paragraph_is_counted_apart_and_never_reported(self):
        self.tree.rule("- Кэш сверх 5%-буфера объясняется каждый цикл.\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["authority_raw"], 0)
        self.assertEqual(out["control_raw"], 1)
        self.assertEqual(out["control_corroborated"], 1)
        self.assertEqual(out["pairs"], [])

    def test_verbatim_backticked_name_is_not_counted_twice(self):
        self.tree.rule(f"- Кэш `_MIN_CASH_PCT` 5%: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["authority_raw"], 0)

    def test_ambiguous_name_is_not_a_surface(self):
        index = {"_MIN_CASH_PCT": [self.holder, "spa_core/other.py"]}
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, index, MAP)
        self.assertEqual(out["candidates"], 0)
        self.assertEqual(out["authority_raw"], 0)

    def test_the_verbatim_exclusion_is_provably_redundant_today(self):
        """Второй сторож, переживший батарею, — и по той же причине.

        Имя, стоящее в абзаце ДОСЛОВНО, несёт все свои различающие токены
        латиницей, поэтому канал токенов отвечает `name_token`, а не
        `name_token_bilingual`, и пара отсеивается и без исключения. Сцены,
        где исключение кусается, не существует; это ЗАМЕР по формам, а не
        уверенность, и его потеря обязана стать видимой.
        """
        names = ("_MIN_CASH_PCT", "CASH", "KILL_SWITCH", "cash_buffer")
        checked = 0
        for name in names:
            for shape in ("`{n}` меняется только ADR",
                          "буфер кэша и `{n}` рядом",
                          "стоп-кран, он же `{n}`"):
                low = shape.format(n=name).lower()
                self.assertIn(name, census._DECLARED_NAME_RE.findall(
                    shape.format(n=name)))
                checked += 1
                self.assertNotEqual(
                    census._token_evidence(low, census._name_tokens(name), MAP),
                    EV_NAME_BILINGUAL)
        self.assertGreater(checked, 0)

    def test_candidates_demand_full_coverage_not_mere_overlap(self):
        # Имя, у которого закрыт лишь один токен из двух, назваться прозой не
        # может, и населением кандидатов не является: пересечение вместо
        # полноты раздуло бы знаменатель, ничего не добавив к ответу.
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        out = census.bilingual_name_reach(
            self.tree.root,
            {"_MIN_CASH_PCT": [self.holder],
             "CASH_HORIZON_PCT": ["spa_core/governance/horizon.py"]}, MAP)
        self.assertEqual(out["candidates"], 1)

    def test_texts_that_exist_but_do_not_read_are_not_measured(self):
        # Тексты правил ЕСТЬ, но ни один не прочитан — это отсутствие
        # наблюдения, а не пустой результат (инв. #17).
        (self.tree.root / RULE_DIR).mkdir(parents=True, exist_ok=True)
        (self.tree.root / RULE_DIR / "каталог.md").mkdir()
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["status"], census.BILINGUAL_UNMEASURED)
        self.assertTrue(out["unreadable"])

    def test_empty_index_is_not_measured(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        out = census.bilingual_name_reach(self.tree.root, {}, MAP)
        self.assertEqual(out["status"], census.BILINGUAL_UNMEASURED)

    def test_no_rule_texts_is_not_measured(self):
        out = census.bilingual_name_reach(self.tree.root, self.index, MAP)
        self.assertEqual(out["status"], census.BILINGUAL_UNMEASURED)


class MapCoverage(unittest.TestCase):

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)

    def test_thresholds_split_into_three_degrees_of_coverage(self):
        out = census.synonym_map_coverage(self.tree.root, MAP)
        self.assertEqual(out["status"], "MEASURED")
        # `min_cash_pct` закрыт целиком, `max_drawdown_stop` — тоже (`stop`
        # и `max` служебные), `var_horizon_days` не закрыт ни одним словом.
        self.assertEqual(out["fully_covered"], 2)
        # Частичное закрытие — СВОЙ разряд: слить его с полным значило бы
        # объявить карту полнее, чем она есть, ровно тем словом, ради
        # измерения которого заказ и поставлен.
        self.assertEqual(out["partly_covered"], 1)
        self.assertEqual(out["not_covered"], 1)
        self.assertIn("var", out["missing_tokens"])
        self.assertIn("horizon", out["missing_tokens"])

    def test_unreadable_policy_is_not_measured(self):
        (self.tree.root / RISK_POLICY_MODULE).unlink()
        out = census.synonym_map_coverage(self.tree.root, MAP)
        self.assertEqual(out["status"], census.BILINGUAL_UNMEASURED)
        self.assertIn("не прочитан", out["reason"])


class Verdicts(unittest.TestCase):

    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.close)
        self.holder = self.tree.write("spa_core/governance/damper.py",
                                      "_MIN_CASH_PCT = 0.05\n")

    def test_empty_map_is_nothing_to_ask_not_clean(self):
        out = census.bilingual_reach(self.tree.root, [], {}, {})
        self.assertEqual(out["verdict"], census.BILINGUAL_NOTHING_TO_ASK)
        self.assertIn("НЕ", out["reason"])

    def test_unmeasured_witness_decides_the_whole_verdict(self):
        out = census.bilingual_reach(
            self.tree.root, [{"guard": "нет.py", "executor": "тоже.py"}],
            {"_MIN_CASH_PCT": [self.holder]}, MAP)
        self.assertEqual(out["verdict"], census.BILINGUAL_UNMEASURED)

    def test_shift_when_the_name_channel_gains_a_corroborated_pair(self):
        self.tree.rule(f"- Кэш сверх 5%-буфера: {AUTHORITY}\n")
        guard = self.tree.write("spa_core/tests/test_y.py", "SEED = 42\n")
        out = census.bilingual_reach(
            self.tree.root, [{"guard": guard, "executor": self.holder}],
            {"_MIN_CASH_PCT": [self.holder]}, MAP)
        self.assertEqual(out["verdict"], census.BILINGUAL_SHIFT)

    def test_inert_verdict_names_the_denominators(self):
        self.tree.rule("- обычный абзац без права изменения.\n")
        guard = self.tree.write("spa_core/tests/test_y.py", "SEED = 42\n")
        out = census.bilingual_reach(
            self.tree.root, [{"guard": guard, "executor": self.holder}],
            {"_MIN_CASH_PCT": [self.holder]}, MAP)
        self.assertEqual(out["verdict"], census.BILINGUAL_INERT)
        self.assertIn("из", out["reason"])

    def test_blind_spots_are_named_not_implied(self):
        self.tree.rule("- обычный абзац.\n")
        guard = self.tree.write("spa_core/tests/test_y.py", "SEED = 42\n")
        out = census.bilingual_reach(
            self.tree.root, [{"guard": guard, "executor": self.holder}],
            {"_MIN_CASH_PCT": [self.holder]}, MAP)
        self.assertTrue(out["blind"])

    def test_empty_population_is_not_measured_rather_than_inert(self):
        # Пустое население и «карта спрошена и не сдвинула» — разные ответы:
        # слить их значило бы выдать «не измерено» за «чисто» (инв. #17).
        self.tree.rule("- обычный абзац.\n")
        out = census.bilingual_reach(
            self.tree.root, [], {"_MIN_CASH_PCT": [self.holder]}, MAP)
        self.assertEqual(out["verdict"], census.BILINGUAL_UNMEASURED)


class ReportPlacement(unittest.TestCase):
    """Секция обязана печататься и у дерева, где СОСЕДНЯЯ координата молчит."""

    def _doc(self, **extra):
        doc = {"status": "CLEAN", "generated_at": "", "counts": {},
               "rows": [], "scanned": 0, "classified": 0, "unreadable": [],
               "renamed_copy_surface": []}
        doc.update(extra)
        return doc

    def test_section_speaks_when_the_neighbour_is_unmeasured(self):
        lines = census.report(self._doc(
            out_of_channel_numbers=None,
            bilingual_reach={"verdict": census.BILINGUAL_INERT,
                             "reason": "ноль ИЗМЕРЕН", "witnesses": {},
                             "map_coverage": {}, "blind": []}))
        self.assertTrue(any("[ДВУЯЗЫЧИЕ]" in line for line in lines))

    def test_absent_coordinate_is_reported_as_not_measured(self):
        lines = census.report(self._doc())
        self.assertTrue(any("[ДВУЯЗЫЧИЕ] НЕ ИЗМЕРЕНО" in line
                            for line in lines))


class Wiring(unittest.TestCase):

    def test_name_channel_accepts_a_shared_index(self):
        # Проводка проверяется ПОДМЕНОЙ индекса, а не наличием параметра:
        # аргумент, который зовущий принял и выбросил, тест по имени пережил бы.
        tree = _Tree()
        self.addCleanup(tree.close)
        # Имя ЛАТИНСКОЕ намеренно: `_DECLARED_NAME_RE` кириллицы не
        # читает вовсе, и русское имя проверяло бы регулярку, а не проводку.
        tree.rule(f"- Не менять `GHOST_ONLY_IN_THE_INDEX` без ADR. {AUTHORITY}\n")
        ghost = "spa_core/ghost_module.py"
        out = census.name_channel(
            tree.root, [], path_candidates=[],
            definitions=({"GHOST_ONLY_IN_THE_INDEX": [ghost]}, 31337, []))
        # Число прочитанных файлов взято из ПОДАННОГО индекса, а не совпало с
        # числом файлов сцены; и имя разрешилось в файл, которого на диске нет
        # вовсе — собственный обход дерева дать этого не мог бы.
        self.assertEqual(out["files_read"], 31337)
        # Имя разрешилось в файл, которого на диске нет вовсе: собственный
        # обход дерева дать этого не мог бы, и выброшенный аргумент оставил бы
        # здесь `absent_from_tree`.
        self.assertEqual(out["by_outcome"][NAME_RESOLVED], 1)
        self.assertEqual(out["by_outcome"][NAME_ABSENT], 0)

    def test_measure_carries_the_coordinate(self):
        source = Path(census.__file__).read_text(encoding="utf-8")
        self.assertIn('"bilingual_reach": bilingual', source)


if __name__ == "__main__":
    unittest.main()
