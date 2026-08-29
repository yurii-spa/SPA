"""Реестр «списано / заморожено» для Tier-B и генератор, который его строит.

ЗАЧЕМ. ADR-133 (решение владельца 2026-08-25) разметил Tier-C: девять константных
списаны, 162 «позвать нечем» заморожены, реестр СГЕНЕРИРОВАН из JSON аудита, а не
набран руками. Tier-B — та же болезнь и вчетверо больший масштаб: из 479 модулей
354 измеренно не дают протокол-зависимого сигнала, и с 2026-08-07 их никто не трогал.

ЧЕМ ЭТОТ ФАЙЛ ОТЛИЧАЕТСЯ ОТ `test_tier_c_writeoff.py`. Тот проверяет РЕЗУЛЬТАТ,
доставленный однажды. Здесь проверяется ГЕНЕРАТОР, который строит такие реестры для
любого тира, — и главный тест ровно один: генератор обязан воспроизвести доставленный
руками `_tier_c_writeoff.py` ПОИМЁННО. Реестр Tier-C для него — положительный
контроль из реальной жизни: он собран другим путём, в другой день, другой сессией.
Не воспроизвёл — генератору верить нельзя, и реестра Tier-B быть не должно.

К каждому положительному контролю здесь есть ОТРИЦАТЕЛЬНЫЙ: сверка, которая
проходит всегда, ничего не проверяет. `test_verification_catches_a_wrong_generator`
подсовывает заведомо испорченный замер и требует, чтобы сверка покраснела.

ГРАНИЦА ЭТОГО ФАЙЛА. Реестр НИЧЕГО не отключает сам по себе — он называет модули и
измеренные причины. Прекращение исполнения — отдельное решение владельца и отдельная
строка в `signal_aggregator`, как это было с Tier-C. Тест ниже эту границу держит:
Tier-B-реестр НЕ ДОЛЖЕН быть подключён к агрегатору до ответа владельца.

Tier-B — советующий слой: капитал не двигает, RiskPolicy и стоп-кран не касается.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

from spa_core.tests._freshness import ts

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO_ROOT / "scripts" / "generate_tier_writeoff.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "analytics_audit"

#: Отчёты аудита, из которых построены реестры, — ПРОВЕНАНС, а не выдумка теста.
#: Живой аудит здесь не гоняется намеренно: он исполняет 180–479 модулей, часть из
#: которых пишет в `data/`, и юнит-прогон начал бы переписывать git-tracked состояние
#: прода (сторож `live_data_write_guard` поймал это на первой версии файла).
TIER_C_REPORT = FIXTURES / "tier_c_report.json"
TIER_B_REPORT = FIXTURES / "tier_b_report.json"


def _load_generator():
    spec = importlib.util.spec_from_file_location("_writeoff_gen_under_test", GENERATOR)
    assert spec and spec.loader, f"не загружается {GENERATOR}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_writeoff_gen_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fake_report(tier: str, rows):
    """Минимальный отчёт аудита той же формы, что пишет реальный инструмент."""
    counts = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {"generated_at": ts(hours_ago=1.0), "tier": tier,
            "module_count": len(rows), "counts": counts, "results": rows}


def _row(name, cls, score=0.0, detail="", wide_ok=None):
    runs = {"aave_v3": {"score": score, "status": "ok"}}
    if detail:
        runs["aave_v3"]["detail"] = detail
    out = {"module": name, "classification": cls, "runs": runs}
    if wide_ok is not None:
        out["wide"] = {"differs_at": None, "ok_runs": wide_ok}
    return out


class GeneratorReproducesTheDeliveredRegistry(unittest.TestCase):
    """Положительный контроль из реальной жизни: реестр Tier-C, доставленный руками."""

    def test_generator_reproduces_tier_c_by_name(self):
        """Главный тест файла. Не сошлось — реестра Tier-B быть не должно.

        Сила контроля в том, что стороны собраны РАЗНЫМИ путями: реестр Tier-C
        доставлен 2026-08-26 по ADR-133, генератор написан 2026-08-29, и общий у них
        только сам замер. Совпадение поимённо здесь — не тавтология."""
        gen = _load_generator()
        report = gen.load_report("C", str(TIER_C_REPORT))
        sets = gen.build_sets(report)
        problems = gen.verify_against_existing("C", sets)
        self.assertEqual(problems, [],
                         "генератор не воспроизводит доставленный _tier_c_writeoff.py:\n"
                         + "\n".join(problems))

    def test_the_provenance_fixture_matches_the_delivered_registry(self):
        """Фикстура — провенанс, а не удобный снимок: протухла ⇒ контроль ослеп.

        Без этого теста предыдущий остался бы зелёным даже после того, как замер
        разойдётся с реальностью: обе стороны читались бы из одного устаревшего файла."""
        from spa_core.analytics import _tier_c_writeoff as delivered
        report = json.loads(TIER_C_REPORT.read_text(encoding="utf-8"))
        self.assertEqual(report["counts"].get("blind_constant"), len(delivered.WRITTEN_OFF))
        self.assertEqual(report["counts"].get("unchecked"), len(delivered.UNKNOWN_FROZEN))
        self.assertEqual(report["module_count"], 180)

    def test_verification_catches_a_wrong_generator(self):
        """ОТРИЦАТЕЛЬНЫЙ контроль: сверка обязана уметь краснеть.

        Без него предыдущий тест зелен и у сверки, которая всегда говорит «сошлось»."""
        gen = _load_generator()
        bogus = {"WRITTEN_OFF": {"модуль_которого_нет": "выдуманная причина"},
                 "BLIND_ACROSS_WIDE": {}, "UNKNOWN_FROZEN": [],
                 "DORMANT": {}, "FAILED": {}}
        problems = gen.verify_against_existing("C", bogus)
        self.assertTrue(problems,
                        "сверка приняла заведомо неверный состав — она ничего не проверяет")

    def test_verification_refuses_when_there_is_nothing_to_compare(self):
        """Отсутствие реестра — НЕ успех сверки (fail-CLOSED).

        Тир A реестра списания не имеет: «сравнивать не с чем» обязано читаться как
        отказ, иначе `--verify A` печатал бы зелёную галочку ни на чём."""
        gen = _load_generator()
        problems = gen.verify_against_existing("A", {"WRITTEN_OFF": {}})
        self.assertTrue(problems, "«реестра нет» прочиталось как успешная сверка")


class GeneratorClassSemantics(unittest.TestCase):
    """Классы замера ложатся в наборы по одному правилу и не смешиваются."""

    def test_constant_and_wide_blind_stay_separate_sets(self):
        """Улики РАЗНОЙ силы обязаны лежать в разных наборах.

        `blind_constant` доказан несуществующим контрольным протоколом.
        `blind_equal` — только отсутствием отличий на широкой вселенной: контрольный
        протокол не ответил, «константа» не доказана. Смешать значило бы выдать
        слабое доказательство за сильное — и списать модули по улике, которой нет."""
        gen = _load_generator()
        sets = gen.build_sets(_fake_report("B", [
            _row("const_one", "blind_constant", score=0.0),
            _row("wide_one", "blind_equal", score=10.0, wide_ok=32),
        ]))
        self.assertEqual(list(sets["WRITTEN_OFF"]), ["const_one"])
        self.assertEqual(list(sets["BLIND_ACROSS_WIDE"]), ["wide_one"])
        self.assertNotIn("wide_one", sets["WRITTEN_OFF"],
                         "слепой-на-широкой попал в списанные — улика подменена")

    def test_reason_comes_from_the_measurement_not_from_a_template(self):
        """Причина обязана нести ИЗМЕРЕННОЕ число, иначе это шаблон, а не замер."""
        gen = _load_generator()
        sets = gen.build_sets(_fake_report("B", [
            _row("const_42", "blind_constant", score=42.0)]))
        self.assertIn("42.0", sets["WRITTEN_OFF"]["const_42"],
                      "в причине нет измеренного значения константы")

    def test_frozen_carries_no_reason_because_the_reason_is_the_class(self):
        """«Позвать нечем» — причина одна на всех, и она в названии набора."""
        gen = _load_generator()
        sets = gen.build_sets(_fake_report("B", [_row("no_entry", "unchecked")]))
        self.assertEqual(list(sets["UNKNOWN_FROZEN"]), ["no_entry"])

    def test_report_for_the_wrong_tier_is_refused(self):
        """Fail-CLOSED: отчёт Tier-C, поданный как Tier-B, — не «почти то же самое»."""
        gen = _load_generator()
        with tempfile_report(_fake_report("C", [_row("x", "unchecked")])) as path:
            with self.assertRaises(Exception):
                gen.load_report("B", path)


class TierBRegistryContents(unittest.TestCase):
    """Реестр обязан описывать РЕАЛЬНЫЕ модули Tier-B, а не имена из головы."""

    def setUp(self):
        from spa_core.analytics import _tier_b_writeoff as reg
        self.reg = reg

    def test_every_listed_name_exists_in_tier_b(self):
        from spa_core.analytics import _module_registry as registry
        known = {m["module"] for m in registry.get_tier_modules("B")}
        missing = sorted(set(self.reg.ALL_LISTED) - known)
        self.assertEqual(missing, [], f"размечены несуществующие модули: {missing}")

    def test_sets_do_not_overlap(self):
        """Класс у модуля ровно один — пересечение означает двойной учёт в метрике."""
        buckets = {
            "WRITTEN_OFF": frozenset(self.reg.WRITTEN_OFF),
            "BLIND_ACROSS_WIDE": frozenset(self.reg.BLIND_ACROSS_WIDE),
            "UNKNOWN_FROZEN": frozenset(self.reg.UNKNOWN_FROZEN),
            "DORMANT": frozenset(self.reg.DORMANT),
            "FAILED": frozenset(self.reg.FAILED),
        }
        names = sorted(buckets)
        for i, left in enumerate(names):
            for right in names[i + 1:]:
                overlap = sorted(buckets[left] & buckets[right])
                self.assertEqual(overlap, [],
                                 f"{left} и {right} пересекаются: {overlap}")
        self.assertEqual(len(self.reg.ALL_LISTED), sum(len(b) for b in buckets.values()))

    def test_every_written_off_name_carries_a_measured_reason(self):
        for name, reason in self.reg.WRITTEN_OFF.items():
            self.assertIn("несуществующем контрольном", reason,
                          f"{name}: списан без улики контрольного протокола")

    def test_the_registry_matches_its_own_provenance_report(self):
        """Реестр обязан быть ФУНКЦИЕЙ замера, а не редактируемым списком.

        Прогоняем зафиксированный отчёт Tier-B через генератор и требуем совпадения
        поимённо. Правка реестра руками — хоть добавление, хоть удаление — краснеет
        здесь, и «поправить, чтобы стало зелено» невозможно, не тронув провенанс."""
        gen = _load_generator()
        sets = gen.build_sets(gen.load_report("B", str(TIER_B_REPORT)))
        for name in ("WRITTEN_OFF", "BLIND_ACROSS_WIDE", "DORMANT", "FAILED"):
            self.assertEqual(set(sets[name]), set(getattr(self.reg, name)),
                             f"{name} разошёлся с замером")
        self.assertEqual(set(sets["UNKNOWN_FROZEN"]), set(self.reg.UNKNOWN_FROZEN))
        self.assertEqual(self.reg.TIER_SIZE, 479)

    def test_the_two_blind_sets_together_are_exactly_the_existing_markup(self):
        """Сверка с НЕЗАВИСИМО выпущенной разметкой слепоты.

        `_protocol_blindness.py` пишет тот же аудит другой командой (`--emit-markup`)
        и в другой момент времени. Объединение моих двух наборов обязано совпасть с
        его `PROTOCOL_BLIND_MODULES` поимённо: одна и та же слепота, разложенная по
        силе улики, не может дать другой состав.

        Честная граница: обе стороны происходят из одного инструмента, поэтому это
        сверка ДВУХ ВЫПУСКОВ, а не двух независимых измерителей. Она ловит расхождение
        разметок и правку любого из файлов руками — но не общую ошибку аудита."""
        from spa_core.analytics import _protocol_blindness as markup
        mine = frozenset(self.reg.WRITTEN_OFF) | frozenset(self.reg.BLIND_ACROSS_WIDE)
        theirs = frozenset(markup.PROTOCOL_BLIND_MODULES)
        self.assertEqual(
            sorted(mine - theirs), [],
            "реестр называет слепыми модули, которых нет в разметке слепоты")
        self.assertEqual(
            sorted(theirs - mine), [],
            "разметка слепоты знает слепых, которых нет в реестре")

    def test_written_off_are_not_among_the_honest_passes(self):
        """Модуль не может быть одновременно списан и признан честно прошедшим.

        `WIDE_OK_MODULES` — те, кто на широкой вселенной ВСЁ-ТАКИ дал другое число,
        то есть протокол читает. Списать такого значило бы выбросить работающий."""
        from spa_core.analytics import _protocol_blindness as markup
        wide_ok = frozenset(markup.WIDE_OK_MODULES)
        self.assertTrue(wide_ok, "набор честных проходов пуст — тест потерял предмет")
        for bucket_name in ("WRITTEN_OFF", "BLIND_ACROSS_WIDE"):
            overlap = sorted(frozenset(getattr(self.reg, bucket_name)) & wide_ok)
            self.assertEqual(overlap, [],
                             f"{bucket_name} захватил честно прошедшие: {overlap}")


class TierBRegistryIsNotWiredYet(unittest.TestCase):
    """Граница решения: разметка есть, отключения — нет, пока владелец не ответил."""

    def test_aggregator_does_not_consume_the_tier_b_registry(self):
        """Списание Tier-C стало действовать ПОСЛЕ ответа владельца (ADR-133).

        Для Tier-B ответа ещё нет. Реестр обязан оставаться описанием, а не тихим
        отключением 166 модулей из живого советующего сигнала: это изменило бы
        `analytics_signals_advisory.json` по восьми протоколам без решения."""
        source = (REPO_ROOT / "spa_core" / "analytics"
                  / "signal_aggregator.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "_tier_b_writeoff", source,
            "агрегатор уже потребляет реестр Tier-B — это решение владельца, "
            "а оно не принято; см. карточку и ADR")


class _tempfile_report:
    def __init__(self, report):
        self.report = report

    def __enter__(self):
        import tempfile
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                               encoding="utf-8")
        json.dump(self.report, self.tmp, ensure_ascii=False)
        self.tmp.close()
        return self.tmp.name

    def __exit__(self, *exc):
        Path(self.tmp.name).unlink(missing_ok=True)
        return False


tempfile_report = _tempfile_report


if __name__ == "__main__":
    unittest.main()
