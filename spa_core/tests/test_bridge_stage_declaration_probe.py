"""Контроль пробы `bridge_stage_declaration_agrees` — в обе стороны и по звеньям.

Зачем батарея существует
------------------------
`.claude/rules/acceptance.md` п. 3: новая проба регистрируется ТОЛЬКО с тестом,
где она зелена на целом контуре и красна на КАЖДОМ порванном звене — с названным
звеном, — и где она НЕ проходит подстрокой (ADR-333). Проба, никогда не видевшая
настоящей поломки, остаётся украшением.

Предмет пробы — согласие ТРЁХ объявлений состава ступени моста находок: тело
`findings_bridge.main()` (что мост РЕАЛЬНО запускает) · `CENSUS_STAGE` · ключи
`CENSUS_PRODUCT`. Карточка предмета —
`inbox-sostav-stupeni-mosta-razoshelsya-s-obyav`: ступень `no_regression_producer`
поставил цикл #912 (ADR-790) и в объявление не дописал, сторож
`StageIsDeclaredNotHandMaintained` краснел ПОСТОЯННО с 23.10, то есть перестал
быть сигналом — следующая забытая ступень утонула бы в уже красном тесте.

Почему сцены СИНТЕТИЧЕСКИЕ, а не «порвём настоящий мост»
--------------------------------------------------------
Порванное звено надо показать ПРОБЕ, а не дереву: правка живого
`findings_bridge.py` ради контроля сделала бы дерево носителем мутации, которую
никто не писал (класс ADR-772). Поэтому `bridge` инъектируется стендом —
одноразовый исходник с телом `main()` и двумя объявлениями рядом.

Настоящий контур при этом тоже проверяется, отдельной пробой: на дереве, как оно
доставлено, вердикт обязан быть `satisfied`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import pathlib
import tempfile
import types
import unittest

from spa_core.monitoring import card_acceptance as ca

PROBE_NAME = "bridge_stage_declaration_agrees"
CARD = "inbox-sostav-stupeni-mosta-razoshelsya-s-obyav"


def stand(body: str, *, stage, product, with_file: bool = True):
    """Одноразовый стенд: исходник с телом `main()` + два объявления рядом.

    Возвращает объект, который проба примет вместо модуля моста. Исходник
    кладётся в temp-каталог и живёт до конца теста: проба читает его с диска
    ровно так же, как читала бы настоящий мост.
    """
    tmp = tempfile.TemporaryDirectory(prefix="spa_bsd_stand_")
    src = pathlib.Path(tmp.name) / "stand_bridge.py"
    src.write_text(body, encoding="utf-8")
    ns = types.SimpleNamespace()
    if with_file:
        ns.__file__ = str(src)
    if stage is not None:
        ns.CENSUS_STAGE = stage
    if product is not None:
        ns.CENSUS_PRODUCT = product
    ns._keepalive = tmp          # каталог не должен исчезнуть до вердикта
    return ns


WHOLE = (
    "def main():\n"
    "    try:\n"
    "        step_a()\n"
    "    except Exception as e:\n"
    '        census_skipped(rec, "alpha_census", e)\n'
    "    try:\n"
    "        step_b()\n"
    "    except Exception as e:\n"
    '        census_skipped(rec, "beta_census", e)\n'
)
WHOLE_STAGE = ("alpha_census", "beta_census")
WHOLE_PRODUCT = {
    "alpha_census": {"module": "m/a.py", "artifact": "data/a.json"},
    "beta_census": {"module": "m/b.py", "artifact": "data/b.json"},
}


def verdict(ns):
    return ca.PROBES[PROBE_NAME](None, bridge=ns)


class TheWholeCircuitIsGreen(unittest.TestCase):
    """Без этой пробы остальные ничего не значат: красная на всём — не сторож."""

    def test_three_declarations_in_agreement_are_satisfied(self):
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE, product=WHOLE_PRODUCT))
        self.assertEqual(ca.SATISFIED, v, why)
        self.assertIn("согласны", why)

    def test_the_real_tree_as_delivered_is_satisfied(self):
        """НАСТОЯЩИЙ контур, а не стенд: предмет карточки закрыт в этом дереве."""
        v, why = ca.PROBES[PROBE_NAME](None)
        self.assertEqual(ca.SATISFIED, v, why)


class EachBrokenLinkIsNamed(unittest.TestCase):
    """Пять порванных звеньев — пять РАЗНЫХ дефектов, и каждый назван.

    Разностей четыре, а не одна, потому что «тело богаче объявления» (забыли
    дописать) и «объявление богаче тела» (ступень убрали, строка осталась)
    лечатся по-разному. Сложить их в «не совпало» значило бы назвать симптом.
    """

    def test_stage_run_by_main_but_undeclared(self):
        v, why = verdict(stand(WHOLE, stage=("alpha_census",),
                               product={"alpha_census": WHOLE_PRODUCT["alpha_census"]}))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("ЗАПУСКАЕТ", why)
        self.assertIn("beta_census", why)

    def test_stage_declared_but_never_run(self):
        prod = dict(WHOLE_PRODUCT)
        prod["gamma_census"] = {"module": "m/g.py", "artifact": "data/g.json"}
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE + ("gamma_census",),
                               product=prod))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("НЕ запускает", why)
        self.assertIn("gamma_census", why)

    def test_declared_stage_missing_from_the_product_map(self):
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE,
                               product={"alpha_census": WHOLE_PRODUCT["alpha_census"]}))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("CENSUS_PRODUCT", why)
        self.assertIn("beta_census", why)

    def test_product_map_carries_a_stage_nobody_declared(self):
        prod = dict(WHOLE_PRODUCT)
        prod["ghost_census"] = {"module": "m/x.py", "artifact": "data/x.json"}
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE, product=prod))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("ghost_census", why)

    def test_a_stage_named_twice_in_the_body(self):
        body = WHOLE + (
            "    try:\n"
            "        step_a_again()\n"
            "    except Exception as e:\n"
            '        census_skipped(rec, "alpha_census", e)\n')
        v, why = verdict(stand(body, stage=WHOLE_STAGE, product=WHOLE_PRODUCT))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("дважды", why)
        self.assertIn("alpha_census", why)


class TheProbeDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: совпадение подстрокой согласием не является.

    Два направления. Первое — объявленное имя ДЛИННЕЕ запускаемого
    (`alpha_census` против `alpha_census_v2`): подстрочная сверка объявила бы
    контур целым. Второе — имя, которое в теле только УПОМЯНУТО (в строке, в
    комментарии, в соседнем словаре), ступенью не становится: иначе объявление
    сверялось бы с прозой о себе.
    """

    def test_a_declared_name_that_merely_contains_the_run_one_is_a_finding(self):
        v, why = verdict(stand(WHOLE,
                               stage=("alpha_census_v2", "beta_census"),
                               product={"alpha_census_v2": {"module": "m/a.py",
                                                            "artifact": "data/a.json"},
                                        "beta_census": WHOLE_PRODUCT["beta_census"]}))
        self.assertEqual(ca.NOT_SATISFIED, v, why)
        self.assertIn("alpha_census", why)

    def test_a_name_only_mentioned_in_the_body_is_not_a_stage(self):
        body = (
            "def main():\n"
            '    print("ступень gamma_census здесь только УПОМЯНУТА")\n'
            '    registry = {"gamma_census": 1}\n'
            "    try:\n"
            "        step_a()\n"
            "    except Exception as e:\n"
            '        census_skipped(rec, "alpha_census", e)\n')
        v, why = verdict(stand(body, stage=("alpha_census",),
                               product={"alpha_census": WHOLE_PRODUCT["alpha_census"]}))
        self.assertEqual(ca.SATISFIED, v, why)

    def test_a_non_literal_stage_name_is_not_counted(self):
        """Имя, вычисляемое в рантайме, по построению не видно разбору.

        Признать его «ступенью» нельзя (нечего признавать), а посчитать контур
        целым — тем более: единственный такой вызов оставляет тело БЕЗ
        измеримых ступеней, и это `unmeasured`, а не согласие.
        """
        body = (
            "def main():\n"
            "    try:\n"
            "        step_a()\n"
            "    except Exception as e:\n"
            "        census_skipped(rec, name_from_somewhere, e)\n")
        v, why = verdict(stand(body, stage=(), product={}))
        self.assertEqual(ca.UNMEASURED, v, why)


class NothingToMeasureIsNeverAgreement(unittest.TestCase):
    """Инв. #17: «нечем измерить» — третий исход, а не `satisfied`.

    Это та сторона, которой дефект опаснее всего: fail-OPEN тише красного
    теста. Пустое объявление рядом с пустым телом подстрочно «согласно» —
    и именно поэтому проба обязана сказать, что не измерила НИЧЕГО.
    """

    def test_an_unparsable_source_is_unmeasured(self):
        v, why = verdict(stand("def main(:\n    pass\n",
                               stage=WHOLE_STAGE, product=WHOLE_PRODUCT))
        self.assertEqual(ca.UNMEASURED, v, why)
        self.assertIn("SyntaxError", why)

    def test_a_source_without_main_is_unmeasured(self):
        v, why = verdict(stand("def other():\n    pass\n",
                               stage=WHOLE_STAGE, product=WHOLE_PRODUCT))
        self.assertEqual(ca.UNMEASURED, v, why)
        self.assertIn("main", why)

    def test_zero_stages_with_empty_declarations_is_unmeasured_not_satisfied(self):
        v, why = verdict(stand("def main():\n    return 0\n", stage=(), product={}))
        self.assertEqual(ca.UNMEASURED, v, why)
        self.assertNotEqual(ca.SATISFIED, v)

    def test_a_missing_file_attribute_is_unmeasured(self):
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE, product=WHOLE_PRODUCT,
                               with_file=False))
        self.assertEqual(ca.UNMEASURED, v, why)

    def test_an_unreadable_source_is_unmeasured(self):
        ns = stand(WHOLE, stage=WHOLE_STAGE, product=WHOLE_PRODUCT)
        ns.__file__ = str(pathlib.Path(ns.__file__).parent / "net-takogo-faila.py")
        v, why = verdict(ns)
        self.assertEqual(ca.UNMEASURED, v, why)

    def test_an_undeclared_census_stage_is_unmeasured(self):
        v, why = verdict(stand(WHOLE, stage=None, product=WHOLE_PRODUCT))
        self.assertEqual(ca.UNMEASURED, v, why)
        self.assertIn("CENSUS_STAGE", why)

    def test_an_undeclared_product_map_is_unmeasured(self):
        v, why = verdict(stand(WHOLE, stage=WHOLE_STAGE, product=None))
        self.assertEqual(ca.UNMEASURED, v, why)
        self.assertIn("CENSUS_PRODUCT", why)


class TheProbeIsReachableByName(unittest.TestCase):
    """Проба, которой нет в реестре, не существует для очереди.

    Шаг 0-офис и `orchestrator_queue.py probe` знают ТОЛЬКО имя: функция,
    написанная и не зарегистрированная, — ровно класс ADR-345 («прибор есть,
    исполняется нигде»), и зелёный тест на функцию о нём не скажет ничего.
    """

    def test_the_name_is_in_the_registry(self):
        self.assertIn(PROBE_NAME, ca.PROBES)

    def test_the_card_declares_this_probe(self):
        root = pathlib.Path(__file__).resolve().parents[2]
        card = root / "nimbalyst-local" / "tracker" / f"{CARD}.md"
        #: Скипа здесь НЕТ намеренно: `nimbalyst-local/` лежит в git, то есть в
        #: CI карточка на месте всегда, и ветка «карточки нет» была бы мёртвой —
        #: а мёртвый скип делает «не измерено» неотличимым от «прошло» (урок #465).
        #: Карточки нет ⇒ падать ГРОМКО: объявление пробы потеряно.
        self.assertTrue(card.is_file(),
                        f"карточки {CARD} нет в дереве — объявление пробы потеряно, "
                        f"и это находка, а не повод промолчать")
        text = card.read_text(encoding="utf-8")
        self.assertIn(f"acceptance_probe: {PROBE_NAME}", text)


if __name__ == "__main__":                                      # pragma: no cover
    unittest.main()
