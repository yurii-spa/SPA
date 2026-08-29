"""«Регистры отказов НЕ ПРОЧИТАНЫ» — отдельный исход, а не обвинение (цикл #421).

Карточка `inbox-nechitaemyi-rationale-chitaetsya-kak-otk` (найдена циклом #418).

**Что было.** `compute_gaps` при отсутствующем, пустом или нечитаемом `rationale`
ставила `explained_protocols = {}`, `blob = ""`, честно дописывала строку в `unchecked`
— и ПРОДОЛЖАЛА рождать находки: каждая возможность офиса уходила ключом
`gap:opportunity_unnamed:<proto>` со степенью **WARN** и текстом «отказ НЕ назван НИ В
ОДНОМ из четырёх регистров аллокатора». Ни один из этих четырёх регистров при этом
прочитан не был. Это утверждение, которого никто не измерял, и направление ошибки —
**fail-OPEN**: мост ADR-066 заводит владельцу карточку на находку, которой, возможно,
нет. Дважды подряд (#394 — третий регистр, #418 — четвёртый) находка этого класса уже
оказывалась ЛОЖНОЙ; там регистр читался и молчал, здесь он не читается вовсе.

**Каждый тест ниже — положительный контроль:** на неисправленном модуле он краснеет,
потому что модуль выдавал WARN там, где обязан был сказать «НЕ ИЗМЕРЕНО». Контроль в
обе стороны тоже здесь: измеренное молчание всех четырёх регистров ОБЯЗАНО остаться
WARN — починка не имеет права заглушить настоящий безымянный простой (ADR-055).
"""
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring import house_view_gap as hvg

NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются
REGISTRY = {"pendle", "maple"}


def chief(opportunities=("maple",), posture="YELLOW"):
    return {"house_view": {"overall_posture": posture,
                           "top_opportunities": [
                               {"value": {"protocol": p, "apy_pct": 8.0},
                                "evidence_level": "L3"} for p in opportunities]}}


def book(held=("pendle",), cash=15000.0, capital=100000.0):
    return {"positions": {p: 10000.0 for p in held},
            "cash_usd": cash, "capital_usd": capital}


def registers_silent():
    """Все четыре регистра ПРИСУТСТВУЮТ и пусты — измеренный ноль (инв. #17)."""
    return {"below_median_cap": [],
            "cash": {"policy_refusals": [], "ineligible_rooms": []},
            "decision_shadow": {"warnings": []}}


def keys(report):
    return [g["key"] for g in report["gaps"]]


class RefusalRegistersNotRead(unittest.TestCase):
    """rationale читать было нечем ⇒ ни одного WARN. Приёмка карточки, дословно."""

    def _unmeasured_cases(self):
        return {
            "rationale отсутствует": None,
            "rationale пуст": {},
            "rationale не словарь (нечитаем)": ["мусор"],
            "разделы есть, но НЕ ТЕ": {"foo": 1, "cash": {"bar": []}},
        }

    def test_no_warn_is_fabricated_when_registers_were_never_read(self):
        for name, rationale in self._unmeasured_cases().items():
            with self.subTest(rationale=name):
                r = hvg.compute_gaps(chief(), book(), rationale, REGISTRY, {}, NOW)
                self.assertEqual(r["counts"]["warn"], 0,
                                 f"{name}: WARN на непрочитанных регистрах — fail-OPEN")

    def test_finding_says_UNMEASURED_under_its_own_key(self):
        """Ключ ДРУГОЙ намеренно: мост не должен принять смену смысла за ту же находку."""
        for name, rationale in self._unmeasured_cases().items():
            with self.subTest(rationale=name):
                r = hvg.compute_gaps(chief(), book(), rationale, REGISTRY, {}, NOW)
                self.assertEqual(keys(r), [f"{hvg.KEY_REFUSAL_UNMEASURED}:maple"])
                g = r["gaps"][0]
                self.assertEqual(g["severity"], "INFO")
                self.assertIn("НЕ ИЗМЕРЕНО", g["message"])
                self.assertIn("регистры отказов не прочитаны", g["message"])
                self.assertNotIn("отказ НЕ назван", g["message"])
                self.assertEqual(g["registers_read"], [])

    def test_key_is_not_the_old_one(self):
        """Тождество находки для моста ADR-066: старый ключ обязан ИСЧЕЗНУТЬ, не сменить текст."""
        r = hvg.compute_gaps(chief(), book(), None, REGISTRY, {}, NOW)
        self.assertNotIn("gap:opportunity_unnamed:maple", keys(r))

    def test_unmeasured_registers_are_named_in_unchecked(self):
        """«Не измерено» обязано быть ЗАПИСАНО там, где о нём читают, а не только в тексте находки."""
        r = hvg.compute_gaps(chief(), book(), {"foo": 1}, REGISTRY, {}, NOW)
        reasons = [u["reason"] for u in r["unchecked"] if u["input"] == "allocation_rationale"]
        self.assertTrue(reasons, "непрочитанные регистры не попали в unchecked")
        self.assertIn("НЕ ИЗМЕРЕНО", reasons[0])
        self.assertEqual(r["counts"]["unchecked"], len(r["unchecked"]))


class MeasuredSilenceStaysWarn(unittest.TestCase):
    """Обратный контроль: починка не имеет права заглушить настоящий безымянный простой."""

    def test_all_four_registers_read_and_silent_is_still_warn(self):
        r = hvg.compute_gaps(chief(), book(), registers_silent(), REGISTRY, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 1)
        g = r["gaps"][0]
        self.assertEqual(g["key"], "gap:opportunity_unnamed:maple")
        self.assertIn("НИ В ОДНОМ из четырёх регистров", g["message"])
        self.assertEqual(list(g["registers_read"]), list(hvg.REGISTER_NAMES))

    def test_named_refusal_still_downgrades_to_info(self):
        rationale = registers_silent()
        rationale["cash"]["policy_refusals"] = [
            {"protocol": "maple", "reason": "tvl_unverified_policy_gate"}]
        r = hvg.compute_gaps(chief(), book(), rationale, REGISTRY, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 0)
        self.assertEqual(keys(r), ["gap:opportunity_explained:maple"])

    def test_partial_read_says_HOW_MANY_registers_it_actually_read(self):
        """«Не назван в четырёх» и «не назван в одном прочитанном» — утверждения разной силы."""
        r = hvg.compute_gaps(chief(), book(), {"below_median_cap": []}, REGISTRY, {}, NOW)
        self.assertEqual(r["counts"]["warn"], 1)
        g = r["gaps"][0]
        self.assertEqual(g["key"], "gap:opportunity_unnamed:maple")
        self.assertIn("ПРОЧИТАННЫХ", g["message"])
        self.assertIn("1 из 4", g["message"])
        self.assertNotIn("НИ В ОДНОМ из четырёх", g["message"])
        self.assertEqual(g["registers_read"], ["below_median_cap"])


class OtherBranchesUntouched(unittest.TestCase):
    """Развилка стоит ПОСЛЕДНЕЙ: ветки реестра адаптеров судят о своём и не задеты.

    Без этих трёх тестов починка выглядела бы одинаково при верной и при слишком широкой
    правке — «регистры не прочитаны» не имеет права проглотить «адаптера нет» или
    «реестр недоступен»: это ответы на ДРУГИЕ вопросы, и они по-прежнему INFO.
    """

    def test_no_adapter_wins_over_unmeasured(self):
        r = hvg.compute_gaps(chief(opportunities=("aerodrome",)), book(), None,
                             {"pendle"}, {}, NOW)
        self.assertEqual(keys(r), ["gap:opportunity_no_adapter:aerodrome"])

    def test_registry_unavailable_wins_over_unmeasured(self):
        r = hvg.compute_gaps(chief(), book(), None, None, {}, NOW)
        self.assertEqual(keys(r), ["gap:opportunity_unclassified:maple"])

    def test_held_opportunity_is_still_no_gap(self):
        r = hvg.compute_gaps(chief(opportunities=("pendle",)), book(), None,
                             REGISTRY, {}, NOW)
        self.assertEqual(r["gaps"], [])
