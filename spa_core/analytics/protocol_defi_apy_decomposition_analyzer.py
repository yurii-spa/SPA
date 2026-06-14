"""
MP-1103: ProtocolDeFiAPYDecompositionAnalyzer
Decomposes a protocol's advertised APY into its constituent components:
base interest, token incentives, liquidity mining, boost, and compounding.
Helps identify which APY components are sustainable vs temporary.

Read-only/advisory — never modifies allocator/risk/execution.
Atomic writes to data/apy_decomposition_log.json (ring-buffer 100).
Pure stdlib only. No external dependencies.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "apy_decomposition_log.json"
)
LOG_CAP = 100

# Sustainability label thresholds (sustainability_ratio)
_SR_SUSTAINABLE: float = 0.8
_SR_MOSTLY_SUSTAINABLE: float = 0.6
_SR_MIXED: float = 0.4
_SR_INCENTIVE_DEPENDENT: float = 0.2
# Below 0.2 → PURE_INCENTIVE_FARM


# ── private helpers ───────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _apy_label(sustainability_ratio: float) -> str:
    """
    Classify the APY by its sustainability_ratio.

    > 0.8  → SUSTAINABLE_YIELD
    0.6–0.8 → MOSTLY_SUSTAINABLE
    0.4–0.6 → MIXED_YIELD
    0.2–0.4 → INCENTIVE_DEPENDENT
    < 0.2  → PURE_INCENTIVE_FARM
    """
    if sustainability_ratio > _SR_SUSTAINABLE:
        return "SUSTAINABLE_YIELD"
    if sustainability_ratio > _SR_MOSTLY_SUSTAINABLE:
        return "MOSTLY_SUSTAINABLE"
    if sustainability_ratio > _SR_MIXED:
        return "MIXED_YIELD"
    if sustainability_ratio > _SR_INCENTIVE_DEPENDENT:
        return "INCENTIVE_DEPENDENT"
    return "PURE_INCENTIVE_FARM"


def _apy_quality_score(
    sustainability_ratio: float,
    incentive_decay_risk_pct: float,
    total_apy: float,
) -> int:
    """
    0–100, where 100 = fully sustainable and zero decay risk.

    Formula:
      base        = sustainability_ratio × 100
      decay_pen   = min(20, incentive_decay_risk_pct / max(1, total_apy) × 20)
      score       = clamp(int(base - decay_pen), 0, 100)
    """
    base = sustainability_ratio * 100.0
    if total_apy > 0:
        decay_pen = min(20.0, incentive_decay_risk_pct / total_apy * 20.0)
    else:
        decay_pen = 0.0
    raw = base - decay_pen
    return max(0, min(100, int(raw)))


def _incentive_decay_risk_pct(
    incentive_apy_pct: float,
    token_incentive_30d_change_pct: float,
) -> float:
    """
    Expected decay in APY if token price continues at 30-day trend.

    formula: incentive_apy × |30d_change| / 100
    """
    return round(incentive_apy_pct * abs(token_incentive_30d_change_pct) / 100.0, 6)


# ── I/O helpers ───────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_path or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_log(result: dict, log_path: str) -> None:
    """Append a summary entry; enforce ring-buffer cap."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": result.get("ts", datetime.now(timezone.utc).isoformat()),
        "protocol_name": result.get("protocol_name", ""),
        "total_advertised_apy_pct": result.get("total_advertised_apy_pct", 0.0),
        "sustainable_apy_pct": result.get("sustainable_apy_pct", 0.0),
        "sustainability_ratio": result.get("sustainability_ratio", 0.0),
        "apy_label": result.get("apy_label", ""),
        "apy_quality_score": result.get("apy_quality_score", 0),
        "incentive_decay_risk_pct": result.get("incentive_decay_risk_pct", 0.0),
    }
    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── public class ──────────────────────────────────────────────────────────────

class ProtocolDeFiAPYDecompositionAnalyzer:
    """
    Decomposes a protocol's advertised APY into sustainable vs incentive components.

    Input dict keys
    ---------------
    base_interest_apy_pct : float
        Organic lending/swap-fee yield (sustainable).
    token_incentive_apy_pct : float
        Native token reward APY (incentive).
    liquidity_mining_apy_pct : float
        Third-party liquidity-mining rewards APY (incentive).
    boost_apy_pct : float
        veToken or NFT boost APY (incentive).
    compounding_apy_pct : float
        Extra APY from auto-compounding (sustainable).
    token_incentive_price_usd : float
        Current incentive token price in USD.
    token_incentive_30d_change_pct : float
        Incentive token price change over last 30 days (e.g. -20 for -20%).
    protocol_name : str
        Protocol identifier for logging.

    Returns
    -------
    dict with keys:
        ts, protocol_name,
        total_advertised_apy_pct, sustainable_apy_pct, incentive_apy_pct,
        sustainability_ratio, incentive_decay_risk_pct,
        apy_quality_score, apy_label,
        components  (sub-dict with all 5 input APY components)
    """

    def analyze(self, data: dict, config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(data, dict):
            raise TypeError(f"data must be a dict, got {type(data).__name__}")

        # ── parse inputs ──────────────────────────────────────────────────────
        base_interest_apy_pct = float(data.get("base_interest_apy_pct", 0.0))
        token_incentive_apy_pct = float(data.get("token_incentive_apy_pct", 0.0))
        liquidity_mining_apy_pct = float(data.get("liquidity_mining_apy_pct", 0.0))
        boost_apy_pct = float(data.get("boost_apy_pct", 0.0))
        compounding_apy_pct = float(data.get("compounding_apy_pct", 0.0))
        token_incentive_price_usd = float(data.get("token_incentive_price_usd", 0.0))
        token_incentive_30d_change_pct = float(
            data.get("token_incentive_30d_change_pct", 0.0)
        )
        protocol_name = str(data.get("protocol_name", "unknown"))

        # ── compute outputs ───────────────────────────────────────────────────
        total_advertised_apy_pct = round(
            base_interest_apy_pct
            + token_incentive_apy_pct
            + liquidity_mining_apy_pct
            + boost_apy_pct
            + compounding_apy_pct,
            6,
        )
        sustainable_apy_pct = round(
            base_interest_apy_pct + compounding_apy_pct, 6
        )
        incentive_apy_pct = round(
            token_incentive_apy_pct + liquidity_mining_apy_pct + boost_apy_pct, 6
        )

        # Sustainability ratio: sustainable / total (avoid div-by-zero)
        if total_advertised_apy_pct > 0:
            sustainability_ratio = round(
                _clamp(sustainable_apy_pct / total_advertised_apy_pct), 6
            )
        else:
            # All components zero → treat as fully sustainable (no yield at all)
            sustainability_ratio = 1.0

        decay_risk = _incentive_decay_risk_pct(
            incentive_apy_pct, token_incentive_30d_change_pct
        )
        quality_score = _apy_quality_score(
            sustainability_ratio, decay_risk, total_advertised_apy_pct
        )
        label = _apy_label(sustainability_ratio)

        result = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "protocol_name": protocol_name,
            "total_advertised_apy_pct": total_advertised_apy_pct,
            "sustainable_apy_pct": sustainable_apy_pct,
            "incentive_apy_pct": incentive_apy_pct,
            "sustainability_ratio": sustainability_ratio,
            "incentive_decay_risk_pct": decay_risk,
            "apy_quality_score": quality_score,
            "apy_label": label,
            "components": {
                "base_interest_apy_pct": base_interest_apy_pct,
                "token_incentive_apy_pct": token_incentive_apy_pct,
                "liquidity_mining_apy_pct": liquidity_mining_apy_pct,
                "boost_apy_pct": boost_apy_pct,
                "compounding_apy_pct": compounding_apy_pct,
                "token_incentive_price_usd": token_incentive_price_usd,
                "token_incentive_30d_change_pct": token_incentive_30d_change_pct,
            },
        }

        if write_log:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
