"""
spa_core/family_fund/research_mode.py

Research mode extension for Family Fund backend.
Shows RS-001 and RS-002 as experimental (non-investable) strategies in the UI.

Research mode panel shows:
  - What RS-001 would theoretically return (with clear RESEARCH ONLY disclaimer)
  - What RS-002 would theoretically return (with IL model output)
  - Source quality for each slot
  - Days until paper trading might become viable

API endpoint: GET /api/research/status
Response:
{
  "rs001": {
    "name": "Anti-Crisis Research",
    "target_apy": 18.2,
    "strict_eligible_fraction": 0.15,
    "status": "RESEARCH_ONLY",
    "blended_apy_projection": float,
    "disclaimer": "Not investable. No historical data for 85% of allocation."
  },
  "rs002": {
    "name": "Cashflow Research",
    "target_gross_apy": 29.24,
    "net_apy_range": [12, 18],
    "il_risk": "HIGH",
    "status": "RESEARCH_ONLY",
    "disclaimer": "IL risk not modeled historically. Research projection only."
  },
  "gate": {
    "paper_ready": false,
    "blockers": ["Owner acceptance not signed", ...],
    "estimated_paper_start": null
  }
}

Rules:
  - stdlib only — no external dependencies
  - Atomic writes: tmp file + os.replace
  - Read-only / advisory — does NOT modify allocator / risk / execution
  - LLM FORBIDDEN

Date: 2026-06-19 (MP-1335, Sprint v9.51)
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

__all__ = ["ResearchModeAPI"]

# ── RS-001 slot definitions (matches rs001_live_apy_engine.py) ──────────────
_RS001_SLOTS = [
    {"slot_id": "stablecoin_t1",        "weight": 0.15, "placeholder_apy": 3.5,  "source_quality": "CLEAN"},
    {"slot_id": "gmx_btc_exposure",     "weight": 0.20, "placeholder_apy": 15.0, "source_quality": "RESEARCH"},
    {"slot_id": "gmx_eth_exposure",     "weight": 0.10, "placeholder_apy": 15.0, "source_quality": "RESEARCH"},
    {"slot_id": "btc_stable_pool",      "weight": 0.35, "placeholder_apy": 25.0, "source_quality": "PLACEHOLDER"},
    {"slot_id": "eth_aggressive_pool",  "weight": 0.05, "placeholder_apy": 45.0, "source_quality": "PLACEHOLDER"},
    {"slot_id": "gold_proxy",           "weight": 0.15, "placeholder_apy": 8.0,  "source_quality": "RESEARCH"},
]

# ── RS-002 slot definitions (matches rs002_live_apy_engine.py) ──────────────
_RS002_SLOTS = [
    {"slot_id": "btc_usd_conc_liq",     "weight": 0.60, "gross_apy": 40.0, "is_lp": True,  "asset_vol": None,  "is_btc_lp": True,  "source_quality": "source_needed"},
    {"slot_id": "rwa_conc_liq",         "weight": 0.10, "gross_apy": 18.0, "is_lp": True,  "asset_vol": 0.05,  "is_btc_lp": False, "source_quality": "source_needed"},
    {"slot_id": "trader_losses_vault",  "weight": 0.14, "gross_apy": 20.0, "is_lp": False, "asset_vol": None,  "is_btc_lp": False, "source_quality": "source_needed"},
    {"slot_id": "stablecoin_deposit",   "weight": 0.16, "gross_apy": 4.0,  "is_lp": False, "asset_vol": None,  "is_btc_lp": False, "source_quality": "CLEAN"},
]

# Default BTC annualized vol assumption for IL projection
_DEFAULT_BTC_VOL = 0.75


class ResearchModeAPI:
    """Plugs into Family Fund HTTP server.

    Provides /api/research/status data for RS-001 and RS-002 experimental
    strategies.  All output is advisory / research-only — never investable.
    """

    # ── RS-001 public constants ───────────────────────────────────────────────
    RS001_TARGET_APY: float = 18.2
    RS001_STRICT_FRACTION: float = 0.15  # stablecoin_t1 is the only CLEAN slot

    # ── RS-002 public constants ───────────────────────────────────────────────
    RS002_GROSS_APY: float = 29.24
    RS002_NET_APY_RANGE: List[float] = [12, 18]
    RS002_IL_RISK: str = "HIGH"

    def __init__(self, base_dir: str = ".") -> None:
        self._base_dir = Path(base_dir).resolve()
        self._data_dir = self._base_dir / "data"
        self._research_dir = self._data_dir / "research"

    # ── Public API ────────────────────────────────────────────────────────────

    def handle_research_status(self) -> dict:
        """Returns /api/research/status payload.

        Returns:
            dict with keys: rs001, rs002, gate
        """
        return {
            "rs001": self.rs001_projection(),
            "rs002": self.rs002_projection(),
            "gate":  self.gate_summary(),
        }

    def rs001_projection(self) -> dict:
        """RS-001 research mode data.

        Returns:
            dict with keys: name, target_apy, strict_eligible_fraction,
                            status, blended_apy_projection, disclaimer
        """
        blended = self._compute_rs001_blended_apy()
        return {
            "name":                    "Anti-Crisis Research",
            "target_apy":              self.RS001_TARGET_APY,
            "strict_eligible_fraction": self.RS001_STRICT_FRACTION,
            "status":                  "RESEARCH_ONLY",
            "blended_apy_projection":  blended,
            "disclaimer":              self.disclaimer("rs001"),
        }

    def rs002_projection(self) -> dict:
        """RS-002 research mode data with IL estimate.

        Returns:
            dict with keys: name, target_gross_apy, net_apy_range, il_risk,
                            status, il_estimate_pct, disclaimer
        """
        il_estimate_pct = self._compute_rs002_il_estimate_pct()
        return {
            "name":             "Cashflow Research",
            "target_gross_apy": self.RS002_GROSS_APY,
            "net_apy_range":    list(self.RS002_NET_APY_RANGE),
            "il_risk":          self.RS002_IL_RISK,
            "status":           "RESEARCH_ONLY",
            "il_estimate_pct":  il_estimate_pct,
            "disclaimer":       self.disclaimer("rs002"),
        }

    def gate_summary(self) -> dict:
        """Gate status summary for Family Fund UI.

        paper_ready is always False during the research phase — the Owner
        acceptance blocker is structural and cannot be removed automatically.

        Returns:
            dict with keys: paper_ready, blockers, estimated_paper_start
        """
        blockers = self._build_gate_blockers()
        return {
            "paper_ready":            False,
            "blockers":               blockers,
            "estimated_paper_start":  None,
        }

    def disclaimer(self, strategy_id: str) -> str:
        """Returns appropriate disclaimer text for a strategy.

        Never returns an empty string — a fallback is always provided.

        Args:
            strategy_id: e.g. "rs001", "rs002" (or any other id for fallback)

        Returns:
            Non-empty disclaimer string.
        """
        _DISCLAIMERS: dict = {
            "rs001": (
                "Not investable. No historical data for 85% of allocation. "
                "Research projection only — theoretical APY based on placeholder "
                "data sources. Past performance of research strategies is not "
                "indicative of future results."
            ),
            "rs002": (
                "IL risk not modeled historically. Research projection only. "
                "Impermanent Loss from concentrated liquidity positions can "
                "significantly reduce net returns. Not available for investment. "
                "No live track record exists for this strategy."
            ),
        }
        return _DISCLAIMERS.get(
            strategy_id,
            (
                f"RESEARCH_ONLY: Strategy '{strategy_id}' is experimental and "
                "not available for investment. No historical performance data. "
                "Research projection only."
            ),
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _compute_rs001_blended_apy(self) -> float:
        """Compute blended APY for RS-001.

        Tries to read a pre-computed breakdown from
        data/research/rs001_apy_breakdown.json; falls back to
        slot-weight × placeholder_apy computation.
        """
        breakdown_path = self._research_dir / "rs001_apy_breakdown.json"
        if breakdown_path.exists():
            try:
                with open(breakdown_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                val = data.get("blended_apy")
                if isinstance(val, (int, float)) and val > 0:
                    return float(val)
            except Exception:
                pass  # fallback to computation below

        # Deterministic fallback: weighted sum of placeholder APYs
        blended = sum(s["weight"] * s["placeholder_apy"] for s in _RS001_SLOTS)
        return round(blended, 4)

    def _compute_rs002_il_estimate_pct(self) -> float:
        """Estimate annualized IL drag (%) for RS-002's BTC/USD concentrated LP.

        Model (from conc_lp_il_model / rs002_live_apy_engine):
            vol_path_drag = btc_vol_annualized^2 * 0.5
            move_drag     = abs(btc_price_move_pct/100) * 0.5

        For the research projection we use zero move_drag (symmetric assumption)
        and the default BTC vol of 75% annualized.
        """
        btc_vol = _DEFAULT_BTC_VOL
        vol_path_drag_pct = (btc_vol ** 2) * 0.5 * 100.0  # convert to %
        # Weight by BTC LP slot (60% of portfolio)
        btc_lp_weight = 0.60
        weighted_drag = round(btc_lp_weight * vol_path_drag_pct, 2)
        return weighted_drag

    def _build_gate_blockers(self) -> List[str]:
        """Build list of gate blockers from system state files.

        The 'Owner acceptance not signed' blocker is always present —
        it is a structural requirement (ADR-002) that cannot be removed
        automatically.
        """
        blockers: List[str] = ["Owner acceptance not signed"]

        golive_path = self._data_dir / "golive_status.json"
        if golive_path.exists():
            try:
                with open(golive_path, "r", encoding="utf-8") as fh:
                    status = json.load(fh)
                raw = status.get("blockers", [])
                # Add up to 5 system blockers (avoid duplicates with owner blocker)
                for b in raw[:5]:
                    if b not in blockers:
                        blockers.append(b)
            except Exception:
                pass  # graceful fallback — owner blocker already in list

        return blockers

    # ── Atomic save helper (for future dashboard integration) ─────────────────

    def save_status(self, path: Optional[str] = None) -> None:
        """Atomically save research status to JSON file.

        Args:
            path: output path; defaults to data/research/research_mode_status.json
        """
        if path is None:
            out_path = self._research_dir / "research_mode_status.json"
        else:
            out_path = Path(path)

        out_path.parent.mkdir(parents=True, exist_ok=True)

        payload = self.handle_research_status()
        payload["_generated_at"] = datetime.now(tz=timezone.utc).isoformat()

        fd, tmp = tempfile.mkstemp(dir=out_path.parent, prefix=".rm_status_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, out_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
