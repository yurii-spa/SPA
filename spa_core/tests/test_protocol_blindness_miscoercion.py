# FROZEN-DATE-OK: injected-clock — TestClockMaskWithInjectedNow передаёт
# фиксированный NOW в _fingerprint(now=) И отметки, выведенные из того же
# якоря (NOW ± CLOCK_WINDOW_S); доменные даты 2021/2022/2023 — предмет
# отрицательного контроля «дата аудита не есть показание часов». Обе стороны
# сравнения закреплены, сдвиг календаря тест не трогает.
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
from datetime import datetime, timezone
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


_COARSE_OFFSET_S = {"aave_v3": 0, "maple": 7, "pendle": 13}


def _blind_with_coarse_clock(context):
    """Константа + отметка времени СЕКУНДНОЙ точности.

    Воспроизводит `defi_protocol_sandwich_attack_exposure_analyzer` (замер
    2026-08-17): весь результат — константа, кроме `timestamp` вида
    `2026-08-17T22:43:34Z`. Повтор ОДНОГО протокола внутри той же секунды даёт
    ТУ ЖЕ строку, поэтому отсев дрожи повтором её не ловит, а прогоны разных
    протоколов разнесены секундами — и путь читается как измерение.

    Смещение здесь детерминировано по протоколу (а не «как повезёт с часами»),
    чтобы тест воспроизводил аварию каждый раз, а не в те прогоны, которые
    удачно легли на границу секунды. Каждая отметка остаётся честным «сейчас»:
    секунды, а не месяцы.
    """
    from datetime import datetime, timedelta, timezone
    proto = context.get("protocol", "")
    stamp = (datetime.now(timezone.utc).replace(microsecond=0)
             + timedelta(seconds=_COARSE_OFFSET_S.get(proto, 21)))
    return {"risk_label": "SAFE",
            "timestamp": stamp.isoformat().replace("+00:00", "Z"),
            "detail": {"current_ltv": 0.5}}


_LAST_AUDIT = {"aave_v3": "2021-03-04T00:00:00Z",
               "maple": "2022-11-19T00:00:00Z",
               "pendle": "2023-06-01T00:00:00Z"}


def _seeing_via_domain_date(context):
    """Различает протоколы ДОМЕННОЙ датой (когда был аудит) под одним ярлыком.

    Отрицательный контроль к маске часов: дата — тоже ISO-строка, но она не
    «сейчас», и заглушить её значит ослепить аудит.
    """
    proto = context.get("protocol", "")
    return {"risk_label": "SAFE",
            "detail": {"current_ltv": 0.5,
                       "last_audit_at": _LAST_AUDIT.get(proto,
                                                        "2020-01-01T00:00:00Z")}}


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

    def test_coarse_clock_field_is_not_a_measurement(self):
        """Авария 2026-08-17: секундная отметка проходила отсев дрожи.

        До починки этот модуль получал `miscoerced` — «зряч, чините коэрсию» о
        модуле, не измерившем ничего; вердикт зависел от секунды прогона.
        """
        audit = _load_audit()
        res = self._classify("coarse_clock", _blind_with_coarse_clock)
        self.assertIn(res["classification"], audit.BLIND_EQUIVALENT,
                      "различие только в собственной отметке времени — "
                      "не зрение: %s" % res.get("miscoerced"))
        self.assertNotIn("miscoerced", res)

    def test_domain_date_stays_a_measurement(self):
        """Обратная сторона той же починки: доменная дата — ИЗМЕРЕНИЕ.

        Краснеет, если маску часов расширить до «любой ISO-строки»: аудит
        протокола отстоит от «сейчас» на годы, и глушить его нельзя.
        """
        audit = _load_audit()
        res = self._classify("domain_date", _seeing_via_domain_date)
        self.assertEqual(res["classification"], "miscoerced",
                         "модуль различил протоколы датой аудита")
        self.assertNotIn(res["classification"], audit.BLIND_EQUIVALENT)
        self.assertIn(".detail.last_audit_at",
                      res["miscoerced"]["differing_paths"])

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


class TestClockMaskWithInjectedNow(unittest.TestCase):
    """Часы — ВХОД, а не окружение: обе стороны сравнения закреплены.

    `.claude/rules/deployment.md`: функция, судящая о свежести, принимает
    `now`; тест передаёт фиксированный момент И фиксированные отметки, поэтому
    он не протухает от сдвига календаря.
    """

    NOW = datetime(2026, 8, 17, 22, 43, 34, tzinfo=timezone.utc)

    def test_own_stamp_is_masked_and_domain_date_is_not(self):
        audit = _load_audit()
        fp_a = audit._fingerprint(
            {"timestamp": "2026-08-17T22:43:34Z",
             "last_audit_at": "2021-03-04T00:00:00Z"},
            "aave_v3", now=self.NOW)
        fp_b = audit._fingerprint(
            {"timestamp": "2026-08-17T22:43:41Z",     # +7 с — те же часы
             "last_audit_at": "2022-11-19T00:00:00Z"},  # доменная дата
            "maple", now=self.NOW)
        self.assertEqual(fp_a[".timestamp"], fp_b[".timestamp"],
                         "две отметки собственных часов — одно и то же")
        self.assertEqual(fp_a[".timestamp"], audit._CLOCK)
        self.assertNotEqual(fp_a[".last_audit_at"], fp_b[".last_audit_at"],
                            "дата аудита — измерение, глушить её нельзя")
        self.assertEqual(audit._differing_paths([fp_a, fp_b], set()),
                         [".last_audit_at"])

    def test_stamp_just_outside_window_stays_a_difference(self):
        """Граница окна проверена с ОБЕИХ сторон, а не только изнутри."""
        audit = _load_audit()
        inside = self.NOW.timestamp() + audit.CLOCK_WINDOW_S - 1
        outside = self.NOW.timestamp() + audit.CLOCK_WINDOW_S + 1
        to_iso = (lambda ts: datetime.fromtimestamp(ts, timezone.utc)
                  .isoformat().replace("+00:00", "Z"))
        fp_in = audit._fingerprint({"ts": to_iso(inside)}, "aave_v3",
                                   now=self.NOW)
        fp_out = audit._fingerprint({"ts": to_iso(outside)}, "aave_v3",
                                    now=self.NOW)
        self.assertEqual(fp_in[".ts"], audit._CLOCK)
        self.assertNotEqual(fp_out[".ts"], audit._CLOCK)


class TestRaisingModuleIsNeverCalledMiscoerced(unittest.TestCase):
    """Пятёрка `failed` Tier-C — не потерянная коэрсия, и это структурно.

    Карточка `inbox-tier-c-pyat-nastoyaschih-otkazov-agregat`: пять модулей
    падают исключением. Исключение всплывает из `_invoke` ДО `_coerce_score`,
    поэтому коэрсировать нечего — вердикт `miscoerced` для такого модуля
    недостижим. Тест держит это утверждение, а не доверяет прочтению кода.
    """

    def tearDown(self):
        for key in [k for k in sys.modules
                    if k.startswith("spa_core.analytics." + _FAKE_PREFIX)]:
            del sys.modules[key]

    def test_module_raising_missing_facts_is_failed_not_miscoerced(self):
        audit = _load_audit()

        def _refuses(context):
            raise ValueError(
                "Missing required fields: ['unique_users_30d']")

        info = _install(_FAKE_PREFIX + "refuses", _refuses)
        res = audit._audit_module(info)
        self.assertEqual(res["classification"], "failed")
        self.assertNotIn("miscoerced", res)
        self.assertNotIn(res["classification"], audit.BLIND_EQUIVALENT)
        self.assertIn("unique_users_30d",
                      res["runs"]["aave_v3"].get("detail", ""),
                      "отказ обязан НАЗЫВАТЬ, чего не хватает")


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
