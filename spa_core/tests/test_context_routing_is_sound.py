"""
test_context_routing_is_sound.py — маршрутизация «protocol-контекст vs
легаси-payload» не должна превращать ДЫРКУ в обязательном поле в подстановку.

Авария, которую воспроизводят эти тесты (04.08.2026, коммит f6197fe82).
Массовая обвязка Tier-B protocol-контекстом добавила модулям ветку «пришёл
контекст → построить доменный вход из структурного профиля». Легаси-вход двух
модулей — тоже dict со строковым ``protocol``, поэтому им понадобился второй
признак, и выбран он был как «нет ключа K»::

    if _pf.is_protocol_context(protocol_data) and "tvl_usd" not in protocol_data:
        ...  "treasury_usd": _p["tvl_usd"] * 0.02,

Но ``tvl_usd`` ОБЯЗАТЕЛЕН. Отсутствие обязательного ключа — ровно то условие,
по которому обязана падать валидация; теперь по нему же срабатывала ветка
подстановки. Данные с дыркой переставали доходить до ``_validate``, получали
выдуманную казну ``TVL × 0.02`` и возвращались наружу как валидная оценка.
Это fail-OPEN класса #29: обязательный гейт не отказывает, а придумывает число.

Устойчивый признак — отсутствие НЕ одного ключа, а ВСЕХ доменных сразу
(``_protocol_facts.is_context_only``): контекст агрегатора это
``{"cycle_ts": …, "protocol": …}``, доменных ключей в нём нет ни одного, а
payload с дыркой в одном поле несёт остальные и уходит на легаси-путь к своей
валидации, как и должен.

Каждый тест здесь — положительный контроль: снять починку (вернуть
``and "<K>" not in``) → краснеет. Последний тест — гард против рецидива
идиомы во ВСЁМ ``spa_core/analytics``, тоже с положительным контролем.
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics.protocol_insurance_scorer import (
    _DOMAIN_KEYS as INSURANCE_DOMAIN_KEYS,
    ProtocolInsuranceScorer,
)
import pytest

from spa_core.analytics import (
    defi_protocol_token_bridge_security_risk_analyzer as _bridge_mod,
)
from spa_core.analytics.defi_protocol_token_bridge_security_risk_analyzer import (
    _DOMAIN_KEYS as BRIDGE_DOMAIN_KEYS,
    DeFiProtocolTokenBridgeSecurityRiskAnalyzer,
)


# ---------------------------------------------------------------------------
# Прогон не смеет писать в spa_core/data/ (agent-test-run-dirties-tracked-fixtures).
# `DATA_FILE` bridge-модуля относителен; под `cd spa_core` (шаг CI) полный payload
# в TestBridgeAnalyzerRefusesHoles доходил до записи лога в каталог ПАКЕТА.
# Разбор — spa_core/tests/_package_data_guard.py.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bridge_log_into_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _bridge_mod, "DATA_FILE", tmp_path / "bridge_security_risk_log.json"
    )

ANALYTICS_DIR = pathlib.Path(__file__).resolve().parents[1] / "analytics"

# Полные легаси-payload'ы обоих модулей. Оба НАМЕРЕННО несут строковый
# "protocol" — без него авария не воспроизводится (is_protocol_context не
# срабатывает), и тест бы ничего не проверял.
FULL_INSURANCE_PAYLOAD = {
    "protocol": "aave_v3",
    "has_insurance": True,
    "insurance_coverage_pct": 25.0,
    "insurance_provider": "nexus_mutual",
    "treasury_usd": 200_000_000.0,
    "tvl_usd": 10_000_000_000.0,
    "bug_bounty_usd": 1_000_000.0,
    "has_timelock": True,
    "timelock_days": 7,
}

FULL_BRIDGE_PAYLOAD = {
    "protocol": "arbitrum",
    "bridge_name": "arbitrum_canonical_rollup_bridge",
    "tvl_usd": 3_000_000_000.0,
    "validation_model": "optimistic",
    "validator_count": 1,
    "days_since_last_audit": 120,
    "historical_hacks": [],
    "open_source": True,
    "bug_bounty_usd": 2_000_000.0,
    "time_to_finality_minutes": 25.0,
}

# Контекст агрегатора ровно той формы, что строит
# signal_aggregator._ModuleAdapter.run: dict(context) + ctx["protocol"].
AGGREGATOR_CONTEXT = {"cycle_ts": "2026-08-04T00:00:00Z", "protocol": "aave_v3"}


class TestIsContextOnly(unittest.TestCase):
    """Сам признак: контекст — это отсутствие ВСЕХ доменных ключей."""

    DOMAIN = frozenset({"tvl_usd", "treasury_usd", "has_insurance"})

    def test_pure_context_is_context(self):
        self.assertTrue(pf.is_context_only(
            {"cycle_ts": "x", "protocol": "aave_v3"}, self.DOMAIN))

    def test_bare_protocol_dict_is_context(self):
        self.assertTrue(pf.is_context_only({"protocol": "aave_v3"}, self.DOMAIN))

    def test_full_domain_payload_is_not_context(self):
        self.assertFalse(pf.is_context_only(
            {"protocol": "aave_v3", "tvl_usd": 1.0,
             "treasury_usd": 2.0, "has_insurance": True}, self.DOMAIN))

    def test_payload_with_a_hole_is_STILL_not_context(self):
        """Сердцевина аварии: дырка в ОДНОМ доменном ключе не делает
        доменный payload контекстом — остальные ключи на месте."""
        holed = {"protocol": "aave_v3", "treasury_usd": 2.0, "has_insurance": True}
        self.assertNotIn("tvl_usd", holed)
        self.assertFalse(pf.is_context_only(holed, self.DOMAIN))

    def test_non_dict_and_non_string_protocol_are_not_context(self):
        self.assertFalse(pf.is_context_only(["protocol"], self.DOMAIN))
        self.assertFalse(pf.is_context_only({"protocol": 5}, self.DOMAIN))
        self.assertFalse(pf.is_context_only("aave_v3", self.DOMAIN))

    def test_empty_domain_keys_degrades_to_is_protocol_context(self):
        """Пустой набор доменных ключей = старое поведение. Явно, чтобы
        случайно пустой frozenset не читался как «всё проверено»."""
        self.assertTrue(pf.is_context_only({"protocol": "x", "tvl_usd": 1.0}, ()))


class TestInsuranceScorerRefusesHoles(unittest.TestCase):
    """protocol_insurance_scorer: payload с дыркой → ОТКАЗ, не подстановка."""

    def setUp(self):
        self.scorer = ProtocolInsuranceScorer()

    def test_full_payload_scores(self):
        res = self.scorer.score(dict(FULL_INSURANCE_PAYLOAD), write_log=False)
        self.assertIsInstance(res, dict)
        self.assertEqual(res["tvl_usd"], FULL_INSURANCE_PAYLOAD["tvl_usd"])

    def test_every_missing_domain_key_raises(self):
        """Для КАЖДОГО доменного ключа: убрать → ValueError.
        До починки ``tvl_usd`` возвращал подставной результат."""
        for key in sorted(INSURANCE_DOMAIN_KEYS):
            with self.subTest(missing=key):
                payload = dict(FULL_INSURANCE_PAYLOAD)
                payload.pop(key)
                with self.assertRaises(ValueError):
                    self.scorer.score(payload, write_log=False)

    def test_missing_tvl_never_returns_fabricated_treasury(self):
        """Именно та фабрикация: казна = TVL × 0.02 из структурного профиля."""
        payload = dict(FULL_INSURANCE_PAYLOAD)
        payload.pop("tvl_usd")
        try:
            res = self.scorer.score(payload, write_log=False)
        except ValueError:
            return                      # честный отказ — то, что нужно
        self.fail(f"вместо отказа вернулся результат: {res!r}")

    def test_aggregator_context_still_routes_to_profile(self):
        """Починка не должна убить обвязку: чистый контекст по-прежнему
        уходит на путь структурного профиля и даёт score."""
        res = self.scorer.score(dict(AGGREGATOR_CONTEXT), write_log=False)
        self.assertIsNotNone(res)

    def test_unknown_protocol_context_is_dormant_none(self):
        res = self.scorer.score(
            {"cycle_ts": "x", "protocol": "__nonexistent_control__"},
            write_log=False)
        self.assertIsNone(res)

    def test_domain_keys_cover_validate_required(self):
        """_DOMAIN_KEYS не должен разъехаться с обязательными ключами:
        забытый в наборе обязательный ключ = дырка возвращается."""
        src = (ANALYTICS_DIR / "protocol_insurance_scorer.py").read_text()
        required = _required_literals(src)
        self.assertTrue(required, "не нашёл список required — тест ослеп")
        self.assertLessEqual(required - {"protocol"}, set(INSURANCE_DOMAIN_KEYS))


class TestBridgeAnalyzerRefusesHoles(unittest.TestCase):
    """Второй экземпляр того же дефекта (дискриминатор был bridge_name)."""

    def setUp(self):
        self.analyzer = DeFiProtocolTokenBridgeSecurityRiskAnalyzer()

    def test_full_payload_analyzes(self):
        res = self.analyzer.analyze(dict(FULL_BRIDGE_PAYLOAD))
        self.assertIsInstance(res, dict)
        self.assertEqual(res["bridge_name"], FULL_BRIDGE_PAYLOAD["bridge_name"])

    def test_every_missing_domain_key_raises(self):
        for key in sorted(BRIDGE_DOMAIN_KEYS):
            with self.subTest(missing=key):
                payload = dict(FULL_BRIDGE_PAYLOAD)
                payload.pop(key)
                with self.assertRaises(ValueError):
                    self.analyzer.analyze(payload)

    def test_missing_bridge_name_never_returns_profile_result(self):
        payload = dict(FULL_BRIDGE_PAYLOAD)
        payload.pop("bridge_name")
        try:
            res = self.analyzer.analyze(payload)
        except ValueError:
            return
        self.fail(f"вместо отказа вернулся результат: {res!r}")

    def test_aggregator_context_still_routes_to_profile(self):
        res = self.analyzer.analyze(dict(AGGREGATOR_CONTEXT))
        self.assertIsNotNone(res)

    def test_domain_keys_cover_validate_required(self):
        src = (ANALYTICS_DIR
               / "defi_protocol_token_bridge_security_risk_analyzer.py").read_text()
        required = _required_literals(src)
        self.assertTrue(required, "не нашёл множество required — тест ослеп")
        self.assertLessEqual(required - {"protocol"}, set(BRIDGE_DOMAIN_KEYS))


# ─── Гард против рецидива идиомы во всём analytics ──────────────────────────

def _required_literals(src: str) -> set:
    """Строковые литералы из присваиваний вида ``required = {...}`` / ``[...]``."""
    out: set = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "required"
                for t in node.targets):
            for el in ast.walk(node.value):
                if isinstance(el, ast.Constant) and isinstance(el.value, str):
                    out.add(el.value)
    return out


def _unsound_discriminators(src: str) -> set:
    """Ключи K из идиомы ``is_protocol_context(X) … "K" not in …``, которые
    при этом ОБЯЗАТЕЛЬНЫ для модуля. Именно такая пара и есть дефект."""
    if "is_protocol_context" not in src:
        return set()
    discriminators: set = set()
    # блок условия: от `is_protocol_context(` до двоеточия конца заголовка if
    for m in re.finditer(r'is_protocol_context\(.{0,400}?:\s*\n', src, re.S):
        discriminators |= set(re.findall(r'"([^"]+)"\s+not\s+in', m.group(0)))
    return discriminators & _required_literals(src)


class TestNoUnsoundDiscriminatorAnywhere(unittest.TestCase):
    """Ни один модуль analytics не отличает контекст по отсутствию
    ОБЯЗАТЕЛЬНОГО ключа."""

    def test_scanner_sees_the_modules_at_all(self):
        """Положительный контроль слепоты: сканер обязан реально находить
        файлы с обвязкой, иначе «нарушений нет» ничего не значит."""
        wired = [p for p in ANALYTICS_DIR.glob("*.py")
                 if "is_protocol_context" in p.read_text()]
        self.assertGreater(len(wired), 50,
                           "сканер не видит обвязанных модулей — тест слеп")

    def test_scanner_catches_the_real_2026_08_04_defect(self):
        """Положительный контроль: дословный код аварии обязан краснить."""
        broken = '''
required = ["protocol", "tvl_usd", "treasury_usd"]
if _pf.is_protocol_context(protocol_data) and "tvl_usd" not in protocol_data:
    pass
'''
        self.assertEqual(_unsound_discriminators(broken), {"tvl_usd"})

    def test_scanner_accepts_a_sound_discriminator(self):
        """Контроль в обратную сторону: НЕобязательный ключ — не находка."""
        ok = '''
required = ["protocol", "tvl_usd"]
if _pf.is_protocol_context(orderbook) and "bids" not in orderbook:
    pass
'''
        self.assertEqual(_unsound_discriminators(ok), set())

    def test_no_module_uses_a_required_key_as_discriminator(self):
        offenders = {}
        for path in sorted(ANALYTICS_DIR.glob("*.py")):
            bad = _unsound_discriminators(path.read_text())
            if bad:
                offenders[path.name] = sorted(bad)
        self.assertEqual(
            offenders, {},
            "контекст отличается по отсутствию ОБЯЗАТЕЛЬНОГО ключа — "
            "легаси-payload с дыркой получит подставленное число вместо "
            f"отказа (fail-OPEN, класс #29): {offenders}. "
            "Признак — _protocol_facts.is_context_only(obj, ДОМЕННЫЕ_КЛЮЧИ).")


if __name__ == "__main__":
    unittest.main()
