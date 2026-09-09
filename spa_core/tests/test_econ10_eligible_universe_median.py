"""ECON-10 меряет медиану ELIGIBLE-НАБОРА, а не медиану книги (ADR-272).

Положительный контроль — авария 2026-09-08: аудитор каждый день сообщал владельцу
«❌ VIOLATION ECON-10 (compound_v3)», а исполнение находки стоило бы −20.7 bps/год,
потому что ВСЕ альтернативы в T1 доходнее не были. Числа ниже — замер того дня
(`data/adapter_orchestrator_status.json`, `data/current_positions.json`).

# FROZEN-DATE-OK: historical-incident — числа и дата 2026-09-08 и есть предмет
# теста (воспроизведение конкретной ложной находки); часов здесь нет вовсе.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.allocator.rebalance_economics import below_median_cap_violations

# Книга 2026-09-08 17:27 UTC (доллары) и её ставки.
BOOK = {"compound_v3": 40000.0, "pendle": 20000.0, "fluid_usdc": 20000.0,
        "maple": 5263.16, "aave_v3": 4736.84, "morpho_blue_base": 4736.84}
BOOK_APY = {"compound_v3": 4.6454, "pendle": 8.0, "fluid_usdc": 5.14,
            "maple": 4.9776, "aave_v3": 3.61, "morpho_blue_base": 4.2907}
CAPS = {"compound_v3": 0.40, "pendle": 0.20, "fluid_usdc": 0.20,
        "maple": 0.20, "aave_v3": 0.40, "morpho_blue_base": 0.20}
CAPITAL = 100000.0
# Eligible-набор того же снимка: живая ставка И живой TVL ≥ $5M (9 пулов, медиана 4.2907).
UNIVERSE = {"aave_v3": 3.61, "aave_v3_base": 3.79, "spark_usdc": 3.81,
            "morpho_steakhouse": 4.28, "morpho_blue_base": 4.2907, "morpho_blue": 4.29,
            "compound_v3": 4.6454, "maple": 4.9776, "fluid_fusdc": 5.14}


def test_the_2026_09_08_finding_was_produced_by_the_book_median():
    """Что происходило до правки: медиана книги 4.81 % → compound_v3 объявлен нарушителем."""
    rows = below_median_cap_violations(
        positions=BOOK, apy_pct=BOOK_APY, tier_caps=CAPS, capital_usd=CAPITAL,
        evidenced=set(BOOK_APY))
    assert [r["protocol"] for r in rows] == ["compound_v3"]
    assert rows[0]["median_basis"] == "funded_book"
    assert rows[0]["median_apy_pct"] == pytest.approx(4.8115, abs=0.001)


def test_the_owners_rule_eligible_universe_median_does_not_fire():
    """Правило владельца («ниже медианы eligible-набора») на тех же числах МОЛЧИТ.

    Медиана eligible 4.2907 %, compound_v3 даёт 4.6454 % — он ВЫШЕ, и это верно:
    все альтернативы в его тире ниже, исполнение находки стоило бы 20 000 × (4.6454 − 3.61) %
    = 207 $/год."""
    rows = below_median_cap_violations(
        positions=BOOK, apy_pct=BOOK_APY, tier_caps=CAPS, capital_usd=CAPITAL,
        evidenced=set(BOOK_APY), universe_apy_pct=UNIVERSE)
    assert rows == []


def test_a_real_violation_still_fires_against_the_eligible_median():
    """Правило НЕ ослаблено: позиция, действительно худшая, чем eligible-набор, краснеет.

    aave_v3 при 3.61 % ниже медианы 4.2907 %; поднимем его долю выше половины
    T1-потолка (25 % > 20 %) — находка обязана появиться."""
    book = dict(BOOK, aave_v3=25000.0)
    rows = below_median_cap_violations(
        positions=book, apy_pct=BOOK_APY, tier_caps=CAPS, capital_usd=CAPITAL,
        evidenced=set(BOOK_APY), universe_apy_pct=UNIVERSE)
    assert [r["protocol"] for r in rows] == ["aave_v3"]
    assert rows[0]["median_basis"] == "eligible_universe" and rows[0]["median_n"] == 9


def test_every_row_names_which_median_produced_it():
    """Читатель обязан видеть, на какой вопрос ответила находка — иначе повторится 08.09."""
    rows = below_median_cap_violations(
        positions=BOOK, apy_pct=BOOK_APY, tier_caps=CAPS, capital_usd=CAPITAL,
        evidenced=set(BOOK_APY))
    assert all("median_basis" in r and "median_n" in r for r in rows)


def test_universe_of_fewer_than_three_is_noise_not_a_signal():
    rows = below_median_cap_violations(
        positions=BOOK, apy_pct=BOOK_APY, tier_caps=CAPS, capital_usd=CAPITAL,
        evidenced=set(BOOK_APY), universe_apy_pct={"a": 1.0, "b": 2.0})
    assert rows == []


# ── аудитор: третий исход вместо подмены медианой книги ───────────────────────────────
def _findings(tmp_path, snapshot):
    from spa_core.agents.allocation_auditor import AllocationAuditor
    from spa_core.risk.policy import RiskConfig
    book = {"generated_at": "2030-01-01T00:00:00+00:00", "capital_usd": CAPITAL,
            "positions": dict(BOOK),
            "positions_detail": {k: {"usd": BOOK[k], "apy_pct": BOOK_APY[k]} for k in BOOK}}
    bp = tmp_path / "current_positions.json"
    bp.write_text(json.dumps(book), encoding="utf-8")
    op = tmp_path / "orch.json"
    op.write_text(json.dumps(snapshot if snapshot is not None else {}), encoding="utf-8")
    if snapshot is None:
        op.unlink()
    tiers = {p: ("T1" if p in ("compound_v3", "aave_v3") else "T2")
             for p in set(BOOK) | set(UNIVERSE)}
    a = AllocationAuditor(positions_path=bp, orchestrator_path=op, config=RiskConfig(),
                          chain_map_provider=lambda: {},
                          tier_provider=lambda x: tiers.get(x, "T2"))
    from datetime import datetime, timezone
    return [f for f in a.audit(now=datetime(2030, 1, 1, tzinfo=timezone.utc)).findings
            if f.rule_id == "ECON-10"]


def test_auditor_says_unmeasured_when_the_snapshot_is_missing(tmp_path):
    """Нет снимка ⇒ «не измерено» с названной причиной, а НЕ находка по медиане книги."""
    got = _findings(tmp_path, None)
    assert len(got) == 1 and got[0].verdict == "UNCHECKED", got
    assert "eligible-набор не измерен" in got[0].detail


def test_auditor_is_quiet_on_the_2026_09_08_snapshot(tmp_path):
    """Тот же день, тот же снимок — аудитор больше не будит владельца ложной находкой."""
    rows = [{"protocol": p, "tier": "T2", "apy_pct": v, "tvl_usd": 1.5e8, "tvl_source": "live"}
            for p, v in UNIVERSE.items()]
    got = _findings(tmp_path, {"adapters": rows})
    assert len(got) == 1 and got[0].verdict == "OK", [f.detail for f in got]
    assert "eligible-набора" in got[0].detail


def test_auditor_excludes_pools_below_the_tvl_floor_from_the_universe(tmp_path):
    """Пул с TVL ниже пола не альтернатива — в медиану он не входит (ADR-053)."""
    from spa_core.agents.allocation_auditor import AllocationAuditor
    from spa_core.risk.policy import RiskConfig
    rows = [{"protocol": p, "tier": "T2", "apy_pct": v, "tvl_usd": 1.5e8, "tvl_source": "live"}
            for p, v in UNIVERSE.items()]
    rows.append({"protocol": "moonwell_base", "tier": "T3", "apy_pct": 14.03,
                 "tvl_usd": 78192.0, "tvl_source": "live"})
    op = tmp_path / "orch.json"; op.write_text(json.dumps({"adapters": rows}), encoding="utf-8")
    a = AllocationAuditor(positions_path=tmp_path / "nope.json", orchestrator_path=op,
                          config=RiskConfig())
    universe, err = a._eligible_universe_apy()
    assert err is None and "moonwell_base" not in universe and len(universe) == 9
