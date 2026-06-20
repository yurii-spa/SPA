"""
MP-1073: ProtocolDeFiProtocolMaturityScoreAnalyzer
===================================================
Advisory-only analytics module.

Scores the institutional maturity of a DeFi protocol across three independent
dimensions, then computes a weighted composite:

  security_score      (0–100)  — audit depth, bug bounty, incident record, loss ratio
  adoption_score      (0–100)  — TVL magnitude, TVL retention, chain footprint, DAU
  development_score   (0–100)  — protocol age, commit velocity, DAO governance, mkt cap

  maturity_composite_score  (0–100)
      = 0.40 × security + 0.35 × adoption + 0.25 × development

  maturity_label  — EXPERIMENTAL / EARLY_STAGE / ESTABLISHED / MATURE / BATTLE_TESTED

Scoring philosophy
------------------
Each sub-score uses piecewise linear bands rather than continuous functions so
the model is interpretable and auditable by non-quants.  All sub-scores are
bounded to [0, 100] before aggregation.

Pure stdlib. Read-only / advisory. No external dependencies.
Ring-buffer log capped at 100 entries → data/protocol_maturity_score_log.json
Atomic writes: tmp + os.replace.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "protocol_maturity_score_log.json",
)
LOG_MAX_ENTRIES = 100

# Composite weights (must sum to 1.0)
_W_SECURITY    = 0.40
_W_ADOPTION    = 0.35
_W_DEVELOPMENT = 0.25

# Maturity-label thresholds (inclusive lower bound of each tier)
_THRESHOLD_EARLY_STAGE  = 20.0   # [20, 40)
_THRESHOLD_ESTABLISHED  = 40.0   # [40, 60)
_THRESHOLD_MATURE       = 60.0   # [60, 80)
_THRESHOLD_BATTLE_TESTED = 80.0  # [80, 100]

_VALID_LABELS = frozenset({
    "EXPERIMENTAL",
    "EARLY_STAGE",
    "ESTABLISHED",
    "MATURE",
    "BATTLE_TESTED",
})

REQUIRED_FIELDS = {
    "protocol_name",
    "launch_date_days_ago",
    "tvl_usd",
    "tvl_peak_usd",
    "audit_count",
    "bug_bounty_usd",
    "num_security_incidents",
    "total_loss_usd",
    "chain_count",
    "unique_users_30d",
    "github_commits_90d",
    "has_dao",
    "token_market_cap_usd",
}

# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_input(p: dict) -> None:
    """Validate a protocol dict; raises ValueError on any violation."""
    missing = REQUIRED_FIELDS - set(p.keys())
    if missing:
        raise ValueError(f"Missing required fields: {sorted(missing)}")

    if not isinstance(p["protocol_name"], str) or not p["protocol_name"].strip():
        raise ValueError("protocol_name must be a non-empty string")
    if not isinstance(p["launch_date_days_ago"], (int, float)) or p["launch_date_days_ago"] < 0:
        raise ValueError("launch_date_days_ago must be a non-negative number")
    if p["tvl_usd"] < 0:
        raise ValueError("tvl_usd must be >= 0")
    if p["tvl_peak_usd"] < 0:
        raise ValueError("tvl_peak_usd must be >= 0")
    if not isinstance(p["audit_count"], int) or isinstance(p["audit_count"], bool) or p["audit_count"] < 0:
        raise ValueError("audit_count must be a non-negative integer")
    if p["bug_bounty_usd"] < 0:
        raise ValueError("bug_bounty_usd must be >= 0")
    if not isinstance(p["num_security_incidents"], int) or isinstance(p["num_security_incidents"], bool) or p["num_security_incidents"] < 0:
        raise ValueError("num_security_incidents must be a non-negative integer")
    if p["total_loss_usd"] < 0:
        raise ValueError("total_loss_usd must be >= 0")
    if not isinstance(p["chain_count"], int) or isinstance(p["chain_count"], bool) or p["chain_count"] < 0:
        raise ValueError("chain_count must be a non-negative integer")
    if not isinstance(p["unique_users_30d"], int) or isinstance(p["unique_users_30d"], bool) or p["unique_users_30d"] < 0:
        raise ValueError("unique_users_30d must be a non-negative integer")
    if not isinstance(p["github_commits_90d"], int) or isinstance(p["github_commits_90d"], bool) or p["github_commits_90d"] < 0:
        raise ValueError("github_commits_90d must be a non-negative integer")
    if not isinstance(p["has_dao"], bool):
        raise ValueError("has_dao must be a boolean")
    if p["token_market_cap_usd"] < 0:
        raise ValueError("token_market_cap_usd must be >= 0")


# ---------------------------------------------------------------------------
# Sub-score components — all return float in [0, 100]
# ---------------------------------------------------------------------------

def _audit_sub(audit_count: int) -> float:
    """Security: audit depth. 0→0, 1→35, 2→60, 3→80, ≥4→100."""
    if audit_count == 0:    return 0.0
    if audit_count == 1:    return 35.0
    if audit_count == 2:    return 60.0
    if audit_count == 3:    return 80.0
    return 100.0


def _bug_bounty_sub(bug_bounty_usd: float) -> float:
    """Security: bug-bounty programme size. $0→0, <$10K→20, <$100K→50, <$1M→75, ≥$1M→100."""
    if bug_bounty_usd == 0:            return 0.0
    if bug_bounty_usd < 10_000:        return 20.0
    if bug_bounty_usd < 100_000:       return 50.0
    if bug_bounty_usd < 1_000_000:     return 75.0
    return 100.0


def _incident_sub(num_incidents: int) -> float:
    """Security: clean incident record. 0→100, 1→65, 2→35, ≥3→0."""
    if num_incidents == 0:  return 100.0
    if num_incidents == 1:  return 65.0
    if num_incidents == 2:  return 35.0
    return 0.0


def _loss_ratio_sub(total_loss_usd: float, tvl_usd: float) -> float:
    """Security: total-loss / TVL ratio. 0%→100, <1%→80, <5%→55, <20%→25, ≥20%→0."""
    denom = max(tvl_usd, 1.0)
    ratio_pct = (total_loss_usd / denom) * 100.0
    if ratio_pct == 0.0:    return 100.0
    if ratio_pct < 1.0:     return 80.0
    if ratio_pct < 5.0:     return 55.0
    if ratio_pct < 20.0:    return 25.0
    return 0.0


def _security_score(p: dict) -> float:
    """
    Weighted security score [0–100]:
      audit × 0.35 + bug_bounty × 0.20 + incident × 0.30 + loss_ratio × 0.15
    """
    s = (
        _audit_sub(p["audit_count"])                          * 0.35
        + _bug_bounty_sub(p["bug_bounty_usd"])                * 0.20
        + _incident_sub(p["num_security_incidents"])          * 0.30
        + _loss_ratio_sub(p["total_loss_usd"], p["tvl_usd"]) * 0.15
    )
    return round(max(0.0, min(100.0, s)), 4)


# ---------------------------------------------------------------------------

def _tvl_abs_sub(tvl_usd: float) -> float:
    """Adoption: TVL magnitude. <$1M→15, <$10M→40, <$100M→65, <$1B→85, ≥$1B→100."""
    if tvl_usd < 1_000_000:        return 15.0
    if tvl_usd < 10_000_000:       return 40.0
    if tvl_usd < 100_000_000:      return 65.0
    if tvl_usd < 1_000_000_000:    return 85.0
    return 100.0


def _tvl_retention_sub(tvl_usd: float, tvl_peak_usd: float) -> float:
    """Adoption: TVL retention vs peak. <30%→0, <50%→25, <70%→50, <90%→75, ≥90%→100."""
    if tvl_peak_usd <= 0:
        return 50.0  # no peak data — neutral
    ratio = tvl_usd / tvl_peak_usd
    if ratio < 0.30:    return 0.0
    if ratio < 0.50:    return 25.0
    if ratio < 0.70:    return 50.0
    if ratio < 0.90:    return 75.0
    return 100.0


def _chain_sub(chain_count: int) -> float:
    """Adoption: multi-chain footprint. 0–1→20, 2→50, 3–4→70, ≥5→100."""
    if chain_count <= 1:    return 20.0
    if chain_count == 2:    return 50.0
    if chain_count <= 4:    return 70.0
    return 100.0


def _users_sub(unique_users_30d: int) -> float:
    """Adoption: monthly unique users. <100→10, <1K→35, <10K→65, <100K→85, ≥100K→100."""
    if unique_users_30d < 100:        return 10.0
    if unique_users_30d < 1_000:      return 35.0
    if unique_users_30d < 10_000:     return 65.0
    if unique_users_30d < 100_000:    return 85.0
    return 100.0


def _adoption_score(p: dict) -> float:
    """
    Weighted adoption score [0–100]:
      tvl_abs × 0.35 + tvl_retention × 0.20 + chains × 0.20 + users × 0.25
    """
    s = (
        _tvl_abs_sub(p["tvl_usd"])                                    * 0.35
        + _tvl_retention_sub(p["tvl_usd"], p["tvl_peak_usd"])         * 0.20
        + _chain_sub(p["chain_count"])                                 * 0.20
        + _users_sub(p["unique_users_30d"])                            * 0.25
    )
    return round(max(0.0, min(100.0, s)), 4)


# ---------------------------------------------------------------------------

def _age_sub(launch_date_days_ago: float) -> float:
    """Development: protocol age. <90d→5, <180d→20, <365d→45, <730d→70, <1095d→85, ≥1095d→100."""
    d = launch_date_days_ago
    if d < 90:      return 5.0
    if d < 180:     return 20.0
    if d < 365:     return 45.0
    if d < 730:     return 70.0
    if d < 1095:    return 85.0
    return 100.0


def _commits_sub(github_commits_90d: int) -> float:
    """Development: recent GitHub activity. 0→0, <5→20, <20→45, <50→70, <100→85, ≥100→100."""
    c = github_commits_90d
    if c == 0:      return 0.0
    if c < 5:       return 20.0
    if c < 20:      return 45.0
    if c < 50:      return 70.0
    if c < 100:     return 85.0
    return 100.0


def _dao_sub(has_dao: bool) -> float:
    """Development: DAO governance in place. True→100, False→20."""
    return 100.0 if has_dao else 20.0


def _mcap_sub(token_market_cap_usd: float) -> float:
    """Development: token market cap. <$1M→15, <$10M→35, <$100M→60, <$1B→85, ≥$1B→100."""
    m = token_market_cap_usd
    if m < 1_000_000:       return 15.0
    if m < 10_000_000:      return 35.0
    if m < 100_000_000:     return 60.0
    if m < 1_000_000_000:   return 85.0
    return 100.0


def _development_score(p: dict) -> float:
    """
    Weighted development score [0–100]:
      age × 0.30 + commits × 0.30 + dao × 0.20 + market_cap × 0.20
    """
    s = (
        _age_sub(p["launch_date_days_ago"])       * 0.30
        + _commits_sub(p["github_commits_90d"])   * 0.30
        + _dao_sub(p["has_dao"])                  * 0.20
        + _mcap_sub(p["token_market_cap_usd"])    * 0.20
    )
    return round(max(0.0, min(100.0, s)), 4)


# ---------------------------------------------------------------------------
# Composite + label
# ---------------------------------------------------------------------------

def _composite_score(sec: float, adp: float, dev: float) -> float:
    """Weighted composite: 0.40 × security + 0.35 × adoption + 0.25 × development."""
    return round(max(0.0, min(100.0,
        _W_SECURITY * sec + _W_ADOPTION * adp + _W_DEVELOPMENT * dev
    )), 4)


def _maturity_label(composite: float) -> str:
    """Map composite score to a 5-tier maturity label."""
    if composite < _THRESHOLD_EARLY_STAGE:      return "EXPERIMENTAL"
    if composite < _THRESHOLD_ESTABLISHED:      return "EARLY_STAGE"
    if composite < _THRESHOLD_MATURE:           return "ESTABLISHED"
    if composite < _THRESHOLD_BATTLE_TESTED:    return "MATURE"
    return "BATTLE_TESTED"


# ---------------------------------------------------------------------------
# Full analysis helper
# ---------------------------------------------------------------------------

def _analyze_protocol(p: dict) -> dict:
    """Validate + compute all outputs for one protocol dict."""
    _validate_input(p)

    sec = _security_score(p)
    adp = _adoption_score(p)
    dev = _development_score(p)
    comp = _composite_score(sec, adp, dev)
    label = _maturity_label(comp)

    return {
        "protocol_name":           p["protocol_name"],
        "security_score":          sec,
        "adoption_score":          adp,
        "development_score":       dev,
        "maturity_composite_score": comp,
        "maturity_label":          label,
    }


# ---------------------------------------------------------------------------
# Main analyzer class
# ---------------------------------------------------------------------------

class ProtocolDeFiProtocolMaturityScoreAnalyzer:
    """
    Scores DeFi protocol maturity across security, adoption, and development.
    Advisory / read-only. No execution side-effects.
    """

    def analyze(self, protocol: dict, config: Optional[dict] = None) -> dict:
        """
        Analyze a single DeFi protocol.

        Parameters
        ----------
        protocol : dict
            Required keys — see module docstring / REQUIRED_FIELDS.

        Returns
        -------
        dict
            protocol_name, security_score, adoption_score, development_score,
            maturity_composite_score, maturity_label, analyzed_at
        """
        if config is None:
            config = {}
        result = _analyze_protocol(protocol)
        result["analyzed_at"] = _iso_now()
        _append_log(result)
        return result

    def analyze_batch(self, protocols: list, config: Optional[dict] = None) -> dict:
        """
        Analyze a list of protocols and return per-protocol results + aggregates.

        Returns
        -------
        dict
            protocols, count, avg_composite_score, top_protocol, bottom_protocol,
            battle_tested_count, experimental_count, analyzed_at
        """
        if config is None:
            config = {}
        if not isinstance(protocols, list) or len(protocols) == 0:
            raise ValueError("protocols must be a non-empty list")

        ts = _iso_now()
        results = [_analyze_protocol(p) for p in protocols]
        for r in results:
            r["analyzed_at"] = ts

        avg_comp = round(
            sum(r["maturity_composite_score"] for r in results) / len(results), 4
        )
        sorted_results = sorted(results, key=lambda r: r["maturity_composite_score"])
        top    = sorted_results[-1]["protocol_name"]
        bottom = sorted_results[0]["protocol_name"]

        output = {
            "protocols":              results,
            "count":                  len(results),
            "avg_composite_score":    avg_comp,
            "top_protocol":           top,
            "bottom_protocol":        bottom,
            "battle_tested_count":    sum(1 for r in results if r["maturity_label"] == "BATTLE_TESTED"),
            "experimental_count":     sum(1 for r in results if r["maturity_label"] == "EXPERIMENTAL"),
            "analyzed_at":            ts,
        }
        _append_log({"batch": True, "count": len(results), "analyzed_at": ts})
        return output


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _iso_now() -> str:
    t = time.gmtime()
    return (
        f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T"
        f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}Z"
    )


def _atomic_write(path: str, data: object) -> None:
    """JSON-dump *data* to *path* via sibling tmp file → os.replace."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    dir_ = os.path.dirname(path)
    atomic_save(data, str(path))
def _init_log(path: str) -> list:
    """Load existing ring-buffer from *path* or return an empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _append_log(result: dict, log_path: str = LOG_PATH) -> None:
    """Append a snapshot of *result* to the ring-buffer log (≤ LOG_MAX_ENTRIES)."""
    entries = _init_log(log_path)
    ts = result.get("analyzed_at") or _iso_now()
    snapshot = {
        "ts":                       ts,
        "protocol_name":            result.get("protocol_name"),
        "security_score":           result.get("security_score"),
        "adoption_score":           result.get("adoption_score"),
        "development_score":        result.get("development_score"),
        "maturity_composite_score": result.get("maturity_composite_score"),
        "maturity_label":           result.get("maturity_label"),
    }
    entries.append(snapshot)
    if len(entries) > LOG_MAX_ENTRIES:
        entries = entries[-LOG_MAX_ENTRIES:]
    try:
        _atomic_write(log_path, entries)
    except OSError:
        pass  # advisory — never crash on log failure


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------

def analyze(protocol: dict, config: Optional[dict] = None) -> dict:
    """Module-level shorthand → ProtocolDeFiProtocolMaturityScoreAnalyzer().analyze()."""
    return ProtocolDeFiProtocolMaturityScoreAnalyzer().analyze(protocol, config)
