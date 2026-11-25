"""ADR-1102 — живое число без ЗАКРЕПЛЁННОГО пула и один пул под двумя ключами.

Почему этот файл существует
---------------------------
ADR-398 установил дисциплину дословно: **хинту запрещено штамповать TVL `live`** — «побеждает
больший TVL» есть тождество, способное молча уехать, а пин делает наблюдение предъявимым.
Дисциплину применили к `adapter_status.json`. Замер 2026-11-25 на живом каталоге показал, что
к ПОВЕРХНОСТИ РЕШЕНИЯ (`current_positions.json.feed_coverage.tvl_sources` — карта, по которой
ADR-053 проверяет пол $5M) её не применил никто:

    ключей с объявленным наблюдением TVL                 17
    из них пул НЕ ЗАКРЕПЛЁН                               3   euler_v2 · morpho_blue · yearn_v3
    собственное поле третьего исхода `tvl_floor_unverified` [] — «ничего не отсутствует»
    один пул 931ea9be под ДВУМЯ ключами   morpho_blue(hint) + morpho_steakhouse(pinned)
    структурный предел пары                              60 % при потолке корзины T2 50 %
    тождество morpho_blue решают 64 соперника с разрывом ставки 0.0053 пп

Ближайший сторож (`pool_identity_collision`) эту пару не берёт ПО ПОСТРОЕНИЮ: его род
`declared` требует, чтобы ключ ОБЪЯВИЛ свой пул, а хинтовый его УГАДЫВАЕТ — оговорка сказана
в самом стороже вслух.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* каждый класс находки имеет положительный контроль, воспроизводящий ИЗМЕРЕННУЮ сцену, и
  обратный контроль на том же приборе: пин ⇒ молчание, один ключ на пул ⇒ молчание;
* порог НЕ перепечатан: пол и потолок корзины сверяются с `RiskConfig` — вторая копия
  разошлась бы молча (`.claude/rules/site-numbers.md`);
* третий исход (инв. #17) различим у КАЖДОЙ двери: нет каталога · нет `feed_coverage` · нет
  `tvl_sources` · нет секции `adapters` · ключа нет во втором артефакте · `pool_match` не
  объявлен · пул не назван. «Пула не названо» НИКОГДА не выдаётся за «коллизий нет»;
* измеренный ноль печатается С НАСЕЛЕНИЕМ: «чисто» обязано быть отличимо от «сверять было
  нечего»;
* находки + неизмеренное ⇒ код 1 и СКАЗАННАЯ нижняя граница: молчаливый код 2 похоронил бы
  названные находки.

Часов у прибора нет вовсе: он не судит о свежести ни одного артефакта, поэтому ни литеральной
даты, ни инъекции часов здесь не требуется — и это НАЗВАННОЕ свойство, а не недосмотр
(`.claude/rules/deployment.md` § «Время в тестах»). Сеть не трогается: фид не зовётся ни раз.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.risk.policy import RiskConfig

import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "pinned_identity_collision_census",
    Path(__file__).resolve().parents[2] / "scripts" / "pinned_identity_collision_census.py",
)
assert _SPEC and _SPEC.loader
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)


def _entry(pool: str, match: str, *, tvl: float, source: str,
           cap: float | None = 0.2, rivals: dict | None = None) -> dict:
    e = {
        "pool_id": pool,
        "pool_match": match,
        "tvl_usd": tvl,
        "tvl_source": source,
        "tier": 2,
    }
    if cap is not None:
        e["per_protocol_cap"] = cap
    if rivals is not None:
        e["hint_rivals"] = rivals
    return e


def _scene(tmp: Path, *, surface: dict, entries: dict,
           tvl_values: dict | None = None, positions: dict | None = None,
           unverified: object = (), drop: str | None = None) -> Path:
    """Одноразовая сцена из ДВУХ артефактов. `drop` снимает названный ключ книги."""
    coverage = {"tvl_sources": surface, "tvl_usd": dict(tvl_values or {})}
    if unverified != ():
        coverage["tvl_floor_unverified"] = unverified
    book = {"generated_at": "scene", "positions": dict(positions or {}),
            "feed_coverage": coverage}
    if drop == "feed_coverage":
        book.pop("feed_coverage")
    elif drop == "tvl_sources":
        book["feed_coverage"].pop("tvl_sources")
    status = {"generated_at": "scene", "adapters": dict(entries)}
    if drop == "adapters":
        status.pop("adapters")
    (tmp / "current_positions.json").write_text(json.dumps(book), encoding="utf-8")
    (tmp / "adapter_status.json").write_text(json.dumps(status), encoding="utf-8")
    return tmp


class LiveWithoutAPinTest(unittest.TestCase):
    """Ось 1 — поверхность объявила наблюдение, а пул не закреплён."""

    def test_the_measured_incident_is_found(self):
        """Положительный контроль: сцена замера 25.11 по трём ключам."""
        with TemporaryDirectory() as d:
            t = _scene(
                Path(d),
                surface={"euler_v2": "live", "morpho_blue": "live", "yearn_v3": "live"},
                tvl_values={"euler_v2": 369_686.0, "morpho_blue": 114_724_290.0,
                            "yearn_v3": 18_321_536.0},
                entries={
                    "euler_v2": _entry("a0f53224", "hint", tvl=150_000_000.0, source="static"),
                    "morpho_blue": _entry("931ea9be", "hint", tvl=2_000_000_000.0,
                                          source="static",
                                          rivals={"count": 64, "apy_spread_pp": 0.0053}),
                    "yearn_v3": _entry("7d89af7a", "hint", tvl=300_000_000.0, source="static"),
                },
                unverified=[],
            )
            r = census.measure(str(t))
        self.assertEqual({row["protocol"] for row in r["live_by_hint"]},
                         {"euler_v2", "morpho_blue", "yearn_v3"})
        self.assertEqual(r["surface_live_keys"], 3)
        self.assertEqual(r["pin_unmeasured"], [])
        self.assertTrue(census._findings(r))

    def test_a_pinned_pool_is_silent(self):
        """Обратный контроль: тот же прибор, пин вместо хинта ⇒ ни одной находки."""
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"fluid_fusdc": "live"},
                       tvl_values={"fluid_fusdc": 151_197_413.0},
                       entries={"fluid_fusdc": _entry("4438dabc", "pinned",
                                                      tvl=151_197_413.0, source="live")})
            r = census.measure(str(t))
        self.assertEqual(r["live_by_hint"], [])
        self.assertFalse(census._findings(r))

    def test_the_floor_consequence_is_named_per_key(self):
        """Последствие — проходит ли ЖИВОЕ число пол; порог берётся у RiskConfig."""
        floor = RiskConfig().min_tvl_usd
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"small": "live", "big": "live"},
                       tvl_values={"small": floor - 1.0, "big": floor + 1.0},
                       entries={"small": _entry("p1", "hint", tvl=1.0, source="static"),
                                "big": _entry("p2", "hint", tvl=1.0, source="static")})
            r = census.measure(str(t))
        got = {row["protocol"]: row["passes_floor"] for row in r["live_by_hint"]}
        self.assertEqual(got, {"small": False, "big": True})

    def test_a_key_the_surface_calls_static_is_not_judged(self):
        """Прибор спрашивает ТОЛЬКО о числах, которые поверхность назвала наблюдением."""
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"moonwell_base": "static"},
                       entries={"moonwell_base": _entry("p9", "hint", tvl=1.0,
                                                        source="static")})
            r = census.measure(str(t))
        self.assertEqual(r["surface_live_keys"], 0)
        self.assertEqual(r["live_by_hint"], [])

    def test_funded_keys_are_marked_and_zero_is_not_funded(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"held": "live", "empty": "live"},
                       tvl_values={"held": 1.0, "empty": 1.0},
                       positions={"held": 20_000.0, "empty": 0.0},
                       entries={"held": _entry("p1", "hint", tvl=1.0, source="static"),
                                "empty": _entry("p2", "hint", tvl=1.0, source="static")})
            r = census.measure(str(t))
        self.assertEqual(r["funded_keys"], ["held"])
        self.assertEqual({row["protocol"]: row["funded"] for row in r["live_by_hint"]},
                         {"held": True, "empty": False})


class OnePoolTwoKeysTest(unittest.TestCase):
    """Ось 2 — потолок концентрации считает ключи разными предметами риска."""

    def test_the_measured_pair_is_found_with_its_structural_ceiling(self):
        """Положительный контроль: пара 931ea9be, предел 20 %+40 % против корзины T2."""
        t2 = RiskConfig().max_total_t2_allocation
        with TemporaryDirectory() as d:
            t = _scene(Path(d),
                       surface={"morpho_blue": "live", "morpho_steakhouse": "live"},
                       tvl_values={"morpho_blue": 114_724_290.0,
                                   "morpho_steakhouse": 114_724_290.0},
                       entries={
                           "morpho_blue": _entry("931ea9be", "hint", tvl=2_000_000_000.0,
                                                 source="static", cap=0.2),
                           "morpho_steakhouse": _entry("931ea9be", "pinned",
                                                       tvl=114_724_290.0, source="live",
                                                       cap=0.4),
                       })
            r = census.measure(str(t))
        self.assertEqual(len(r["collisions"]), 1)
        col = r["collisions"][0]
        self.assertEqual(col["protocols"], ["morpho_blue", "morpho_steakhouse"])
        self.assertAlmostEqual(col["structural_ceiling"], 0.6)
        self.assertTrue(col["exceeds_t2_bucket"])
        self.assertGreater(col["structural_ceiling"], t2)
        self.assertFalse(col["structural_ceiling_partial"])

    def test_a_collision_alone_is_a_finding_and_exits_one(self):
        """Дыра покрытия, НАЙДЕННАЯ мутацией (#1247): сцена с коллизией и БЕЗ хинта.

        Мутация «вердикт перестал читать коллизии» выжила первый прогон, потому что все
        сцены оси 2 проверяли только поле `collisions`, а вердикт — ни одна. Выжившую
        мутацию записывают и чинят СЦЕНУ, а не список мутаций (урок #1202/#1217).
        """
        import contextlib
        import io
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live", "b": "live"},
                       tvl_values={"a": 1.0, "b": 1.0},
                       entries={"a": _entry("same", "pinned", tvl=1.0, source="live", cap=0.2),
                                "b": _entry("same", "pinned", tvl=1.0, source="live", cap=0.4)},
                       unverified=[])
            r = census.measure(str(t))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = census.main(["--data-dir", str(t)])
        self.assertEqual(r["live_by_hint"], [], "сцена обязана быть БЕЗ оси 1")
        self.assertEqual(len(r["collisions"]), 1)
        self.assertTrue(census._findings(r))
        self.assertEqual(code, 1)
        self.assertIn("ОДИН ПУЛ", buf.getvalue())

    def test_one_key_per_pool_is_silent(self):
        """Обратный контроль: разные пулы ⇒ коллизии нет, прибор молчит об оси 2."""
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live", "b": "live"},
                       tvl_values={"a": 1.0, "b": 1.0},
                       entries={"a": _entry("pool_a", "pinned", tvl=1.0, source="live"),
                                "b": _entry("pool_b", "pinned", tvl=1.0, source="live")})
            r = census.measure(str(t))
        self.assertEqual(r["collisions"], [])
        self.assertEqual(r["pools_compared"], 2)

    def test_a_pair_below_the_bucket_cap_is_still_named_but_not_flagged(self):
        """Коллизия есть и при малых потолках — а признак превышения корзины отдельный."""
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live", "b": "live"},
                       tvl_values={"a": 1.0, "b": 1.0},
                       entries={"a": _entry("same", "pinned", tvl=1.0, source="live", cap=0.05),
                                "b": _entry("same", "pinned", tvl=1.0, source="live", cap=0.05)})
            r = census.measure(str(t))
        self.assertEqual(len(r["collisions"]), 1)
        self.assertFalse(r["collisions"][0]["exceeds_t2_bucket"])

    def test_an_undeclared_cap_does_not_pass_a_partial_sum_off_as_full(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live", "b": "live"},
                       tvl_values={"a": 1.0, "b": 1.0},
                       entries={"a": _entry("same", "pinned", tvl=1.0, source="live", cap=0.2),
                                "b": _entry("same", "pinned", tvl=1.0, source="live", cap=None)})
            r = census.measure(str(t))
        col = r["collisions"][0]
        self.assertTrue(col["structural_ceiling_partial"])
        self.assertEqual(col["caps_unmeasured"], ["b"])
        self.assertAlmostEqual(col["structural_ceiling"], 0.2)


class ThirdOutcomeTest(unittest.TestCase):
    """Инвариант #17 — отсутствие наблюдения ОТДЕЛЬНЫМ значением у каждой двери."""

    def test_no_data_dir(self):
        with TemporaryDirectory() as d:
            missing = Path(d) / "nope"
            with self.assertRaises(census.NotMeasured) as cm:
                census.measure(str(missing))
        self.assertIn("каталога данных нет", str(cm.exception))

    def test_no_feed_coverage(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={}, entries={}, drop="feed_coverage")
            with self.assertRaises(census.NotMeasured) as cm:
                census.measure(str(t))
        self.assertIn("feed_coverage", str(cm.exception))

    def test_no_tvl_sources_map(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={}, entries={}, drop="tvl_sources")
            with self.assertRaises(census.NotMeasured) as cm:
                census.measure(str(t))
        self.assertIn("tvl_sources", str(cm.exception))

    def test_no_adapters_section_in_the_second_artifact(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live"}, entries={}, drop="adapters")
            with self.assertRaises(census.NotMeasured) as cm:
                census.measure(str(t))
        self.assertIn("adapters", str(cm.exception))

    def test_a_key_absent_from_the_second_artifact_is_unmeasured_not_clean(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"ghost": "live"}, tvl_values={"ghost": 1.0},
                       entries={})
            r = census.measure(str(t))
        self.assertEqual([row["protocol"] for row in r["pin_unmeasured"]], ["ghost"])
        self.assertEqual([row["protocol"] for row in r["pool_unmeasured"]], ["ghost"])
        self.assertEqual(r["live_by_hint"], [])
        self.assertTrue(census._unmeasured(r))
        self.assertFalse(census._findings(r))

    def test_an_undeclared_pool_match_is_unmeasured_not_unpinned(self):
        """«Не объявил» ≠ «не закреплён»: иначе прибор выдумал бы находку."""
        with TemporaryDirectory() as d:
            e = _entry("p1", "pinned", tvl=1.0, source="live")
            e.pop("pool_match")
            t = _scene(Path(d), surface={"a": "live"}, tvl_values={"a": 1.0},
                       entries={"a": e})
            r = census.measure(str(t))
        self.assertEqual(r["live_by_hint"], [])
        self.assertEqual([row["reason"] for row in r["pin_unmeasured"]],
                         ["второй артефакт не объявил `pool_match`"])

    def test_an_unnamed_pool_is_never_read_as_no_collision(self):
        with TemporaryDirectory() as d:
            e1 = _entry("", "pinned", tvl=1.0, source="live")
            e2 = _entry("", "pinned", tvl=1.0, source="live")
            t = _scene(Path(d), surface={"a": "live", "b": "live"},
                       tvl_values={"a": 1.0, "b": 1.0}, entries={"a": e1, "b": e2})
            r = census.measure(str(t))
        self.assertEqual(r["collisions"], [])
        self.assertEqual({row["protocol"] for row in r["pool_unmeasured"]}, {"a", "b"})
        self.assertEqual(r["pools_compared"], 0)
        self.assertTrue(census._unmeasured(r))

    def test_the_surface_may_not_declare_its_own_third_outcome(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live"}, tvl_values={"a": 1.0},
                       entries={"a": _entry("p", "pinned", tvl=1.0, source="live")})
            r = census.measure(str(t))
        self.assertIsNone(r["surface_declares_unverified_count"])
        self.assertIn("не объявила `tvl_floor_unverified`", "\n".join(census.format_report(r)))


class VerdictTest(unittest.TestCase):
    """Коды возврата и форма отчёта."""

    def _run(self, tmp: Path) -> tuple[int, str]:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = census.main(["--data-dir", str(tmp)])
        return code, buf.getvalue()

    def test_clean_scene_prints_the_population_not_just_a_tick(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live"}, tvl_values={"a": 1.0},
                       entries={"a": _entry("p", "pinned", tvl=1.0, source="live")},
                       unverified=[])
            code, text = self._run(t)
        self.assertEqual(code, 0)
        self.assertIn("измеренный НОЛЬ", text)
        self.assertIn("сверено 1 ключ", text)

    def test_findings_exit_one(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"a": "live"}, tvl_values={"a": 1.0},
                       entries={"a": _entry("p", "hint", tvl=1.0, source="static")},
                       unverified=[])
            code, text = self._run(t)
        self.assertEqual(code, 1)
        self.assertIn("ЖИВОЕ БЕЗ ПИНА", text)

    def test_unmeasured_only_exits_two(self):
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"ghost": "live"}, tvl_values={"ghost": 1.0},
                       entries={})
            code, text = self._run(t)
        self.assertEqual(code, 2)
        self.assertIn("НЕ ИЗМЕРЕНО (пин)", text)

    def test_findings_plus_unmeasured_exit_one_and_say_lower_bound(self):
        """Молчаливый код 2 похоронил бы находки; молчаливый 0 — обратное."""
        with TemporaryDirectory() as d:
            t = _scene(Path(d), surface={"hinted": "live", "ghost": "live"},
                       tvl_values={"hinted": 1.0, "ghost": 1.0},
                       entries={"hinted": _entry("p", "hint", tvl=1.0, source="static")})
            code, text = self._run(t)
        self.assertEqual(code, 1)
        self.assertIn("НИЖНЯЯ ГРАНИЦА", text)

    def test_broken_file_is_unmeasured_with_a_named_reason(self):
        with TemporaryDirectory() as d:
            t = Path(d)
            (t / "current_positions.json").write_text("{ не json", encoding="utf-8")
            code, text = self._run(t)
        self.assertEqual(code, 2)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("не разобран", text)


class ThresholdsHaveOneDefinitionTest(unittest.TestCase):
    """Порог — решение, а не замер: вторая копия разошлась бы молча."""

    def test_floor_and_bucket_come_from_riskconfig(self):
        cfg = RiskConfig()
        floor, t2 = census.thresholds()
        self.assertEqual(floor, float(cfg.min_tvl_usd))
        self.assertEqual(t2, float(cfg.max_total_t2_allocation))

    def test_no_threshold_literal_is_retyped_in_the_prober(self):
        src = Path(census.__file__).read_text(encoding="utf-8")
        body = src.split('"""', 2)[-1]  # докстрока цитирует замер — там литералы законны
        for literal in ("5_000_000", "5000000", "0.50", "0.5)"):
            self.assertNotIn(literal, body,
                             f"порог {literal} перепечатан в коде прибора — у него обязано "
                             f"быть одно определение (`RiskConfig`)")


if __name__ == "__main__":
    unittest.main()
