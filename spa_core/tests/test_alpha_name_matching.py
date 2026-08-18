"""Сличение имён протоколов: ВЕЛИЧИНА замерена, вид совпадения назван.

Карточка `inbox-slichenie-imen-protokolov-podstrokoi-vyr` (заведена циклом
#277, исполнена #283) просила три вещи: ЗАМЕРИТЬ, сколько пар канона дают
подстрочное совпадение, не будучи одним протоколом; решить форму сличения;
закрепить выбор тестами в обе стороны.

Замер (эти тесты) дал не тот ответ, которого карточка ждала:

  на каноне из 56 имён подстрочное сличение даёт 17 пар. 15 из них совпадают
  и по ГРАНИЦАМ ТОКЕНОВ, 2 — только как подстрока (`frax` ⊂ `fraxlend`,
  `frax` ⊂ `sfrax`), и обе «только подстрочные» пары ВЕРНЫ по существу
  (Frax и его же продукты). Ложная пара на каноне ровно одна —
  `pendle_pt_susde` ↔ `susde`, — и она совпадает по границам токенов, то есть
  переход к «границам токенов» её НЕ чинит, а два верных совпадения ломает.

Отсюда решение цикла #283: форму сличения НЕ менять (иначе мы платим двумя
верными совпадениями за ноль исправленных ложных), а вид совпадения назвать в
артефакте, чтобы самый слабый класс можно было отобрать запросом.

Тесты ниже держат ОБЕ стороны: и что подстрочное сличение осталось (вернуть
«точное совпадение» — покраснеет), и что вид совпадения назван верно.

Время в тестах не участвует: канон — код, а не отметка (см. правило
`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import unittest

from spa_core.agents.alpha_agent import (
    MATCH_EXACT,
    MATCH_SUBSTR,
    MATCH_TOKEN,
    _norm,
    coverage_match,
    diversification,
    match_names,
)
from spa_core.agents.protocol_research_agent import known_protocols


def _canon() -> list[str]:
    """Канон покрытия — нормализованный и отсортированный."""
    doc = known_protocols()
    assert doc.get("measured"), f"канон НЕ измерен: {doc.get('reason')}"
    return sorted({_norm(i) for i in (doc.get("ids") or [])})


class TestMatchKind(unittest.TestCase):
    """Вид совпадения — от сильного к слабому, на своих примерах."""

    def test_exact_after_normalisation(self):
        # дефис против подчёркивания — одно и то же имя (требование карточки)
        self.assertEqual(match_names("morpho-blue", "morpho_blue"), MATCH_EXACT)
        self.assertEqual(match_names("  Morpho Blue ", "morpho_blue"), MATCH_EXACT)

    def test_token_boundary_match(self):
        # то же имя с добавленным токеном (цепь / пул / версия)
        self.assertEqual(match_names("aave_v3", "aave_v3_base"), MATCH_TOKEN)
        self.assertEqual(match_names("susde", "ethena_susde"), MATCH_TOKEN)
        self.assertEqual(match_names("pendle", "pendle_pt_usdc"), MATCH_TOKEN)

    def test_substring_only_match_is_named_as_the_weakest(self):
        # граница токенов НЕ совпала — совпадение самое слабое и должно
        # называться так, а не выдаваться за равное предыдущим
        self.assertEqual(match_names("frax", "fraxlend"), MATCH_SUBSTR)
        self.assertEqual(match_names("frax", "sfrax"), MATCH_SUBSTR)

    def test_unrelated_names_do_not_match(self):
        self.assertEqual(match_names("aave_v3", "compound_v3"), "")
        self.assertEqual(match_names("morpho_blue", "morpho_steakhouse"), "")

    def test_empty_name_never_matches(self):
        # пустое имя — подстрока чего угодно; молчаливое совпадение здесь
        # снимало бы бонус всем подряд
        self.assertEqual(match_names("", "aave_v3"), "")
        self.assertEqual(match_names("aave_v3", "   "), "")


class TestSubstringMatchingIsStillInForce(unittest.TestCase):
    """Положительный контроль на РЕШЕНИЕ #283: подстрочное сличение осталось.

    Если кто-то сузит сличение до точного совпадения или до границ токенов,
    эти два теста покраснеют — и покраснеют с ценой, названной в шапке файла.
    """

    def test_substring_pair_still_removes_the_bonus(self):
        bonus, basis, kind = diversification("sfrax", ["frax"])
        self.assertEqual(bonus, 0, "родня по имени обязана терять бонус")
        self.assertEqual(basis, "frax")
        self.assertEqual(kind, MATCH_SUBSTR)

    def test_token_boundary_pair_still_removes_the_bonus(self):
        bonus, basis, kind = diversification("aave_v3_base", ["aave_v3"])
        self.assertEqual(bonus, 0, "тот же протокол на другой цепи — не диверсификация")
        self.assertEqual(basis, "aave_v3")
        self.assertEqual(kind, MATCH_TOKEN)

    def test_genuinely_new_protocol_keeps_the_bonus(self):
        # обратный контроль: не совпало ни с чем — бонус на месте
        bonus, basis, kind = diversification("gearbox_v4", ["aave_v3", "maple"])
        self.assertEqual(bonus, 15)
        self.assertEqual(basis, "")
        self.assertEqual(kind, "")

    def test_unmeasured_coverage_pays_nobody_and_names_no_kind(self):
        bonus, basis, kind = diversification(
            "gearbox_v4", {"measured": False, "reason": "манифесты не измерены"}
        )
        self.assertEqual(bonus, 0, "fail-CLOSED: «не смотрели» не оплачивается")
        self.assertIn("не измерено", basis)
        self.assertEqual(kind, "", "вида совпадения нет — сличения не было")


class TestCanonMeasurement(unittest.TestCase):
    """Сам ЗАМЕР — величина, а не рассуждение о ней (пункт 1 карточки).

    Числа зафиксированы намеренно: если канон вырастет и класс слабых
    совпадений вырастет вместе с ним, тест покраснеет и потребует нового
    замера, а не молчаливого дрейфа. Это не запрет расти — это требование
    ЗАМЕТИТЬ рост.
    """

    # Замер 2026-08-18 на каноне из 56 имён (реестр адаптеров + манифесты SDK).
    EXPECTED_TOKEN_PAIRS = 15
    EXPECTED_SUBSTR_PAIRS = 2

    # Единственная пара канона, которая совпадает, НЕ будучи одним протоколом:
    # PT-токен Pendle на sUSDE — это не сам sUSDE. По форме имени она
    # неотличима от верной ('ethena_susde', 'susde'), и в этом суть вывода.
    KNOWN_FALSE_PAIR = ("pendle_pt_susde", "susde")

    def _pairs(self) -> dict[str, list[tuple[str, str]]]:
        ids = _canon()
        out: dict[str, list[tuple[str, str]]] = {}
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                kind = match_names(a, b)
                if kind:
                    out.setdefault(kind, []).append((a, b))
        return out

    def test_canon_is_measurable_and_not_empty(self):
        ids = _canon()
        self.assertGreater(len(ids), 40, "канон подозрительно мал — замер испорчен")

    def test_pair_counts_are_pinned(self):
        pairs = self._pairs()
        self.assertEqual(
            len(pairs.get(MATCH_TOKEN, [])), self.EXPECTED_TOKEN_PAIRS,
            "число совпадений по границам токенов изменилось — перемерить и "
            "переписать число вместе с объяснением, а не молча",
        )
        self.assertEqual(
            len(pairs.get(MATCH_SUBSTR, [])), self.EXPECTED_SUBSTR_PAIRS,
            "число ТОЛЬКО-подстрочных совпадений изменилось — это самый слабый "
            "класс, рост обязан быть замечен",
        )
        # точных совпадений внутри канона быть не может: канон — множество
        self.assertEqual(pairs.get(MATCH_EXACT, []), [])

    def test_the_only_false_pair_is_token_aligned_not_substring(self):
        """Ключевой вывод: переход к границам токенов ложную пару НЕ чинит."""
        a, b = self.KNOWN_FALSE_PAIR
        canon = _canon()
        self.assertIn(a, canon)
        self.assertIn(b, canon)
        self.assertEqual(
            match_names(a, b), MATCH_TOKEN,
            "если бы ложная пара была подстрочной, сужение сличения имело бы смысл",
        )
        # ... и она по ФОРМЕ совпадает с верной парой того же вида
        self.assertEqual(match_names("ethena_susde", "susde"), MATCH_TOKEN)

    def test_substring_only_pairs_are_the_frax_family(self):
        pairs = self._pairs().get(MATCH_SUBSTR, [])
        self.assertEqual(
            sorted(pairs), [("frax", "fraxlend"), ("frax", "sfrax")],
            "состав слабого класса изменился — перечитать вывод карточки",
        )


class TestCoverageMatchOrder(unittest.TestCase):
    """`coverage_match` отдаёт ПЕРВОЕ совпадение по порядку множества."""

    def test_returns_first_match_deterministically(self):
        name, kind = coverage_match("aave_v3_base", ["aave_v3", "aave_v3_base"])
        self.assertEqual((name, kind), ("aave_v3", MATCH_TOKEN))
        name, kind = coverage_match("aave_v3_base", ["aave_v3_base", "aave_v3"])
        self.assertEqual((name, kind), ("aave_v3_base", MATCH_EXACT))

    def test_no_match_returns_empty_pair(self):
        self.assertEqual(coverage_match("gearbox_v4", ["aave_v3"]), ("", ""))

    def test_empty_coverage_never_matches(self):
        self.assertEqual(coverage_match("aave_v3", []), ("", ""))
        self.assertEqual(coverage_match("aave_v3", None), ("", ""))


if __name__ == "__main__":
    unittest.main()
