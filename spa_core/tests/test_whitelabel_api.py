"""Тесты MP-407 — White-label API v1 offline core (spa_core/api/whitelabel_api.py).

unittest (НЕ pytest), БЕЗ сети (dispatch вызывается напрямую, без сокетов);
вся персистентность — только в tempdir. Plaintext-ключи существуют только
как сгенерированные в tempdir значения.

Модуль загружается по пути файла (importlib): существующий
``spa_core/api/__init__.py`` тянет fastapi (опциональная зависимость
существующего server.py), которой может не быть в офлайн-среде; ядро
whitelabel_api от неё НЕ зависит и тестируется без неё.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from spa_core.risk.scoring_engine import grade_for_score

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "spa_core" / "api" / "whitelabel_api.py"


def _load_module():
    """Загрузка whitelabel_api по пути файла — мимо api/__init__ (fastapi)."""
    try:
        from spa_core.api import whitelabel_api as module  # fastapi есть
        return module
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(
            "spa_whitelabel_api_under_test", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


wl = _load_module()

RISK_SCORES_DOC = {
    "generated_at": "2026-06-11T06:00:00+00:00",
    "engine_version": "1.0",
    "scores": [
        {"protocol": "Aave V3", "slug": "aave-v3", "grade": "B",
         "score_numeric": 0.7922},
        {"protocol": "Compound V3", "slug": "compound-v3", "grade": "B",
         "score_numeric": 0.7678},
        {"protocol": "Morpho Blue", "slug": "morpho-blue", "grade": "A",
         "score_numeric": 0.88},
        "garbage-entry", 42, None,
        {"protocol": "", "grade": "A", "score_numeric": 0.9},   # пустое имя
        {"protocol": "Broken Score", "slug": "broken-score",
         "grade": "C", "score_numeric": "oops"},                 # не число
    ],
}

ORCH_DOC = {
    "execution_mode": "read_only_simulation",
    "adapters": [
        {"protocol": "aave_v3", "tier": "T1"},
        {"protocol": "compound_v3", "tier": "T1"},
        {"protocol": "morpho_blue", "tier": "T2"},
        {"protocol": "yearn_v3", "tier": "T2"},
        "junk", None,
    ],
}

TARGET_DOC = {
    "target_weights": {
        "morpho_blue": 0.2, "yearn_v3": 0.2, "euler_v2": 0.2, "maple": 0.2,
    },
    "expected_apy_pct": 3.011,
    "model_used": "risk_adjusted",
    "timestamp": "2026-06-10T06:06:22+00:00",
    "cash_pct": 0.2,
    "risk_breakdown": {
        "morpho_blue": {"risk_grade": "A"},
        "yearn_v3": {"risk_grade": "B"},
    },
}

LADDER_DOC = {
    "updated_at": "2026-06-11T08:16:44+00:00",
    "level_code": "L0",
    "level_name": "paper",
    "aum_usd": 100017.3,
    "aum_cap_usd": 100000.0,
    "incidents_total": 0,
    "last_incident": None,
}

ANCHORS_DOC = {
    "schema_version": 1,
    "anchors": [
        {"date": "2026-06-10", "merkle_root": "ab" * 32, "leaf_count": 3,
         "computed_at": "2026-06-10T10:00:00+00:00", "published": False},
        {"date": "2026-06-11", "merkle_root": None, "leaf_count": 0,
         "computed_at": "2026-06-11T10:16:38+00:00", "published": False},
        "junk",
    ],
}

ALERTS_DOC = {
    "generated_at": "2026-06-10T08:56:41+00:00",
    "alerts": [
        {"severity": "warning", "message": "tvl drop",
         "timestamp": "2026-06-09T12:00:00+00:00"},
    ],
}

VALID_PAYLOAD = {
    "positions": [
        {"protocol": "aave_v3", "amount_usd": 60000.0, "chain": "ethereum"},
        {"protocol": "mystery_farm", "amount_usd": 40000.0},
    ]
}


class FakeClock:
    """Инжектируемый clock для RateLimiter."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class WhitelabelBase(unittest.TestCase):
    """Общий tempdir-каркас: data_dir в tempdir, никакой записи в репо."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name) / "data"
        self.data_dir.mkdir(parents=True)

    def write_sources(self):
        _write_json(self.data_dir / wl.RISK_SCORES_FILENAME, RISK_SCORES_DOC)
        _write_json(self.data_dir / wl.ORCH_STATUS_FILENAME, ORCH_DOC)
        _write_json(self.data_dir / wl.TARGET_ALLOC_FILENAME, TARGET_DOC)
        _write_json(self.data_dir / wl.LADDER_STATUS_FILENAME, LADDER_DOC)
        _write_json(self.data_dir / wl.ANCHORS_FILENAME, ANCHORS_DOC)
        _write_json(self.data_dir / wl.RISK_ALERTS_FILENAME, ALERTS_DOC)

    def make_key(self, plan="basic", active=True):
        """Синтетический ключ в tempdir; plaintext живёт только в тесте."""
        info = wl.generate_api_key(plan, data_dir=self.data_dir)
        if not active:
            doc = json.loads(
                (self.data_dir / wl.API_KEYS_FILENAME).read_text("utf-8"))
            for entry in doc["keys"]:
                if entry["key_id"] == info["key_id"]:
                    entry["active"] = False
            _write_json(self.data_dir / wl.API_KEYS_FILENAME, doc)
        return info

    def headers(self, info):
        return {"X-API-Key": info["api_key_plaintext"]}

    def no_tmp_leftovers(self):
        stray = [p for p in self.data_dir.rglob("*") if p.name.endswith(".tmp")]
        self.assertEqual(stray, [], f"stray tmp files: {stray}")


# ─── валидация payload ───────────────────────────────────────────────────────


class TestValidatePayload(unittest.TestCase):
    def assert400(self, payload, fragment=None):
        positions, err = wl.validate_analyze_payload(payload)
        self.assertIsNone(positions)
        self.assertIsInstance(err, dict)
        self.assertEqual(err["code"], 400)
        self.assertIn("error", err)
        if fragment:
            self.assertIn(fragment, err["error"])

    def test_non_dict_payload(self):
        self.assert400("garbage")

    def test_none_payload(self):
        self.assert400(None)

    def test_list_payload(self):
        self.assert400([{"protocol": "aave_v3", "amount_usd": 1}])

    def test_missing_positions(self):
        self.assert400({}, "positions")

    def test_positions_not_list(self):
        self.assert400({"positions": {"protocol": "x"}}, "positions")

    def test_empty_positions(self):
        self.assert400({"positions": []})

    def test_position_not_dict(self):
        self.assert400({"positions": ["junk"]}, "positions[0]")

    def test_missing_protocol(self):
        self.assert400({"positions": [{"amount_usd": 1.0}]}, "protocol")

    def test_empty_protocol(self):
        self.assert400(
            {"positions": [{"protocol": "  ", "amount_usd": 1.0}]}, "protocol")

    def test_non_string_protocol(self):
        self.assert400(
            {"positions": [{"protocol": 42, "amount_usd": 1.0}]}, "protocol")

    def test_missing_amount(self):
        self.assert400({"positions": [{"protocol": "aave_v3"}]}, "amount_usd")

    def test_non_numeric_amount(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": "many"}]},
            "amount_usd")

    def test_bool_amount_is_not_number(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": True}]},
            "amount_usd")

    def test_nan_amount(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": float("nan")}]},
            "amount_usd")

    def test_negative_amount(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": -5.0}]},
            ">= 0")

    def test_zero_total(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": 0.0}]},
            "total")

    def test_non_string_chain(self):
        self.assert400(
            {"positions": [{"protocol": "aave_v3", "amount_usd": 1.0,
                            "chain": 1}]}, "chain")

    def test_valid_payload_passes(self):
        positions, err = wl.validate_analyze_payload(VALID_PAYLOAD)
        self.assertIsNone(err)
        self.assertEqual(len(positions), 2)
        self.assertEqual(positions[0]["chain"], "ethereum")
        self.assertIsNone(positions[1]["chain"])

    def test_error_index_reported(self):
        self.assert400(
            {"positions": [{"protocol": "ok", "amount_usd": 1.0}, "junk"]},
            "positions[1]")


# ─── нормализация / индексы ──────────────────────────────────────────────────


class TestNormalization(unittest.TestCase):
    def test_normalize_variants(self):
        self.assertEqual(wl.normalize_protocol("Aave V3"), "aave_v3")
        self.assertEqual(wl.normalize_protocol("aave-v3"), "aave_v3")
        self.assertEqual(wl.normalize_protocol("  Morpho Blue  "), "morpho_blue")

    def test_risk_index_aliases_and_garbage(self):
        index = wl.build_risk_index(RISK_SCORES_DOC)
        self.assertIn("aave_v3", index)
        self.assertEqual(index["aave_v3"]["grade"], "B")
        self.assertEqual(index["morpho_blue"]["score_numeric"], 0.88)
        # битый score → запись есть, но score None
        self.assertIsNone(index["broken_score"]["score_numeric"])

    def test_risk_index_tolerates_bad_doc(self):
        self.assertEqual(wl.build_risk_index(None), {})
        self.assertEqual(wl.build_risk_index({"scores": "junk"}), {})
        self.assertEqual(wl.build_risk_index([1, 2]), {})

    def test_tier_map(self):
        tiers = wl.build_tier_map(ORCH_DOC)
        self.assertEqual(tiers["aave_v3"], "T1")
        self.assertEqual(tiers["morpho_blue"], "T2")

    def test_tier_map_tolerates_bad_doc(self):
        self.assertEqual(wl.build_tier_map(None), {})
        self.assertEqual(wl.build_tier_map({"adapters": "junk"}), {})


# ─── analyze_portfolio ───────────────────────────────────────────────────────


class TestAnalyzePortfolio(WhitelabelBase):
    def analyze(self, payload=None):
        return wl.analyze_portfolio(
            payload or VALID_PAYLOAD, data_dir=self.data_dir)

    def test_known_protocol_scored(self):
        self.write_sources()
        doc = self.analyze()
        aave = doc["positions"][0]
        self.assertTrue(aave["risk"]["known"])
        self.assertEqual(aave["risk"]["grade"], "B")
        self.assertEqual(aave["risk"]["score_numeric"], 0.7922)

    def test_unknown_protocol_honest_null(self):
        self.write_sources()
        doc = self.analyze()
        unknown = doc["positions"][1]
        self.assertFalse(unknown["risk"]["known"])
        self.assertIsNone(unknown["risk"]["grade"])
        self.assertIsNone(unknown["risk"]["score_numeric"])
        self.assertIn("unknown", unknown["risk"]["note"])

    def test_weighted_score_known_only(self):
        self.write_sources()
        doc = self.analyze()
        # только aave_v3 известен → weighted score == его score
        self.assertEqual(doc["portfolio"]["weighted_risk_score"], 0.7922)
        self.assertEqual(doc["portfolio"]["weighted_risk_grade"],
                         grade_for_score(0.7922))

    def test_weighted_score_two_known_manual(self):
        self.write_sources()
        payload = {"positions": [
            {"protocol": "aave_v3", "amount_usd": 75000.0},
            {"protocol": "compound_v3", "amount_usd": 25000.0},
        ]}
        doc = self.analyze(payload)
        expected = round((0.7922 * 75000 + 0.7678 * 25000) / 100000, 6)
        self.assertEqual(doc["portfolio"]["weighted_risk_score"], expected)
        self.assertEqual(doc["portfolio"]["unknown_share_pct"], 0.0)

    def test_unknown_share_pct(self):
        self.write_sources()
        doc = self.analyze()
        self.assertEqual(doc["portfolio"]["unknown_share_pct"], 40.0)

    def test_top1_concentration(self):
        self.write_sources()
        doc = self.analyze()
        self.assertEqual(doc["portfolio"]["top1_protocol"], "aave_v3")
        self.assertEqual(doc["portfolio"]["top1_concentration_pct"], 60.0)

    def test_tier_split(self):
        self.write_sources()
        payload = {"positions": [
            {"protocol": "aave_v3", "amount_usd": 50000.0},
            {"protocol": "morpho_blue", "amount_usd": 30000.0},
            {"protocol": "mystery_farm", "amount_usd": 20000.0},
        ]}
        doc = self.analyze(payload)
        split = doc["portfolio"]["tier_split_pct"]
        self.assertEqual(split["T1"], 50.0)
        self.assertEqual(split["T2"], 30.0)
        self.assertEqual(split["unknown"], 20.0)

    def test_share_pct_per_position(self):
        self.write_sources()
        doc = self.analyze()
        self.assertEqual(doc["positions"][0]["share_pct"], 60.0)
        self.assertEqual(doc["positions"][1]["share_pct"], 40.0)

    def test_protocol_name_normalization_matches_slug(self):
        self.write_sources()
        payload = {"positions": [
            {"protocol": "Aave V3", "amount_usd": 100.0}]}
        doc = self.analyze(payload)
        self.assertTrue(doc["positions"][0]["risk"]["known"])
        self.assertEqual(doc["positions"][0]["tier"], "T1")

    def test_missing_risk_scores_all_unknown(self):
        # risk_scores.json отсутствует → все unknown + note
        _write_json(self.data_dir / wl.ORCH_STATUS_FILENAME, ORCH_DOC)
        doc = self.analyze()
        self.assertIsNone(doc["portfolio"]["weighted_risk_score"])
        self.assertIsNone(doc["portfolio"]["weighted_risk_grade"])
        self.assertEqual(doc["portfolio"]["unknown_share_pct"], 100.0)
        self.assertTrue(
            any(wl.RISK_SCORES_FILENAME in n for n in doc["notes"]))

    def test_broken_risk_scores_tolerated(self):
        (self.data_dir / wl.RISK_SCORES_FILENAME).write_text(
            "{broken", encoding="utf-8")
        doc = self.analyze()
        self.assertIsNone(doc["portfolio"]["weighted_risk_score"])

    def test_missing_orch_tier_unknown(self):
        _write_json(self.data_dir / wl.RISK_SCORES_FILENAME, RISK_SCORES_DOC)
        doc = self.analyze()
        self.assertEqual(doc["positions"][0]["tier"], "unknown")
        self.assertTrue(
            any(wl.ORCH_STATUS_FILENAME in n for n in doc["notes"]))

    def test_garbage_payload_returns_400_shape(self):
        doc = self.analyze({"positions": "junk"})
        self.assertTrue(wl.is_error(doc))
        self.assertEqual(doc["code"], 400)

    def test_disclaimer_and_advisory(self):
        self.write_sources()
        doc = self.analyze()
        self.assertTrue(doc["advisory_only"])
        self.assertIn("NOT investment advice", doc["disclaimer"])

    def test_total_usd(self):
        self.write_sources()
        doc = self.analyze()
        self.assertEqual(doc["portfolio"]["total_usd"], 100000.0)
        self.assertEqual(doc["portfolio"]["num_positions"], 2)


# ─── recommended_allocations ─────────────────────────────────────────────────


class TestRecommendedAllocations(WhitelabelBase):
    def test_missing_file_honest_unavailable(self):
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertFalse(doc["available"])
        self.assertIn(wl.TARGET_ALLOC_FILENAME, doc["note"])

    def test_broken_file_honest_unavailable(self):
        (self.data_dir / wl.TARGET_ALLOC_FILENAME).write_text(
            "{broken", encoding="utf-8")
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertFalse(doc["available"])

    def test_weights_converted_to_pct(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertTrue(doc["available"])
        by_proto = {a["protocol"]: a for a in doc["allocations"]}
        self.assertEqual(by_proto["morpho_blue"]["weight_pct"], 20.0)
        self.assertEqual(doc["cash_pct"], 20.0)

    def test_tier_and_grade_attached(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        by_proto = {a["protocol"]: a for a in doc["allocations"]}
        self.assertEqual(by_proto["morpho_blue"]["tier"], "T2")
        self.assertEqual(by_proto["morpho_blue"]["risk_grade"], "A")
        # протокола нет в оркестраторе → tier unknown, grade нет → None
        self.assertEqual(by_proto["maple"]["tier"], "unknown")
        self.assertIsNone(by_proto["maple"]["risk_grade"])

    def test_disclaimer_present(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertIn("NOT investment advice", doc["disclaimer"])
        self.assertTrue(doc["advisory_only"])

    def test_is_demo_absent_honest_null_with_note(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertIsNone(doc["is_demo"])
        self.assertTrue(any("is_demo" in n for n in doc["notes"]))

    def test_is_demo_from_file(self):
        self.write_sources()
        target = dict(TARGET_DOC)
        target["is_demo"] = False
        _write_json(self.data_dir / wl.TARGET_ALLOC_FILENAME, target)
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertIs(doc["is_demo"], False)

    def test_execution_mode_from_orch(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertEqual(doc["execution_mode"], "read_only_simulation")

    def test_non_numeric_weight_skipped(self):
        target = {"target_weights": {"good": 0.5, "bad": "junk"}}
        _write_json(self.data_dir / wl.TARGET_ALLOC_FILENAME, target)
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertEqual([a["protocol"] for a in doc["allocations"]], ["good"])

    def test_metadata_passthrough(self):
        self.write_sources()
        doc = wl.recommended_allocations(data_dir=self.data_dir)
        self.assertEqual(doc["model_used"], "risk_adjusted")
        self.assertEqual(doc["expected_apy_pct"], 3.011)
        self.assertEqual(doc["as_of"], "2026-06-10T06:06:22+00:00")


# ─── webhook_signals ─────────────────────────────────────────────────────────


class TestWebhookSignals(WhitelabelBase):
    def test_no_files_empty_list_with_note(self):
        doc = wl.webhook_signals(data_dir=self.data_dir)
        self.assertEqual(doc["signals"], [])
        self.assertEqual(doc["count"], 0)
        self.assertTrue(any("no signals" in n for n in doc["notes"]))

    def test_pull_stub_no_delivery(self):
        doc = wl.webhook_signals(data_dir=self.data_dir)
        self.assertEqual(doc["delivery"]["mode"], "pull")
        self.assertIn("not implemented", doc["delivery"]["note"])

    def test_anchor_signals(self):
        self.write_sources()
        doc = wl.webhook_signals(data_dir=self.data_dir)
        anchors = [s for s in doc["signals"]
                   if s["type"] == "proof_of_track_anchor"]
        self.assertEqual(len(anchors), 2)
        self.assertEqual(anchors[0]["data"]["merkle_root"], "ab" * 32)

    def test_ladder_level_signal(self):
        self.write_sources()
        doc = wl.webhook_signals(data_dir=self.data_dir)
        levels = [s for s in doc["signals"]
                  if s["type"] == "capital_ladder_level"]
        self.assertEqual(len(levels), 1)
        self.assertEqual(levels[0]["data"]["level_code"], "L0")

    def test_incident_signal_when_present(self):
        self.write_sources()
        ladder = dict(LADDER_DOC)
        ladder["last_incident"] = {"date": "2026-06-05", "loss_pct": -1.2}
        _write_json(self.data_dir / wl.LADDER_STATUS_FILENAME, ladder)
        doc = wl.webhook_signals(data_dir=self.data_dir)
        incidents = [s for s in doc["signals"] if s["type"] == "incident"]
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["ts"], "2026-06-05")

    def test_risk_alert_signal(self):
        self.write_sources()
        doc = wl.webhook_signals(data_dir=self.data_dir)
        alerts = [s for s in doc["signals"] if s["type"] == "risk_alert"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["data"]["severity"], "warning")

    def test_risk_policy_blocks_list_format(self):
        _write_json(self.data_dir / wl.RISK_BLOCKS_FILENAME, [
            {"timestamp": "2026-06-08T00:00:00+00:00", "reason": "cap"},
        ])
        doc = wl.webhook_signals(data_dir=self.data_dir)
        blocks = [s for s in doc["signals"] if s["type"] == "risk_policy_block"]
        self.assertEqual(len(blocks), 1)

    def test_since_filter(self):
        self.write_sources()
        doc = wl.webhook_signals(
            "2026-06-11T00:00:00+00:00", data_dir=self.data_dir)
        self.assertTrue(
            all(s["ts"] >= "2026-06-11" for s in doc["signals"]))
        anchors = [s for s in doc["signals"]
                   if s["type"] == "proof_of_track_anchor"]
        self.assertEqual(len(anchors), 1)  # только якорь 2026-06-11

    def test_since_z_suffix_supported(self):
        self.write_sources()
        doc = wl.webhook_signals("2026-06-11T00:00:00Z", data_dir=self.data_dir)
        self.assertFalse(wl.is_error(doc))

    def test_invalid_since_400_shape(self):
        doc = wl.webhook_signals("not-a-ts", data_dir=self.data_dir)
        self.assertTrue(wl.is_error(doc))
        self.assertEqual(doc["code"], 400)

    def test_sorted_by_ts(self):
        self.write_sources()
        doc = wl.webhook_signals(data_dir=self.data_dir)
        stamps = [s["ts"] for s in doc["signals"] if s["ts"] is not None]
        self.assertEqual(stamps, sorted(stamps))

    def test_broken_source_tolerated(self):
        (self.data_dir / wl.ANCHORS_FILENAME).write_text(
            "{broken", encoding="utf-8")
        _write_json(self.data_dir / wl.RISK_ALERTS_FILENAME, ALERTS_DOC)
        doc = wl.webhook_signals(data_dir=self.data_dir)
        self.assertFalse(wl.is_error(doc))
        self.assertTrue(
            any(wl.ANCHORS_FILENAME in n for n in doc["notes"]))
        self.assertEqual(doc["count"], 1)

    def test_sources_reported(self):
        self.write_sources()
        doc = wl.webhook_signals(data_dir=self.data_dir)
        self.assertTrue(doc["sources"][wl.ANCHORS_FILENAME])
        self.assertFalse(doc["sources"][wl.RISK_BLOCKS_FILENAME])


# ─── auth ────────────────────────────────────────────────────────────────────


class TestAuth(WhitelabelBase):
    def test_valid_key_authenticates(self):
        info = self.make_key(plan="pro")
        identity = wl.authenticate(
            info["api_key_plaintext"], data_dir=self.data_dir)
        self.assertEqual(identity, {"key_id": info["key_id"], "plan": "pro"})

    def test_wrong_key_rejected(self):
        self.make_key()
        self.assertIsNone(
            wl.authenticate("spa_wl_wrong", data_dir=self.data_dir))

    def test_inactive_key_rejected(self):
        info = self.make_key(active=False)
        self.assertIsNone(
            wl.authenticate(info["api_key_plaintext"], data_dir=self.data_dir))

    def test_no_keys_file_api_closed(self):
        self.assertIsNone(
            wl.authenticate("spa_wl_any", data_dir=self.data_dir))

    def test_broken_keys_file_api_closed(self):
        (self.data_dir / wl.API_KEYS_FILENAME).write_text(
            "{broken", encoding="utf-8")
        self.assertIsNone(
            wl.authenticate("spa_wl_any", data_dir=self.data_dir))

    def test_none_and_empty_key_rejected(self):
        self.make_key()
        self.assertIsNone(wl.authenticate(None, data_dir=self.data_dir))
        self.assertIsNone(wl.authenticate("", data_dir=self.data_dir))
        self.assertIsNone(wl.authenticate(42, data_dir=self.data_dir))

    def test_file_stores_sha256_not_plaintext(self):
        info = self.make_key()
        raw = (self.data_dir / wl.API_KEYS_FILENAME).read_text("utf-8")
        self.assertNotIn(info["api_key_plaintext"], raw)
        expected = hashlib.sha256(
            info["api_key_plaintext"].encode("utf-8")).hexdigest()
        self.assertIn(expected, raw)

    def test_two_keys_independent(self):
        a = self.make_key(plan="basic")
        b = self.make_key(plan="pro")
        ia = wl.authenticate(a["api_key_plaintext"], data_dir=self.data_dir)
        ib = wl.authenticate(b["api_key_plaintext"], data_dir=self.data_dir)
        self.assertNotEqual(ia["key_id"], ib["key_id"])
        self.assertEqual(ib["plan"], "pro")

    def test_entry_without_hash_tolerated(self):
        _write_json(self.data_dir / wl.API_KEYS_FILENAME,
                    {"keys": [{"key_id": "k1", "plan": "basic",
                               "active": True}, "junk"]})
        self.assertIsNone(wl.authenticate("anything", data_dir=self.data_dir))

    def test_gen_key_atomic_no_tmp(self):
        self.make_key()
        self.no_tmp_leftovers()

    def test_extract_api_key_header_variants(self):
        self.assertEqual(wl.extract_api_key({"X-API-Key": "abc"}), "abc")
        self.assertEqual(wl.extract_api_key({"x-api-key": "abc"}), "abc")
        self.assertEqual(
            wl.extract_api_key({"Authorization": "Bearer tok"}), "tok")
        self.assertIsNone(wl.extract_api_key({"Authorization": "Basic xx"}))
        self.assertIsNone(wl.extract_api_key({}))
        self.assertIsNone(wl.extract_api_key(None))


# ─── rate limit ──────────────────────────────────────────────────────────────


class TestRateLimiter(unittest.TestCase):
    def test_allows_up_to_limit(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=3, window_sec=60.0, clock=clock)
        self.assertTrue(all(rl.allow("k") for _ in range(3)))

    def test_limit_plus_one_blocked(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=3, window_sec=60.0, clock=clock)
        for _ in range(3):
            rl.allow("k")
        self.assertFalse(rl.allow("k"))

    def test_window_resets_with_injected_clock(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=2, window_sec=60.0, clock=clock)
        rl.allow("k")
        rl.allow("k")
        self.assertFalse(rl.allow("k"))
        clock.advance(60.0)
        self.assertTrue(rl.allow("k"))

    def test_partial_window_does_not_reset(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=1, window_sec=60.0, clock=clock)
        rl.allow("k")
        clock.advance(59.9)
        self.assertFalse(rl.allow("k"))

    def test_keys_independent(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=1, window_sec=60.0, clock=clock)
        self.assertTrue(rl.allow("a"))
        self.assertTrue(rl.allow("b"))
        self.assertFalse(rl.allow("a"))

    def test_remaining(self):
        clock = FakeClock()
        rl = wl.RateLimiter(limit=5, window_sec=60.0, clock=clock)
        self.assertEqual(rl.remaining("k"), 5)
        rl.allow("k")
        self.assertEqual(rl.remaining("k"), 4)

    def test_default_constants(self):
        self.assertEqual(wl.RATE_LIMIT_PER_MIN, 60)
        self.assertEqual(wl.RATE_WINDOW_SEC, 60.0)
        rl = wl.RateLimiter()
        self.assertEqual(rl.limit, 60)


# ─── usage (billing-заготовка) ───────────────────────────────────────────────


class TestUsage(WhitelabelBase):
    def test_creates_file_with_schema(self):
        entry = wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        self.assertEqual(entry["requests_total"], 1)
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(usage["k1"]["by_endpoint"]["/v1/signals"], 1)
        self.assertIsNotNone(usage["k1"]["last_request_at"])

    def test_counters_grow(self):
        for _ in range(3):
            wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        wl.record_usage("k1", "/v1/portfolio/analyze", data_dir=self.data_dir)
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(usage["k1"]["requests_total"], 4)
        self.assertEqual(usage["k1"]["by_endpoint"]["/v1/signals"], 3)
        self.assertEqual(usage["k1"]["by_endpoint"]["/v1/portfolio/analyze"], 1)

    def test_keys_tracked_separately(self):
        wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        wl.record_usage("k2", "/v1/signals", data_dir=self.data_dir)
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(usage["k1"]["requests_total"], 1)
        self.assertEqual(usage["k2"]["requests_total"], 1)

    def test_no_tmp_leftovers(self):
        wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        self.no_tmp_leftovers()

    def test_file_is_valid_json_after_writes(self):
        for _ in range(5):
            wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        doc = json.loads(
            (self.data_dir / wl.USAGE_FILENAME).read_text("utf-8"))
        self.assertEqual(doc["k1"]["requests_total"], 5)

    def test_broken_file_tolerated_reset(self):
        (self.data_dir / wl.USAGE_FILENAME).write_text(
            "{broken", encoding="utf-8")
        self.assertEqual(wl.load_usage(data_dir=self.data_dir), {})
        entry = wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        self.assertEqual(entry["requests_total"], 1)

    def test_non_dict_values_dropped(self):
        _write_json(self.data_dir / wl.USAGE_FILENAME,
                    {"k1": "junk", "k2": {"requests_total": 7,
                                          "by_endpoint": {},
                                          "last_request_at": None}})
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertNotIn("k1", usage)
        self.assertEqual(usage["k2"]["requests_total"], 7)

    def test_rotation_caps_keys(self):
        bulk = {
            f"key_{i:04d}": {"requests_total": 1, "by_endpoint": {},
                             "last_request_at": f"2026-01-01T00:{i % 60:02d}:00"}
            for i in range(wl.USAGE_MAX_KEYS)
        }
        _write_json(self.data_dir / wl.USAGE_FILENAME, bulk)
        wl.record_usage("fresh", "/v1/signals", data_dir=self.data_dir)
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(len(usage), wl.USAGE_MAX_KEYS)
        self.assertIn("fresh", usage)

    def test_corrupt_counters_tolerated(self):
        _write_json(self.data_dir / wl.USAGE_FILENAME,
                    {"k1": {"requests_total": "junk",
                            "by_endpoint": "junk",
                            "last_request_at": None}})
        entry = wl.record_usage("k1", "/v1/signals", data_dir=self.data_dir)
        self.assertEqual(entry["requests_total"], 1)
        self.assertEqual(entry["by_endpoint"]["/v1/signals"], 1)


# ─── dispatch ────────────────────────────────────────────────────────────────


class TestDispatch(WhitelabelBase):
    def setUp(self):
        super().setUp()
        self.write_sources()
        self.key = self.make_key()
        self.limiter = wl.RateLimiter(clock=FakeClock())

    def call(self, method, path, headers=None, body=None, **kw):
        kw.setdefault("data_dir", self.data_dir)
        kw.setdefault("limiter", self.limiter)
        return wl.dispatch(method, path, headers, body, **kw)

    def test_unknown_path_404(self):
        status, doc = self.call("GET", "/v1/unknown", self.headers(self.key))
        self.assertEqual(status, 404)
        self.assertEqual(doc["code"], 404)

    def test_root_path_404(self):
        status, _ = self.call("GET", "/", self.headers(self.key))
        self.assertEqual(status, 404)

    def test_no_key_401(self):
        status, doc = self.call("GET", "/v1/signals", {})
        self.assertEqual(status, 401)
        self.assertIn("error", doc)

    def test_bad_key_401(self):
        status, _ = self.call(
            "GET", "/v1/signals", {"X-API-Key": "spa_wl_bad"})
        self.assertEqual(status, 401)

    def test_inactive_key_401(self):
        inactive = self.make_key(active=False)
        status, _ = self.call("GET", "/v1/signals", self.headers(inactive))
        self.assertEqual(status, 401)

    def test_method_mismatch_405(self):
        status, _ = self.call(
            "GET", "/v1/portfolio/analyze", self.headers(self.key))
        self.assertEqual(status, 405)
        status, _ = self.call(
            "POST", "/v1/allocations/recommended", self.headers(self.key),
            body={})
        self.assertEqual(status, 405)

    def test_analyze_happy_path(self):
        status, doc = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key),
            body=VALID_PAYLOAD)
        self.assertEqual(status, 200)
        self.assertEqual(doc["portfolio"]["total_usd"], 100000.0)

    def test_analyze_json_string_body(self):
        status, doc = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key),
            body=json.dumps(VALID_PAYLOAD))
        self.assertEqual(status, 200)
        self.assertEqual(doc["portfolio"]["num_positions"], 2)

    def test_analyze_bytes_body(self):
        status, _ = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key),
            body=json.dumps(VALID_PAYLOAD).encode("utf-8"))
        self.assertEqual(status, 200)

    def test_analyze_invalid_json_400(self):
        status, doc = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key),
            body="{broken")
        self.assertEqual(status, 400)
        self.assertIn("JSON", doc["error"])

    def test_analyze_missing_body_400(self):
        status, _ = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key))
        self.assertEqual(status, 400)

    def test_analyze_garbage_payload_400(self):
        status, _ = self.call(
            "POST", "/v1/portfolio/analyze", self.headers(self.key),
            body={"positions": []})
        self.assertEqual(status, 400)

    def test_allocations_happy_path(self):
        status, doc = self.call(
            "GET", "/v1/allocations/recommended", self.headers(self.key))
        self.assertEqual(status, 200)
        self.assertTrue(doc["available"])

    def test_signals_happy_path(self):
        status, doc = self.call("GET", "/v1/signals", self.headers(self.key))
        self.assertEqual(status, 200)
        self.assertGreater(doc["count"], 0)

    def test_signals_since_query(self):
        status, doc = self.call(
            "GET", "/v1/signals?since=2026-06-11T00:00:00%2B00:00".replace(
                "%2B", "+"),
            self.headers(self.key))
        self.assertEqual(status, 200)
        self.assertEqual(doc["since"], "2026-06-11T00:00:00+00:00")

    def test_signals_bad_since_400(self):
        status, _ = self.call(
            "GET", "/v1/signals?since=garbage", self.headers(self.key))
        self.assertEqual(status, 400)

    def test_trailing_slash_routes(self):
        status, _ = self.call("GET", "/v1/signals/", self.headers(self.key))
        self.assertEqual(status, 200)

    def test_bearer_auth_works(self):
        status, _ = self.call(
            "GET", "/v1/signals",
            {"Authorization": f"Bearer {self.key['api_key_plaintext']}"})
        self.assertEqual(status, 200)

    def test_rate_limit_429(self):
        clock = FakeClock()
        tiny = wl.RateLimiter(limit=2, window_sec=60.0, clock=clock)
        h = self.headers(self.key)
        self.assertEqual(
            self.call("GET", "/v1/signals", h, limiter=tiny)[0], 200)
        self.assertEqual(
            self.call("GET", "/v1/signals", h, limiter=tiny)[0], 200)
        status, doc = self.call("GET", "/v1/signals", h, limiter=tiny)
        self.assertEqual(status, 429)
        self.assertIn("rate limit", doc["error"])
        clock.advance(60.0)
        self.assertEqual(
            self.call("GET", "/v1/signals", h, limiter=tiny)[0], 200)

    def test_rate_limit_keys_independent_in_dispatch(self):
        other = self.make_key()
        tiny = wl.RateLimiter(limit=1, window_sec=60.0, clock=FakeClock())
        self.assertEqual(
            self.call("GET", "/v1/signals", self.headers(self.key),
                      limiter=tiny)[0], 200)
        self.assertEqual(
            self.call("GET", "/v1/signals", self.headers(other),
                      limiter=tiny)[0], 200)

    def test_usage_recorded_on_happy_path(self):
        self.call("GET", "/v1/signals", self.headers(self.key))
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(
            usage[self.key["key_id"]]["by_endpoint"]["/v1/signals"], 1)

    def test_usage_not_recorded_for_401(self):
        self.call("GET", "/v1/signals", {})
        self.assertEqual(wl.load_usage(data_dir=self.data_dir), {})

    def test_usage_not_recorded_when_record_false(self):
        self.call("GET", "/v1/signals", self.headers(self.key), record=False)
        self.assertEqual(wl.load_usage(data_dir=self.data_dir), {})

    def test_dispatch_never_raises(self):
        status, doc = wl.dispatch(None, None, None, None,
                                  data_dir=self.data_dir,
                                  limiter=self.limiter)
        self.assertIn(status, (400, 404, 401, 405))
        self.assertIsInstance(doc, dict)


# ─── CLI ─────────────────────────────────────────────────────────────────────


class TestCLI(WhitelabelBase):
    def _main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = wl.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_check_default_exit0_json_summary(self):
        self.write_sources()
        rc, out, err = self._main(["--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        summary = json.loads(out)
        self.assertEqual(summary["mode"], "check")
        self.assertTrue(summary["ok"], summary)

    def test_check_smoke_statuses(self):
        self.write_sources()
        rc, out, _ = self._main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        results = json.loads(out)["results"]
        self.assertEqual(results["POST /v1/portfolio/analyze"], 200)
        self.assertEqual(results["unauthorized"], 401)
        self.assertEqual(results["unknown_path"], 404)
        self.assertEqual(results["method_mismatch"], 405)
        self.assertEqual(results["rate_limited"], 429)

    def test_check_writes_nothing_to_data_dir(self):
        self.write_sources()
        before = sorted(p.name for p in self.data_dir.iterdir())
        rc, _, _ = self._main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        after = sorted(p.name for p in self.data_dir.iterdir())
        self.assertEqual(before, after)
        self.assertFalse((self.data_dir / wl.USAGE_FILENAME).exists())
        self.assertFalse((self.data_dir / wl.API_KEYS_FILENAME).exists())
        self.no_tmp_leftovers()

    def test_check_exit0_on_empty_data_dir(self):
        rc, out, err = self._main(["--check", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        self.assertTrue(json.loads(out)["ok"])

    def test_gen_key_writes_hash_only(self):
        rc, out, err = self._main(
            ["--gen-key", "--plan", "pro", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        plaintext = [line for line in out.splitlines()
                     if line.startswith("spa_wl_")][0]
        raw = (self.data_dir / wl.API_KEYS_FILENAME).read_text("utf-8")
        self.assertNotIn(plaintext, raw)
        doc = json.loads(raw)
        self.assertEqual(doc["keys"][0]["plan"], "pro")
        self.assertEqual(doc["keys"][0]["key_hash"],
                         hashlib.sha256(plaintext.encode()).hexdigest())
        # сгенерированный ключ реально аутентифицируется
        self.assertIsNotNone(
            wl.authenticate(plaintext, data_dir=self.data_dir))

    def test_gen_key_twice_appends(self):
        self._main(["--gen-key", "--data-dir", str(self.data_dir)])
        self._main(["--gen-key", "--data-dir", str(self.data_dir)])
        doc = json.loads(
            (self.data_dir / wl.API_KEYS_FILENAME).read_text("utf-8"))
        self.assertEqual(len(doc["keys"]), 2)
        self.no_tmp_leftovers()

    def test_run_writes_usage_snapshot(self):
        self.write_sources()
        rc, out, err = self._main(["--run", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertNotIn("Traceback", err)
        summary = json.loads(out)
        self.assertEqual(summary["mode"], "run")
        usage = wl.load_usage(data_dir=self.data_dir)
        self.assertEqual(usage["_selftest"]["requests_total"], 1)
        self.no_tmp_leftovers()

    def test_run_twice_idempotent_structure(self):
        self.write_sources()
        self._main(["--run", "--data-dir", str(self.data_dir)])
        self._main(["--run", "--data-dir", str(self.data_dir)])
        usage = wl.load_usage(data_dir=self.data_dir)
        # структура та же, счётчик честно растёт
        self.assertEqual(set(usage), {"_selftest"})
        self.assertEqual(usage["_selftest"]["requests_total"], 2)
        self.assertEqual(set(usage["_selftest"]),
                         {"requests_total", "by_endpoint", "last_request_at"})

    def test_garbage_argument_error_exit0(self):
        rc, _, err = self._main(["--bogus-flag"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_conflicting_modes_error_exit0(self):
        rc, _, err = self._main(["--check", "--run"])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)

    def test_serve_bad_port_error_exit0(self):
        rc, _, err = self._main(
            ["--serve", "--port", "junk", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)
        self.assertNotIn("Traceback", err)
        rc, _, err = self._main(
            ["--serve", "--port", "99999", "--data-dir", str(self.data_dir)])
        self.assertEqual(rc, 0)
        self.assertIn("ERROR", err)

    def test_subprocess_check_no_traceback(self):
        # запуск файла как скрипта: работает и без fastapi
        # (python3 -m spa_core.api.whitelabel_api — эквивалент при
        # установленном fastapi из существующего api/__init__.py)
        self.write_sources()
        proc = subprocess.run(
            [sys.executable, str(MODULE_PATH),
             "--check", "--data-dir", str(self.data_dir)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])


# ─── гигиена ─────────────────────────────────────────────────────────────────


class TestHygiene(unittest.TestCase):
    FORBIDDEN_PREFIXES = (
        "anthropic", "openai", "langchain", "litellm",
        "google.generativeai", "requests", "web3", "urllib",
        "pandas", "numpy",
    )

    def _imports(self):
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.append(node.module)
        return mods

    def test_no_forbidden_imports(self):
        for mod in self._imports():
            for bad in self.FORBIDDEN_PREFIXES:
                self.assertFalse(
                    mod == bad or mod.startswith(bad + "."),
                    f"forbidden import {mod}")

    def test_llm_forbidden_lint_clean(self):
        # тот же AST-сканер, что в CI (как в test_tear_sheet)
        from spa_core.ci.llm_forbidden_lint import find_forbidden_imports
        violations = find_forbidden_imports(
            MODULE_PATH.read_text(encoding="utf-8"), "whitelabel_api.py")
        self.assertEqual(violations, [])

    def test_http_server_only_lazy_import(self):
        # http.server не на module-level: offline-ядро не тянет сокеты
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        top_level = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.append(node.module)
        self.assertNotIn("http.server", top_level)
        self.assertNotIn("socket", top_level)

    def test_reuses_risk_engine_grade_by_import(self):
        self.assertIn("spa_core.risk.scoring_engine", self._imports())

    def test_no_plaintext_key_literals_in_module(self):
        # в исходнике нет «зашитых» ключей: spa_wl_ встречается только
        # как генерируемый префикс f-строки
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"spa_wl_[A-Za-z0-9_\-]{10,}")

    def test_disclaimer_not_investment_advice(self):
        self.assertIn("NOT investment advice", wl.DISCLAIMER)

    def test_constants(self):
        self.assertEqual(wl.API_KEYS_FILENAME, "api_keys.json")
        self.assertEqual(wl.USAGE_FILENAME, "api_usage.json")
        self.assertEqual(wl.RATE_LIMIT_PER_MIN, 60)
        self.assertEqual(wl.USAGE_MAX_KEYS, 500)
        self.assertEqual(set(wl._ROUTES), {
            "/v1/portfolio/analyze",
            "/v1/allocations/recommended",
            "/v1/signals",
        })

    def test_webhook_stub_documented(self):
        self.assertIn("no egress", wl.WEBHOOK_DELIVERY_NOTE)


if __name__ == "__main__":
    unittest.main()
