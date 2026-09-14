"""discovery_step.py — поиск НОВЫХ протоколов шагом дневного цикла (решение владельца 19.08,
ADR-089 §6, вариант 1; карточка `agent-poisk-protokolov-shag-dnevnogo-tsikla`).

Что здесь и почему
------------------
Сканер вселенной DeFiLlama с порогами качества (`spa_core/adapter_sdk/discovery.py`:
TVL ≥ $5M, возраст ≥ 180 дней когда фид его показывает, только стейблы, полоса APY,
«не наш ещё») существовал с июня и писал бы `data/candidate_registry.json` — но его
никто не запускал (замер #283–#287, владелец: «программу, которая его делает, никто не
запускает»). У реестра при этом ДВА читателя в дневном цикле (`alpha_agent.run_alpha_scan`,
`protocol_research_agent`), которые каждый понедельник честно писали «не измерено».
Еженедельный `com.spa.source_discovery` (ADR-142) — ДРУГОЙ инструмент: резолвер pool_id
для десяти уже выбранных имён, не поиск нового (`docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md`
§2). Этот модуль — недостающий писатель, повешенный на существующий ритм.

Три исхода шага, различимые по построению (инв. #17)
---------------------------------------------------
* ``ok`` / ``degraded`` — фид опрошен, реестр ПЕРЕЗАПИСАН (кандидаты есть / честно ноль);
* ``refused`` — фид недоступен или ответил мусором: реестр НЕ трогается (прошлый замер
  остаётся с его собственной датой), причина названа. Выдуманных кандидатов ноль
  (`.claude/rules/adapters.md` — никаких fake-fallback'ов);
* ``skipped`` — прогон под pytest без инъектированного фида: цикл вызывается из набора
  сотни раз, и живой фид под тестом не опрашивается ПО ПОСТРОЕНИЮ (тот же порядок, что
  у `erc4626_rate_monitor` в Step 0-pre).

Исход шага едет в `data/candidate_discovery_status.json` — иначе отказ был бы виден только
в логе, а читатель реестра различал бы лишь «свежий / протух». Читатель обоих файлов —
секция брифинга `build_candidate_registry_section()` (ADR-142: артефакт без читателя вреден).

Границы. Read-only разведка: капитал не двигает, исполнение не гейтит, тир не назначает
(`suggested_tier` всегда «candidate»); попадание в whitelist — только ADR/владелец.
Шаг не смеет ронять цикл: любое исключение — «refused» с названной причиной.
Только stdlib. LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("spa.discovery_step")

REGISTRY_FILENAME = "candidate_registry.json"
STATUS_FILENAME = "candidate_discovery_status.json"

#: Контракт (ADR-154/158): что этот шаг ПРОИЗВОДИТ. Сверка — artifact_contract.
PRODUCES = (
    "data/candidate_registry.json",
    "data/candidate_discovery_status.json",
)

OK, DEGRADED, REFUSED, SKIPPED = "ok", "degraded", "refused", "skipped"


def coverage_slugs() -> frozenset:
    """«Это уже наше?» — канон из ДВУХ мест, а не одного.

    `discovery.covered_protocol_slugs()` знает семь файловых адаптеров и манифесты SDK;
    реестр `ADAPTER_REGISTRY` (36 имён) шире, и без него уже охваченный протокол приехал
    бы как новый кандидат (класс карточки `inbox-issledovatel-kandidatov-schitaet-chto-ak`).
    Из ключа реестра берётся первый сегмент (`fluid_usdc` → `fluid`, `aave_v3_base` →
    `aave`): сопоставление у сканера — подстрока по slug проекта DeFiLlama.
    """
    from spa_core.adapter_sdk.discovery import covered_protocol_slugs
    slugs = set(covered_protocol_slugs())
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        for entry in ADAPTER_REGISTRY:
            key = str(entry[0] if isinstance(entry, (tuple, list)) else entry).strip().lower()
            head = key.split("_", 1)[0]
            if len(head) >= 3:
                slugs.add(head)
    except Exception as exc:  # noqa: BLE001 — реестр не прочитался: покрытие УЖЕ, не пусто
        log.warning("discovery_step: ADAPTER_REGISTRY не прочитан (%s) — покрытие только по SDK", exc)
    return frozenset(slugs)


def _under_pytest() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def run_discovery_step(
    data_dir: "str | os.PathLike | None" = None,
    *,
    fetch_fn: Optional[Callable[[], list]] = None,
    now_ts: Optional[float] = None,
    gates=None,
    write: bool = True,
    under_pytest: Optional[bool] = None,
) -> dict:
    """Один шаг поиска. Возврат — словарь исхода (см. модуль); никогда не бросает.

    ``fetch_fn`` — инъекция фида (тесты и проба), ``now_ts`` — часы как вход.
    """
    from spa_core.adapter_sdk import discovery as d

    ddir = Path(data_dir) if data_dir is not None else Path(d.DEFAULT_OUTPUT_PATH).parent
    registry = ddir / REGISTRY_FILENAME
    status_path = ddir / STATUS_FILENAME
    now = float(now_ts) if now_ts is not None else time.time()
    stamp = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    out: dict = {"status": REFUSED, "reason": "", "candidates": None, "scanned_pools": None,
                 "registry_written": False, "registry": str(registry), "generated_at": stamp}

    pytest_run = _under_pytest() if under_pytest is None else bool(under_pytest)
    if fetch_fn is None and pytest_run:
        out.update(status=SKIPPED, reason="прогон под pytest: живой фид DeFiLlama не опрашивается по построению")
        return out

    try:
        report = d.run_discovery(fetch_fn=fetch_fn, gates=gates,
                                 covered_protocols=coverage_slugs(), now_ts=now)
    except Exception as exc:  # noqa: BLE001 — шаг не смеет ронять цикл
        out.update(reason=f"сканер упал: {type(exc).__name__}: {exc}")
        _write_status(status_path, out, write)
        return out

    if report.get("status") == "error":
        out.update(reason=f"фид недоступен или непригоден: {report.get('error')} — реестр не тронут, "
                          f"выдуманных кандидатов ноль")
        log.warning("discovery_step: REFUSED — %s", out["reason"])
        _write_status(status_path, out, write)
        return out

    cands = report.get("candidates") or []
    out.update(status=OK if cands else DEGRADED, candidates=len(cands),
               scanned_pools=int(report.get("scanned_pools") or 0),
               reason="" if cands else "фид опрошен, ни один пул не прошёл пороги — измеренный ноль")
    if write:
        try:
            d.write_report_atomic(report, registry)
            out["registry_written"] = True
        except OSError as exc:
            out.update(status=REFUSED, reason=f"реестр не записан: {type(exc).__name__}: {exc}")
    _write_status(status_path, out, write)
    return out


def _write_status(path: Path, out: dict, write: bool) -> None:
    if not write:
        return
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(dict(out), str(path))
    except Exception as exc:  # noqa: BLE001 — статус вторичен; отказ назван в логе
        log.warning("discovery_step: статус шага не записан (%s)", exc)
