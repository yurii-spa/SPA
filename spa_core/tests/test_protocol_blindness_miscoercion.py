"""Положительный контроль В ОБЕ СТОРОНЫ для аудита протокол-слепоты.

Авария (цикл #142/#144, карточка `inbox-slepota-mozhet-byt-poteryannoi-koerciei`):
`scripts/audit_protocol_blindness.py` судил модуль по числу, которое вернула
`_ModuleAdapter._coerce_score` — по ЛОССОВОЙ проекции результата. Модуль,
измеривший LTV/APY каждого протокола и подписавший их одним грубым
`risk_label="SAFE"`, снаружи выглядел константой: коэрсия возвращает номер
ярлыка. Аудит объявлял такой модуль слепым, а `run_tier_b` переставал его
исполнять вовсе — вердикт «слеп» читается как «модуль бесполезен».

Оба направления обязаны краснеть при мутации починки:
* модуль, РАЗЛИЧАЮЩИЙ протоколы в полном результате, — не слепой;
* модуль, честно константный, — слепой (и не смеет уехать в «зрячие»
  из-за часов в поле `ts`).

Сеть не трогаем: модули синтетические, регистрируются в `sys.modules`.
"""
from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_FAKE_PREFIX = "_fake_blindness_mod_"


def _install(name: str, analyze) -> dict:
    full = "spa_core.analytics." + name
    mod = types.ModuleType(full)
    mod.analyze = analyze
    sys.modules[full] = mod
    return {"module": name, "class": None, "tier": "B",
            "category": "test", "weight": 0.5, "protocols": ["all"]}


def _load_audit():
    spec = importlib.util.spec_from_file_location(
        "audit_protocol_blindness_under_test",
        REPO_ROOT / "scripts" / "audit_protocol_blindness.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── синтетические модули ─────────────────────────────────────────────────────

_LTV = {"aave_v3": 0.55, "maple": 0.71, "pendle": 0.64}


def _seeing_under_one_label(context):
    """ИЗМЕРИЛ каждый протокол, подписал одним ярлыком — воспроизводит
    `collateral_health_monitor`/`defi_cross_chain_yield_comparator`."""
    proto = context.get("protocol", "")
    ltv = _LTV.get(proto, 0.42)
    return {"risk_label": "SAFE",
            "detail": {"current_ltv": ltv,
                       "buffer_pct": round((0.85 - ltv) * 100.0, 4)}}


def _honestly_blind(context):
    """Ничего про протокол не знает: та же константа кому угодно."""
    return {"risk_label": "SAFE", "detail": {"current_ltv": 0.5}}


def _blind_with_clock(context):
    """Константа + отметка времени: часы не являются измерением протокола."""
    from datetime import datetime, timezone
    return {"risk_label": "SAFE",
            "ts": datetime.now(timezone.utc).isoformat(),
            "detail": {"current_ltv": 0.5}}


def _blind_echoing_input(context):
    """Эхо имени протокола на входе — модуль его не вычислял."""
    return {"risk_label": "SAFE",
            "protocol": context.get("protocol"),
            "detail": {"current_ltv": 0.5, "note":
                       "profile for %s" % context.get("protocol")}}


class TestAuditSeesThroughCoercion(unittest.TestCase):

    def tearDown(self):
        for key in [k for k in sys.modules
                    if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
            del sys.modules[key]

    def _classify(self, name: str, fn) -> dict:
        audit = _load_audit()
        return audit._audit_module(_install(_FAKE_PREFIX + name, fn))

    # ── сторона 1: зрячий обязан опознаваться зрячим ────────────────────────

    def test_module_differentiating_under_one_label_is_not_blind(self):
        audit = _load_audit()
        res = self._classify("seeing", _seeing_under_one_label)
        self.assertEqual(res["classification"], "miscoerced",
                         "модуль измерил каждый протокол — слепым он не является")
        self.assertNotIn(res["classification"], audit.BLIND_EQUIVALENT)
        paths = res["miscoerced"]["differing_paths"]
        self.assertIn(".detail.current_ltv", paths)
        # коэрсия при этом честно осталась константой ярлыка — это и есть потеря
        self.assertEqual(res["miscoerced"]["score"], 10.0)

    def test_seeing_module_absent_from_emitted_blind_markup(self):
        audit = _load_audit()
        res = self._classify("seeing2", _seeing_under_one_label)
        report = {"generated_at": "T", "results": [res]}
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "_pb.py"
            audit.emit_markup(report, out)
            ns: dict = {}
            exec(out.read_text(encoding="utf-8"), ns)  # noqa: S102 — тест
        name = _FAKE_PREFIX + "seeing2"
        self.assertNotIn(name, ns["PROTOCOL_BLIND_MODULES"])
        self.assertIn(name, ns["MISCOERCED_MODULES"])
        self.assertIn(".detail.current_ltv",
                      ns["MISCOERCED_DETAIL"][name]["differing_paths"])

    # ── сторона 2: честно слепой обязан остаться слепым ─────────────────────

    def test_honestly_blind_module_stays_blind(self):
        audit = _load_audit()
        res = self._classify("blind", _honestly_blind)
        self.assertIn(res["classification"], audit.BLIND_EQUIVALENT,
                      "константа для любого протокола — это слепота")
        self.assertNotIn("miscoerced", res)

    def test_clock_field_is_not_a_measurement(self):
        audit = _load_audit()
        res = self._classify("clock", _blind_with_clock)
        self.assertIn(res["classification"], audit.BLIND_EQUIVALENT,
                      "различие только в отметке времени — не зрение")

    def test_echo_of_input_is_not_a_measurement(self):
        audit = _load_audit()
        res = self._classify("echo", _blind_echoing_input)
        self.assertIn(res["classification"], audit.BLIND_EQUIVALENT,
                      "эхо имени протокола модуль не вычислял")

    def test_blind_module_lands_in_emitted_markup(self):
        audit = _load_audit()
        res = self._classify("blind2", _honestly_blind)
        report = {"generated_at": "T", "results": [res]}
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "_pb.py"
            audit.emit_markup(report, out)
            ns: dict = {}
            exec(out.read_text(encoding="utf-8"), ns)  # noqa: S102 — тест
        name = _FAKE_PREFIX + "blind2"
        self.assertIn(name, ns["PROTOCOL_BLIND_MODULES"])
        self.assertNotIn(name, ns["MISCOERCED_MODULES"])


class TestAggregatorHonoursMiscoercedMarkup(unittest.TestCase):
    """Ярлык в проде называет ЧТО чинить, а константу в composite не пускает."""

    def tearDown(self):
        for key in [k for k in sys.modules
                    if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
            del sys.modules[key]

    def test_miscoerced_module_gets_own_status_and_is_not_executed(self):
        from spa_core.analytics import signal_aggregator as sa

        executed = []

        def _tracked(context):
            executed.append(context.get("protocol"))
            return _seeing_under_one_label(context)

        info = _install(_FAKE_PREFIX + "agg", _tracked)
        with TemporaryDirectory() as tmp:
            agg = sa.SignalAggregator(data_dir=Path(tmp))
            orig_get = sa.registry.get_tier_modules
            sa.registry.get_tier_modules = lambda tier: [info]  # noqa: E731
            orig_set = sa.MISCOERCED_MODULES
            sa.MISCOERCED_MODULES = frozenset({info["module"]})
            try:
                agg.run_tier_b(["aave_v3"], {})
            finally:
                sa.registry.get_tier_modules = orig_get
                sa.MISCOERCED_MODULES = orig_set
        self.assertEqual(executed, [], "размеченный модуль не исполняется")
        summary = agg._module_status_summary()
        self.assertEqual(summary["counts"].get("miscoerced"), 1)
        self.assertNotIn("blind", summary["counts"],
                         "ярлык «слеп» о зрячем модуле — та самая ложь")

    def test_real_markup_sets_do_not_overlap(self):
        from spa_core.analytics._protocol_blindness import (
            MISCOERCED_MODULES,
            PROTOCOL_BLIND_MODULES,
            WIDE_OK_MODULES,
        )
        self.assertFalse(PROTOCOL_BLIND_MODULES & MISCOERCED_MODULES)
        self.assertFalse(WIDE_OK_MODULES & MISCOERCED_MODULES)


if __name__ == "__main__":
    unittest.main()
