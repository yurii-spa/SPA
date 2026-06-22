#!/usr/bin/env python3
"""Sky / sUSDS read-only APY feed (MP-202, Sprint v4.25 / SPA-V425).

Advisory-фид видимости APY/TVL пула sUSDS (Sky, ex-MakerDAO Savings USDS)
через DeFiLlama ``/pools``. Фид делает APY **видимым** аллокатору, но НЕ
участвует в аллокации:

ЖЁСТКИЙ ГЕЙТ АЛЛОКАЦИИ (ключевая фича модуля)
---------------------------------------------
По policy ADR Sky/sUSDS остаётся на Watch List до **on-chain** подтверждения
GSM Pause Delay >= 48h. On-chain проверка требует RPC-ключей (MP-017), которые
НЕ выполнены, поэтому:

* :meth:`SkySUSDSFeed.allocation_weight` → всегда ``0.0`` (захардкожено);
* :meth:`SkySUSDSFeed.eligible_for_allocation` → всегда ``False`` с reason
  ``GATE_REASON``.

Опциональный файл ручной аттестации ``data/susds_gsm_attestation.json``
(``verified: true`` literal + ``verified_at`` + ``pause_delay_hours >= 48``)
лишь ЧИТАЕТСЯ и отражается в статусе — отсутствие/мусор = честное «НЕ
подтверждено». Даже при валидной аттестации weight остаётся ``0.0``: снятие
гейта — только отдельным спринтом ПОСЛЕ MP-017 (advisory only, деньги/policy
не затрагиваются).

Две read-поверхности по конвенции ``defillama_feed`` (SPA-V398):

* ``get_apy``/``get_tvl`` — APY как **decimal** (0.065 == 6.5%), без фильтров;
* ``fetch_apy``/``fetch_tvl``/``fetch_pool`` — APY как **percentage** (6.5) с
  liveness-фильтрами: TVL floor ``MIN_TVL_USD`` и APY sanity band ``0..200``.

Поиск пула устойчив: сперва точный ``pool_id`` (конфигурируемый /
``SUSDS_POOL_ID``), затем fallback по (project ∈ {sky-lending, sky},
symbol SUSDS) среди stablecoin-пулов; 0 или >1 кандидатов без точного
pool_id — честный ``None`` + лог, фид НИКОГДА не выдумывает данные.

Персист снапшота — ``data/susds_feed_status.json``, атомарно
(tmp + os.replace, паттерн capital_ladder/golive_checker), история с ротацией
<= 500, терпимость к битому файлу.

CLI:
    python3 -m spa_core.adapters.sky_susds_feed --check   # fetch+print, без записи
    python3 -m spa_core.adapters.sky_susds_feed --run     # fetch + персист снапшота

Scope / safety: LLM FORBIDDEN — детерминированная логика; зависимости — только
stdlib (urllib, как в defillama_feed). Все сетевые ошибки →
``None`` + лог, никогда не raise наружу. Модуль ничего не исполняет on-chain.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config
from spa_core.utils.atomic import atomic_save

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_FILENAME = "susds_feed_status.json"
ATTESTATION_FILENAME = "susds_gsm_attestation.json"

# Liveness filters for the ``fetch_*`` surface (same values as defillama_feed).
MIN_TVL_USD = 100_000.0
APY_SANITY_MAX = 200.0

# Pool discovery defaults. DeFiLlama lists Sky Savings USDS under the project
# slug "sky-lending" (historically also plain "sky"), symbol "SUSDS".
DEFAULT_PROJECTS: tuple[str, ...] = ("sky-lending", "sky")
DEFAULT_SYMBOL = "SUSDS"
DEFAULT_CHAIN = "Ethereum"

# Snapshot history rotation cap.
HISTORY_MAX = 500

# ── Allocation gate (HARD-CODED until MP-017) ────────────────────────────────
# The on-chain GSM Pause Delay >= 48h check needs RPC keys (MP-017, NOT done).
# Until a dedicated post-MP-017 sprint lifts this gate the feed is advisory
# only: weight is a literal constant, not derived from any input.
ALLOCATION_WEIGHT = 0.0
GSM_PAUSE_DELAY_MIN_HOURS = 48.0
GATE_REASON = (
    "GSM Pause Delay >=48h не подтверждён on-chain "
    "(MP-017 RPC keys отсутствуют)"
)


# ─── Atomic / tolerant IO helpers (паттерн capital_ladder / golive_checker) ──


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Atomic JSON write via centralized atomic_save (MP-1453)."""
    atomic_save(obj, str(path))
def _read_json(path: Path) -> Any:
    """Читает JSON терпимо: нет файла / битый файл → None, никогда не raise."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _num(value: Any) -> Optional[float]:
    """Число или None (bool — не число)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ─── Feed ─────────────────────────────────────────────────────────────────────


class SkySUSDSFeed:
    """Read-only cached client for the Sky sUSDS pool on DeFiLlama ``/pools``.

    Advisory APY-visibility feed: never allocates, never executes, never mocks.
    """

    PROTOCOL = "sky_susds"

    def __init__(
        self,
        api_url: Optional[str] = None,
        cache_ttl: Optional[int] = None,
        timeout: Optional[int] = None,
        enabled: Optional[bool] = None,
        pool_id: Optional[str] = None,
        projects: Optional[tuple[str, ...]] = None,
        symbol: str = DEFAULT_SYMBOL,
        chain: str = DEFAULT_CHAIN,
        data_dir: Optional[os.PathLike] = None,
    ):
        self.api_url = api_url if api_url is not None else config.DEFILLAMA_API_URL
        self.cache_ttl = (
            cache_ttl if cache_ttl is not None else config.DEFILLAMA_CACHE_TTL
        )
        self.timeout = timeout if timeout is not None else config.DEFILLAMA_TIMEOUT
        self.enabled = enabled if enabled is not None else config.DEFILLAMA_ENABLED
        # Точный pool uuid имеет приоритет над fallback-поиском.
        env_pool_id = os.getenv("SUSDS_POOL_ID", "").strip()
        self.pool_id = pool_id if pool_id is not None else (env_pool_id or None)
        self.projects = tuple(
            p.lower() for p in (projects if projects is not None else DEFAULT_PROJECTS)
        )
        self.symbol = symbol
        self.chain = chain
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

        self._cache: Optional[list] = None
        self._cache_ts: float = 0.0

    # ── internal: raw pools (cache TTL) ──────────────────────────────────────

    def _fetch_pools(self) -> Optional[list]:
        """Сырой список пулов, из кэша в пределах TTL. None на любой ошибке."""
        if not self.enabled:
            return None

        now = time.monotonic()
        if self._cache is not None and (now - self._cache_ts) < self.cache_ttl:
            return self._cache

        try:
            # Pin Accept-Encoding to gzip (см. defillama_feed, SPA-V398). urllib
            # не распаковывает автоматически — делаем это по gzip-магии вручную.
            req = urllib.request.Request(
                self.api_url,
                headers={"Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — log and degrade honestly
            logger.warning("sky_susds: DeFiLlama fetch failed: %s", exc)
            return None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            logger.warning("sky_susds: unexpected DeFiLlama payload: %r",
                           type(payload).__name__)
            return None
        data = payload.get("data")
        if not isinstance(data, list):
            logger.warning("sky_susds: DeFiLlama payload 'data' is not a list")
            return None

        self._cache = data
        self._cache_ts = now
        return data

    # ── internal: robust pool discovery ──────────────────────────────────────

    def find_pool(self) -> Optional[dict]:
        """Находит пул sUSDS устойчиво; честный ``None`` при неоднозначности.

        1. Точный ``pool_id`` (uuid DeFiLlama), если сконфигурирован.
        2. Fallback: (project ∈ ``self.projects``, symbol, chain) среди
           **stablecoin**-пулов. Ровно один кандидат — ок; 0 или >1 без
           точного pool_id — ``None`` + лог (ничего не выдумываем).
        """
        pools = self._fetch_pools()
        if not pools:
            return None

        if self.pool_id:
            for pool in pools:
                if isinstance(pool, dict) and str(pool.get("pool")) == self.pool_id:
                    return pool
            logger.warning(
                "sky_susds: configured pool_id %s not found; trying fallback",
                self.pool_id,
            )

        symbol_u = self.symbol.upper()
        chain_l = self.chain.lower()
        candidates: list[dict] = []
        for pool in pools:
            if not isinstance(pool, dict):
                continue
            if str(pool.get("project", "")).lower() not in self.projects:
                continue
            if str(pool.get("symbol", "")).upper() != symbol_u:
                continue
            if str(pool.get("chain", "")).lower() != chain_l:
                continue
            if pool.get("stablecoin") is not True:
                continue
            candidates.append(pool)

        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            logger.warning(
                "sky_susds: no pool matched projects=%s symbol=%s chain=%s "
                "(stablecoin only) — no live data",
                self.projects, self.symbol, self.chain,
            )
        else:
            logger.warning(
                "sky_susds: %d ambiguous candidates without exact pool_id "
                "(%s) — refusing to guess",
                len(candidates),
                [c.get("pool") for c in candidates],
            )
        return None

    # ── legacy surface: decimal APY, no liveness filters ─────────────────────

    def get_pool(self) -> Optional[dict]:
        """Сырой dict пула DeFiLlama, или ``None``."""
        return self.find_pool()

    def get_apy(self) -> Optional[float]:
        """Live APY как **decimal** (0.065 == 6.5%), или ``None``."""
        pool = self.find_pool()
        if pool is None:
            return None
        apy = _num(pool.get("apy"))
        return apy / 100.0 if apy is not None else None

    def get_tvl(self) -> Optional[float]:
        """Live TVL в USD, или ``None``."""
        pool = self.find_pool()
        if pool is None:
            return None
        return _num(pool.get("tvlUsd"))

    # ── liveness-filtered surface: percentage APY (конвенция SPA-V398) ───────

    def fetch_pool(self, min_tvl_usd: float = MIN_TVL_USD) -> Optional[dict]:
        """``{"apy", "tvl", "pool_id"}`` живого пула, или ``None`` — не мок.

        ``apy`` — **percentage** (6.5 == 6.5%). Фильтры liveness:
        TVL < ``min_tvl_usd`` (dead/spam) или APY вне ``0..APY_SANITY_MAX`` →
        ``None``. Никогда не raise.
        """
        try:
            pool = self.find_pool()
            if pool is None:
                return None

            tvl = _num(pool.get("tvlUsd"))
            if tvl is None or tvl < min_tvl_usd:
                logger.warning(
                    "sky_susds: TVL %s below floor %.0f — pool not live",
                    tvl, min_tvl_usd,
                )
                return None

            apy = _num(pool.get("apy"))
            if apy is None or apy < 0 or apy > APY_SANITY_MAX:
                logger.warning(
                    "sky_susds: anomalous/missing APY %s rejected "
                    "(sanity band 0..%.0f)", apy, APY_SANITY_MAX,
                )
                return None

            return {"apy": apy, "tvl": tvl, "pool_id": pool.get("pool")}
        except Exception as exc:  # noqa: BLE001 — never raise, never mock
            logger.warning("sky_susds: fetch_pool failed: %s", exc)
            return None

    def fetch_apy(self) -> Optional[float]:
        """Live APY как **percentage** (6.5), или ``None``."""
        result = self.fetch_pool()
        return result["apy"] if result else None

    def fetch_tvl(self) -> Optional[float]:
        """Live TVL в USD (с liveness-фильтрами), или ``None``."""
        result = self.fetch_pool()
        return result["tvl"] if result else None

    # ── allocation gate (HARD 0% until MP-017) ───────────────────────────────

    def gsm_attestation_verified(self) -> bool:
        """Читает опциональную ручную аттестацию GSM Pause Delay.

        ``data/susds_gsm_attestation.json`` валидна ТОЛЬКО при literal
        ``verified: true`` + непустом ``verified_at`` +
        ``pause_delay_hours >= 48`` (числом, bool не считается).
        Отсутствие / мусор / частичные поля = честное ``False``.
        Информационно: даже ``True`` НЕ снимает гейт (нужен MP-017 + отдельный
        спринт) — аттестация лишь отражается в статусе.
        """
        doc = _read_json(self.data_dir / ATTESTATION_FILENAME)
        if not isinstance(doc, dict):
            return False
        if doc.get("verified") is not True:
            return False
        verified_at = doc.get("verified_at")
        if not isinstance(verified_at, str) or not verified_at.strip():
            return False
        delay = _num(doc.get("pause_delay_hours"))
        return delay is not None and delay >= GSM_PAUSE_DELAY_MIN_HOURS

    def allocation_weight(self) -> float:
        """Вес в аллокации: всегда ``0.0`` (захардкожено до MP-017).

        Даже при валидной аттестации вес НЕ меняется — снятие гейта только
        отдельным спринтом после MP-017 (advisory-фид, деньги не двигаются).
        """
        return ALLOCATION_WEIGHT

    def eligible_for_allocation(self) -> bool:
        """Допуск к аллокации: всегда ``False`` (см. :data:`GATE_REASON`)."""
        return False

    def gate_status(self) -> dict:
        """Полный advisory-вердикт гейта (для статуса/дашборда)."""
        attested = self.gsm_attestation_verified()
        return {
            "eligible_for_allocation": False,
            "allocation_weight": ALLOCATION_WEIGHT,
            "reason": GATE_REASON,
            "gsm_attestation_verified": attested,
            "note": (
                "attestation present but gate stays hard-closed until MP-017 "
                "+ dedicated un-gating sprint"
                if attested
                else "no valid attestation; gate hard-closed (MP-017 pending)"
            ),
        }

    # ── snapshot / persistence ───────────────────────────────────────────────

    def build_snapshot(self) -> dict:
        """Снимок фида + гейта. Никогда не raise; офлайн = честный unavailable."""
        ts = datetime.now(timezone.utc).isoformat()
        live = self.fetch_pool()
        gate = self.gate_status()
        apy_pct = live["apy"] if live else None
        return {
            "source": "sky_susds_feed",
            "protocol": self.PROTOCOL,
            "is_demo": False,
            "advisory_only": True,
            "updated_at": ts,
            "status": "ok" if live else "unavailable",
            "live_data": live is not None,
            "pool_id": live["pool_id"] if live else self.pool_id,
            "apy_pct": apy_pct,
            "apy_decimal": (apy_pct / 100.0) if apy_pct is not None else None,
            "tvl_usd": live["tvl"] if live else None,
            "min_tvl_usd": MIN_TVL_USD,
            "apy_sanity_max": APY_SANITY_MAX,
            "gate": gate,
            # дублируем ключевые поля гейта на верхний уровень для потребителей
            "allocation_weight": gate["allocation_weight"],
            "eligible_for_allocation": gate["eligible_for_allocation"],
        }

    def run(self, write: bool = True) -> dict:
        """Полный прогон: fetch → снапшот → (опц.) атомарный персист.

        ``write=False`` (--check) — только вычисление, без записи. История в
        ``data/susds_feed_status.json`` ротируется до :data:`HISTORY_MAX`;
        битый существующий файл толерантно игнорируется.
        """
        snapshot = self.build_snapshot()
        if write:
            prev = _read_json(self.data_dir / STATUS_FILENAME)
            history: list = []
            if isinstance(prev, dict) and isinstance(prev.get("history"), list):
                history = [h for h in prev["history"] if isinstance(h, dict)]
            history.append(
                {
                    "ts": snapshot["updated_at"],
                    "status": snapshot["status"],
                    "apy_pct": snapshot["apy_pct"],
                    "tvl_usd": snapshot["tvl_usd"],
                }
            )
            doc = dict(snapshot)
            doc["history"] = history[-HISTORY_MAX:]
            _atomic_write_json(self.data_dir / STATUS_FILENAME, doc)
        return snapshot

    def summary(self, snapshot: dict) -> str:
        """Человекочитаемый отчёт для CLI."""
        apy = snapshot.get("apy_pct")
        tvl = snapshot.get("tvl_usd")
        gate = snapshot.get("gate", {})
        lines = [
            "─" * 56,
            f"SKY / sUSDS READ-ONLY FEED (MP-202)   [{snapshot.get('updated_at')}]",
            "─" * 56,
            f"  status: {snapshot.get('status')}",
            f"  apy: {('%.4f%%' % apy) if apy is not None else 'unavailable (no live data — feed is honest, not mocked)'}",
            f"  tvl: {('$%s' % format(tvl, ',.0f')) if tvl is not None else 'unavailable'}",
            f"  pool_id: {snapshot.get('pool_id') or 'not resolved'}",
            f"  allocation_weight: {gate.get('allocation_weight', ALLOCATION_WEIGHT):.1f} (HARD until MP-017)",
            f"  eligible_for_allocation: {gate.get('eligible_for_allocation', False)}",
            f"  reason: {gate.get('reason', GATE_REASON)}",
            f"  gsm_attestation_verified: {gate.get('gsm_attestation_verified', False)}",
            "  note: advisory APY visibility only — никогда не аллоцирует",
            "─" * 56,
        ]
        return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: Optional[list] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="sky_susds_feed",
        description=(
            "Sky/sUSDS read-only APY feed (MP-202) — advisory only, "
            "allocation weight hard 0% until MP-017."
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true",
        help="fetch + print, без записи статуса",
    )
    group.add_argument(
        "--run", action="store_true",
        help="fetch + атомарный персист data/susds_feed_status.json",
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    feed = SkySUSDSFeed(data_dir=args.data_dir)
    snapshot = feed.run(write=bool(args.run))
    print(feed.summary(snapshot))
    # Недоступность сети — честный unavailable, НЕ ошибка CLI.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# end of file
