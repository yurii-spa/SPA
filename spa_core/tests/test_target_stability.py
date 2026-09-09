"""Приёмка `spa_core/monitoring/target_stability.py` (заказ CIO G5→G6).

Каждая сцена здесь — положительный контроль на конкретную ошибку, а не
украшение: сторож, ни разу не видевший настоящей поломки, ничего не держит
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Литеральных дат в файле нет вовсе: модуль спрашивает часы ровно один раз и
только чтобы проштамповать ``generated_at`` — свежесть он не судит, поэтому
календарь хоста на вердикт не влияет по построению, а не по договорённости.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict

from spa_core.allocator import allocation_models as models
from spa_core.monitoring.target_stability import (
    STATUS_CRITICAL,
    STATUS_OK,
    STATUS_UNMEASURED,
    STATUS_WARNING,
    find_margin,
    live_apy_map,
    measure,
    measure_injection_doors,
    observed_daily_moves,
    one_sided_move,
    run,
)

CAPITAL = 100_000.0


# ──────────────────────────────────────────────────────────────────────────
# стенд: минимальный снимок + подставной производитель цели
# ──────────────────────────────────────────────────────────────────────────
def _status_doc(rates_pp: Dict[str, float], *, nulls=()) -> dict:
    adapters: Dict[str, dict] = {
        p: {"live_apy": v, "apy": v, "fallback_apy": 99.0}
        for p, v in rates_pp.items()}
    for p in nulls:
        adapters[p] = {"live_apy": None, "apy": None, "fallback_apy": 99.0}
    return {"schema_version": 2, "adapters": adapters}


def _write_snapshot(data_dir: Path, rates_pp: Dict[str, float], *, nulls=()) -> None:
    (data_dir / "adapter_status.json").write_text(
        json.dumps(_status_doc(rates_pp, nulls=nulls)), encoding="utf-8")


def _write_history(data_dir: Path, series: Dict[str, list]) -> None:
    """Журнал решений: по строке на день, ``apy_evidenced_pct`` — наблюдение."""
    n = max((len(v) for v in series.values()), default=0)
    with open(data_dir / "allocation_rationale_history.jsonl", "w",
              encoding="utf-8") as fh:
        for i in range(n):
            row = {"cycle_date": f"2026-08-{i + 1:02d}",
                   "apy_evidenced_pct": {p: v[i] for p, v in series.items()
                                         if i < len(v)}}
            fh.write(json.dumps(row) + "\n")


def _greedy_producer(caps: Dict[str, float], *, cash_floor: float = 0.60):
    """Тот же принцип, что у живого производителя: жадный рюкзак по потолкам.

    ``cash_floor`` по умолчанию делает бюджет СВЯЗЫВАЮЩИМ (0.40 при потолках
    0.40): иначе оба протокола получают свой потолок независимо от порядка,
    ступени нет вовсе, и сцена измеряла бы отсутствие предмета. Ровно на этом
    первая редакция файла давала «маржа = None» там, где она мала.

    Нужен там, где сцена должна ЗАДАТЬ форму ступени, а не унаследовать её от
    сегодняшнего снимка. Совпадение принципа с настоящей моделью проверяется
    отдельной сценой ниже (`test_real_model_pours_the_full_cap_to_the_winner`),
    поэтому это не «вторая реализация правил», а стенд.
    """
    def factory(_sandbox: Path):
        def produce(provider: Dict[str, float]) -> Dict[str, float]:
            order = sorted(provider.items(), key=lambda kv: (-kv[1], kv[0]))
            budget = 1.0 - cash_floor
            out: Dict[str, float] = {}
            for proto, _rate in order:
                if budget <= 1e-12:
                    break
                room = min(caps.get(proto, 0.0), budget)
                if room <= 1e-12:
                    continue
                out[proto] = round(room * CAPITAL, 2)
                budget -= room
            return out
        return produce
    return factory


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


# ──────────────────────────────────────────────────────────────────────────
# 1. ЯДРО: усиление шума до хода размером с потолок
# ──────────────────────────────────────────────────────────────────────────
class TestAmplification(_Base):
    def test_real_model_pours_the_full_cap_to_the_winner(self):
        """Замер 09.09: величина победы в размер порции НЕ входит.

        Это и есть форма, из-за которой шум усиливается: две ничьи, зазор
        0.0002 pp — и между ними переезжает ПОЛНЫЙ потолок T1 (40 % капитала).
        Сцена стои́т на НАСТОЯЩЕЙ модели, а не на стенде: если однажды
        ``optimized_yield_breakdown`` перестанет наливать по потолок, эта
        сцена обязана покраснеть первой.
        """
        caps = {"alpha": 0.40, "beta": 0.40}
        adapters = [{"protocol": "alpha", "apy_pct": 4.2907, "tier": "T1"},
                    {"protocol": "beta", "apy_pct": 4.2905, "tier": "T1"}]
        # cash_floor=0.60 ⇒ бюджет 0.40 = ровно один потолок: ступень видна.
        won = models.optimized_yield_breakdown(
            adapters, {}, tier_caps=caps, t2_total_cap=0.5, cash_floor=0.60)
        self.assertAlmostEqual(won["weights"]["alpha"], 0.40, places=9)
        self.assertNotIn("beta", won["weights"])

        adapters[1]["apy_pct"] = 4.2909  # +0.0004 pp у соседа
        flipped = models.optimized_yield_breakdown(
            adapters, {}, tier_caps=caps, t2_total_cap=0.5, cash_floor=0.60)
        self.assertAlmostEqual(flipped["weights"]["beta"], 0.40, places=9)
        moved = one_sided_move(
            {k: v * CAPITAL for k, v in won["weights"].items()},
            {k: v * CAPITAL for k, v in flipped["weights"].items()})
        # 0.0004 pp на входе -> десятки тысяч долларов на выходе.
        self.assertGreaterEqual(moved, 0.30 * CAPITAL)

    def test_margin_is_tiny_when_two_rates_are_nearly_tied(self):
        produce = _greedy_producer({"alpha": 0.40, "beta": 0.40})(Path("."))
        provider = {"alpha": 0.042907, "beta": 0.042905}
        base = produce(provider)
        margin = find_margin(produce, base, provider, "beta", +1,
                             capital_usd=CAPITAL)
        self.assertIsNotNone(margin)
        assert margin is not None
        self.assertLess(margin, 0.01)

    def test_reported_margin_is_the_NEARER_of_the_two_directions(self):
        """Маржа в ОТЧЁТЕ — расстояние до БЛИЖАЙШЕГО края, не до дальнего.

        Мутация ``min``→``max`` пережила две редакции этого файла. Первая не
        имела сцены вовсе; вторая звала ``find_margin`` по направлениям
        напрямую и потому не трогала ту строку ``measure``, где из двух
        направлений выбирается одно. Сцена обязана идти ТЕМ ЖЕ путём, каким
        число попадает в отчёт, — иначе она проверяет соседа, а не предмет.

        Стенд: ``gamma`` долит остатком бюджета, поэтому у него КОНЕЧНЫ обе
        стороны — вверх до обгона ``beta`` (≈1.0 pp), вниз до потери остатка
        в пользу ``delta`` (≈0.01 pp). Назови отчёт дальнюю, и книга выглядела
        бы в сто раз устойчивее, чем она есть.
        """
        caps = {"alpha": .20, "beta": .20, "gamma": .20, "delta": .20}
        _write_snapshot(self.data, {"alpha": 5.00, "beta": 4.00,
                                    "gamma": 3.00, "delta": 2.99})
        _write_history(self.data, {p: [4.0, 4.0] for p in caps})
        doc = measure(self.data,
                      producer_factory=_greedy_producer(caps, cash_floor=0.45),
                      capital_usd=CAPITAL)
        gamma = next(r for r in doc["protocols"] if r["protocol"] == "gamma")
        self.assertIsNotNone(gamma["margin_up_pp"])
        self.assertIsNotNone(gamma["margin_down_pp"])
        self.assertGreater(gamma["margin_up_pp"], gamma["margin_down_pp"])
        self.assertEqual(gamma["margin_pp"], gamma["margin_down_pp"])

    def test_margin_is_large_when_the_rival_is_far_away(self):
        produce = _greedy_producer({"alpha": 0.40, "beta": 0.40})(Path("."))
        provider = {"alpha": 0.0800, "beta": 0.0300}
        base = produce(provider)
        margin = find_margin(produce, base, provider, "beta", +1,
                             capital_usd=CAPITAL)
        self.assertIsNotNone(margin)
        assert margin is not None
        self.assertGreater(margin, 4.0)


# ──────────────────────────────────────────────────────────────────────────
# 2. КОНТРОЛЬ ДЕТЕРМИНИЗМА — буква заказа #534
# ──────────────────────────────────────────────────────────────────────────
class TestDeterminism(_Base):
    def test_same_frozen_inputs_reproduce_the_same_target(self):
        _write_snapshot(self.data, {"alpha": 5.0, "beta": 4.0})
        _write_history(self.data, {"alpha": [5.0, 5.0], "beta": [4.0, 4.0]})
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        self.assertEqual(doc["determinism"], "reproduced")

    def test_nondeterministic_producer_is_CRITICAL_and_margins_are_withheld(self):
        """Недетерминированный производитель обесценивает КАЖДУЮ маржу.

        Молча посчитать их поверх такого производителя значило бы выдать
        случайные числа за замер — сторож обязан остановиться и сказать.
        """
        state = {"n": 0}

        def factory(_sandbox: Path):
            def produce(_provider):
                state["n"] += 1
                return {"alpha": 40000.0 + state["n"]}
            return produce

        _write_snapshot(self.data, {"alpha": 5.0})
        _write_history(self.data, {"alpha": [5.0, 5.0]})
        doc = measure(self.data, producer_factory=factory, capital_usd=CAPITAL)
        self.assertEqual(doc["determinism"], "DIVERGED")
        self.assertEqual(doc["status"], STATUS_CRITICAL)
        self.assertEqual(doc["protocols"], [])
        self.assertTrue(any("НЕДЕТЕРМИНИРОВАН" in f for f in doc["findings"]))


# ──────────────────────────────────────────────────────────────────────────
# 3. ДВЕРИ ИНЪЕКЦИИ — «половина инъекции» это та же бомба (урок #453)
# ──────────────────────────────────────────────────────────────────────────
class TestInjectionDoors(_Base):
    def test_provider_only_door_is_measured_not_assumed(self):
        produce = _greedy_producer({"alpha": .4, "beta": .4})(self.data)
        (self.data / "adapter_status.json").write_text(
            json.dumps(_status_doc({"alpha": 5.0, "beta": 4.0})), encoding="utf-8")
        provider = {"alpha": 0.05, "beta": 0.04}
        base = produce(provider)
        out = measure_injection_doors(produce, self.data, provider, base, "beta")
        self.assertEqual(out["verdict"], "provider_is_the_only_door")
        self.assertEqual(out["file_only_moved_usd"], 0.0)

    def test_second_door_refuses_to_report_margins(self):
        """Производитель, читающий ЕЩЁ и файл, делает возмущение неполным.

        Это ровно авария #453 в своей форме: параметр есть, но путь к ОС
        (здесь — к файлу) остался открыт. Сторож обязан отказать, а не
        посчитать маржи по половине входа.
        """
        status_path = self.data / "adapter_status.json"
        status_path.write_text(json.dumps(_status_doc({"alpha": 5.0, "beta": 4.0})),
                               encoding="utf-8")

        def factory(sandbox: Path):
            def produce(provider):
                doc = json.loads((sandbox / "adapter_status.json").read_text())
                merged = dict(provider)
                for p, e in doc["adapters"].items():
                    if e.get("live_apy") is not None:
                        merged[p] = float(e["live_apy"]) / 100.0
                return _greedy_producer({"alpha": .4, "beta": .4})(sandbox)(merged)
            return produce

        _write_history(self.data, {"alpha": [5.0, 5.0], "beta": [4.0, 4.0]})
        doc = measure(self.data, producer_factory=factory, capital_usd=CAPITAL)
        self.assertEqual(doc["injection_doors"]["verdict"], "file_also_moves_target")
        self.assertEqual(doc["status"], STATUS_UNMEASURED)
        self.assertEqual(doc["protocols"], [])

    def test_probe_direction_is_measured_not_assumed(self):
        """Якорь налит ПО ПОТОЛОК: подъём его ставки не двигает ничего.

        Первая редакция пробы поднимала именно якорь и получала «двери
        различить нельзя» на входе, где ответ есть (замер 09.09). Направление
        обязано выбираться замером: −3 pp якорь роняет и двери различает.
        """
        produce = _greedy_producer({"alpha": .4, "beta": .4})(self.data)
        (self.data / "adapter_status.json").write_text(
            json.dumps(_status_doc({"alpha": 5.0, "beta": 4.0})), encoding="utf-8")
        provider = {"alpha": 0.05, "beta": 0.04}
        base = produce(provider)
        out = measure_injection_doors(produce, self.data, provider, base, "alpha")
        self.assertEqual(out["verdict"], "provider_is_the_only_door")
        self.assertEqual(out["delta_pp"], -3.0)

    def test_probe_that_moves_nothing_says_unmeasured(self):
        def factory(_s: Path):
            return lambda _p: {"alpha": 40000.0}
        (self.data / "adapter_status.json").write_text(
            json.dumps(_status_doc({"alpha": 5.0})), encoding="utf-8")
        out = measure_injection_doors(factory(self.data), self.data,
                                      {"alpha": 0.05}, {"alpha": 40000.0}, "alpha")
        self.assertEqual(out["verdict"], "unmeasured")


# ──────────────────────────────────────────────────────────────────────────
# 4. ТРЕТИЙ ИСХОД — «не измерено» не есть ни ноль, ни «прошло»
# ──────────────────────────────────────────────────────────────────────────
class TestThirdOutcome(_Base):
    def test_protocol_without_history_is_unmeasured_not_stable(self):
        """Ноль наблюдений НЕ выдаётся за «шума нет».

        Замер 09.09: у ``fluid_fusdc`` маржа есть, а хода ставки в журнале
        нет вовсе (перепись входов там неполна). Записать его в «маржа держит»
        значило бы объявить устойчивым то, что не измерялось.
        """
        _write_snapshot(self.data, {"alpha": 4.2907, "beta": 4.2905})
        _write_history(self.data, {"alpha": [4.29, 4.29]})   # beta истории НЕ имеет
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        beta = next(r for r in doc["protocols"] if r["protocol"] == "beta")
        self.assertEqual(beta["verdict"], "unmeasured")
        self.assertIn("beta", doc["unmeasured"])
        self.assertNotEqual(beta["verdict"], "margin_holds")

    def test_unreadable_snapshot_is_unmeasured_with_a_named_reason(self):
        (self.data / "adapter_status.json").write_text("{ not json",
                                                       encoding="utf-8")
        doc = measure(self.data, capital_usd=CAPITAL)
        self.assertEqual(doc["status"], STATUS_UNMEASURED)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))
        self.assertEqual(doc["protocols"], [])

    def test_snapshot_without_any_observation_is_unmeasured(self):
        _write_snapshot(self.data, {}, nulls=("alpha", "beta"))
        doc = measure(self.data, capital_usd=CAPITAL)
        self.assertEqual(doc["status"], STATUS_UNMEASURED)

    def test_unchecked_is_counted_separately_from_zeros(self):
        """Растворив «не измерено» в нулях, прибор замолчал бы незаметно.

        Проверяется ИМЕННО ``run`` — форма, которую читают ступень переписей и
        шаг 0-офис. Прежняя редакция этой сцены уходила в обходную ветку и
        ``counts`` не трогала вовсе: обнуление счётчика проходило мимо неё.
        """
        root = self.data / "root"
        (root / "data").mkdir(parents=True)
        _write_snapshot(root / "data", {"alpha": 4.2907, "beta": 4.2905})
        _write_history(root / "data", {"alpha": [4.29, 4.29]})
        doc = run(root=str(root), write=False,
                  producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                  capital_usd=CAPITAL)
        self.assertIn("beta", doc["unmeasured"])
        self.assertGreaterEqual(doc["counts"]["unchecked"], 1)
        self.assertEqual(doc["counts"]["unchecked"],
                         len(doc["unmeasured"]))

    def test_no_move_in_range_is_an_answer_not_a_refusal(self):
        """«Ставку не подними так, чтобы вошёл» — это ОТВЕТ, а не отказ.

        Такой протокол связан не ставкой (у нас — TVL-полом MP-011), и путать
        его с «не измерено» нельзя: причины разные и починки разные.
        """
        produce = _greedy_producer({"alpha": .4, "beta": 0.0})(Path("."))
        provider = {"alpha": 0.05, "beta": 0.04}
        base = produce(provider)
        self.assertIsNone(find_margin(produce, base, provider, "beta", +1,
                                      capital_usd=CAPITAL))


# ──────────────────────────────────────────────────────────────────────────
# 5. ВЕРДИКТ и АГРЕГАТ
# ──────────────────────────────────────────────────────────────────────────
class TestVerdicts(_Base):
    def test_noise_decided_when_the_rate_crosses_its_own_margin_often(self):
        _write_snapshot(self.data, {"alpha": 4.2907, "beta": 4.2905})
        # beta ходит на 0.5 pp в день — во много раз больше своей маржи.
        _write_history(self.data, {"alpha": [4.29] * 6,
                                   "beta": [4.29, 4.79, 4.29, 4.79, 4.29, 4.79]})
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        beta = next(r for r in doc["protocols"] if r["protocol"] == "beta")
        self.assertEqual(beta["verdict"], "noise_decided")
        self.assertEqual(doc["status"], STATUS_CRITICAL)

    def test_frequency_counts_moves_at_the_margin_itself(self):
        """Счёт идёт по ``>=`` маржи, и сцена стои́т ВПРИТЫК к ней.

        Прежние сцены имели ходы в тысячи раз больше маржи — при них любое
        условие счёта давало один и тот же вердикт, и подмена порога прошла
        бы молча. Здесь ход подобран чуть выше маржи: сдвинь условие — и
        ``noise_decided`` схлопнется в ``margin_holds``.
        """
        produce = _greedy_producer({"alpha": .4, "beta": .4})(Path("."))
        provider = {"alpha": 0.0500, "beta": 0.0480}
        base = produce(provider)
        margin = find_margin(produce, base, provider, "beta", +1,
                             capital_usd=CAPITAL)
        self.assertIsNotNone(margin)
        assert margin is not None
        self.assertAlmostEqual(margin, 0.20, places=2)

        step = margin * 1.05          # чуть больше маржи, а не кратно ей
        _write_snapshot(self.data, {"alpha": 5.00, "beta": 4.80})
        _write_history(self.data, {
            "alpha": [5.0] * 7,
            "beta": [4.80 + (step if i % 2 else 0.0) for i in range(7)]})
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        beta = next(r for r in doc["protocols"] if r["protocol"] == "beta")
        self.assertEqual(beta["verdict"], "noise_decided")
        self.assertEqual(beta["days_exceeding_margin"], 6)

    def test_margin_holds_when_the_rate_never_crosses_it(self):
        _write_snapshot(self.data, {"alpha": 8.0, "beta": 3.0})
        _write_history(self.data, {"alpha": [8.0] * 6,
                                   "beta": [3.0, 3.001, 3.0, 3.001, 3.0, 3.001]})
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        beta = next(r for r in doc["protocols"] if r["protocol"] == "beta")
        self.assertEqual(beta["verdict"], "margin_holds")
        self.assertIn(doc["status"], (STATUS_OK, STATUS_WARNING))

    def test_aggregate_is_a_floor_and_excludes_the_unmeasured(self):
        """Сумму нельзя раздувать неизмеренным — иначе это уже не замер.

        Обратная ошибка (записать неизмеренное в «устойчиво») закрыта сценой
        `test_protocol_without_history_is_unmeasured_not_stable`; здесь —
        вторая сторона той же дисциплины.
        """
        _write_snapshot(self.data, {"alpha": 4.2907, "beta": 4.2905})
        _write_history(self.data, {"beta": [4.29, 4.79, 4.29, 4.79, 4.29, 4.79]})
        doc = measure(self.data,
                      producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                      capital_usd=CAPITAL)
        alpha = next(r for r in doc["protocols"] if r["protocol"] == "alpha")
        self.assertEqual(alpha["verdict"], "unmeasured")
        self.assertNotIn(alpha["target_usd"],
                         (doc.get("capital_on_noise_decided_usd"),))
        self.assertTrue(any("ПОЛ, а не потолок" in f for f in doc["findings"]))


# ──────────────────────────────────────────────────────────────────────────
# 6. ВХОДЫ: провенанс наблюдения и единицы
# ──────────────────────────────────────────────────────────────────────────
class TestInputs(_Base):
    def test_null_observation_never_falls_back_to_a_literal(self):
        """ADR-061: ``live_apy: null`` значит «не наблюдали».

        Подставить сюда ``fallback_apy`` значило бы измерять устойчивость
        выдуманного входа — ровно то, против чего написан ADR-061.
        """
        doc = _status_doc({"alpha": 5.0}, nulls=("beta",))
        self.assertEqual(live_apy_map(doc), {"alpha": 0.05})

    def test_percent_is_converted_to_the_provider_decimal_contract(self):
        self.assertEqual(live_apy_map(_status_doc({"alpha": 4.2907})),
                         {"alpha": 0.042907})

    def test_observed_moves_are_adjacent_day_differences(self):
        _write_history(self.data, {"alpha": [4.0, 4.5, 4.1]})
        moves, err, rows = observed_daily_moves(self.data)
        self.assertEqual(err, "")
        self.assertEqual(rows, 3)
        self.assertEqual([round(x, 6) for x in moves["alpha"]], [0.5, 0.4])

    def test_single_observation_yields_no_move_series(self):
        """Одна отметка — это НЕ «ход равен нулю»."""
        _write_history(self.data, {"alpha": [4.0]})
        moves, _err, _rows = observed_daily_moves(self.data)
        self.assertNotIn("alpha", moves)

    def test_unreadable_history_is_named_not_silently_empty(self):
        moves, err, rows = observed_daily_moves(self.data / "nope")
        self.assertEqual(moves, {})
        self.assertTrue(err)
        self.assertEqual(rows, 0)


# ──────────────────────────────────────────────────────────────────────────
# 7. ПЕСОЧНИЦА: живое data/ прибор не трогает
# ──────────────────────────────────────────────────────────────────────────
class TestSandboxDiscipline(_Base):
    def test_measure_leaves_the_data_dir_byte_identical(self):
        """Проба дверей ПИШЕТ в снимок — обязана писать только в копию.

        Напиши она в переданный каталог, прибор правил бы живое состояние
        книги ради собственного замера (`.claude/rules/deployment.md`, п. 4).
        """
        _write_snapshot(self.data, {"alpha": 5.0, "beta": 4.0})
        _write_history(self.data, {"alpha": [5.0, 5.0], "beta": [4.0, 4.1]})
        before = {p.name: p.read_bytes() for p in sorted(self.data.iterdir())}
        measure(self.data,
                producer_factory=_greedy_producer({"alpha": .4, "beta": .4}),
                capital_usd=CAPITAL)
        after = {p.name: p.read_bytes() for p in sorted(self.data.iterdir())}
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
