"""Порог применимости сторожа: где оверлею запрещено срабатывать (ADR-206).

Решение владельца 2026-09-01, вариант 1 (карточка
`own-storozh-sam-sozdaet-prosadku-na-rovnykh-knigakh`): **не пускать сторожа на ровные
книги.** Причина не в цене круга, а в МЕСТЕ применения: при любой ненулевой комиссии
оверлей на книге, чья просадка меньше стоимости его круга, может только ДОБАВИТЬ
просадку — и на замере 01.09 добавлял.

Каждый тест здесь — **положительный контроль на реальной аварии 2026-09-01**, а не на
придуманном ряде. Фикстура `fixtures/guardian_forward_flat_books_2026-09-01.json` —
дословный срез живого `data/aggressive_lab/<книга>/realized_series.jsonl` того дня
(51 точка хвоста backtest = ровно `WARMUP_POINTS`, которые читает `_guard_book`, плюс
все 27 forward-дней). Числа, которые он воспроизводит, — те самые, что в тот день
стояли в `data/swarm/guardian_forward.json`:

| книга | своя просадка | просадка «под защитой» | во сколько раз ХУЖЕ |
|---|---|---|---|
| `leverage_loop` | −0.019 % | **−0.4133 %** | 21.8× |
| `levered_restaking` | −0.0561 % | **−0.1691 %** | 3.0× |
| `lrt_neutral` | −5.2366 % | −0.15 % | защита настоящая — обратный контроль |

Проверка проверки: снять порог (вернуть `guardian_applicability` всегда `applicable`) —
и тесты класса «после починки» краснеют на этих же числах. `lrt_neutral` — обратный
контроль: починка, которая обезоружила бы настоящую защиту, тоже красная.

FROZEN-DATE-OK: дата в имени фикстуры и в датах forward-дней — предмет теста
(исторический замер конкретного дня), а не окружение; свежесть здесь не судится.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.strategy_lab.swarm import guardian_forward as gf

FIXTURE = Path(__file__).with_name("fixtures") / "guardian_forward_flat_books_2026-09-01.json"

#: Дословный снимок `data/swarm/guardian_forward.json` за 2026-09-01 — то, что сторож
#: показывал ДО порога. Ключ: (своя просадка книги, просадка «под защитой»).
REPORTED_2026_09_01 = {
    "leverage_loop": (-0.019, -0.4133),
    "levered_restaking": (-0.0561, -0.1691),
    "lrt_neutral": (-5.2366, -0.15),
}


def _book_dir(root: Path, name: str, doc: dict) -> Path:
    """Разложить срез фикстуры обратно в тот вид, из которого читает `_guard_book`."""
    d = root / name
    d.mkdir(parents=True)
    with (d / "realized_series.jsonl").open("w") as fh:
        for eq in doc["backtest"]:
            fh.write(json.dumps({"phase": "backtest", "equity_usd": eq}) + "\n")
        for date, eq in zip(doc["forward_dates"], doc["forward"]):
            fh.write(json.dumps({"phase": "forward", "date": date, "equity_usd": eq}) + "\n")
    (d / "meta.json").write_text(json.dumps({"risk_class": "aggressive"}))
    return d


class _Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(FIXTURE.read_text())

    def view(self, book: str) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            return gf._guard_book(_book_dir(Path(tmp), book, self.raw[book]))


class TestFixtureReplaysTheRealDay(_Fixture):
    """Сначала — что фикстура вообще воспроизводит аварию, а не соседнее число."""

    def test_fixture_reproduces_the_books_own_drawdown_verbatim(self):
        for book, (raw_dd, _) in REPORTED_2026_09_01.items():
            with self.subTest(book=book):
                self.assertEqual(self.view(book)["raw"]["max_dd_pct"], raw_dd)

    def test_without_the_gate_the_guardian_is_deeper_than_what_it_guards(self):
        """Сама авария: у двух книг «защищённая» просадка ГЛУБЖЕ собственной."""
        for book in ("leverage_loop", "levered_restaking"):
            with self.subTest(book=book):
                raw_dd, guarded_dd = REPORTED_2026_09_01[book]
                eq = [float(v) for v in self.raw[book]["backtest"]] 
                fwd = [float(v) for v in self.raw[book]["forward"]]
                scale = fwd[0] / eq[-1]
                combined = [v * scale for v in eq] + fwd[1:]
                fs = len(eq) - 1
                guarded, _, _ = gf.vol_guardian_trace(combined)  # оверлей БЕЗ порога
                got = gf._max_drawdown_pct([v / guarded[fs] for v in guarded[fs:]])
                self.assertEqual(got, guarded_dd)
                self.assertLess(got, raw_dd, "авария в том, что защита глубже охраняемого")


class TestFlatBooksAreLeftAlone(_Fixture):
    """Критерий готовности карточки: просадка в отчёте роя равна СОБСТВЕННОЙ просадке книги."""

    def test_guarded_drawdown_now_equals_the_books_own(self):
        for book in ("leverage_loop", "levered_restaking"):
            with self.subTest(book=book):
                v = self.view(book)
                self.assertEqual(v["state"], gf.NOTHING_TO_PROTECT)
                self.assertEqual(v["guarded"]["max_dd_pct"], v["raw"]["max_dd_pct"])
                self.assertEqual(v["guarded"]["max_dd_pct"], REPORTED_2026_09_01[book][0])

    def test_a_book_left_alone_pays_no_commission_and_shows_no_events(self):
        v = self.view("leverage_loop")
        self.assertEqual(v["derisk_events_forward"], [])
        self.assertEqual(v["exposure_now"], 1.0)
        self.assertEqual(v["guarded"]["apy_pct"], v["raw"]["apy_pct"])

    def test_the_refusal_is_named_not_silent(self):
        """«Не сработал» обязано отличаться от «сработал и ничего не нашёл»."""
        a = self.view("leverage_loop")["applicability"]
        self.assertFalse(a["applicable"])
        self.assertEqual(a["reason"], "nothing_to_protect")
        self.assertEqual(a["round_trip_cost_pct"], 0.15)
        self.assertIn("защищать нечего", a["note"])


class TestRealProtectionSurvives(_Fixture):
    """Обратный контроль: починка, обезоружившая бы настоящую защиту, — тоже авария."""

    def test_a_book_with_real_drawdown_stays_guarded(self):
        v = self.view("lrt_neutral")
        raw_dd, guarded_dd = REPORTED_2026_09_01["lrt_neutral"]
        self.assertNotEqual(v["state"], gf.NOTHING_TO_PROTECT)
        self.assertEqual(v["applicability"]["reason"], "dd_exceeds_round_trip")
        self.assertEqual(v["raw"]["max_dd_pct"], raw_dd)
        self.assertEqual(v["guarded"]["max_dd_pct"], guarded_dd)
        self.assertGreater(v["guarded"]["max_dd_pct"], v["raw"]["max_dd_pct"])
        self.assertTrue(v["derisk_events_forward"])


class TestThresholdIsDerivedNotLiteral(unittest.TestCase):
    """Порог обязан следовать за ценой круга — иначе это второе, расходящееся число."""

    def test_cost_follows_the_params_the_overlay_actually_charges(self):
        self.assertEqual(gf.round_trip_cost_pct(), 0.15)
        self.assertEqual(gf.round_trip_cost_pct(roundtrip_cost=0.01), 1.0)
        self.assertEqual(gf.round_trip_cost_pct(roundtrip_cost=0.0015, derisk_frac=0.5), 0.075)

    def test_the_verdict_moves_with_the_cost_not_with_a_constant(self):
        window = [1.0] * 11 + [0.995, 1.0]  # своя просадка 0.5 %
        self.assertTrue(gf.guardian_applicability(window)["applicable"])
        self.assertFalse(gf.guardian_applicability(window, roundtrip_cost=0.01)["applicable"])


class TestAbsenceOfMeasurementNeverDisarms(unittest.TestCase):
    """Инвариант #17 в самом пороге: снять защиту может только ПОЛОЖИТЕЛЬНОЕ измерение."""

    def test_empty_and_short_windows_leave_the_guardian_armed(self):
        for window in ([], [1.0], [1.0, 1.0], [1.0] * 11):
            with self.subTest(points=len(window)):
                a = gf.guardian_applicability(window)
                self.assertTrue(a["applicable"])
                self.assertEqual(a["reason"], "dd_unmeasured")
                self.assertIsNone(a["raw_max_dd_pct"])

    def test_a_window_long_enough_to_judge_is_judged(self):
        a = gf.guardian_applicability([1.0] * (gf.GUARDIAN_PARAMS["lookback"] + 2))
        self.assertFalse(a["applicable"])
        self.assertEqual(a["reason"], "nothing_to_protect")

    def test_a_broken_window_does_not_disarm(self):
        self.assertEqual(gf.guardian_applicability([0.0] * 20)["reason"], "dd_unmeasured")


class TestShadowDomainsUseTheSameThreshold(unittest.TestCase):
    """Тень читают при отборе теми же глазами — врать ей нельзя тем же способом."""

    def test_a_flat_shadow_series_is_left_alone_and_says_so(self):
        eq = [1.0 + 0.0001 * i for i in range(60)]
        v = gf._guard_shadow([f"d{i}" for i in range(60)], eq, domain="t")
        self.assertEqual(v["state"], gf.NOTHING_TO_PROTECT)
        self.assertEqual(v["what_if"]["guarded_max_dd_pct"], v["what_if"]["raw_max_dd_pct"])
        self.assertEqual(v["derisk_events"], [])

    def test_a_volatile_shadow_series_is_still_guarded(self):
        eq = [100.0]
        for i in range(60):
            eq.append(eq[-1] * (1.0 + (0.05 if i % 7 == 3 else -0.02)))
        v = gf._guard_shadow([f"d{i}" for i in range(len(eq))], eq, domain="t")
        self.assertNotEqual(v["state"], gf.NOTHING_TO_PROTECT)
        self.assertEqual(v["applicability"]["reason"], "dd_exceeds_round_trip")


if __name__ == "__main__":
    unittest.main()
