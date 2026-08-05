# FROZEN-DATE-OK: даты — синтетические фикстуры истории, обе стороны сравнения запинены; логика модуля часы не читает (generated_at — только метаданные-штамп).
"""Тесты секций пост-циклового отчёта (A4, поток 2 плана relocation 2026-08-04).

Покрытие:
* фикстура «живой книги» (equity-ряд + позиции + adapter_status + apy-ряд) —
  РУЧНЫЕ ожидания для 4 трекеров (portfolio_stats, volatility, attribution,
  market share) + adapter_health;
* честные SKIPPED-кейсы (пустой data/, нет apy_today, нет LP/стейкинга,
  нет gas/токеномики) — с причинами;
* изоляция провала: упавший трекер → секция ERROR, соседи и runner целы;
  упавший сборщик секций → метрики и summary целы;
* контракт: в sections всегда ровно 9 ключей плана.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.analytics.analytics_runner import run_post_cycle_analytics
from spa_core.analytics.report_sections import (
    SECTION_NAMES,
    build_report_sections,
)

# ---------------------------------------------------------------------------
# Фикстура «живой книги»
# ---------------------------------------------------------------------------

_EQUITIES = [100_000.0, 100_100.0, 100_050.0, 100_200.0]
_APY_TODAY = [3.0, 3.2, 3.1, 3.3]  # проценты, как пишет цикл


def _equity_doc() -> dict:
    bars = []
    for i, (e, a) in enumerate(zip(_EQUITIES, _APY_TODAY)):
        bars.append({
            "date": f"2026-07-{i + 1:02d}",
            "equity": e,
            "apy_today": a,
            "positions": {"aave_v3": e * 0.6, "morpho_blue": e * 0.4},
        })
    return {"generated_at": "2026-07-04T08:00:00+00:00", "source": "cycle_runner",
            "is_demo": False, "daily": bars}


def _write_live_book(data_dir: Path) -> None:
    (data_dir / "equity_curve_daily.json").write_text(
        json.dumps(_equity_doc()), encoding="utf-8")
    (data_dir / "current_positions.json").write_text(json.dumps({
        "generated_at": "2026-07-04T08:00:00+00:00",
        "positions": {"aave_v3": 60_000.0, "morpho_blue": 40_000.0},
    }), encoding="utf-8")
    (data_dir / "adapter_status.json").write_text(json.dumps({
        "schema_version": 2,
        "generated_at": "2026-07-03T08:00:00+00:00",
        "adapters": {
            "aave_v3": {"apy": 4.0, "tvl_usd": 12_000_000_000.0, "tier": 1,
                        "chain": "ethereum", "active": True},
            "morpho_blue": {"apy": 6.0, "tvl_usd": 4_000_000_000.0, "tier": 2,
                            "chain": "ethereum", "active": True},
        },
    }), encoding="utf-8")
    # Дневной apy-ряд для stability-компонента aave_v3 (даты НЕ пересекаются
    # с точкой adapter_status 2026-07-03 → итоговый ряд детерминирован:
    # [4.0, 4.2, 4.1] + текущая точка 4.0).
    (data_dir / "apy_series_daily.json").write_text(json.dumps({
        "series": {"aave_v3": [["2026-06-30", 4.0], ["2026-07-01", 4.2],
                               ["2026-07-02", 4.1]]},
    }), encoding="utf-8")


@pytest.fixture()
def live_book(tmp_path: Path) -> Path:
    _write_live_book(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Контракт секций
# ---------------------------------------------------------------------------

class TestSectionsContract:

    def test_exactly_nine_plan_sections(self, live_book):
        sections = build_report_sections(live_book, _equity_doc())
        assert sorted(sections.keys()) == sorted(SECTION_NAMES)
        assert len(sections) == 9
        for name, sec in sections.items():
            assert sec["status"] in ("OK", "SKIPPED", "ERROR"), name
            if sec["status"] == "SKIPPED":
                assert sec["reason"], f"SKIPPED без причины: {name}"

    def test_runner_embeds_sections_and_writes_them(self, live_book):
        summary = run_post_cycle_analytics(data_dir=live_book)
        assert summary["errors"] == []
        on_disk = json.loads(
            (live_book / "analytics_summary.json").read_text(encoding="utf-8"))
        assert sorted(on_disk["sections"].keys()) == sorted(SECTION_NAMES)
        # Метрики MP-104 не пострадали
        for key in ("sharpe", "drawdown", "volatility", "benchmark",
                    "streaks", "calmar", "concentration"):
            assert summary["metrics"][key] is not None


# ---------------------------------------------------------------------------
# Ручные ожидания на фикстуре живой книги
# ---------------------------------------------------------------------------

class TestPortfolioStatsSection:

    def test_hand_computed_values(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())["portfolio_stats"]
        assert sec["status"] == "OK"
        assert sec["data_points"] == 4
        # 100_000 → 100_200: total return = 0.2%
        assert sec["total_return_pct"] == pytest.approx(0.2, abs=1e-9)
        # Единственная просадка: 100_100 → 100_050 = 50/100_100 = 0.04995%
        assert sec["max_drawdown_pct"] == pytest.approx(0.05, abs=0.0005)
        # VaR95 (исторический): худший дневной возврат −50/100_100
        assert sec["value_at_risk_95"] == pytest.approx(50 / 100_100, abs=1e-6)
        assert sec["first_date"] == "2026-07-01"
        assert sec["last_date"] == "2026-07-04"

    def test_short_curve_skipped(self, tmp_path):
        doc = {"daily": [{"date": "2026-07-01", "equity": 100_000.0}]}
        sec = build_report_sections(tmp_path, doc)["portfolio_stats"]
        assert sec["status"] == "SKIPPED"
        assert "короче 2 точек" in sec["reason"]


class TestPortfolioVolatilitySection:

    def test_hand_computed_values(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())[
            "portfolio_volatility_tracker"]
        assert sec["status"] == "OK"
        assert sec["n_readings"] == 4
        # mean([3.0, 3.2, 3.1, 3.3]) = 3.15%
        assert sec["mean_apy_pct"] == pytest.approx(3.15, abs=1e-6)
        # stdev выборки = sqrt(5e-6/3) в долях → 0.1291 п.п.
        assert sec["vol_7d_pp"] == pytest.approx(0.1291, abs=0.0001)
        assert sec["regime"] == "STABLE"     # 0.00129 < 0.005
        assert sec["trend"] == "STABLE"      # vol7 == vol30 (одни и те же 4 точки)

    def test_no_apy_today_skipped(self, tmp_path):
        doc = {"daily": [{"date": "2026-07-01", "equity": 100_000.0},
                         {"date": "2026-07-02", "equity": 100_100.0}]}
        sec = build_report_sections(tmp_path, doc)["portfolio_volatility_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "apy_today" in sec["reason"]

    def test_no_state_file_written(self, live_book):
        build_report_sections(live_book, _equity_doc())
        # Секция — snapshot in-memory; ring-buffer движка НЕ пишется
        assert not (live_book / "portfolio_volatility.json").exists()


class TestYieldAttributionSection:

    def test_hand_computed_values(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())[
            "yield_attribution_tracker"]
        assert sec["status"] == "OK"
        # 60k × 4% + 40k × 6% = 2400 + 2400 = 4800 $/год на 100k
        assert sec["total_allocated_usd"] == pytest.approx(100_000.0)
        assert sec["total_annual_yield_usd"] == pytest.approx(4_800.0)
        assert sec["effective_apy_pct"] == pytest.approx(4.8, abs=1e-9)
        # Равный вклад в доход: по 50%
        by_id = {c["adapter_id"]: c for c in sec["contributions"]}
        assert by_id["aave_v3"]["contribution_pct"] == pytest.approx(50.0)
        assert by_id["morpho_blue"]["contribution_pct"] == pytest.approx(50.0)
        assert by_id["aave_v3"]["weight_pct"] == pytest.approx(60.0)
        assert sec["top_by_apy"] == "morpho_blue"
        # HHI-диверсификация: 1 − (0.6² + 0.4²) = 0.48
        assert sec["diversification_score"] == pytest.approx(0.48, abs=1e-6)
        # int-tier из живой схемы нормализован в "T<n>" (не "unknown")
        assert sec["tier_breakdown"]["T1"]["allocated_usd"] == pytest.approx(60_000.0)
        assert sec["tier_breakdown"]["T2"]["allocated_usd"] == pytest.approx(40_000.0)
        assert "unknown" not in sec["tier_breakdown"]
        assert sec["apy_unknown"] == []

    def test_no_positions_skipped_never_simulated(self, tmp_path):
        # adapter_status есть, позиций нет → SKIPPED, а НЕ симуляция трекера
        (tmp_path / "adapter_status.json").write_text(json.dumps({
            "adapters": {"aave_v3": {"apy": 4.0, "tvl_usd": 1e10, "tier": 1}},
        }), encoding="utf-8")
        sec = build_report_sections(tmp_path, {})["yield_attribution_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "current_positions.json" in sec["reason"]

    def test_position_without_apy_flagged_not_fabricated(self, live_book):
        # Позиция без записи в adapter_status → вклад 0 + честный флаг
        cp = json.loads((live_book / "current_positions.json").read_text())
        cp["positions"]["ghost_protocol"] = 10_000.0
        (live_book / "current_positions.json").write_text(json.dumps(cp))
        sec = build_report_sections(live_book, _equity_doc())[
            "yield_attribution_tracker"]
        assert sec["status"] == "OK"
        assert sec["apy_unknown"] == ["ghost_protocol"]
        assert "note" in sec
        ghost = next(c for c in sec["contributions"]
                     if c["adapter_id"] == "ghost_protocol")
        assert ghost["apy_pct"] == 0.0
        assert ghost["annual_yield_usd"] == 0.0


class TestMarketShareSection:

    def test_hand_computed_values(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())[
            "defi_protocol_market_share_tracker"]
        assert sec["status"] == "OK"
        assert sec["protocol_count"] == 2
        assert sec["total_tvl_usd"] == pytest.approx(16_000_000_000.0)
        # Доли 75/25 → HHI = 75² + 25² = 6250
        assert sec["hhi_concentration"] == pytest.approx(6250.0, abs=0.01)
        assert sec["category_leader"] == "aave_v3"
        shares = {p["name"]: p for p in sec["protocols"]}
        assert shares["aave_v3"]["tvl_market_share_pct"] == pytest.approx(75.0)
        assert shares["morpho_blue"]["tvl_market_share_pct"] == pytest.approx(25.0)
        assert shares["aave_v3"]["market_position"] == "DOMINANT"   # >40%
        assert shares["morpho_blue"]["market_position"] == "LEADING"  # >20%
        assert shares["aave_v3"]["category_leader"] is True
        # Честность: метрики без входов не публикуются, а перечислены
        assert "share_change" in sec["omitted_metrics"]
        for p in sec["protocols"]:
            assert "tvl_share_change_30d_pct" not in p
            assert "protocol_stickiness_score" not in p

    def test_no_log_side_effect(self, live_book, monkeypatch):
        # write_log=False по контракту секции: если движок всё же попробует
        # писать ring-buffer лог — этот стаб уронит секцию в ERROR.
        from spa_core.analytics.defi_protocol_market_share_tracker import (
            DeFiProtocolMarketShareTracker,
        )

        def _no_write(entry, log_path):
            raise AssertionError("market_share log write attempted")

        monkeypatch.setattr(DeFiProtocolMarketShareTracker, "_append_log",
                            staticmethod(_no_write))
        sec = build_report_sections(live_book, _equity_doc())[
            "defi_protocol_market_share_tracker"]
        assert sec["status"] == "OK"

    def test_no_tvl_skipped(self, tmp_path):
        (tmp_path / "adapter_status.json").write_text(json.dumps({
            "adapters": {"a": {"apy": 4.0, "tier": 1}},  # TVL нет
        }), encoding="utf-8")
        sec = build_report_sections(tmp_path, {})[
            "defi_protocol_market_share_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "TVL" in sec["reason"]


class TestAdapterHealthSection:

    def test_partial_composite_hand_computed(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())[
            "adapter_health_scorecard"]
        assert sec["status"] == "OK"
        rows = {r["adapter_id"]: r for r in sec["adapters"]}
        aave = rows["aave_v3"]
        # apy 4% → 4/15 × 100 = 26.67; tvl ≥ $10M → 100;
        # ряд [4.0, 4.2, 4.1, 4.0(status)] → stdev 0.09574 п.п. → 98.09
        assert aave["components"]["apy"] == pytest.approx(26.67, abs=0.01)
        assert aave["components"]["liquidity"] == pytest.approx(100.0)
        assert aave["components"]["stability"] == pytest.approx(98.09, abs=0.01)
        assert aave["weight_coverage"] == pytest.approx(0.65)
        # (26.67×0.25 + 98.09×0.20 + 100×0.20) / 0.65 = 71.21
        assert aave["composite_partial"] == pytest.approx(71.21, abs=0.01)
        assert aave["unchecked_components"] == ["safety", "slippage"]
        # morpho_blue: одна точка APY → stability тоже UNCHECKED
        morpho = rows["morpho_blue"]
        assert morpho["unchecked_components"] == ["safety", "slippage", "stability"]
        assert morpho["components"]["apy"] == pytest.approx(40.0)
        assert morpho["composite_partial"] == pytest.approx(
            (40.0 * 0.25 + 100.0 * 0.20) / 0.45, abs=0.01)
        # grade/recommendation по 65% входов НЕ выдаются
        assert "grade" not in aave and "recommendation" not in aave

    def test_empty_status_skipped(self, tmp_path):
        sec = build_report_sections(tmp_path, {})["adapter_health_scorecard"]
        assert sec["status"] == "SKIPPED"


# ---------------------------------------------------------------------------
# SKIPPED-кейсы «данных нет по построению»
# ---------------------------------------------------------------------------

class TestHonestSkips:

    def test_empty_data_dir_all_nine_skipped(self, tmp_path):
        sections = build_report_sections(tmp_path, {})
        assert len(sections) == 9
        for name, sec in sections.items():
            assert sec["status"] == "SKIPPED", f"{name}: {sec}"
            assert sec["reason"]

    def test_lp_skipped_without_file_ok_with_positions(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())["lp_position_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "LP" in sec["reason"]
        # А с реальным файлом позиций — честная сводка
        (live_book / "lp_positions.json").write_text(json.dumps([
            {"position_id": "p1", "pool_id": "x", "protocol": "curve",
             "token_pair": "USDC/USDT", "entry_capital_usd": 10_000.0,
             "fees_accumulated_usd": 50.0, "days_active": 10.0,
             "status": "ACTIVE"},
            {"position_id": "p2", "pool_id": "y", "protocol": "uniswap",
             "token_pair": "ETH/USDC", "entry_capital_usd": 5_000.0,
             "fees_accumulated_usd": 10.0, "days_active": 3.0,
             "status": "CLOSED"},
        ]), encoding="utf-8")
        sec2 = build_report_sections(live_book, _equity_doc())["lp_position_tracker"]
        assert sec2["status"] == "OK"
        assert sec2["total_positions"] == 2
        assert sec2["active_positions"] == 1
        assert sec2["total_fees_earned_usd"] == pytest.approx(50.0)  # только ACTIVE
        assert sec2["overall_fee_yield_pct"] == pytest.approx(0.005)

    def test_staking_skipped_without_positions(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())["staking_reward_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "стейкинг" in sec["reason"]

    def test_chain_fee_skipped_reason_mentions_gas_and_eth_price(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())["chain_fee_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "gas" in sec["reason"]
        assert "ETH" in sec["reason"]

    def test_governance_skipped(self, live_book):
        sec = build_report_sections(live_book, _equity_doc())[
            "governance_token_value_tracker"]
        assert sec["status"] == "SKIPPED"
        assert "токеномики" in sec["reason"]


# ---------------------------------------------------------------------------
# Fail-safe: провал трекера/сборщика не ломает отчёт
# ---------------------------------------------------------------------------

class TestFailureIsolation:

    def test_one_tracker_crash_is_isolated(self, live_book, monkeypatch):
        import spa_core.analytics.portfolio_stats as ps_mod

        def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(ps_mod, "portfolio_summary", _boom)
        sections = build_report_sections(live_book, _equity_doc())
        assert sections["portfolio_stats"]["status"] == "ERROR"
        assert "RuntimeError" in sections["portfolio_stats"]["error"]
        # Соседи живы и содержательны
        assert sections["portfolio_volatility_tracker"]["status"] == "OK"
        assert sections["yield_attribution_tracker"]["status"] == "OK"
        assert sections["defi_protocol_market_share_tracker"]["status"] == "OK"
        assert len(sections) == 9

    def test_tracker_crash_does_not_break_runner(self, live_book, monkeypatch):
        import spa_core.analytics.yield_attribution_tracker as yat_mod

        def _boom(*a, **kw):
            raise RuntimeError("attribution down")

        monkeypatch.setattr(yat_mod.YieldAttributionTracker,
                            "generate_report", _boom)
        summary = run_post_cycle_analytics(data_dir=live_book)
        assert summary["sections"]["yield_attribution_tracker"]["status"] == "ERROR"
        # Метрики и файл целы
        assert summary["metrics"]["sharpe"] is not None
        assert (live_book / "analytics_summary.json").exists()

    def test_whole_builder_crash_keeps_metrics(self, live_book, monkeypatch):
        import spa_core.analytics.report_sections as rs_mod

        def _boom(*a, **kw):
            raise RuntimeError("sections down")

        monkeypatch.setattr(rs_mod, "build_report_sections", _boom)
        summary = run_post_cycle_analytics(data_dir=live_book)
        assert summary["sections"] == {}
        assert any(e.startswith("sections:") for e in summary["errors"])
        assert summary["metrics"]["sharpe"] is not None
        assert (live_book / "analytics_summary.json").exists()
