"""
RiskAdjustedRanker — advisory-модуль аналитики: ранжирует DeFi-адаптеры
по risk-adjusted yield (доходность на единицу риска).

Это READ-ONLY / advisory модуль. Он НИКОГДА не двигает деньги, не делает
сделок и не вызывает execution / risk / monitoring. Только агрегирует и
ранжирует уже посчитанные адаптеры из data/adapter_status.json.

Метрики:
    risk_adjusted_score = apy_pct / max(risk_score, EPS)
    excess_yield_pct    = apy_pct - RISK_FREE_PCT   (T-bill baseline)

Только stdlib. Читает data/adapter_status.json, пишет
data/risk_adjusted_report.json (кольцевой буфер из 30 снапшотов).

CLI:
    python3 -m spa_core.analytics.risk_adjusted_ranker --check   # вывод без записи (дефолт)
    python3 -m spa_core.analytics.risk_adjusted_ranker --run     # вычислить + записать

MP-593.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Risk-free baseline (T-bill yield, %) для расчёта excess yield.
RISK_FREE_PCT: float = 4.0

# Fallback risk_score, если у адаптера нет поля risk_score.
DEFAULT_RISK_SCORE: float = 0.5

# Минимальный APY (%), при котором адаптер считается eligible.
MIN_APY_PCT: float = 0.0

# Защита от деления на ноль в risk_adjusted_score.
EPS: float = 1e-9

# USDC peg tolerance для peg_healthy check.
_PEG_TOLERANCE: float = 0.005

# Ring-buffer size для save_report.
_RING_BUFFER_SIZE: int = 30

# Ключи верхнего уровня adapter_status.json, которые не являются адаптерами.
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode",
    "live_apy_enabled", "mev_protection", "adapters",
    "base_gas_monitor",
})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RankedAdapter:
    """Один адаптер с посчитанными risk-adjusted метриками."""
    name: str
    protocol: str
    tier: str
    network: str
    apy_pct: float
    risk_score: float
    tvl_usd: float
    risk_adjusted_score: float
    excess_yield_pct: float
    peg_healthy: bool
    eligible: bool
    rank: Optional[int] = None  # заполняется при ранжировании (1..N среди eligible)

    def to_dict(self) -> dict:
        """Возвращает запись в виде dict, пригодного для JSON-сериализации."""
        return {
            "name": self.name,
            "protocol": self.protocol,
            "tier": self.tier,
            "network": self.network,
            "apy_pct": self.apy_pct,
            "risk_score": self.risk_score,
            "tvl_usd": self.tvl_usd,
            "risk_adjusted_score": self.risk_adjusted_score,
            "excess_yield_pct": self.excess_yield_pct,
            "peg_healthy": self.peg_healthy,
            "eligible": self.eligible,
            "rank": self.rank,
        }


@dataclass
class RankerReport:
    """Сводный отчёт ранжирования всех адаптеров."""
    generated_at: str
    ranked: List[RankedAdapter]
    total_adapters: int
    eligible_count: int
    best_adapter: str
    best_score: float
    top_tier_leaders: Dict[str, str]  # tier → name лучшего адаптера в tier

    def to_dict(self) -> dict:
        """Возвращает отчёт в виде dict, пригодного для JSON-сериализации."""
        return {
            "generated_at": self.generated_at,
            "ranked": [r.to_dict() for r in self.ranked],
            "total_adapters": self.total_adapters,
            "eligible_count": self.eligible_count,
            "best_adapter": self.best_adapter,
            "best_score": self.best_score,
            "top_tier_leaders": dict(self.top_tier_leaders),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _num(val: object) -> Optional[float]:
    """Возвращает float если val — число (не bool), иначе None."""
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return None


def _extract_apy(entry: dict) -> float:
    """Извлекает APY (%) из entry. Приоритет: apy_pct → apy → 0.0."""
    for key in ("apy_pct", "apy"):
        val = _num(entry.get(key))
        if val is not None:
            return val
    return 0.0


def _extract_risk_score(entry: dict) -> float:
    """Извлекает risk_score из entry. Fallback — DEFAULT_RISK_SCORE."""
    val = _num(entry.get("risk_score"))
    if val is not None:
        return val
    return DEFAULT_RISK_SCORE


def _extract_tvl(entry: dict) -> float:
    """Извлекает tvl_usd из entry (0.0 если отсутствует/не число)."""
    val = _num(entry.get("tvl_usd"))
    return val if val is not None else 0.0


def _extract_peg_healthy(entry: dict) -> bool:
    """Определяет peg_healthy. Default-safe (отсутствие usdc_price → True).

    True при |usdc_price - 1.0| <= _PEG_TOLERANCE.
    """
    price = _num(entry.get("usdc_price"))
    if price is not None:
        # EPS добавлен для устойчивости к floating-point представлению границы
        # (например abs(0.995 - 1.0) == 0.005000000000000004).
        return abs(price - 1.0) <= _PEG_TOLERANCE + EPS
    return True


def _resolve_network(entry: dict) -> str:
    """Извлекает chain/network из entry. Возвращает строку или ''."""
    raw = entry.get("network") or entry.get("chain") or ""
    return str(raw)


def _resolve_protocol(entry: dict, name: str) -> str:
    """Извлекает человекочитаемое имя протокола из entry."""
    proto = (
        entry.get("protocol")
        or entry.get("name")
        or entry.get("display_name")
        or name
    )
    return str(proto)


# ---------------------------------------------------------------------------
# RiskAdjustedRanker
# ---------------------------------------------------------------------------

class RiskAdjustedRanker:
    """Ранжирует DeFi-адаптеры по risk-adjusted yield (apy / risk_score).

    Advisory / read-only: только читает ``data/adapter_status.json`` и
    вычисляет ранжирование. Никогда не двигает средства.

    Параметры
    ---------
    data_path : str | None
        Путь к ``adapter_status.json``. По умолчанию — ``data/`` относительно
        корня репозитория.

    Пример использования
    --------------------
    ranker = RiskAdjustedRanker()
    ranked = ranker.rank_all()
    top5   = ranker.get_top_n(5)
    report = ranker.get_report()
    path   = ranker.save_report()
    """

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self._data_path = _DEFAULT_DATA_DIR / "adapter_status.json"
        else:
            self._data_path = Path(data_path)
        self._output_dir = self._data_path.parent

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_adapter_status(self) -> dict:
        """Загружает adapter_status.json. Возвращает {} при любой ошибке.

        Никогда не бросает исключений — fail-safe (missing file / битый JSON /
        не-dict верхний уровень → {}).
        """
        try:
            with open(self._data_path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Internal: extract & build adapter records
    # ------------------------------------------------------------------

    def _extract_adapters(self) -> List[RankedAdapter]:
        """Разбирает adapter_status.json в список RankedAdapter.

        Два источника (dual-source):
        1. Protocol-level dict-записи верхнего уровня, у которых есть 'apy'
           (более точные — имеют приоритет).
        2. Список ``adapters[]`` — дополняет, не дублируя по имени.

        Служебные ключи (_SKIP_KEYS, ключи на '_', non-dict, без 'apy')
        пропускаются.
        """
        data = self.load_adapter_status()
        result: List[RankedAdapter] = []
        seen: set = set()  # имена уже добавленных адаптеров

        # ── Источник 1: protocol-level entries (приоритетные) ──────────────
        for key, val in data.items():
            if key in _SKIP_KEYS or key.startswith("_"):
                continue
            if not isinstance(val, dict):
                continue
            if "apy" not in val and "apy_pct" not in val:
                continue
            name = str(val.get("adapter_id") or val.get("protocol_key") or key)
            if name in seen:
                continue
            result.append(self._build_adapter(name, val))
            seen.add(name)

        # ── Источник 2: adapters[] list (заполняет пробелы) ────────────────
        for adapter in data.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            name = str(
                adapter.get("protocol_key")
                or adapter.get("adapter_id")
                or adapter.get("name")
                or "unknown"
            )
            if name in seen:
                continue  # уже покрыто protocol-level записью
            result.append(self._build_adapter(name, adapter))
            seen.add(name)

        return result

    def _build_adapter(self, name: str, entry: dict) -> RankedAdapter:
        """Строит RankedAdapter из одной записи (с посчитанными метриками)."""
        apy = _extract_apy(entry)
        risk = _extract_risk_score(entry)
        tvl = _extract_tvl(entry)
        peg_healthy = _extract_peg_healthy(entry)
        ras = apy / max(risk, EPS)
        excess = apy - RISK_FREE_PCT
        eligible = peg_healthy and apy >= MIN_APY_PCT
        return RankedAdapter(
            name=name,
            protocol=_resolve_protocol(entry, name),
            tier=str(entry.get("tier", "")),
            network=_resolve_network(entry),
            apy_pct=round(apy, 4),
            risk_score=round(risk, 4),
            tvl_usd=round(tvl, 2),
            risk_adjusted_score=round(ras, 4),
            excess_yield_pct=round(excess, 4),
            peg_healthy=peg_healthy,
            eligible=eligible,
            rank=None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def rank_all(self) -> List[RankedAdapter]:
        """Возвращает eligible-адаптеры, отсортированные по risk_adjusted_score.

        Сортировка: risk_adjusted_score desc, tie-break — apy desc, затем
        name asc. Каждому проставляется rank=1..N. Non-eligible адаптеры
        ИСКЛЮЧАЮТСЯ (см. get_excluded()).
        """
        eligible = [a for a in self._extract_adapters() if a.eligible]
        eligible.sort(key=lambda a: (-a.risk_adjusted_score, -a.apy_pct, a.name))
        for idx, adapter in enumerate(eligible, start=1):
            adapter.rank = idx
        return eligible

    def get_excluded(self) -> List[RankedAdapter]:
        """Возвращает non-eligible адаптеры (rank остаётся None)."""
        return [a for a in self._extract_adapters() if not a.eligible]

    def get_top_n(self, n: int) -> List[RankedAdapter]:
        """Возвращает топ-N ранжированных адаптеров.

        n <= 0 → пустой список. n больше длины → весь список.
        """
        ranked = self.rank_all()
        if n <= 0:
            return []
        return ranked[:n]

    def get_by_tier(self, tier: str) -> List[RankedAdapter]:
        """Возвращает ранжированные eligible-адаптеры заданного tier.

        Tier нормализуется к верхнему регистру. Несуществующий tier → [].
        """
        target = str(tier).strip().upper()
        return [a for a in self.rank_all() if a.tier.strip().upper() == target]

    def get_tier_leaders(self) -> Dict[str, str]:
        """Для каждого tier — имя лучшего eligible-адаптера по score.

        Возвращает
        ----------
        dict[str, str]
            {tier(upper): name}. Tiers без eligible-адаптеров не включаются.
        """
        leaders: Dict[str, str] = {}
        best_score: Dict[str, float] = {}
        for adapter in self.rank_all():
            tier = adapter.tier.strip().upper()
            if not tier:
                tier = "UNKNOWN"
            if tier not in best_score or adapter.risk_adjusted_score > best_score[tier]:
                best_score[tier] = adapter.risk_adjusted_score
                leaders[tier] = adapter.name
        return leaders

    def get_report(self) -> RankerReport:
        """Создаёт полный RankerReport.

        Возвращает
        ----------
        RankerReport
            ranked (eligible, отсортированные), total_adapters, eligible_count,
            best_adapter, best_score, top_tier_leaders.
        """
        now = datetime.now(timezone.utc).isoformat()
        all_adapters = self._extract_adapters()
        ranked = self.rank_all()

        if ranked:
            best_adapter = ranked[0].name
            best_score = ranked[0].risk_adjusted_score
        else:
            best_adapter = ""
            best_score = 0.0

        return RankerReport(
            generated_at=now,
            ranked=ranked,
            total_adapters=len(all_adapters),
            eligible_count=len(ranked),
            best_adapter=best_adapter,
            best_score=best_score,
            top_tier_leaders=self.get_tier_leaders(),
        )

    def to_dict(self) -> dict:
        """Возвращает полный отчёт в виде dict, пригодного для JSON-сериализации."""
        return self.get_report().to_dict()

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Сохраняет отчёт в data/risk_adjusted_report.json атомарно.

        Хранит кольцевой буфер из последних 30 снапшотов (tmp + os.replace,
        без .tmp-мусора при ошибке).

        Параметры
        ---------
        output_path : str | None
            Путь к выходному файлу. По умолчанию:
            ``{data_dir}/risk_adjusted_report.json``.

        Возвращает
        ----------
        str
            Абсолютный путь к сохранённому файлу.
        """
        if output_path is None:
            out_path = self._output_dir / "risk_adjusted_report.json"
        else:
            out_path = Path(output_path)

        new_snapshot = self.to_dict()

        # Загружаем существующий ring-buffer
        snapshots: List[dict] = []
        try:
            with open(out_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            if isinstance(existing, dict) and "snapshots" in existing:
                raw_snaps = existing.get("snapshots", [])
                if isinstance(raw_snaps, list):
                    snapshots = raw_snaps
            elif isinstance(existing, list):
                snapshots = existing
        except Exception:
            snapshots = []

        # Добавляем новый snapshot, ограничиваем ring-buffer
        snapshots.append(new_snapshot)
        snapshots = snapshots[-_RING_BUFFER_SIZE:]

        output = {
            "schema_version": 1,
            "generated_at": new_snapshot["generated_at"],
            "latest": new_snapshot,
            "snapshots": snapshots,
        }

        # Атомарная запись: tmp + os.replace
        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = str(out_path) + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(output, fh, indent=2, ensure_ascii=False)
            os.replace(tmp_path, str(out_path))
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return str(out_path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry-point.

    Usage:
        python3 -m spa_core.analytics.risk_adjusted_ranker [--check | --run]

    --check (default): вычислить и вывести, без записи на диск.
    --run:             вычислить, вывести и атомарно записать в data/.
    """
    if argv is None:
        argv = sys.argv[1:]

    run_mode = "--run" in argv

    ranker = RiskAdjustedRanker()
    report = ranker.get_report()

    print("=== RiskAdjustedRanker Report ===")
    print(f"Generated: {report.generated_at}")
    print(f"Total adapters: {report.total_adapters}  "
          f"(eligible: {report.eligible_count})")
    print(f"Best adapter: {report.best_adapter} "
          f"(score={report.best_score:.2f})")
    print()

    print("Ranking (risk-adjusted score = APY / risk_score):")
    for adapter in report.ranked:
        print(
            f"  #{adapter.rank:<2d} {adapter.name:24s} "
            f"tier={adapter.tier:4s} "
            f"apy={adapter.apy_pct:6.2f}%  "
            f"risk={adapter.risk_score:.2f}  "
            f"score={adapter.risk_adjusted_score:7.2f}  "
            f"excess={adapter.excess_yield_pct:+.2f}%"
        )

    excluded = ranker.get_excluded()
    if excluded:
        print(f"\nExcluded (non-eligible): {len(excluded)}")
        for adapter in excluded:
            print(f"  - {adapter.name} "
                  f"(peg_healthy={adapter.peg_healthy}, apy={adapter.apy_pct:.2f}%)")

    if report.top_tier_leaders:
        print("\nTier leaders:")
        for tier, name in sorted(report.top_tier_leaders.items()):
            print(f"  {tier}: {name}")

    if run_mode:
        path = ranker.save_report()
        print(f"\n✅ Report saved → {path}")
    else:
        print("\n(dry-run: use --run to save to data/risk_adjusted_report.json)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
