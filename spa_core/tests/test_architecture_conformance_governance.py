"""B7 — наблюдение за управлением ↔ книга (ADR-070 п.14, рамка ADR-066).

ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (.claude/rules/deployment.md, «проверка сторожа сторожей»).
Каждый тест воспроизводит РЕАЛЬНЫЙ класс аварии этого модуля:

  * замер 2026-08-01: watchlist держал шесть протоколов, в которые мы не можем
    инвестировать, отвечал «8 пространств здоровы, 0 ошибок» — и пересечение с
    живым портфелем было ПУСТО. Ловит `test_watched_stranger_is_a_finding`;
  * замер 2026-08-18 (эта сессия): из семи held-протоколов пять не имеют канала,
    и ДВА из них (`euler_v2`, `yearn_v3`) не названы даже как известная дыра —
    безымянное отсутствие. Ловит `test_held_without_any_channel_is_a_finding`;
  * класс fail-OPEN мониторов: нечитаемая книга обязана давать UNCHECKED, а не
    «нарушений нет». Ловит `test_unreadable_book_is_unchecked_not_ok`.

Обратная сторона (обязательна — иначе сторож просто всегда красный):
протокол, за которым мы НЕ следим НАМЕРЕННО и это записано с причиной
(`GOVERNANCE_SOURCE_UNCONFIRMED`), тревоги НЕ поднимает —
`test_deliberately_unwatched_named_protocol_is_silent`.

Время — вход (`NOW`), не окружение. Живой сети не требуется.
"""
import datetime as dt
import inspect
import unittest

from spa_core.monitoring import architecture_conformance as ac

NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)


def _manifest():
    return {"schema_version": 1, "agents": [], "artifacts": [],
            "designed_architectures": []}


def _gov(*, held=None, monitored=(), named=(), whitelist=None,
         measured=True, reason=None, whitelist_measured=True,
         whitelist_reason=None):
    """Готовый блок фактов B7 — уже нормализованный, как его отдаёт сборщик."""
    def pairs(names):
        return {n.replace("_", "").replace("-", "").lower(): n for n in names}
    return {
        "measured": measured, "reason": reason,
        "held": None if held is None else pairs(held),
        "monitored": pairs(monitored), "named": pairs(named),
        "whitelist_measured": whitelist_measured,
        "whitelist_reason": whitelist_reason,
        "whitelist": None if whitelist is None else pairs(whitelist),
    }


def _run(governance):
    # drift_measured=True — иначе B5 добавляет СВОЙ отказ и вердикт UNCHECKED
    # приходит не от B7; тест обязан называть свою причину.
    return ac.run_checks(_manifest(), set(), lambda p: None, {}, NOW,
                         drift_measured=True, governance=governance)


def _keys(report):
    return {f["key"] for f in report["findings"]}


class B7HeldCoverage(unittest.TestCase):
    def test_held_without_any_channel_is_a_finding(self):
        """Держим капитал, канала нет, дыра даже не названа → находка."""
        r = _run(_gov(held=["aave_v3", "euler_v2"],
                      monitored=["aave-v3"], named=[],
                      whitelist=["aave_v3", "euler_v2"]))
        self.assertIn("B7:held_unwatched:euler_v2", _keys(r))
        self.assertNotIn("B7:held_unwatched:aave_v3", _keys(r))
        self.assertEqual(r["overall"], "WARN")

    def test_deliberately_unwatched_named_protocol_is_silent(self):
        """Обратная сторона: не следим НАМЕРЕННО и это записано → тишина.

        Без этого теста «починить» сторожа можно было бы, объявив всё held
        нарушением, — и он краснел бы на честно названной дыре.
        """
        r = _run(_gov(held=["aave_v3", "spark_susds"],
                      monitored=["aave-v3"], named=["spark_susds"],
                      whitelist=["aave_v3", "spark_susds"]))
        self.assertEqual([f for f in r["findings"] if f["check"] == "B7"], [])
        self.assertEqual(r["overall"], "OK")

    def test_key_spelling_is_folded_not_a_finding(self):
        """`aave-v3` в канале и `aave_v3` в книге — один протокол, не дыра."""
        r = _run(_gov(held=["aave_v3"], monitored=["aave-v3"],
                      whitelist=["aave_v3"]))
        self.assertEqual(r["overall"], "OK")


class B7Strangers(unittest.TestCase):
    def test_watched_stranger_is_a_finding(self):
        """Канал настроен на протокол, который мы не держим и не вайтлистим."""
        r = _run(_gov(held=["aave_v3"], monitored=["aave-v3", "curve"],
                      named=[], whitelist=["aave_v3"]))
        self.assertIn("B7:watched_not_ours:curve", _keys(r))
        self.assertEqual(r["overall"], "WARN")

    def test_whitelisted_but_not_held_is_not_a_stranger(self):
        """Вайтлист-протокол без позиции — наш; следить за ним нормально."""
        r = _run(_gov(held=["aave_v3"], monitored=["aave-v3", "compound_v3"],
                      whitelist=["aave_v3", "compound_v3"]))
        self.assertEqual(r["overall"], "OK")


class B7FailClosed(unittest.TestCase):
    def test_unreadable_book_is_unchecked_not_ok(self):
        """«Канал наблюдения недоступен» ≠ «нарушений нет» (инвариант 2)."""
        r = _run(_gov(held=None, measured=False,
                      reason="portfolio status missing", monitored=["aave-v3"],
                      whitelist=["aave_v3"]))
        self.assertEqual(r["findings"], [])
        self.assertEqual(r["overall"], "UNCHECKED")
        refusals = [u for u in r["unchecked"] if u["check"] == "B7_governance"]
        self.assertEqual(len(refusals), 1)
        self.assertIn("portfolio status missing", refusals[0]["reason"])

    def test_refusal_input_matches_finding_check_name(self):
        """Отказ обязан держать открытой B7-карточку (мост ADR-070 п.5)."""
        r = _run(_gov(held=None, measured=False, reason="x"))
        self.assertEqual({u["input"] for u in r["unchecked"]
                          if u["check"] == "B7_governance"}, {"B7"})

    def test_unreadable_whitelist_refuses_the_stranger_half_only(self):
        """Вайтлист не прочли — held-половина всё равно проверена."""
        r = _run(_gov(held=["euler_v2"], monitored=["aave-v3"], named=[],
                      whitelist=None, whitelist_measured=False,
                      whitelist_reason="ADAPTER_REGISTRY unreadable"))
        self.assertIn("B7:held_unwatched:euler_v2", _keys(r))
        self.assertTrue(any("ADAPTER_REGISTRY unreadable" in u["reason"]
                            for u in r["unchecked"]))


class B7Gatherer(unittest.TestCase):
    def test_gatherer_never_returns_none_and_never_raises(self):
        got = ac.gather_governance_coverage()
        self.assertIsInstance(got, dict)
        self.assertIn("measured", got)
        if not got["measured"]:
            self.assertTrue(got["reason"], "неизмеренное обязано нести причину")

    def test_gatherer_reports_reason_when_watcher_unimportable(self):
        import builtins
        real = builtins.__import__

        def boom(name, *a, **kw):
            if name == "spa_core.alerts.governance_watcher":
                raise ImportError("simulated")
            return real(name, *a, **kw)

        builtins.__import__ = boom
        try:
            got = ac.gather_governance_coverage()
        finally:
            builtins.__import__ = real
        self.assertFalse(got["measured"])
        self.assertIn("simulated", got["reason"])

    def test_main_actually_asks_for_b7(self):
        """Пропущенный аргумент = молча не проверено. Храповик на проводку."""
        src = inspect.getsource(ac.main)
        self.assertIn("governance=gather_governance_coverage()", src)


class B7DoesNotTouchMoneyPath(unittest.TestCase):
    def test_b7_findings_are_warn_never_critical(self):
        """Наблюдение за управлением — advisory: не гейт исполнения."""
        r = _run(_gov(held=["euler_v2"], monitored=["curve"], named=[],
                      whitelist=["euler_v2"]))
        b7 = [f for f in r["findings"] if f["check"] == "B7"]
        self.assertTrue(b7)
        self.assertEqual({f["severity"] for f in b7}, {"WARN"})


if __name__ == "__main__":
    unittest.main()
