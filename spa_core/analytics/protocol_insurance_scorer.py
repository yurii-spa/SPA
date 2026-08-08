"""
MP-787 ProtocolInsuranceScorer
Scores how well-protected a DeFi protocol is against losses by evaluating
insurance coverage, treasury reserves, bug bounty programmes, and timelocks.

Protection tiers: FORTRESS (>=80), PROTECTED (>=60), PARTIAL (>=40), EXPOSED (<40)
Ring-buffer log (cap 100), atomic writes, stdlib only.
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_CAP = 100

_TIERS = [
    (80, "FORTRESS"),
    (60, "PROTECTED"),
    (40, "PARTIAL"),
    (0,  "EXPOSED"),
]

_DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)

_LOG_FILE = "protocol_insurance_log.json"

# Доменные ключи легаси-входа score() — ими protocol-контекст агрегатора
# ({"cycle_ts", "protocol"}) отличается от доменного payload'а. Держать в
# синхроне с ``_validate.required`` (гард — test_context_routing_is_sound).
_DOMAIN_KEYS = frozenset({
    "has_insurance",
    "insurance_coverage_pct",
    "insurance_provider",
    "treasury_usd",
    "tvl_usd",
    "bug_bounty_usd",
    "has_timelock",
    "timelock_days",
})

# Score component caps
_COVERAGE_MAX    = 40.0
_TREASURY_MAX    = 30.0
_BUG_BOUNTY_MAX  = 20.0
_TIMELOCK_MAX    = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_ = os.path.dirname(path) or "."
    atomic_save(data, str(path))
def _load_log(path: str) -> List[Dict]:
    try:
        with open(path) as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _append_log(path: str, entry: Dict, cap: int = _LOG_CAP) -> None:
    log = _load_log(path)
    log.append(entry)
    if len(log) > cap:
        log = log[-cap:]
    _atomic_write(path, log)


# ---------------------------------------------------------------------------
# Score sub-components
# ---------------------------------------------------------------------------

def _coverage_score(has_insurance: bool, insurance_coverage_pct: float) -> float:
    """
    0-40 pts.  insurance_coverage_pct * 0.4, capped at 40.
    Zero if no insurance.
    """
    if not has_insurance:
        return 0.0
    raw = insurance_coverage_pct * 0.4
    return round(min(max(raw, 0.0), _COVERAGE_MAX), 4)


def _treasury_score(treasury_usd: Optional[float], tvl_usd: float) -> Optional[float]:
    """
    0-30 pts on a log scale.
    At treasury/tvl >= 0.20 (20%) → 30 pts.
    Uses log10 scaling: score = log10(1 + ratio/0.20) / log10(2) * 30
    clamped to [0, 30].

    ``treasury_usd is None`` — казна НЕ ИЗМЕРЕНА (решение владельца 2026-08-07,
    ADR-070 п.15). Возвращается ``None``, а НЕ 0.0: ноль означал бы «казны нет»,
    то есть такое же утверждение о протоколе, как выдуманные 2% TVL, только с
    другим знаком. Ноль остаётся честным ответом на измеренную пустую казну.
    """
    if treasury_usd is None:
        return None
    if tvl_usd <= 0 or treasury_usd < 0:
        return 0.0
    ratio = treasury_usd / tvl_usd
    # log10(1 + ratio/0.20) / log10(2) → 1.0 when ratio=0.20
    raw = math.log10(1.0 + ratio / 0.20) / math.log10(2.0) * _TREASURY_MAX
    return round(min(max(raw, 0.0), _TREASURY_MAX), 4)


def _bug_bounty_score(bug_bounty_usd: float) -> float:
    """
    0-20 pts on log scale.
    At bug_bounty_usd >= $1,000,000 → 20 pts.
    score = log10(1 + bounty/1_000_000) / log10(2) * 20
    """
    if bug_bounty_usd <= 0:
        return 0.0
    raw = math.log10(1.0 + bug_bounty_usd / 1_000_000.0) / math.log10(2.0) * _BUG_BOUNTY_MAX
    return round(min(max(raw, 0.0), _BUG_BOUNTY_MAX), 4)


def _timelock_score(has_timelock: bool, timelock_days: int) -> float:
    """
    0-10 pts.  has_timelock * min(timelock_days, 10) pts.
    """
    if not has_timelock:
        return 0.0
    pts = float(min(int(timelock_days), 10))
    return round(pts, 4)


def _protection_tier(total_score: float) -> str:
    for threshold, label in _TIERS:
        if total_score >= threshold:
            return label
    return "EXPOSED"


# ---------------------------------------------------------------------------
# ProtocolInsuranceScorer
# ---------------------------------------------------------------------------

class ProtocolInsuranceScorer:
    """
    Scores a DeFi protocol's insurance and safety posture.

    Usage
    -----
    scorer = ProtocolInsuranceScorer()
    result = scorer.score(protocol_data)
    print(scorer.get_protection_tier())
    print(scorer.get_score_breakdown())
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        self._log_path = os.path.join(self._data_dir, _LOG_FILE)
        self._last_result: Optional[Dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, protocol_data: Dict, write_log: bool = True) -> Dict:
        """
        Compute the full insurance score for a protocol.

        Required keys
        -------------
        protocol               : str
        has_insurance          : bool
        insurance_coverage_pct : float   (0–100)
        insurance_provider     : str     (empty string OK)
        treasury_usd           : float | None  (None = НЕ ИЗМЕРЕНО, компонента
                                 исключается из итога и из его базы — ADR-070 п.15;
                                 отсутствие ключа по-прежнему ValueError)
        tvl_usd                : float
        bug_bounty_usd         : float
        has_timelock           : bool
        timelock_days          : int

        Returns result dict and appends to ring-buffer log.
        """
        # ── Protocol-context (ADR-031 Tier-B mass wiring, audit 2026-08-04 step-2) ──
        # Контекст агрегатора → структурный профиль из _protocol_facts → СОБСТВЕННЫЙ
        # движок модуля; лог отключён на context-пути; неизвестный протокол → None
        # (громкий dormant, не фабрикация).
        from spa_core.analytics import _protocol_facts as _pf
        # легаси-вход этого модуля тоже несёт строковый "protocol" — различаем
        # по отсутствию ВСЕХ доменных ключей сразу. Признак «нет tvl_usd»
        # (как было до 04.08) неустойчив: tvl_usd ОБЯЗАТЕЛЕН, поэтому
        # легаси-payload с дыркой в нём переставал доходить до _validate и
        # получал подставную казну TVL × 0.02 вместо отказа — fail-OPEN.
        if _pf.is_context_only(protocol_data, _DOMAIN_KEYS):
            _p = _pf.generic_profile_for(protocol_data["protocol"])
            if _p is None:
                return None
            _legacy = {
                "protocol": _p["name"],
                "has_insurance": False,
                "insurance_coverage_pct": 0.0,
                "insurance_provider": "none",
                # Казна протокола в структурной базе _protocol_facts ОТСУТСТВУЕТ.
                # До 08.08 здесь стояло ``_p["tvl_usd"] * 0.02`` — выдуманное
                # число, одинаковое (ratio 0.02) для КАЖДОГО протокола: оно
                # давало 4.13 «заработанных» балла из 30 на пустом месте и было
                # одной из причин, по которым модуль размечен ``blind_equal``.
                # Решение владельца 2026-08-07 (ADR-070 п.15): не измерено —
                # значит отказ, а не подстановка.
                "treasury_usd": None,
                "tvl_usd": _p["tvl_usd"],
                "bug_bounty_usd": _p["bug_bounty_usd"],
                "has_timelock": bool(_p["has_timelock"]),
                "timelock_days": _p["timelock_hours"] / 24.0,
            }
            return _pf.extract_protocol_score(self.score(_legacy, write_log=False),
                                              _p)
        self._validate(protocol_data)

        protocol           = protocol_data["protocol"]
        has_insurance      = bool(protocol_data["has_insurance"])
        coverage_pct       = float(protocol_data.get("insurance_coverage_pct", 0.0))
        insurance_provider = str(protocol_data.get("insurance_provider", ""))
        _treasury_raw      = protocol_data["treasury_usd"]
        treasury_usd       = (None if _treasury_raw is None
                              else float(_treasury_raw))
        tvl_usd            = float(protocol_data["tvl_usd"])
        bug_bounty_usd     = float(protocol_data.get("bug_bounty_usd", 0.0))
        has_timelock       = bool(protocol_data["has_timelock"])
        timelock_days      = int(protocol_data.get("timelock_days", 0))

        cov_score  = _coverage_score(has_insurance, coverage_pct)
        tres_score = _treasury_score(treasury_usd, tvl_usd)
        bug_score  = _bug_bounty_score(bug_bounty_usd)
        tl_score   = _timelock_score(has_timelock, timelock_days)

        # ── Неизмеренная компонента: вон из ЧИСЛИТЕЛЯ и из ЗНАМЕНАТЕЛЯ ──────
        # Иначе «не измерено» превращается в «нуль баллов», то есть в обвинение
        # протокола, ничем не подкреплённое. Итог по-прежнему в шкале 0-100
        # (доля заработанного от ИЗМЕРИМОГО максимума) — пороги тиров
        # калиброваны на ней, поэтому отказ не двигает тир на пустом месте
        # (ADR-070 п.15: «UNCHECKED не блокирует протоколы»). База отказа
        # называется вслух: unmeasured_components / score_basis_max.
        unmeasured: List[str] = []
        earned = 0.0
        basis_max = 0.0
        for name, part, part_max in (
            ("coverage",   cov_score,  _COVERAGE_MAX),
            ("treasury",   tres_score, _TREASURY_MAX),
            ("bug_bounty", bug_score,  _BUG_BOUNTY_MAX),
            ("timelock",   tl_score,   _TIMELOCK_MAX),
        ):
            if part is None:
                unmeasured.append(name)
                continue
            earned += part
            basis_max += part_max

        if basis_max <= 0:
            # Не измерено НИЧЕГО — score'а не существует; молча выдать 0 значило
            # бы объявить протокол беззащитным. Fail-CLOSED: dormant.
            return None

        total = round(earned / basis_max * 100.0, 4)
        total = min(total, 100.0)   # hard cap

        tier = _protection_tier(total)
        if treasury_usd is None:
            treasury_ratio = None
        else:
            treasury_ratio = (treasury_usd / tvl_usd) if tvl_usd > 0 else 0.0

        result = {
            "protocol": protocol,
            # inputs snapshot
            "has_insurance": has_insurance,
            "insurance_coverage_pct": coverage_pct,
            "insurance_provider": insurance_provider,
            "treasury_usd": treasury_usd,
            "tvl_usd": tvl_usd,
            "treasury_tvl_ratio": (None if treasury_ratio is None
                                   else round(treasury_ratio, 6)),
            "bug_bounty_usd": bug_bounty_usd,
            "has_timelock": has_timelock,
            "timelock_days": timelock_days,
            # score breakdown
            "coverage_score": cov_score,
            "treasury_score": tres_score,
            "bug_bounty_score": bug_score,
            "timelock_score": tl_score,
            "total_insurance_score": total,
            "protection_tier": tier,
            # Отказ обязан быть ВИДЕН в результате, иначе он неотличим от нуля.
            "unmeasured_components": list(unmeasured),
            "score_basis_max": round(basis_max, 4),
            "earned_points": round(earned, 4),
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        self._last_result = result
        if write_log:
            _append_log(self._log_path, result)
        return result

    def get_protection_tier(self) -> Optional[str]:
        """Return the protection tier from the most recent score() call."""
        if self._last_result is None:
            return None
        return self._last_result["protection_tier"]

    def get_score_breakdown(self) -> Optional[Dict]:
        """Return the score breakdown from the most recent score() call."""
        if self._last_result is None:
            return None
        r = self._last_result
        return {
            "protocol": r["protocol"],
            "coverage_score": r["coverage_score"],
            "treasury_score": r["treasury_score"],
            "bug_bounty_score": r["bug_bounty_score"],
            "timelock_score": r["timelock_score"],
            "total_insurance_score": r["total_insurance_score"],
            "protection_tier": r["protection_tier"],
            "unmeasured_components": list(r.get("unmeasured_components", [])),
            "score_basis_max": r.get("score_basis_max"),
            "score_max": {
                "coverage": _COVERAGE_MAX,
                "treasury": _TREASURY_MAX,
                "bug_bounty": _BUG_BOUNTY_MAX,
                "timelock": _TIMELOCK_MAX,
                "total": 100,
            },
        }

    def get_log(self) -> List[Dict]:
        """Return the full ring-buffer log from disk."""
        return _load_log(self._log_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(data: Dict) -> None:
        required = [
            "protocol",
            "has_insurance",
            "insurance_coverage_pct",
            "insurance_provider",
            "treasury_usd",
            "tvl_usd",
            "bug_bounty_usd",
            "has_timelock",
            "timelock_days",
        ]
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"Missing required keys: {missing}")

        coverage = float(data.get("insurance_coverage_pct", 0))
        if not (0.0 <= coverage <= 100.0):
            raise ValueError("insurance_coverage_pct must be in [0, 100]")

        if float(data["tvl_usd"]) < 0:
            raise ValueError("tvl_usd must be >= 0")

        # ``treasury_usd is None`` — ЯВНОЕ «не измерено» (ADR-070 п.15), это
        # разрешённое значение. Отсутствие ключа — по-прежнему ValueError:
        # дырка в payload'е не должна тихо превращаться в отказ компоненты
        # (именно так фабрикация 04.08 и пролезала — см. score()).
        if data["treasury_usd"] is not None and float(data["treasury_usd"]) < 0:
            raise ValueError("treasury_usd must be >= 0")

        if float(data.get("bug_bounty_usd", 0)) < 0:
            raise ValueError("bug_bounty_usd must be >= 0")

        if int(data.get("timelock_days", 0)) < 0:
            raise ValueError("timelock_days must be >= 0")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    samples = [
        {
            "protocol": "Aave V3",
            "has_insurance": True,
            "insurance_coverage_pct": 80.0,
            "insurance_provider": "Nexus Mutual",
            "treasury_usd": 50_000_000,
            "tvl_usd": 400_000_000,
            "bug_bounty_usd": 1_000_000,
            "has_timelock": True,
            "timelock_days": 7,
        },
        {
            "protocol": "NewProtocol",
            "has_insurance": False,
            "insurance_coverage_pct": 0.0,
            "insurance_provider": "",
            "treasury_usd": 100_000,
            "tvl_usd": 2_000_000,
            "bug_bounty_usd": 10_000,
            "has_timelock": False,
            "timelock_days": 0,
        },
    ]

    scorer = ProtocolInsuranceScorer()
    for s in samples:
        r = scorer.score(s)
        print(f"\n{r['protocol']}: {r['total_insurance_score']:.1f}/100  [{r['protection_tier']}]")
        bd = scorer.get_score_breakdown()
        for k, v in bd.items():
            if k not in ("protocol", "protection_tier", "score_max"):
                print(f"  {k}: {v}")
        print(f"  tier: {scorer.get_protection_tier()}")
