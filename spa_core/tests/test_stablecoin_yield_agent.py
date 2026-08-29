"""spa_core/tests/test_stablecoin_yield_agent.py — Stablecoin Yield analyst (AAA Phase 2, step 7).

Proves the first live analyst on the harness: ranks conservative-tier (T1/T2) stablecoin yields by
RISK-ADJUSTED APY from the live feed, evidence-tags each, excludes+counts exotic T3, fails CLOSED to
UNKNOWN on a missing/stale feed, and never fabricates a number. PURE / sandbox files only / no LLM.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.investment_os.agents.stablecoin_yield import StablecoinYieldAgent
from spa_core.investment_os.harness import UNKNOWN


def _dt(day=17):
    return datetime(2026, 7, day, 9, 0, tzinfo=timezone.utc)


def _ranking(tmp_path):
    # ФИКСТУРА обновлена (цикл #174, карточка ADR-076.2): у строк появилось поле
    # `apy_source` — провенанс числа. Ни одно УТВЕРЖДЕНИЕ этих тестов не тронуто:
    # порядок, тир-фильтр, метки доказанности, счётчик T3 проверяются дословно как
    # раньше. Изменена только фикстура, и в честную сторону: она называет себя
    # «живым рейтингом», а с 09.08 это надо заявить полем, а не подразумевать —
    # иначе строка неотличима от литерала `fallback_apy` (ровно так офис
    # публиковал aerodrome 8.5 % как наблюдение). Отказ потребителя от строк без
    # провенанса закреплён отдельно: test_office_opportunities_are_observations.py.
    p = tmp_path / "apy_ranking.json"
    p.write_text(json.dumps({
        "generated_at": "2026-07-16T07:43:58Z",
        "count": 4,
        "by_risk_adjusted": [
            {"protocol": "aave_usdc", "tier": "T1", "apy_pct": 4.2, "risk_adjusted_apy": 3.9,
             "network": "ethereum", "tvl_usd": 5e8, "risk_score": 0.2, "last_updated": "2026-07-16T07:00:00Z",
             "apy_source": "live", "observed_apy_pct": 4.2, "tvl_source": "live"},
            {"protocol": "morpho_usdc", "tier": "T2", "apy_pct": 6.1, "risk_adjusted_apy": 4.5,
             "network": "base", "tvl_usd": 1e8, "risk_score": 0.4, "last_updated": "2026-07-16T07:00:00Z",
             "apy_source": "live", "observed_apy_pct": 6.1, "tvl_source": "live"},
            {"protocol": "pendle_yt_susde", "tier": "T3", "apy_pct": 14.0, "risk_adjusted_apy": 7.0,
             "network": "ethereum", "tvl_usd": 0.0, "risk_score": 0.9, "last_updated": "2026-07-16T07:00:00Z",
             "apy_source": "live", "observed_apy_pct": 14.0, "tvl_source": "static"},
            {"protocol": "sky_susds", "tier": "T2", "apy_pct": 5.0, "risk_adjusted_apy": 4.0,
             "network": "ethereum", "tvl_usd": 2e8, "risk_score": 0.5, "last_updated": "2026-07-16T07:00:00Z",
             "apy_source": "live", "observed_apy_pct": 5.0, "tvl_source": "live"},
        ],
    }), encoding="utf-8")
    return p


def test_analyze_ranks_conservative_by_risk_adjusted(tmp_path):
    a = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path)
    out = a.analyze()
    assert out["status"] == "ok"
    picks = out["top_stablecoin_yields"]
    # only T1/T2 considered; sorted by risk_adjusted_apy desc → morpho(4.5) > sky(4.0) > aave(3.9)
    protos = [p["value"]["protocol"] for p in picks]
    assert protos == ["morpho_usdc", "sky_susds", "aave_usdc"]
    assert out["n_considered_conservative"] == 3


def test_t3_excluded_but_counted(tmp_path):
    a = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path)
    out = a.analyze()
    protos = [p["value"]["protocol"] for p in out["top_stablecoin_yields"]]
    assert "pendle_yt_susde" not in protos          # exotic T3 excluded from picks
    assert out["refused_exotic_t3_count"] == 1       # but honestly counted


def test_evidence_tags_present(tmp_path):
    """Наблюдённое число из фида — ровно L2, и НИКОГДА выше.

    ИЗМЕНЕНО НАМЕРЕННО 2026-08-29 (инвариант 16: обоснование здесь + запись
    в docs/journal/2026-W35.md). Тест раньше требовал ``T1 → "L4", T2 → "L3"``
    и тем самым ЗАКРЕПЛЯЛ ложное утверждение: по каноническому стандарту
    ``docs/37_apy_realism_and_evidence_standard.md`` **L4 = «исполнено реальным,
    хоть и небольшим, капиталом; наблюдались проскальзывание, газ, наполнение
    заявки»**. Реального капитала не было ни разу — система на paper-стадии.
    Живой артефакт ``data/investment_os/stablecoin_yield.json`` носил ``L4``
    на числах из публичного API.

    Проверка не ослаблена, а УСИЛЕНА: раньше допускалась пара значений и
    связь уровня с ТИРОМ (разные оси — тир про риск протокола, уровень про
    зрелость нашего знания); теперь требуется точное L2 И отдельно
    запрещается любое L4+, чего старый тест не проверял вовсе.
    """
    a = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path)
    picks = a.analyze()["top_stablecoin_yields"]
    assert picks, "без выборок проверка была бы вакуумной"
    for p in picks:
        assert p["evidence_level"] == "L2", (
            f"{p['value'].get('protocol')}: наблюдённое число из фида — это L2 "
            "(«источник тянется нашим кодом, проверен по схеме и свежести»)")
        assert "apy_ranking.json" in p["source"]
    # Уровень НЕ зависит от тира: T1 и T2 получают одно и то же.
    by_proto = {p["value"]["protocol"]: p["evidence_level"] for p in picks}
    assert by_proto["aave_usdc"] == by_proto["morpho_usdc"] == "L2"
    # Класс запрета целиком: заявка об исполнении капиталом до go-live невозможна.
    assert not [p for p in picks if p["evidence_level"] in ("L4", "L5", "L6")]


def test_missing_feed_is_unknown(tmp_path):
    a = StablecoinYieldAgent(ranking_path=tmp_path / "nope.json", data_dir=tmp_path)
    out = a.analyze()
    assert out["status"] == UNKNOWN and "fail-closed" in out["reason"]


def test_stale_feed_is_unknown(tmp_path):
    import os
    p = _ranking(tmp_path)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp()
    os.utime(p, (old, old))                          # make the file 6+ months old
    a = StablecoinYieldAgent(ranking_path=p, data_dir=tmp_path)
    out = a.analyze()
    assert out["status"] == UNKNOWN


def test_empty_rows_is_unknown(tmp_path):
    p = tmp_path / "apy_ranking.json"
    p.write_text(json.dumps({"generated_at": "x", "by_risk_adjusted": []}), encoding="utf-8")
    a = StablecoinYieldAgent(ranking_path=p, data_dir=tmp_path)
    assert a.analyze()["status"] == UNKNOWN


def test_run_emits_advisory_artifact(tmp_path):
    a = StablecoinYieldAgent(ranking_path=_ranking(tmp_path), data_dir=tmp_path)
    path = a.run(now=_dt())
    doc = json.loads(path.read_text())
    assert doc["is_advisory"] is True
    assert doc["agent"] == "stablecoin_yield"
    assert doc["status"] == "ok"
    assert doc["top_stablecoin_yields"]
    assert (tmp_path / "stablecoin_yield_proof.jsonl").exists()
