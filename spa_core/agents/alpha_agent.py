"""Alpha Agent — еженедельный скан кандидатов на whitelist (MP-304).

ИСТОЧНИКИ (все fail-safe, пустой список если файл не найден):
  data/candidate_registry.json — кандидаты от discovery (adapter_sdk/discovery.py)
  data/adapter_orchestrator_status.json — текущие активные протоколы (для сравнения)
  data/analytics_summary.json — текущая аналитика портфеля

СКОРИНГ КАНДИДАТОВ (детерминированный, без LLM):
AlphaScore = dataclass(protocol_id, name, score, rationale, risk_flags, suggested_tier)

score = взвешенная сумма (0-100):
  tvl_score: TVL >$100M → 30, >$50M → 20, >$10M → 10, else 0
  apy_score: 5-10% → 20, 3-5% → 10, >10% → 5 (sanity cap), else 0
  exit_score: instant (0h) → 20, <24h → 15, <168h → 5, else 0
  tier_bonus: T2 → 15, T3 → 10 (diversity)
  diversification_bonus: если протокол не пересекается с уже активными → 15

risk_flags:
  "credit_risk" если "credit" в имени протокола
  "peg_risk" если "peg" в имени протокола или символе
  "low_liquidity" если TVL < $10M
  "high_exit_latency" если exit > 72h

Топ-5 кандидатов по score → data/alpha_candidates.json (атомарно).

LLM-enhanced rationale (опционально):
generate_rationale_with_llm(candidate: dict, llm_fn=None) -> str
  При llm_fn=None → детерминированный шаблон:
  "Protocol {name} scored {score}/100. TVL: ${tvl}M. APY: {apy}%. Risks: {flags}."

Stdlib only. Atomic writes (tmp + os.replace). No imports from execution/risk agents.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger("spa.agents.alpha_agent")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Output file
ALPHA_CANDIDATES_FILENAME = "alpha_candidates.json"
TOP_N_DEFAULT = 5

# Score component weights / thresholds
_TVL_TIER1 = 100_000_000.0   # $100M → 30
_TVL_TIER2 = 50_000_000.0    # $50M  → 20
_TVL_TIER3 = 10_000_000.0    # $10M  → 10

_APY_HIGH_LOW = 5.0           # 5% lower bound of "good APY" band
_APY_HIGH_HIGH = 10.0         # 10% upper bound of "good APY" band
_APY_MEDIUM_LOW = 3.0         # 3% lower bound of "medium APY" band
_APY_SANITY_CAP = 30.0        # >30% is suspicious (already filtered by discovery)

_EXIT_INSTANT = 0.0           # 0h  → instant → 20
_EXIT_DAY = 24.0              # <24h → 15
_EXIT_WEEK = 168.0            # <168h (7 days) → 5
_EXIT_HIGH_RISK = 72.0        # >72h → high_exit_latency flag


# ─── AlphaScore dataclass ─────────────────────────────────────────────────────


@dataclass
class AlphaScore:
    """Scoring result for a single candidate protocol."""

    protocol_id: str
    name: str
    score: int                              # 0–100 total
    tvl_score: int = 0
    apy_score: int = 0
    exit_score: int = 0
    tier_bonus: int = 0
    diversification_bonus: int = 0
    rationale: str = ""
    risk_flags: list[str] = field(default_factory=list)
    suggested_tier: str = "candidate"       # always "candidate" — never T1/T2/T3

    # Raw data (for rationale generation)
    tvl_usd: float = 0.0
    apy_pct: float = 0.0
    exit_latency_hours: Optional[float] = None
    chain: str = ""
    symbol: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ─── IO helpers ───────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any) -> Any:
    """Read JSON defensively. Missing/corrupt file → default (never raises)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("_read_json %s unreadable (%s) — using default", path.name, exc)
        return default


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic write: tmpfile in same dir + os.replace. Never leaves .tmp on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, str(path))
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


# ─── Score component functions (deterministic, LLM-forbidden) ─────────────────


def _score_tvl(tvl_usd: float) -> int:
    """TVL score component (0–30)."""
    if tvl_usd > _TVL_TIER1:
        return 30
    if tvl_usd > _TVL_TIER2:
        return 20
    if tvl_usd > _TVL_TIER3:
        return 10
    return 0


def _score_apy(apy_pct: float) -> int:
    """APY score component (0–20). Sanity cap at >10% returns only 5."""
    if _APY_HIGH_LOW <= apy_pct <= _APY_HIGH_HIGH:
        return 20
    if _APY_MEDIUM_LOW <= apy_pct < _APY_HIGH_LOW:
        return 10
    if apy_pct > _APY_HIGH_HIGH:
        return 5  # sanity cap — suspiciously high
    return 0


def _score_exit(exit_latency_hours: Optional[float]) -> int:
    """Exit latency score component (0–20)."""
    if exit_latency_hours is None:
        return 0  # unknown → 0 (conservative)
    if exit_latency_hours <= _EXIT_INSTANT:
        return 20   # instant
    if exit_latency_hours < _EXIT_DAY:
        return 15   # <24h
    if exit_latency_hours < _EXIT_WEEK:
        return 5    # <168h (7 days)
    return 0


def _score_tier_bonus(suggested_tier: str) -> int:
    """Tier diversity bonus (0–15)."""
    t = str(suggested_tier).strip().upper()
    if t == "T2":
        return 15
    if t == "T3":
        return 10
    # "candidate" means unknown tier → small bonus for diversity potential
    return 10


def _score_diversification(protocol: str, active_protocols: list[str]) -> int:
    """Diversification bonus if protocol not in active protocols (0–15).

    Normalises dashes/underscores so "morpho-blue" == "morpho_blue",
    then uses substring match to handle prefix slugs ("spark" ⊆ "sparklend").
    """
    def _norm(s: str) -> str:
        return str(s).strip().lower().replace("-", "_")

    prot_n = _norm(protocol)
    for active in active_protocols:
        active_n = _norm(active)
        if prot_n in active_n or active_n in prot_n:
            return 0
    return 15


def _compute_risk_flags(
    protocol: str,
    symbol: str,
    tvl_usd: float,
    exit_latency_hours: Optional[float],
) -> list[str]:
    """Determine risk flags from candidate properties."""
    flags: list[str] = []
    protocol_lower = str(protocol).strip().lower()
    symbol_lower = str(symbol).strip().lower()

    if "credit" in protocol_lower:
        flags.append("credit_risk")
    if "peg" in protocol_lower or "peg" in symbol_lower:
        flags.append("peg_risk")
    if tvl_usd < _TVL_TIER3:
        flags.append("low_liquidity")
    if exit_latency_hours is not None and exit_latency_hours > _EXIT_HIGH_RISK:
        flags.append("high_exit_latency")

    return flags


# ─── LLM-enhanced rationale (optional; deterministic fallback) ────────────────


def generate_rationale_with_llm(
    candidate: dict,
    llm_fn: Optional[Callable[[dict], str]] = None,
) -> str:
    """Generate a rationale string for a candidate.

    Parameters
    ----------
    candidate : dict — candidate dict (from AlphaScore.to_dict() or raw).
    llm_fn    : optional callable(candidate_dict) → str. When None (default),
                falls back to a deterministic template. LLM_FORBIDDEN in risk/
                execution/monitoring components — this function must NOT be called
                from those domains.

    Returns
    -------
    str — human-readable rationale.
    """
    if llm_fn is not None:
        try:
            return str(llm_fn(candidate))
        except Exception as exc:
            log.warning("llm_fn failed (%s) — falling back to deterministic template", exc)

    # Deterministic template (fallback / default)
    name = candidate.get("name") or candidate.get("protocol_id") or "?"
    score = candidate.get("score", 0)
    tvl_usd = float(candidate.get("tvl_usd") or 0.0)
    apy_pct = float(candidate.get("apy_pct") or 0.0)
    flags = candidate.get("risk_flags") or []
    flags_str = ", ".join(flags) if flags else "none"
    tvl_m = tvl_usd / 1_000_000.0
    return (
        f"Protocol {name} scored {score}/100. "
        f"TVL: ${tvl_m:.1f}M. APY: {apy_pct:.2f}%. "
        f"Risks: {flags_str}."
    )


# ─── Core scoring function ─────────────────────────────────────────────────────


def score_candidate(candidate: dict, active_protocols: list[str]) -> AlphaScore:
    """Score a single candidate dict → AlphaScore.

    Parameters
    ----------
    candidate        : dict from candidate_registry.json (discovery output).
    active_protocols : list of protocol keys currently active (from orchestrator).

    Returns
    -------
    AlphaScore — fully computed score with components and risk flags.
    """
    protocol = str(candidate.get("protocol") or candidate.get("protocol_id") or "")
    name = protocol  # display name; use protocol slug
    symbol = str(candidate.get("symbol") or "")
    chain = str(candidate.get("chain") or "")
    tvl_usd = float(candidate.get("tvl_usd") or 0.0)
    apy_pct = float(candidate.get("apy_pct") or 0.0)
    exit_latency_hours: Optional[float] = None
    if candidate.get("exit_latency_hours") is not None:
        try:
            exit_latency_hours = float(candidate["exit_latency_hours"])
        except (TypeError, ValueError):
            pass

    # Use discovery's suggested_tier if provided
    raw_tier = str(candidate.get("suggested_tier") or "candidate").strip()

    # Score components
    tvl_score = _score_tvl(tvl_usd)
    apy_score = _score_apy(apy_pct)
    exit_score = _score_exit(exit_latency_hours)
    tier_bonus = _score_tier_bonus(raw_tier)
    div_bonus = _score_diversification(protocol, active_protocols)

    total = tvl_score + apy_score + exit_score + tier_bonus + div_bonus
    # Clamp to 0–100
    total = max(0, min(100, total))

    risk_flags = _compute_risk_flags(protocol, symbol, tvl_usd, exit_latency_hours)

    alpha = AlphaScore(
        protocol_id=protocol,
        name=name,
        score=total,
        tvl_score=tvl_score,
        apy_score=apy_score,
        exit_score=exit_score,
        tier_bonus=tier_bonus,
        diversification_bonus=div_bonus,
        risk_flags=risk_flags,
        suggested_tier="candidate",  # always candidate — never promote directly
        tvl_usd=tvl_usd,
        apy_pct=apy_pct,
        exit_latency_hours=exit_latency_hours,
        chain=chain,
        symbol=symbol,
    )
    alpha.rationale = generate_rationale_with_llm(alpha.to_dict())
    return alpha


# ─── Data loading helpers ──────────────────────────────────────────────────────


def _load_candidates(data_dir: Path) -> list[dict]:
    """Load candidate_registry.json → list of candidate dicts. Fail-safe."""
    doc = _read_json(data_dir / "candidate_registry.json", {})
    if isinstance(doc, dict):
        candidates = doc.get("candidates") or []
        return [c for c in candidates if isinstance(c, dict)]
    if isinstance(doc, list):
        return [c for c in doc if isinstance(c, dict)]
    return []


def _load_active_protocols(data_dir: Path) -> list[str]:
    """Load adapter_orchestrator_status.json → list of active protocol keys."""
    doc = _read_json(data_dir / "adapter_orchestrator_status.json", {})
    if not isinstance(doc, dict):
        return []
    adapters = doc.get("adapters") or []
    protocols = []
    for a in adapters:
        if isinstance(a, dict):
            p = a.get("protocol")
            if p:
                protocols.append(str(p))
    return protocols


def _load_analytics(data_dir: Path) -> dict:
    """Load analytics_summary.json. Fail-safe."""
    doc = _read_json(data_dir / "analytics_summary.json", {})
    return doc if isinstance(doc, dict) else {}


# ─── Public API ───────────────────────────────────────────────────────────────


def run_alpha_scan(
    data_dir: str | os.PathLike | None = None,
    top_n: int = TOP_N_DEFAULT,
) -> dict:
    """Full alpha scan: load sources → score candidates → write alpha_candidates.json.

    Fail-safe: any individual source failure returns empty data, never crashes.
    The output file is written atomically (tmp + os.replace).

    Returns
    -------
    dict — the alpha_candidates.json document.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    candidates_raw = _load_candidates(ddir)
    active_protocols = _load_active_protocols(ddir)

    scored: list[AlphaScore] = []
    for raw in candidates_raw:
        try:
            s = score_candidate(raw, active_protocols)
            scored.append(s)
        except Exception as exc:
            log.warning("score_candidate failed for %s (%s) — skipped", raw, exc)

    # Sort by score desc, then protocol_id for deterministic tie-breaking
    scored.sort(key=lambda s: (-s.score, s.protocol_id))
    top = scored[:top_n]

    now_ts = datetime.now(timezone.utc).isoformat()
    doc: dict = {
        "generated_at": now_ts,
        "scan_basis": "candidate_registry + active_adapters",
        "candidates": [s.to_dict() for s in top],
        "already_active": active_protocols,
        "note": (
            "candidates require ADR/human review before whitelisting — "
            "do not auto-promote"
        ),
        "total_candidates_scanned": len(candidates_raw),
        "total_scored": len(scored),
    }

    try:
        _atomic_write_json(ddir / ALPHA_CANDIDATES_FILENAME, doc)
        log.info(
            "Alpha scan complete: %d candidates scored, top %d written to %s",
            len(scored),
            len(top),
            ALPHA_CANDIDATES_FILENAME,
        )
    except Exception as exc:
        log.warning("alpha_candidates.json write failed (%s) — scan result in memory only", exc)

    return doc


def get_top_candidates(
    n: int = TOP_N_DEFAULT,
    data_dir: str | os.PathLike | None = None,
) -> list[AlphaScore]:
    """Run a scan and return the top-N AlphaScore objects.

    Parameters
    ----------
    n         : number of top candidates to return (default: 5).
    data_dir  : data directory (default: <repo>/data).

    Returns
    -------
    list[AlphaScore] — sorted by score descending.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    candidates_raw = _load_candidates(ddir)
    active_protocols = _load_active_protocols(ddir)

    scored: list[AlphaScore] = []
    for raw in candidates_raw:
        try:
            s = score_candidate(raw, active_protocols)
            scored.append(s)
        except Exception as exc:
            log.warning("score_candidate failed for %s (%s) — skipped", raw, exc)

    scored.sort(key=lambda s: (-s.score, s.protocol_id))
    return scored[:n]
