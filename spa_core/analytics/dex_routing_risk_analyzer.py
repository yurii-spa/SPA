"""
MP-673: DEXRoutingRiskAnalyzer
Analyze risk of DEX routing paths — multi-hop swaps accumulate slippage,
introduce MEV risk, and can fail under gas limits.

Advisory/read-only — never modifies allocator, risk, or execution domains.
Pure stdlib only. Atomic writes (tmp + os.replace).
"""

from dataclasses import dataclass
from typing import List
import json
import time
import os
from pathlib import Path

DATA_FILE = Path("data/dex_routing_log.json")
MAX_ENTRIES = 100

GAS_UNITS_PER_HOP = 150_000  # ~150k gas per swap hop


@dataclass
class RoutingHop:
    dex_id: str
    pool_address: str        # string identifier
    token_in: str
    token_out: str
    pool_tvl_usd: float
    hop_slippage_bps: float  # expected slippage in basis points per hop


@dataclass
class RoutingProfile:
    route_id: str
    trade_amount_usd: float
    hops: List[RoutingHop]
    gas_price_gwei: float
    eth_price_usd: float
    max_slippage_tolerance_bps: float  # user setting


@dataclass
class RoutingRiskReport:
    route_id: str
    hop_count: int
    total_slippage_bps: float       # sum of hop slippages
    cumulative_slippage_pct: float  # total_slippage_bps / 100
    gas_cost_usd: float
    gas_as_pct_of_trade: float
    mev_risk_score: float           # 0.0–1.0
    execution_risk: str             # LOW / MEDIUM / HIGH / CRITICAL
    expected_output_usd: float      # trade_amount - slippage losses - gas
    verdict: str                    # EXECUTE / SPLIT / REJECT
    warnings: List[str]


class DEXRoutingRiskAnalyzer:
    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = data_file

    def _total_slippage_bps(self, hops: List[RoutingHop]) -> float:
        """Sum slippage across all hops."""
        return sum(h.hop_slippage_bps for h in hops)

    def _cumulative_slippage_pct(self, total_slippage_bps: float) -> float:
        """Convert bps to percentage (100 bps = 1.0%)."""
        return total_slippage_bps / 100

    def _gas_cost_usd(
        self,
        hop_count: int,
        gas_price_gwei: float,
        eth_price_usd: float,
    ) -> float:
        """Estimate gas cost in USD: 150k gas per hop."""
        return GAS_UNITS_PER_HOP * hop_count * gas_price_gwei * 1e-9 * eth_price_usd

    def _gas_as_pct_of_trade(self, gas_cost_usd: float, trade_amount_usd: float) -> float:
        if trade_amount_usd <= 0:
            return 0.0
        return gas_cost_usd / trade_amount_usd * 100

    def _mev_risk_score(self, hop_count: int, trade_amount_usd: float) -> float:
        """0.1 base + 0.15/hop + 0.2 if trade > $10k. Capped at 1.0."""
        score = 0.1 + 0.15 * hop_count
        if trade_amount_usd > 10_000:
            score += 0.2
        return min(1.0, score)

    def _execution_risk(
        self,
        total_slippage_bps: float,
        max_slippage_tolerance_bps: float,
        hop_count: int,
        gas_as_pct: float,
    ) -> str:
        if total_slippage_bps > max_slippage_tolerance_bps:
            return "CRITICAL"
        elif hop_count >= 4:
            return "HIGH"
        elif hop_count >= 2 or gas_as_pct > 5:
            return "MEDIUM"
        else:
            return "LOW"

    def _expected_output_usd(
        self,
        trade_amount_usd: float,
        cumulative_slippage_pct: float,
        gas_cost_usd: float,
    ) -> float:
        """trade_amount * (1 - cumulative_slippage_pct/100) - gas_cost. Never negative."""
        output = trade_amount_usd * (1 - cumulative_slippage_pct / 100) - gas_cost_usd
        return max(0.0, output)

    def _verdict(
        self,
        execution_risk: str,
        expected_output_usd: float,
        trade_amount_usd: float,
        hop_count: int,
        gas_as_pct: float,
    ) -> str:
        if execution_risk == "CRITICAL" or expected_output_usd < trade_amount_usd * 0.97:
            return "REJECT"
        elif hop_count >= 3 or gas_as_pct > 3:
            return "SPLIT"
        else:
            return "EXECUTE"

    def _warnings(
        self,
        hop_count: int,
        total_slippage_bps: float,
        max_slippage_tolerance_bps: float,
        gas_as_pct: float,
        mev_risk_score: float,
    ) -> List[str]:
        warns: List[str] = []
        if hop_count >= 3:
            warns.append(f"⚠️ {hop_count}-hop route — consider direct path")
        if total_slippage_bps > max_slippage_tolerance_bps:
            warns.append(
                f"🚨 Route slippage {total_slippage_bps:.0f}bps exceeds tolerance {max_slippage_tolerance_bps:.0f}bps"
            )
        if gas_as_pct > 5:
            warns.append(
                f"⚠️ Gas cost {gas_as_pct:.1f}% of trade — unprofitable for small trades"
            )
        if mev_risk_score > 0.5:
            warns.append("🏃 High MEV risk — use private RPC")
        return warns

    def analyze(self, profile: RoutingProfile) -> RoutingRiskReport:
        # ── Protocol-context (ADR-031 Tier-B mass wiring, audit 2026-08-04 step-2) ──
        # Контекст агрегатора → структурный профиль из _protocol_facts → СОБСТВЕННЫЙ
        # движок модуля; неизвестный протокол → None (громкий dormant, не фабрикация).
        from spa_core.analytics import _protocol_facts as _pf
        if _pf.is_protocol_context(profile):
            import dataclasses as _dc
            _p = _pf.generic_profile_for(profile["protocol"])
            if _p is None:
                return None
            _hop = RoutingHop(dex_id="uniswap_v3", pool_address="ctx",
                              token_in=_p["asset"], token_out="USDC",
                              pool_tvl_usd=_p["tvl_usd"],
                              hop_slippage_bps=max(_p["fee_pct"] * 100.0, 5.0))
            _inp = RoutingProfile(route_id=_p["name"],
                                  trade_amount_usd=_p["capital_usd"], hops=[_hop],
                                  gas_price_gwei=20.0, eth_price_usd=3000.0,
                                  max_slippage_tolerance_bps=50.0)
            _rep = _dc.asdict(self.analyze(_inp))
            return _pf.extract_protocol_score(_rep, _p)
        hop_count = len(profile.hops)
        total_slip = self._total_slippage_bps(profile.hops)
        cum_slip_pct = self._cumulative_slippage_pct(total_slip)
        gas_cost = self._gas_cost_usd(hop_count, profile.gas_price_gwei, profile.eth_price_usd)
        gas_pct = self._gas_as_pct_of_trade(gas_cost, profile.trade_amount_usd)
        mev = self._mev_risk_score(hop_count, profile.trade_amount_usd)
        exec_risk = self._execution_risk(
            total_slip,
            profile.max_slippage_tolerance_bps,
            hop_count,
            gas_pct,
        )
        expected_out = self._expected_output_usd(profile.trade_amount_usd, cum_slip_pct, gas_cost)
        verdict = self._verdict(exec_risk, expected_out, profile.trade_amount_usd, hop_count, gas_pct)
        warns = self._warnings(
            hop_count, total_slip, profile.max_slippage_tolerance_bps, gas_pct, mev
        )
        return RoutingRiskReport(
            route_id=profile.route_id,
            hop_count=hop_count,
            total_slippage_bps=total_slip,
            cumulative_slippage_pct=cum_slip_pct,
            gas_cost_usd=gas_cost,
            gas_as_pct_of_trade=gas_pct,
            mev_risk_score=mev,
            execution_risk=exec_risk,
            expected_output_usd=expected_out,
            verdict=verdict,
            warnings=warns,
        )

    def analyze_batch(self, profiles: List[RoutingProfile]) -> List[RoutingRiskReport]:
        return [self.analyze(p) for p in profiles]

    def save_results(self, results: List[RoutingRiskReport]) -> None:
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(self.data_file.read_text())
        except Exception:
            existing = []
        for r in results:
            existing.append(
                {
                    "timestamp": time.time(),
                    "route_id": r.route_id,
                    "hop_count": r.hop_count,
                    "total_slippage_bps": r.total_slippage_bps,
                    "execution_risk": r.execution_risk,
                    "verdict": r.verdict,
                }
            )
        existing = existing[-MAX_ENTRIES:]
        tmp = self.data_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2))
        os.replace(tmp, self.data_file)

    def load_history(self) -> List[dict]:
        try:
            return json.loads(self.data_file.read_text())
        except Exception:
            return []
