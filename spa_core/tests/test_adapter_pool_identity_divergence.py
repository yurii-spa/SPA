"""ADR-233 — один ключ адаптера, разрешённый в РАЗНЫЕ пулы двумя производителями.

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на замер 2026-09-05 (цикл #492), а не
выдуманный пример. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Что было измерено
=================
`aave_v3` — КРУПНЕЙШАЯ позиция книги ($40 000, 40 %, потолок T1 выбран целиком).
В снимке 2026-09-05 06:00Z два артефакта одного дневного цикла сказали::

    data/adapter_status.json              live_apy 2.5804  (06:00:26.447071Z)
    data/adapter_orchestrator_status.json apy_pct  5.2651  (06:00:28.610293Z)

Разрыв отметок наблюдения — 2.16 с. РОВНО ТОТ ЖЕ разрыв 2.16 с был у всех девяти
общих протоколов того же снимка, и восемь из девяти сошлись до четвёртого знака
(`compound_v3`, `morpho_steakhouse`, `morpho_blue`, `yearn_v3`, `euler_v2`,
`maple`, `aave_v3_base`, `morpho_blue_base`). Разошёлся ровно один.

Отсюда следует главное, и на этом стоит весь модуль: **разрыв отметок есть
свойство пары АРТЕФАКТОВ (их пишет один дневной цикл), а не протокола, и объяснить
им расхождение ОДНОГО из девяти нельзя.** Прежний диагноз (цикл #470, 03.09 —
«числа расходятся ровно тогда, когда расходятся отметки наблюдения», предлагалось
переименовать находку в `apy_stale_copy_vs_live` со ПОНИЖЕНИЕМ до WARN) этим
замером опровергнут; понижение не сделано.

Настоящая причина — ЧЕТЫРЕ кандидата у одного ключа в живом фиде 05.09
(17 041 пул), и два пути отбирают из РАЗНЫХ множеств::

    aa70268e-4b52-42bf-a116-608b370f9501  $153.55M  3.58713  underlying USDC
    6f00d46b-8735-49ae-9ced-2a0fccc56ad0  $ 58.62M  5.24713  "Umbrella"
                                                    underlying 0xD4fa… — НЕ USDC,
                                                    apyBase 3.58713 + apyReward 1.66
    effcb4a4-4dcb-45e5-935d-f15542c13e6b  $  1.53M  2.58038  "Prime Instance"
    27296bf9-617a-46e4-9d6d-eefc71e9e0b6  $  0.65M  4.37200  "Aave Horizon Market"

`adapter_status_generator` фильтрует кандидатов по каноническому underlying и
«Umbrella» отвергает; путь адаптера (`DeFiLlamaFeed.get_pool`, точное совпадение
символа) про underlying не спрашивает вовсе. Пока ядро рынка в снимке есть,
побеждает оно у обоих. Стоит ядру выпасть — генератор падает на `effcb4a4…`
(2.58038), адаптер на `6f00d46b…` (5.24713). Воспроизведено удалением ОДНОГО пула
из живого фида через настоящих вызывающих: разрыв 2.6668 пп против записанных в
снимке 2.6847 пп.
"""
# FROZEN-DATE-OK: даты фикстур — сам предмет теста (воспроизводится снимок
# 2026-09-05 06:00Z, где предметом является совпадение такта двух артефактов).
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import adapter_feed_divergence as afd

# Отметки ДОСЛОВНО из снимка 05.09 — оба артефакта одного цикла, разрыв 2.16 с.
TS_STATUS = "2026-09-05T06:00:26.447071+00:00"
TS_ORCH = "2026-09-05T06:00:28.610293+00:00"
NOW = dt.datetime(2026, 9, 5, 6, 30, 0, tzinfo=dt.timezone.utc)

CORE_POOL = "aa70268e-4b52-42bf-a116-608b370f9501"     # $153.55M, 3.58713, USDC
UMBRELLA_POOL = "6f00d46b-8735-49ae-9ced-2a0fccc56ad0"  # $58.62M, 5.24713, НЕ USDC
PRIME_POOL = "effcb4a4-4dcb-45e5-935d-f15542c13e6b"     # $1.53M, 2.58038


def _status_doc(adapters: dict, ts: str = TS_STATUS) -> dict:
    return {"schema_version": 1, "generated_at": ts, "adapters": adapters}


def _orch_doc(adapters: list, ts: str = TS_ORCH) -> dict:
    return {"schema_version": 1, "generated_at": ts, "source": "adapter_orchestrator",
            "adapters": adapters}


def _run(status_adapters, orch_adapters, *, now=NOW) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "data")
        os.makedirs(data)
        with open(os.path.join(data, "adapter_status.json"), "w") as fh:
            json.dump(_status_doc(status_adapters), fh)
        with open(os.path.join(data, "adapter_orchestrator_status.json"), "w") as fh:
            json.dump(_orch_doc(orch_adapters), fh)
        return afd.run(root=tmp, now=now, data_dir=data)


def _status(apy: float, pool: str | None) -> dict:
    """Сторона `adapter_status.json` для `aave_v3` — форма живого артефакта 05.09."""
    entry = {
        "display_name": "Aave V3", "apy": apy, "live_apy": apy,
        "live_apy_as_of": TS_STATUS, "live_apy_fresh": True, "fallback_apy": 3.5,
        "tvl_usd": 12_000_000_000.0, "tvl_source": "static", "tier": 1,
        "chain": "ethereum", "per_protocol_cap": 0.4, "active": True,
    }
    if pool is not None:
        entry["pool_id"] = pool
    return entry


def _orch(apy: float, pool: str | None, *, tvl: float = 58_396_614.0) -> dict:
    """Сторона снимка оркестратора для `aave_v3` — форма живого артефакта 05.09."""
    entry = {
        "protocol": "aave_v3", "adapter_class": "AaveV3Adapter", "tier": "T1",
        "apy_pct": apy, "tvl_usd": tvl, "status": "ok", "error": None,
        "warning": None, "live_data": True, "tvl_source": "live",
        "health_score": 1.0,
    }
    if pool is not None:
        entry["pool_id"] = pool
    return entry


def _finding(report: dict, kind: str) -> dict:
    return next(f for f in report["findings"] if f["kind"] == kind)


def _kinds(report: dict) -> set:
    return {f["kind"] for f in report["findings"]}


#: Роды оси ДОХОДНОСТИ/ЛИЧНОСТИ. Всё остальное, что сторож честно говорит о тех же
#: фикстурах, — не предмет этих тестов и глушить его нельзя. Фикстуры повторяют
#: живой снимок 05.09, где `adapter_status` несёт статический литерал TVL ($12 млрд),
#: а оркестратор — живое число; сторож пишет об этом `tvl_provenance` (INFO), и это
#: состояние НАЗВАНО и решено (ADR-053). Тесты ниже проверяют свою ось, а не
#: требуют от сторожа замолчать о соседней.
_APY_AXIS = {"apy", "apy_live_vs_live", "apy_literal_vs_live", "apy_both_literal",
             "apy_identity_mismatch", "pool_identity_mismatch"}


def _apy_kinds(report: dict) -> list:
    return [f["kind"] for f in report["findings"] if f["kind"] in _APY_AXIS]


def _loud(report: dict) -> list:
    """Находки, которые ЗВУЧАТ (CRITICAL/WARN) — INFO-провенанс сюда не входит."""
    return [f["kind"] for f in report["findings"]
            if f["severity"] in (afd.CRITICAL, afd.WARN)]


class TestTheMeasuredIncident(unittest.TestCase):
    """Снимок 05.09 06:00Z дословно: 2.5804 против 5.2651 на РАЗНЫХ пулах."""

    def _report(self):
        return _run({"aave_v3": _status(2.5804, PRIME_POOL)},
                    [_orch(5.2651, UMBRELLA_POOL)])

    def test_different_pools_are_named_identity_mismatch_not_a_feed_contradiction(self):
        r = self._report()
        self.assertIn("apy_identity_mismatch", _kinds(r))
        # Ключевое: старый род НЕ выставляется. Пока он выставлялся, сообщение
        # звало чинить fail-CLOSED — то есть выбирать между двумя ВЕРНЫМИ числами.
        self.assertNotIn("apy_live_vs_live", _kinds(r))

    def test_the_finding_carries_both_pools_and_the_measured_delta(self):
        f = _finding(self._report(), "apy_identity_mismatch")
        self.assertEqual(f["severity"], afd.CRITICAL)
        self.assertEqual(f["identity"], "different")
        self.assertEqual(f["adapter_status_apy"], 2.5804)
        self.assertEqual(f["orchestrator_apy"], 5.2651)
        self.assertEqual(f["delta_pp"], 2.6847)
        self.assertEqual(f["adapter_status_pool"], PRIME_POOL)
        self.assertEqual(f["orchestrator_pool"], UMBRELLA_POOL)

    def test_severity_is_NOT_softened_by_the_rename(self):
        """Инвариант #16: диагноз уточняется, громкость не понижается."""
        r = self._report()
        self.assertEqual(afd.exit_code(r), 2)
        self.assertGreaterEqual(r["counts"]["critical"], 1)

    def test_the_message_sends_the_fix_to_pinning_not_to_fail_closed(self):
        msg = _finding(self._report(), "apy_identity_mismatch")["message"]
        self.assertIn("ЗАКРЕПИТЬ", msg)
        self.assertIn(PRIME_POOL, msg)
        self.assertIn(UMBRELLA_POOL, msg)


class TestTheRealContradictionStaysReachable(unittest.TestCase):
    """CRITICAL инварианта 2 обязан остаться ДОСТИЖИМЫМ — иначе это глушение."""

    def test_same_pool_two_numbers_is_still_a_feed_contradiction(self):
        r = _run({"aave_v3": _status(2.5804, CORE_POOL)},
                 [_orch(5.2651, CORE_POOL)])
        f = _finding(r, "apy_live_vs_live")
        self.assertEqual(f["severity"], afd.CRITICAL)
        self.assertEqual(f["identity"], "same")
        self.assertIn("fail-CLOSED", f["message"])
        self.assertNotIn("apy_identity_mismatch", _kinds(r))
        self.assertEqual(afd.exit_code(r), 2)

    def test_same_pool_and_the_same_number_is_no_finding_at_all(self):
        r = _run({"aave_v3": _status(3.58713, CORE_POOL)},
                 [_orch(3.58713, CORE_POOL)])
        self.assertEqual(_apy_kinds(r), [])
        self.assertEqual(_loud(r), [])


class TestUnmeasuredIdentityIsAThirdOutcome(unittest.TestCase):
    """«Личность не названа» ≠ «пул тот же». Разные ответы — разные слова."""

    def test_identity_unchecked_when_the_orchestrator_is_silent(self):
        r = _run({"aave_v3": _status(2.5804, PRIME_POOL)}, [_orch(5.2651, None)])
        f = _finding(r, "apy_live_vs_live")
        self.assertEqual(f["identity"], "unchecked")
        self.assertEqual(f["severity"], afd.CRITICAL)
        self.assertIn("НЕ ИЗМЕРЕНО", f["message"])
        self.assertIn("orchestrator", f["message"])

    def test_identity_unchecked_when_adapter_status_is_silent(self):
        r = _run({"aave_v3": _status(2.5804, None)}, [_orch(5.2651, UMBRELLA_POOL)])
        f = _finding(r, "apy_live_vs_live")
        self.assertEqual(f["identity"], "unchecked")
        self.assertIn("adapter_status", f["message"])

    def test_an_empty_string_is_not_an_identity(self):
        r = _run({"aave_v3": _status(2.5804, "   ")}, [_orch(5.2651, UMBRELLA_POOL)])
        self.assertEqual(_finding(r, "apy_live_vs_live")["identity"], "unchecked")

    def test_unchecked_never_claims_the_pools_are_the_same(self):
        """Самая опасная подмена: молчание, прочитанное как согласие."""
        msg = _finding(
            _run({"aave_v3": _status(2.5804, None)}, [_orch(5.2651, None)]),
            "apy_live_vs_live")["message"]
        self.assertIn("НЕ ИЗМЕРЕНО", msg)
        self.assertNotIn("ОДИН пул", msg)


class TestAgreementOnDifferentPoolsIsCoincidence(unittest.TestCase):
    """Числа сошлись, пулы разные — ключ всё равно не закреплён."""

    def test_matching_numbers_on_different_pools_are_still_reported(self):
        r = _run({"aave_v3": _status(3.58713, CORE_POOL)},
                 [_orch(3.58713, UMBRELLA_POOL)])
        f = _finding(r, "pool_identity_mismatch")
        self.assertEqual(f["severity"], afd.WARN)
        self.assertEqual(f["identity"], "different")
        self.assertIn("совпадение, а не согласие", f["message"])
        self.assertEqual(_loud(r), ["pool_identity_mismatch"])

    def test_matching_numbers_on_the_same_pool_are_silent(self):
        r = _run({"aave_v3": _status(3.58713, CORE_POOL)},
                 [_orch(3.58713, CORE_POOL)])
        self.assertEqual(_apy_kinds(r), [])


class TestTheEightThatAgreedStaySilent(unittest.TestCase):
    """Восемь протоколов снимка 05.09 сошлись — сторож обязан о них молчать.

    Это контроль на ложное срабатывание: если бы новый род срабатывал на разрыве
    ОТМЕТОК (2.16 с у всех девяти), заговорили бы все девять.
    """

    #: ДОСЛОВНО из снимка 05.09 06:00Z — восемь сошедшихся пар.
    AGREED = {
        "compound_v3": 4.0534, "morpho_steakhouse": 4.0956, "morpho_blue": 4.0956,
        "yearn_v3": 3.7814, "euler_v2": 3.1795, "maple": 5.0318,
        "aave_v3_base": 3.888, "morpho_blue_base": 4.7368,
    }

    def test_none_of_the_eight_produces_a_finding(self):
        status = {k: _status(v, f"pool-{k}") for k, v in self.AGREED.items()}
        orch = [dict(_orch(v, f"pool-{k}"), protocol=k) for k, v in self.AGREED.items()]
        r = _run(status, orch)
        self.assertEqual(_apy_kinds(r), [])
        self.assertEqual(_loud(r), [])

    def test_the_ninth_alone_is_what_speaks(self):
        """Девятый (`aave_v3`) добавлен к восьми — находка ровно одна."""
        status = {k: _status(v, f"pool-{k}") for k, v in self.AGREED.items()}
        orch = [dict(_orch(v, f"pool-{k}"), protocol=k) for k, v in self.AGREED.items()]
        status["aave_v3"] = _status(2.5804, PRIME_POOL)
        orch.append(_orch(5.2651, UMBRELLA_POOL))
        r = _run(status, orch)
        self.assertEqual(_apy_kinds(r), ["apy_identity_mismatch"])
        self.assertEqual(_loud(r), ["apy_identity_mismatch"])
        self.assertEqual(_finding(r, "apy_identity_mismatch")["protocol"], "aave_v3")


class TestJournalKeyContinuity(unittest.TestCase):
    """Ряд рецидива `aave_v3:apy_live_vs_live` (с 01.09) НЕ должен разорваться.

    Переименование рода для артефактов без метки личности молча обнулило бы
    счётчик рецидива ADR-207 и погасило бы строку `↺` шага 0-офис. Поэтому при
    `identity="unchecked"` имя рода остаётся прежним.
    """

    def test_unpinned_artifacts_keep_the_historical_kind_name(self):
        r = _run({"aave_v3": _status(11.2163, None)}, [_orch(4.9823, None)])
        self.assertIn("apy_live_vs_live", _kinds(r))
        f = _finding(r, "apy_live_vs_live")
        self.assertEqual(f["delta_pp"], 6.234)   # замер 01.09 17:40Z, дословно
        self.assertEqual(f["identity"], "unchecked")


class TestIdentityVerdictUnit(unittest.TestCase):
    """Сам вердикт личности — по каждой ветке."""

    def test_same_is_case_insensitive(self):
        v, s, o = afd._identity_verdict({"pool_id": CORE_POOL.upper()},
                                        {"pool_id": CORE_POOL})
        self.assertEqual(v, "same")

    def test_different(self):
        v, s, o = afd._identity_verdict({"pool_id": PRIME_POOL},
                                        {"pool_id": UMBRELLA_POOL})
        self.assertEqual((v, s, o), ("different", PRIME_POOL, UMBRELLA_POOL))

    def test_missing_either_side_is_unchecked(self):
        self.assertEqual(afd._identity_verdict({}, {"pool_id": CORE_POOL})[0], "unchecked")
        self.assertEqual(afd._identity_verdict({"pool_id": CORE_POOL}, {})[0], "unchecked")

    def test_non_string_identity_is_not_an_identity(self):
        self.assertEqual(afd._identity_verdict({"pool_id": 42},
                                               {"pool_id": CORE_POOL})[0], "unchecked")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
