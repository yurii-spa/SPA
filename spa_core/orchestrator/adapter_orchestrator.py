#!/usr/bin/env python3
"""adapter_orchestrator.py — запускает все read-only адаптеры, агрегирует статус,
пишет JSON атомарно (SPA-V386).

Назначение
==========
Единый цикл, который опрашивает read-only протокол-адаптеры из
``spa_core/adapters/`` (Morpho, Yearn, Euler, Maple), собирает APY/TVL/статус,
считает per-adapter и общий health score и атомарно пишет результат на диск.

Безопасность / scope
=====================
* STRICTLY READ-ONLY / SIMULATION. Используются ТОЛЬКО методы ``get_yield_info()``
  read-only адаптеров — никаких on-chain транзакций, кошельков, подписей.
* НЕ импортирует и НЕ запускает ничего из ``spa_core/execution/`` (домен execution
  заморожен для LLM-агентов; там живут wallet/eth_signer/router/safety_checks).
* НЕ перезаписывает ``data/adapter_status.json`` — это выход модуля
  ``spa_core/execution/adapter_status.py`` (single source of truth, v3.33) со своими
  тестами. Оркестратор пишет в отдельный файл ``data/adapter_orchestrator_status.json``.
* НЕ трогает feed-health стек (SPA-BL-011 заморожен).
* Только stdlib + уже импортируемые адаптеры (которые внутри используют requests).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from spa_core.adapters import (
    AaveV3Adapter,
    CompoundV3Adapter,
    EulerV2Adapter,
    MapleAdapter,
    MorphoBlueAdapter,
    PendleAdapter,
    YearnV3Adapter,
)
from spa_core.orchestrator.health_score import (
    compute_health_score,
    compute_overall_health,
)

log = logging.getLogger(__name__)

# ─── Конфигурация ──────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Имя файла-выхода. НАМЕРЕННО не "adapter_status.json" — тот файл принадлежит
# модулю execution/adapter_status.py. См. docstring модуля.
STATUS_FILENAME = "adapter_orchestrator_status.json"
RUNS_FILENAME = "orchestrator_runs.json"

# Таймаут на один адаптер (секунды).
ADAPTER_TIMEOUT_SEC = 5.0
# Размер кольцевого буфера прогонов по умолчанию.
DEFAULT_MAX_RUNS = 30

# Реестр read-only адаптеров: (protocol_key, tier, adapter_class).
# Тир дублируется здесь как fallback на случай, если адаптер упадёт ещё при
# инстанцировании (тогда get_yield_info().tier недоступен).
ADAPTER_REGISTRY: list[tuple[str, str, type]] = [
    # SPA-V405: Aave V3 is the T1 anchor (40% cap) that lets the allocator fill
    # the structural remainder left by the four 20%-capped T2 adapters.
    ("aave_v3", "T1", AaveV3Adapter),
    # SPA-V411: Compound V3 (Comet USDC) is the second T1 anchor — blue-chip
    # lending market alongside Aave. Diversifies the T1 anchor (no single point
    # of failure) and gives the allocator more headroom to fill the remainder.
    ("compound_v3", "T1", CompoundV3Adapter),
    ("morpho_blue", "T2", MorphoBlueAdapter),
    ("yearn_v3", "T2", YearnV3Adapter),
    ("euler_v2", "T2", EulerV2Adapter),
    ("maple", "T2", MapleAdapter),
    # MP-201: Pendle PT stablecoin markets — T2/T3 dynamic tier, fixed-rate APY
    # via the Pendle V2 REST API. Declared T2 here as registry-level default.
    ("pendle", "T2", PendleAdapter),
]


# ─── Структура результата ──────────────────────────────────────────────────────


@dataclass
class OrchestratorResult:
    """Агрегированный результат одного цикла оркестратора."""

    run_ts: str
    duration_sec: float
    adapters: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    overall_health: dict = field(default_factory=dict)
    # SPA-V398: "ok" when ≥1 adapter has live data, "no_live_data" when none do.
    status: str = "ok"
    # "live" when ≥1 adapter returned a live APY, otherwise "stale".
    data_freshness: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Запуск одного адаптера ────────────────────────────────────────────────────


def _run_one_adapter(
    protocol_key: str,
    tier: str,
    adapter_cls: type,
    run_ts: str,
    now: datetime,
) -> dict:
    """Опросить один адаптер. Никогда не бросает исключение — любая ошибка
    отражается в полях ``status``/``error`` результата."""
    record: dict[str, Any] = {
        "protocol": protocol_key,
        "adapter_class": adapter_cls.__name__,
        "tier": tier,
        "apy_pct": None,
        "tvl_usd": None,
        "status": "error",
        "last_updated": run_ts,
        "error": None,
        "warning": None,
        # SPA-V398: True only when the adapter returned a live APY from the feed.
        "live_data": False,
    }
    try:
        adapter = adapter_cls()
        info = adapter.get_yield_info()
        raw_apy = getattr(info, "apy", None)
        tvl_usd = float(info.tvl_usd) if isinstance(info.tvl_usd, (int, float)) else None

        record["protocol"] = getattr(info, "protocol", protocol_key) or protocol_key
        record["tier"] = getattr(info, "tier", tier) or tier
        record["tvl_usd"] = tvl_usd

        if not isinstance(raw_apy, (int, float)):
            # SPA-V398: no live APY → honest "no live data" error, never a mock.
            record["apy_pct"] = None
            record["status"] = "error"
            record["error"] = "live_feed_unavailable"
            record["live_data"] = False
        else:
            # YieldInfo.apy — десятичная доля (0.083); приводим к процентам.
            apy_pct = round(float(raw_apy) * 100.0, 4)
            record["apy_pct"] = apy_pct
            record["live_data"] = True
            if apy_pct <= 0:
                # Данные получены, но APY нулевой/отрицательный — частичные данные.
                record["status"] = "partial"
                record["warning"] = "non-positive APY"
            else:
                record["status"] = "ok"
    except Exception as exc:  # noqa: BLE001 — изоляция: один упавший адаптер не валит цикл.
        log.warning("adapter %s failed: %s", protocol_key, exc)
        record["status"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["live_data"] = False

    record["health_score"] = compute_health_score(record, now=now)
    return record


def _collect_adapter_statuses(
    registry: list[tuple[str, str, type]],
    run_ts: str,
    timeout: float,
    now: datetime,
) -> list[dict]:
    """Параллельно опросить все адаптеры с пер-адаптерным таймаутом."""
    results: list[dict] = []
    executor = ThreadPoolExecutor(max_workers=max(1, len(registry)))
    try:
        future_map = {
            executor.submit(_run_one_adapter, key, tier, cls, run_ts, now): (key, tier, cls)
            for (key, tier, cls) in registry
        }
        for future, (key, tier, cls) in future_map.items():
            try:
                results.append(future.result(timeout=timeout))
            except FuturesTimeout:
                log.warning("adapter %s timed out after %ss", key, timeout)
                record = {
                    "protocol": key,
                    "adapter_class": cls.__name__,
                    "tier": tier,
                    "apy_pct": None,
                    "tvl_usd": None,
                    "status": "timeout",
                    "last_updated": run_ts,
                    "error": f"timeout after {timeout}s",
                    "warning": None,
                    "live_data": False,
                }
                record["health_score"] = compute_health_score(record, now=now)
                results.append(record)
            except Exception as exc:  # noqa: BLE001 — на всякий случай.
                record = {
                    "protocol": key,
                    "adapter_class": cls.__name__,
                    "tier": tier,
                    "apy_pct": None,
                    "tvl_usd": None,
                    "status": "error",
                    "last_updated": run_ts,
                    "error": f"{type(exc).__name__}: {exc}",
                    "warning": None,
                    "live_data": False,
                }
                record["health_score"] = compute_health_score(record, now=now)
                results.append(record)
    finally:
        # Не блокируемся на зависших потоках — это read-only опросы.
        executor.shutdown(wait=False)

    # Стабильный порядок: как в реестре.
    order = {key: i for i, (key, _, _) in enumerate(registry)}
    results.sort(key=lambda r: order.get(r["protocol"], len(order)))
    return results


# ─── Агрегация ─────────────────────────────────────────────────────────────────


def _build_summary(adapters: list[dict], overall: dict) -> dict:
    """Собрать сводку по списку результатов адаптеров."""
    ok = [a for a in adapters if a.get("status") == "ok"]
    partial = [a for a in adapters if a.get("status") == "partial"]
    errored = [
        a for a in adapters if a.get("status") in {"error", "timeout"} or a.get("error")
    ]

    # best_apy — только среди ok-адаптеров с числовым APY.
    best_apy = None
    apy_candidates = [
        a for a in ok if isinstance(a.get("apy_pct"), (int, float))
    ]
    if apy_candidates:
        best = max(apy_candidates, key=lambda a: a["apy_pct"])
        best_apy = {"protocol": best["protocol"], "apy_pct": best["apy_pct"]}

    total_tvl = sum(
        a["tvl_usd"]
        for a in adapters
        if isinstance(a.get("tvl_usd"), (int, float))
    )

    # SPA-V398: count adapters that returned a genuine live APY (no mocks exist).
    live = [a for a in adapters if a.get("live_data")]
    adapters_with_live_apy = len(live)

    return {
        "total": len(adapters),
        "ok": len(ok),
        "partial": len(partial),
        "error": len(errored),
        "avg_health_score": overall.get("score", 0.0),
        "grade": overall.get("grade", "F"),
        "best_apy": best_apy,
        "total_tvl_usd": round(total_tvl, 2),
        "live_data": adapters_with_live_apy > 0,
        "adapters_with_live_apy": adapters_with_live_apy,
        "data_freshness": "live" if adapters_with_live_apy > 0 else "stale",
    }


# ─── Атомарная запись ──────────────────────────────────────────────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Записать JSON атомарно: tmpfile в той же директории + os.replace (rename).

    os.replace атомарен в пределах одной файловой системы — читатели всегда видят
    либо старый, либо новый файл целиком, без частично записанного состояния.
    """
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
        os.replace(tmp_name, path)
    except Exception:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        finally:
            raise


def _append_run(runs_path: Path, run_record: dict) -> None:
    """Дописать прогон в кольцевой буфер ``orchestrator_runs.json`` (последние N)."""
    runs_path = Path(runs_path)
    data: dict[str, Any] = {"runs": [], "max_runs": DEFAULT_MAX_RUNS}
    if runs_path.exists():
        try:
            loaded = json.loads(runs_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (ValueError, OSError) as exc:
            log.warning("orchestrator_runs.json unreadable (%s) — пересоздаю", exc)

    max_runs = data.get("max_runs", DEFAULT_MAX_RUNS)
    if not isinstance(max_runs, int) or max_runs <= 0:
        max_runs = DEFAULT_MAX_RUNS
    runs = data.get("runs", [])
    if not isinstance(runs, list):
        runs = []

    runs.append(run_record)
    runs = runs[-max_runs:]  # кольцевой буфер: храним только последние max_runs.
    _atomic_write_json(runs_path, {"runs": runs, "max_runs": max_runs})


# ─── Публичная точка входа ─────────────────────────────────────────────────────


def run_orchestrator(
    *,
    registry: list[tuple[str, str, type]] | None = None,
    write: bool = True,
    data_dir: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> OrchestratorResult:
    """Запустить один цикл оркестратора.

    Параметры
    ---------
    registry  : переопределяемый список (protocol_key, tier, adapter_class).
                По умолчанию — ``ADAPTER_REGISTRY``.
    write     : если True — атомарно пишет status- и runs-файлы. Если False
                (dry-run) — ничего не пишет на диск.
    data_dir  : каталог для data/*.json (по умолчанию <repo>/data).
    timeout   : пер-адаптерный таймаут (по умолчанию ADAPTER_TIMEOUT_SEC).
    now_fn    : источник текущего времени (для тестов).
    """
    reg = registry if registry is not None else ADAPTER_REGISTRY
    timeout = timeout if timeout is not None else ADAPTER_TIMEOUT_SEC
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR

    now_dt = now_fn()
    run_ts = now_dt.isoformat()
    t0 = time.monotonic()
    adapters = _collect_adapter_statuses(reg, run_ts, timeout, now_dt)
    duration = round(time.monotonic() - t0, 4)

    overall = compute_overall_health(adapters, now=now_dt)
    summary = _build_summary(adapters, overall)

    # SPA-V398: top-level liveness verdict. When NO adapter has live data the
    # whole cycle is flagged "no_live_data" (e.g. DeFiLlama unreachable) — the
    # honest signal that downstream consumers must not treat this as real yields.
    live_count = summary.get("adapters_with_live_apy", 0)
    overall_status = "ok" if live_count > 0 else "no_live_data"
    data_freshness = summary.get("data_freshness", "stale")

    result = OrchestratorResult(
        run_ts=run_ts,
        duration_sec=duration,
        adapters=adapters,
        summary=summary,
        overall_health=overall,
        status=overall_status,
        data_freshness=data_freshness,
    )

    if write:
        status_doc = {
            "generated_at": run_ts,
            "schema_version": 1,
            "source": "adapter_orchestrator",
            "execution_mode": "read_only_simulation",
            **result.to_dict(),
        }
        _atomic_write_json(ddir / STATUS_FILENAME, status_doc)
        _append_run(
            ddir / RUNS_FILENAME,
            {
                "run_ts": run_ts,
                "duration_sec": duration,
                "summary": summary,
                "overall_health": overall,
                # SPA-V398: per-run liveness audit trail.
                "status": overall_status,
                "live_data": live_count > 0,
                "adapters_with_live_apy": live_count,
                "data_freshness": data_freshness,
            },
        )

    return result


if __name__ == "__main__":  # pragma: no cover — удобный ручной запуск.
    logging.basicConfig(level=logging.INFO)
    res = run_orchestrator(write=False)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=2))
