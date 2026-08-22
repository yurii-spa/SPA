# FROZEN-DATE-OK: historical-incident — литеральные даты в фикстурах описывают
# исторические кризисы (предмет схемы), окон свежести здесь нет.
"""Protection Lab: схема сценария — fail-CLOSED валидация датасета и replay-спеки."""
from __future__ import annotations

import unittest

from spa_core.stress.protection_lab.schema import (
    scenario_from_dict,
    validate_scenario_dict,
)


def _minimal_valid() -> dict:
    return {
        "id": "H99_test_event",
        "name": "Test Event",
        "event_class": ["stablecoin_depeg"],
        "window_utc": {"start": "2023-03-10", "end": "2023-03-13"},
        "speed": "-13% за 2 дня",
        "summary": "тестовый сценарий",
        "timeline": [
            {"ts": "2023-03-10T22:00:00Z", "event": "анонс", "observed": True,
             "source_url": "https://example.com/a"},
            {"ts": "2023-03-11T08:00:00Z", "event": "дно", "observed": True},
        ],
        "market_impact": {
            "btc": {"from_usd": 20000, "to_usd": 19000, "drawdown_pct": 5.0,
                    "window": "24h"},
        },
        "causes": {"primary": "тест"},
        "sources": [
            {"url": "https://example.com/1", "supports": "peg path"},
            {"url": "https://example.com/2", "supports": "btc"},
            {"url": "https://example.com/3", "supports": "timeline"},
        ],
        "confidence_notes": "тест",
        "replay": {
            "duration_days": 7,
            "start_date": "2023-03-10",
            "shocks": [
                {"kind": "peg", "params": {
                    "symbol": "USDC", "path": [[0, 1.0], [1, 0.88], [3, 1.0]]}},
                {"kind": "freeze", "params": {
                    "protocol": "maple", "from_day": 1, "to_day": 3}},
                {"kind": "capital_loss", "params": {
                    "protocol": "maple", "day": 2, "loss_pct": 0.3}},
            ],
            "assumptions": ["тестовое допущение"],
        },
    }


class SchemaValidation(unittest.TestCase):
    def test_valid_scenario_loads(self):
        self.assertEqual(validate_scenario_dict(_minimal_valid()), [])
        sc = scenario_from_dict(_minimal_valid())
        self.assertTrue(sc.has_replay)
        self.assertEqual(sc.replay.duration_days, 7)

    def test_historical_scenario_requires_sources(self):
        raw = _minimal_valid()
        raw["sources"] = [{"url": "https://example.com/1", "supports": "x"}]
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("≥3 источников" in e for e in errors))

    def test_synthetic_scenario_may_skip_sources(self):
        raw = _minimal_valid()
        raw["sources"] = [{"url": "https://e.com", "supports": "-"}]
        raw["synthetic"] = True
        errors = [e for e in validate_scenario_dict(raw) if "источник" in e]
        self.assertEqual(errors, [])

    def test_source_without_supports_rejected(self):
        raw = _minimal_valid()
        raw["sources"][0].pop("supports")
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("supports" in e for e in errors))

    def test_timeline_entry_without_observed_flag_rejected(self):
        raw = _minimal_valid()
        raw["timeline"][0].pop("observed")
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("observed" in e for e in errors))

    def test_unsorted_timeline_rejected(self):
        raw = _minimal_valid()
        raw["timeline"] = list(reversed(raw["timeline"]))
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("раньше предыдущего" in e for e in errors))

    def test_drawdown_arithmetic_mismatch_rejected(self):
        raw = _minimal_valid()
        raw["market_impact"]["btc"]["drawdown_pct"] = 40.0  # from/to дают 5%
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("не сходится" in e for e in errors))

    def test_shock_day_outside_duration_rejected(self):
        raw = _minimal_valid()
        raw["replay"]["shocks"].append(
            {"kind": "freeze", "params": {"protocol": "aave_v3",
                                          "from_day": 5, "to_day": 99}})
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("вне [0, 7)" in e for e in errors))

    def test_unknown_shock_kind_rejected(self):
        raw = _minimal_valid()
        raw["replay"]["shocks"].append({"kind": "meteor", "params": {}})
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("неизвестный kind" in e for e in errors))

    def test_peg_price_out_of_band_rejected(self):
        raw = _minimal_valid()
        raw["replay"]["shocks"][0]["params"]["path"] = [[0, 1.0], [1, 5.0]]
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("вне [0, 2]" in e for e in errors))

    def test_capital_loss_bounds(self):
        raw = _minimal_valid()
        raw["replay"]["shocks"][2]["params"]["loss_pct"] = 1.5
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("вне (0, 1]" in e for e in errors))

    def test_unknown_event_class_rejected(self):
        raw = _minimal_valid()
        raw["event_class"] = ["alien_invasion"]
        errors = validate_scenario_dict(raw)
        self.assertTrue(any("event_class" in e for e in errors))

    def test_invalid_dict_raises_on_construction(self):
        raw = _minimal_valid()
        raw["sources"] = []
        with self.assertRaises(ValueError):
            scenario_from_dict(raw)


if __name__ == "__main__":
    unittest.main()
