"""Aggressive sleeve shadow composer (ADR-201) — тень 50/30/20 с рычагом пропорций CIO.

Мандат владельца 2026-08-31: слив по турниру #28 строить, и CIO обязан ПОСТОЯННО
следить за ним и периодически пересматривать пропорции — «не просто слили и забыли»
(карточка ``inbox-sliv-aggressive-cio-obyazan-kurirovat-pr``).

Тень: капитал не двигает, ничего не гейтит, никем из аллокаторов не читается
(IS_ADVISORY, инвариант #9). Ежедневная доходность = Σ вес × доходность компонента:
``pendle_pt_levered`` идёт ПОД каноническим guardian-оверлеем (замер 31.08:
19.1%DD → 7.6%DD), ``susde_dn`` — как есть, YT-слот — КЭШ (0%) до theta-модели
(турнир #10; слот назван, доходность не выдумывается).

Леджер ``data/sleeve_aggressive/ledger.jsonl`` — append-only, идемпотентен по дате
(паттерн Phase F). Дом НЕ ``data/aggressive_lab/`` — ту панель переписывает ночной
прогон, forward-трек там уже терялся.

Ревью пропорций — детерминированное (LLM запрещён), каждое — запись с decision_id;
границы ±10пп жёсткие, за ними REFUSED_OUT_OF_BOUNDS без применения. Fail-closed:
нет forward-точки компонента ⇒ день UNCHECKED, недостающая метрика ревью ⇒ HOLD.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("spa.strategy_lab.sleeve")

IS_ADVISORY = True
LEDGER_DIRNAME = "sleeve_aggressive"
LEDGER_FILENAME = "ledger.jsonl"
LEDGER_SCHEMA = "sleeve-shadow-v1"
SEED_EQUITY = 100_000.0
#: Хвост backtest-фазы как разогрев guardian-оверлея (как у guardian_forward).
GUARDIAN_WARMUP_DAYS = 60

#: Компонент-якорь: получатель веса при де-риск-сдвиге (низко-DD, ADR-201 §1.3).
ANCHOR = "susde_dn"
#: Слот, который до theta-модели честно стоит в кэше (доходность 0).
CASH_SLOT = "yt_cash_slot"


@dataclass(frozen=True)
class SleeveConfig:
    """Версионированный мандат слива (паттерн TriggerParams, Phase E).

    Числа порогов — ADR-201 §1.3; смена любого — новый ADR + bump version.
    ``guarded_backtest_dd_pct`` — ЗАМЕРЕННЫЕ guardian-просадки бэктеста
    (прогон 31.08, docs/DYNAMIC_LEVERAGE_GUARDIAN.md UPD): не выдуманы здесь.
    """
    version: str = "v1.0"
    version_date: str = "2026-08-31"
    mode: str = "shadow"
    base_weights: Dict[str, float] = field(default_factory=lambda: {
        "pendle_pt_levered": 0.50, ANCHOR: 0.30, CASH_SLOT: 0.20})
    max_drift_pp: float = 10.0          # |вес − база| ≤ ±10пп, жёстко
    review_min_hold_days: int = 7       # между ПРИМЕНЁННЫМИ сдвигами
    dd_breach_mult: float = 2.0         # trailing-DD > mult × замеренной ⇒ предложение
    shift_pp: float = 10.0              # размер одного сдвига к якорю
    trailing_window_days: int = 30
    dd_floor_pct: float = 2.0           # порог не ниже пола (2×0.1% — шум)
    guarded_backtest_dd_pct: Dict[str, float] = field(default_factory=lambda: {
        "pendle_pt_levered": 7.6, ANCHOR: 0.1})


# ── чистая математика ────────────────────────────────────────────────────────


def _max_drawdown_pct(equity: List[float]) -> Optional[float]:
    if len(equity) < 2:
        return None
    peak = equity[0]
    worst = 0.0
    for v in equity[1:]:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return round(-worst * 100.0, 4)


def compose_day(
    weights: Dict[str, float],
    component_returns: Dict[str, Optional[float]],
) -> Optional[float]:
    """Дневная доходность слива. Любой компонент с ненулевым весом без числа
    (кроме кэш-слота: его доходность 0 ПО ОПРЕДЕЛЕНИЮ) ⇒ None (UNCHECKED) —
    день не выдумывается частичной суммой."""
    total = 0.0
    for comp, w in weights.items():
        if w <= 0:
            continue
        r = 0.0 if comp == CASH_SLOT else component_returns.get(comp)
        if r is None:
            return None
        total += w * float(r)
    return total


def review_proportions(
    *,
    config: SleeveConfig,
    current_weights: Dict[str, float],
    trailing_equity: Dict[str, List[float]],
    days_since_last_applied: Optional[float],
) -> dict:
    """Детерминированное ревью CIO (ADR-201 §1.3). Возвращает решение с причиной.

    statuses: HOLD_HEALTHY · HOLD_COOLDOWN · HOLD_UNMEASURED ·
              PROPOSE_APPLIED · REFUSED_OUT_OF_BOUNDS
    """
    breaches: List[str] = []
    for comp, base_dd in config.guarded_backtest_dd_pct.items():
        if current_weights.get(comp, 0.0) <= 0:
            continue
        eq = trailing_equity.get(comp)
        if not eq or len(eq) < config.trailing_window_days:
            return {"status": "HOLD_UNMEASURED", "component": comp,
                    "reason": f"forward-история {comp}: {len(eq or [])}/"
                              f"{config.trailing_window_days}д — короче "
                              f"trailing-окна, HOLD, не угадываем"}
        dd = _max_drawdown_pct(eq[-config.trailing_window_days:])
        threshold = max(config.dd_breach_mult * base_dd, config.dd_floor_pct)
        if dd is not None and dd > threshold:
            breaches.append(comp)

    if not breaches:
        return {"status": "HOLD_HEALTHY",
                "reason": "trailing-просадки компонентов в пределах порогов"}

    if days_since_last_applied is not None \
            and days_since_last_applied < config.review_min_hold_days:
        return {"status": "HOLD_COOLDOWN", "breached": breaches,
                "reason": f"сдвиг был {days_since_last_applied:.1f}д назад "
                          f"(< {config.review_min_hold_days}д)"}

    comp = sorted(breaches)[0]  # детерминированный выбор при нескольких
    shift = config.shift_pp / 100.0
    proposed = dict(current_weights)
    proposed[comp] = round(proposed.get(comp, 0.0) - shift, 4)
    proposed[ANCHOR] = round(proposed.get(ANCHOR, 0.0) + shift, 4)

    for c, w in proposed.items():
        base = config.base_weights.get(c, 0.0)
        if abs(w - base) > config.max_drift_pp / 100.0 + 1e-9 or w < -1e-9:
            return {"status": "REFUSED_OUT_OF_BOUNDS", "component": comp,
                    "proposed": proposed,
                    "reason": f"|{c}: {w:.2f} − база {base:.2f}| > "
                              f"±{config.max_drift_pp}пп — вес НЕ меняется; "
                              f"дальше — только решением владельца"}

    return {"status": "PROPOSE_APPLIED", "component": comp,
            "old_weights": dict(current_weights), "new_weights": proposed,
            "reason": f"trailing-DD {comp} превысила "
                      f"{config.dd_breach_mult}× замеренной guardian-просадки — "
                      f"{config.shift_pp}пп к якорю {ANCHOR}"}


# ── леджер (append-only, идемпотентно по дате — паттерн Phase F) ────────────


def _ledger_path(data_dir: Path) -> Path:
    return Path(data_dir) / LEDGER_DIRNAME / LEDGER_FILENAME


def load_ledger(data_dir: Path) -> List[dict]:
    path = _ledger_path(data_dir)
    if not path.exists():
        return []
    out: List[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            continue  # нечитаемая строка не валит чтение; append её не тронет
        if isinstance(obj, dict) and obj.get("date"):
            out.append(obj)
    return sorted(out, key=lambda r: str(r.get("date")))


def append_ledger(record: dict, data_dir: Path) -> int:
    """Та же дисциплина, что Phase F: строка того же дня ЗАМЕНЯЕТСЯ, чужие —
    побайтно сохраняются (включая нечитаемые), атомарная запись."""
    from spa_core.utils.atomic import atomic_save_text
    path = _ledger_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    date = record.get("date")
    kept: List[str] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                kept.append(raw)
                continue
            if isinstance(obj, dict) and obj.get("date") == date:
                continue
            kept.append(raw)
    kept.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
    atomic_save_text("\n".join(kept) + "\n", str(path))
    return len(kept)


# ── дневной прогон тени ──────────────────────────────────────────────────────


def _guarded_daily_return(equity: List[float]) -> Optional[float]:
    """Последняя дневная доходность pendle-ноги ПОД каноническим guardian."""
    from spa_core.strategy_lab.aggressive_lab.guardian import apply_guardian_vol
    if len(equity) < 3:
        return None
    guarded = apply_guardian_vol(equity)
    if len(guarded) < 2 or not guarded[-2]:
        return None
    return guarded[-1] / guarded[-2] - 1.0


def _component_series(panel_dir: Path, sid: str) -> tuple[List[float], List[str], int]:
    """(equity разогрев+forward, forward-даты, длина bt-хвоста) из phase-aware loader'а.

    bt-хвост нужен ТОЛЬКО как разогрев guardian'а (rolling-vol lookback,
    ``_guarded_daily_return``) — backtest и forward не на одной базе капитала
    (backtest у левериджа кончается выросшим, forward стартует с сид-капитала),
    поэтому склеенный ``eq`` НЕЛЬЗЯ использовать для trailing-DD ревью:
    один день 31.08.2026 читал разрыв бэктест→форвард как 72.7% просадки при
    двух положительных доходностях в тот день (найдено в проде, UPD ниже)."""
    from spa_core.strategy_lab.aggressive_lab import loader as ld
    s = ld.load_strategy(sid, data_dir=Path(panel_dir))
    bt = [p for p in s.backtest.series if isinstance(p.get("equity_usd"), (int, float))]
    fwd = [p for p in s.forward.series if isinstance(p.get("equity_usd"), (int, float))]
    bt_tail = bt[-GUARDIAN_WARMUP_DAYS:]
    eq = [float(p["equity_usd"]) for p in bt_tail] + \
         [float(p["equity_usd"]) for p in fwd]
    dates = [str(p.get("date")) for p in fwd]
    return eq, dates, len(bt_tail)


def run_sleeve_shadow(
    *,
    data_dir: Path,
    panel_dir: Path,
    date_str: str,
    config: Optional[SleeveConfig] = None,
) -> dict:
    """Один такт тени: доходность дня + ревью пропорций + строка леджера.

    Never raises (fail-open на границе — тень не имеет права валить цикл);
    внутри — fail-closed: непосчитанное называется UNCHECKED, не выдумывается.
    """
    try:
        cfg = config or SleeveConfig()
        ledger = load_ledger(data_dir)
        last = ledger[-1] if ledger else None
        weights = dict((last or {}).get("weights") or cfg.base_weights)
        equity_prev = float((last or {}).get("equity") or SEED_EQUITY)

        comp_returns: Dict[str, Optional[float]] = {}
        trailing: Dict[str, List[float]] = {}
        for comp in cfg.guarded_backtest_dd_pct:
            eq, fwd_dates, bt_count = _component_series(Path(panel_dir), comp)
            if date_str not in fwd_dates:
                comp_returns[comp] = None   # нет forward-точки ⇒ UNCHECKED
                trailing[comp] = []
                continue
            cut = len(eq) - (len(fwd_dates) - fwd_dates.index(date_str) - 1)
            series = eq[:cut]
            if comp == "pendle_pt_levered":
                comp_returns[comp] = _guarded_daily_return(series)
            else:
                comp_returns[comp] = (series[-1] / series[-2] - 1.0
                                      if len(series) >= 2 and series[-2] else None)
            # Ревью смотрит ТОЛЬКО forward: bt-хвост — чужая база капитала,
            # склейка с ним читается как фиктивная просадка (см. docstring
            # _component_series). guardian-разогрев (comp_returns выше) —
            # отдельный, легитимный, случай использования bt-хвоста.
            trailing[comp] = series[bt_count:][-cfg.trailing_window_days:]

        days_since = None
        for rec in reversed(ledger):
            if (rec.get("review") or {}).get("status") == "PROPOSE_APPLIED":
                try:
                    from datetime import date as _d
                    days_since = (_d.fromisoformat(date_str)
                                  - _d.fromisoformat(str(rec["date"]))).days
                except ValueError:
                    days_since = None
                break

        review = review_proportions(
            config=cfg, current_weights=weights, trailing_equity=trailing,
            days_since_last_applied=days_since)
        if review["status"] == "PROPOSE_APPLIED":
            weights = review["new_weights"]

        ret = compose_day(weights, comp_returns)
        record = {
            "schema": LEDGER_SCHEMA,
            "decision_id": f"sleeve-{date_str}",
            "date": date_str,
            "policy_version": cfg.version,
            "mode": cfg.mode,
            "weights": weights,
            "component_returns": comp_returns,
            "checked": ret is not None,
            "sleeve_return": ret,
            "equity": round(equity_prev * (1.0 + ret), 2) if ret is not None else equity_prev,
            "review": review,
            "is_advisory": True,
        }
        append_ledger(record, Path(data_dir))
        return record
    except Exception as exc:  # noqa: BLE001 — тень не валит цикл
        log.warning("sleeve shadow failed (%s) — cycle unaffected", exc)
        return {"error": type(exc).__name__, "is_advisory": True}
