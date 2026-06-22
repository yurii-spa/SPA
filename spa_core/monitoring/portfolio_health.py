"""
spa_core/monitoring/portfolio_health.py
========================================
Portfolio Health v2.0 — multi-engine (A/B/C) health scoring.

Движки:
  A — Core (paper trading, основной)   вес 60%
  B — HY (high-yield, новый)           вес 25%
  C — LP (liquidity pool, новый)       вес 15%

Дополнительно: DataTrust health, BEE health.

Правила:
  fail-closed: нет данных / ошибка чтения → 0 (за исключением
               специально оговорённых: B/C без файла → 50).
  DataTrust без файлов → 100 (нет алармов = хорошо).
  BEE без safety_report → 0 (fail-closed).

LLM_FORBIDDEN: никаких AI-вызовов, только stdlib.
Запись: модуль read-only / аналитический — ничего не пишет в data/.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

__version__ = "2.0.0"

# Веса движков (должны суммироваться в 1.0)
_ENGINE_WEIGHTS: dict[str, float] = {"A": 0.60, "B": 0.25, "C": 0.15}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _PROJECT_ROOT / "data"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> tuple[object, str | None]:
    """
    Безопасная загрузка JSON.
    Возвращает (data, None) при успехе, (None, error_str) при ошибке.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, json.JSONDecodeError) as e:
        return None, str(e)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Ограничить значение в диапазоне [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Engine A — Core (paper trading)
# ---------------------------------------------------------------------------

def _score_engine_a(data_dir: Path) -> dict:
    """
    Engine A (Core): paper trading status health. Вес 60%.

    Источники:
      paper_trading_status.json — last_cycle_status, kill_switch, adapters, risk_policy
      equity_curve_daily.json  — max_drawdown_pct

    fail-closed: любая ошибка чтения или критический флаг → score=0.
    """
    # LLM_FORBIDDEN
    try:
        status_path = data_dir / "paper_trading_status.json"
        if not status_path.exists():
            return {
                "engine": "A",
                "score": 0,
                "status": "error",
                "details": {"reason": "paper_trading_status.json not found (fail-closed)"},
            }

        status, err = _load_json(status_path)
        if err or not isinstance(status, dict):
            return {
                "engine": "A",
                "score": 0,
                "status": "error",
                "details": {"reason": f"read error: {err} (fail-closed)"},
            }

        # Немедленные fail-closed проверки
        if status.get("kill_switch_active", True):
            return {
                "engine": "A",
                "score": 0,
                "status": "error",
                "details": {"reason": "kill_switch_active=True (fail-closed)"},
            }

        if status.get("is_demo", True):
            return {
                "engine": "A",
                "score": 0,
                "status": "error",
                "details": {"reason": "is_demo=True (fail-closed)"},
            }

        if status.get("last_cycle_status", "error") != "ok":
            return {
                "engine": "A",
                "score": 0,
                "status": "error",
                "details": {
                    "reason": (
                        f"last_cycle_status={status.get('last_cycle_status')!r} (fail-closed)"
                    )
                },
            }

        # Базовый score 100 — вычитаем штрафы
        score = 100.0
        reasons: list[str] = []

        # -20: risk policy не одобрена
        if not status.get("risk_policy_approved", False):
            score -= 20.0
            reasons.append("risk_policy_not_approved")

        # Drawdown из equity_curve_daily.json (при наличии)
        equity_path = data_dir / "equity_curve_daily.json"
        max_dd = 0.0
        if equity_path.exists():
            curve, curve_err = _load_json(equity_path)
            if not curve_err and isinstance(curve, dict):
                raw_dd = curve.get("summary", {}).get("max_drawdown_pct", 0.0)
                max_dd = raw_dd if isinstance(raw_dd, (int, float)) else 0.0

        if max_dd < -5.0:
            # Ниже kill-switch порога по drawdown → score=0
            score = 0.0
            reasons.append(
                f"max_drawdown={max_dd:.2f}% (<=-5%%, kill-switch threshold)"
            )
        elif max_dd < -3.0:
            score -= 20.0
            reasons.append(f"max_drawdown={max_dd:.2f}%")
        elif max_dd < -1.0:
            score -= 10.0
            reasons.append(f"max_drawdown={max_dd:.2f}%")

        # -15: нет живых адаптеров
        num_adapters = status.get("num_adapters_live", 0) or 0
        if num_adapters == 0:
            score -= 15.0
            reasons.append("num_adapters_live=0")

        score = _clamp(score)
        status_label = "ok" if score >= 80 else ("degraded" if score >= 40 else "error")

        return {
            "engine": "A",
            "score": round(score, 2),
            "status": status_label,
            "details": {
                "last_cycle_status": status.get("last_cycle_status"),
                "kill_switch_active": status.get("kill_switch_active"),
                "risk_policy_approved": status.get("risk_policy_approved"),
                "num_adapters_live": num_adapters,
                "max_drawdown_pct": max_dd,
                "current_equity": status.get("current_equity"),
                "is_demo": status.get("is_demo"),
                "reasons": reasons,
            },
        }

    except Exception as e:  # pylint: disable=broad-except
        return {
            "engine": "A",
            "score": 0,
            "status": "error",
            "details": {"reason": f"exception: {e} (fail-closed)"},
        }


# ---------------------------------------------------------------------------
# Engine B — HY (High Yield)
# ---------------------------------------------------------------------------

def _is_engine_stub(data: dict) -> bool:
    """
    True если файл движка — seed/stub без реальных данных.
    Признаки: cycles_completed==0 ИЛИ equity==0.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    cycles = data.get("cycles_completed", 0) or 0
    equity = data.get("equity", 0.0) or 0.0
    return cycles == 0 or equity == 0.0


def _score_engine_b(data_dir: Path) -> dict:
    """
    Engine B (HY — High Yield): reads data/hy_paper_trading.json.

    Если файл не найден → score=50 (движок не развёрнут, нейтральный).
    Если файл есть, но это stub (cycles_completed==0 или equity==0) → score=50.
    Если файл есть, но читать нельзя → score=0 (fail-closed).
    """
    # LLM_FORBIDDEN
    try:
        hy_path = data_dir / "hy_paper_trading.json"
        if not hy_path.exists():
            return {
                "engine": "B",
                "score": 50,
                "status": "not_deployed",
                "details": {
                    "reason": (
                        "hy_paper_trading.json not found; engine not deployed → neutral 50"
                    )
                },
            }

        data, err = _load_json(hy_path)
        if err or not isinstance(data, dict):
            return {
                "engine": "B",
                "score": 0,
                "status": "error",
                "details": {"reason": f"read error: {err} (fail-closed)"},
            }

        # Stub-файл: движок ещё не запускался → нейтральный 50
        if _is_engine_stub(data):
            return {
                "engine": "B",
                "score": 50,
                "status": "not_deployed",
                "details": {
                    "reason": (
                        "hy_paper_trading.json is a stub "
                        f"(cycles_completed={data.get('cycles_completed', 0)}, "
                        f"equity={data.get('equity', 0)}); "
                        "engine not yet running → neutral 50"
                    ),
                    "cycles_completed": data.get("cycles_completed", 0),
                },
            }

        return _score_engine_hy_lp("B", data)

    except Exception as e:  # pylint: disable=broad-except
        return {
            "engine": "B",
            "score": 0,
            "status": "error",
            "details": {"reason": f"exception: {e} (fail-closed)"},
        }


# ---------------------------------------------------------------------------
# Engine C — LP (Liquidity Pool)
# ---------------------------------------------------------------------------

def _score_engine_c(data_dir: Path) -> dict:
    """
    Engine C (LP — Liquidity Pool): reads data/lp_paper_trading.json.

    Если файл не найден → score=50 (движок не развёрнут, нейтральный).
    Если файл есть, но это stub (cycles_completed==0 или equity==0) → score=50.
    Если файл есть, но читать нельзя → score=0 (fail-closed).
    """
    # LLM_FORBIDDEN
    try:
        lp_path = data_dir / "lp_paper_trading.json"
        if not lp_path.exists():
            return {
                "engine": "C",
                "score": 50,
                "status": "not_deployed",
                "details": {
                    "reason": (
                        "lp_paper_trading.json not found; engine not deployed → neutral 50"
                    )
                },
            }

        data, err = _load_json(lp_path)
        if err or not isinstance(data, dict):
            return {
                "engine": "C",
                "score": 0,
                "status": "error",
                "details": {"reason": f"read error: {err} (fail-closed)"},
            }

        # Stub-файл: движок ещё не запускался → нейтральный 50
        if _is_engine_stub(data):
            return {
                "engine": "C",
                "score": 50,
                "status": "not_deployed",
                "details": {
                    "reason": (
                        "lp_paper_trading.json is a stub "
                        f"(cycles_completed={data.get('cycles_completed', 0)}, "
                        f"equity={data.get('equity', 0)}); "
                        "engine not yet running → neutral 50"
                    ),
                    "cycles_completed": data.get("cycles_completed", 0),
                },
            }

        return _score_engine_hy_lp("C", data)

    except Exception as e:  # pylint: disable=broad-except
        return {
            "engine": "C",
            "score": 0,
            "status": "error",
            "details": {"reason": f"exception: {e} (fail-closed)"},
        }


def _score_engine_hy_lp(engine: str, data: dict) -> dict:
    """
    Общий scorer для B и C на основе словаря их статуса.
    Ожидаемые поля: kill_switch_active, is_demo, last_cycle_status, max_drawdown_pct.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    if data.get("kill_switch_active", False):
        return {
            "engine": engine,
            "score": 0,
            "status": "error",
            "details": {"reason": "kill_switch_active=True (fail-closed)"},
        }

    score = 100.0
    reasons: list[str] = []

    if data.get("is_demo", False):
        score -= 30.0
        reasons.append("is_demo=True")

    if data.get("last_cycle_status", "ok") != "ok":
        score -= 30.0
        reasons.append(f"last_cycle_status={data.get('last_cycle_status')!r}")

    max_dd = data.get("max_drawdown_pct", 0.0) or 0.0
    if max_dd < -5.0:
        score = 0.0
        reasons.append(f"max_drawdown={max_dd:.2f}%")
    elif max_dd < -3.0:
        score -= 20.0
        reasons.append(f"max_drawdown={max_dd:.2f}%")
    elif max_dd < -1.0:
        score -= 10.0
        reasons.append(f"max_drawdown={max_dd:.2f}%")

    score = _clamp(score)
    status_label = "ok" if score >= 80 else ("degraded" if score >= 40 else "error")

    return {
        "engine": engine,
        "score": round(score, 2),
        "status": status_label,
        "details": {
            "last_cycle_status": data.get("last_cycle_status"),
            "max_drawdown_pct": max_dd,
            "current_equity": data.get("current_equity"),
            "reasons": reasons,
        },
    }


# ---------------------------------------------------------------------------
# Public API — get_engine_health
# ---------------------------------------------------------------------------

def get_engine_health(engine: str, *, data_dir: Path | None = None) -> dict:
    """
    Вернуть health dict для движка A, B или C.

    Returns:
        {
            "engine": str,
            "score": float (0–100),
            "status": str,     # "ok" | "degraded" | "error" | "not_deployed"
            "details": dict,
        }

    fail-closed:
      - неизвестный движок → score=0
      - ошибка чтения файла → score=0
      - B/C без файла (не развёрнут) → score=50 (исключение)
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _dir = data_dir or _DATA_DIR

    _dispatch = {
        "A": _score_engine_a,
        "B": _score_engine_b,
        "C": _score_engine_c,
    }

    if engine not in _dispatch:
        return {
            "engine": engine,
            "score": 0,
            "status": "error",
            "details": {"reason": f"unknown engine {engine!r} (fail-closed)"},
        }

    return _dispatch[engine](_dir)


# ---------------------------------------------------------------------------
# DataTrust health
# ---------------------------------------------------------------------------

def get_datatrust_health(*, data_dir: Path | None = None) -> dict:
    """
    Health DataTrust подсистемы.

    Источники:
      data/circuit_breaker_state.json — OPEN → 0; HALF_OPEN → 50; CLOSED → 100
      data/datatrust_alarm_log.json   — CRITICAL алармы за последние 24ч → 0

    Если файлов нет → score=100 (нет алармов = хорошо).
    fail-closed: OPEN circuit или критические алармы → 0.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _dir = data_dir or _DATA_DIR
    try:
        score = 100.0
        reasons: list[str] = []
        cb_state: str | None = None
        critical_alarms_24h = 0

        # 1. Circuit breaker state
        cb_path = _dir / "circuit_breaker_state.json"
        if cb_path.exists():
            cb_data, err = _load_json(cb_path)
            if err or not isinstance(cb_data, dict):
                # Не можем прочитать CB state → fail-closed
                return {
                    "score": 0,
                    "status": "error",
                    "details": {
                        "reason": (
                            f"circuit_breaker_state.json read error: {err} (fail-closed)"
                        )
                    },
                }

            cb_state = cb_data.get("state", "OPEN")
            if cb_state == "OPEN":
                return {
                    "score": 0,
                    "status": "error",
                    "details": {
                        "reason": "circuit_breaker=OPEN (fail-closed)",
                        "circuit_breaker_state": cb_state,
                    },
                }
            if cb_state == "HALF_OPEN":
                score = min(score, 50.0)
                reasons.append("circuit_breaker=HALF_OPEN")
            # CLOSED → no penalty

        # 2. Alarm log — CRITICAL за последние 24 часов
        alarm_path = _dir / "datatrust_alarm_log.json"
        if alarm_path.exists():
            alarm_data, err = _load_json(alarm_path)
            if not err:
                alarms: list = []
                if isinstance(alarm_data, list):
                    alarms = alarm_data
                elif isinstance(alarm_data, dict):
                    alarms = alarm_data.get("alarms", [])

                now_utc = datetime.now(timezone.utc)
                cutoff = now_utc - timedelta(hours=24)

                for alarm in alarms:
                    if not isinstance(alarm, dict):
                        continue
                    level = str(alarm.get("level", "")).lower()
                    if level != "critical":
                        continue
                    created_raw = alarm.get("created_at", "")
                    try:
                        ts = datetime.fromisoformat(
                            str(created_raw).replace("Z", "+00:00")
                        )
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        if ts >= cutoff:
                            critical_alarms_24h += 1
                    except (ValueError, AttributeError, TypeError):
                        # Не можем распарсить дату → считаем свежим (fail-closed)
                        critical_alarms_24h += 1

                if critical_alarms_24h > 0:
                    return {
                        "score": 0,
                        "status": "error",
                        "details": {
                            "reason": (
                                f"{critical_alarms_24h} CRITICAL alarm(s) in last 24h"
                                " (fail-closed)"
                            ),
                            "critical_alarms_24h": critical_alarms_24h,
                            "circuit_breaker_state": cb_state,
                        },
                    }

        score = _clamp(score)
        status_label = "ok" if score >= 80 else ("degraded" if score >= 40 else "error")

        return {
            "score": round(score, 2),
            "status": status_label,
            "details": {
                "circuit_breaker_state": cb_state,
                "critical_alarms_24h": critical_alarms_24h,
                "alarm_log_exists": alarm_path.exists() if alarm_path else False,
                "circuit_breaker_exists": cb_path.exists() if cb_path else False,
                "reasons": reasons,
            },
        }

    except Exception as e:  # pylint: disable=broad-except
        return {
            "score": 0,
            "status": "error",
            "details": {"reason": f"exception: {e} (fail-closed)"},
        }


# ---------------------------------------------------------------------------
# BEE health
# ---------------------------------------------------------------------------

def get_bee_health(*, data_dir: Path | None = None) -> dict:
    """
    Health BEE (Backward Error Evaluation / counterfactual) подсистемы.

    Источники:
      data/bee/safety_report.json       — events_where_gate_triggered / total_events_analyzed
      data/bee/backtest_live_fit.json   — fit_80pct_ci.verdict == "in_distribution" → +10

    Формула:
      base = (events_where_gate_triggered / total_events_analyzed) * 100
      penalty = min(false_positives * 5, 20)
      bonus = +10 если verdict == "in_distribution" (но не выше 100)
      score = clamp(base - penalty + bonus, 0, 100)

    fail-closed: нет safety_report.json → score=0.
    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _dir = data_dir or _DATA_DIR
    bee_dir = _dir / "bee"

    try:
        safety_path = bee_dir / "safety_report.json"

        # fail-closed: нет safety_report → 0
        if not safety_path.exists():
            return {
                "score": 0,
                "status": "error",
                "details": {"reason": "safety_report.json not found (fail-closed)"},
            }

        safety, err = _load_json(safety_path)
        if err or not isinstance(safety, dict):
            return {
                "score": 0,
                "status": "error",
                "details": {"reason": f"safety_report.json error: {err} (fail-closed)"},
            }

        total_events = safety.get("total_events_analyzed", 0) or 0
        gate_triggered = safety.get("events_where_gate_triggered", 0) or 0
        false_positives = safety.get("false_positives", 0) or 0

        # fail-closed: нет событий → нет данных для оценки
        if total_events == 0:
            return {
                "score": 0,
                "status": "error",
                "details": {
                    "reason": "total_events_analyzed=0 (fail-closed, no BEE data)"
                },
            }

        # Базовый score
        base_score = (gate_triggered / total_events) * 100.0
        score = base_score

        # Штраф за ложные срабатывания
        fp_penalty = min(false_positives * 5.0, 20.0)
        score -= fp_penalty

        # Бонус за fit_80pct_ci.verdict == "in_distribution"
        fit_verdict: str | None = None
        fit_path = bee_dir / "backtest_live_fit.json"
        if fit_path.exists():
            fit, fit_err = _load_json(fit_path)
            if not fit_err and isinstance(fit, dict):
                fit_80 = fit.get("fit_80pct_ci", {})
                if isinstance(fit_80, dict):
                    fit_verdict = fit_80.get("verdict")
                if fit_verdict is None:
                    fit_verdict = fit.get("verdict")
                if fit_verdict == "in_distribution":
                    score = min(100.0, score + 10.0)

        score = _clamp(score)
        status_label = "ok" if score >= 80 else ("degraded" if score >= 40 else "error")

        return {
            "score": round(score, 2),
            "status": status_label,
            "details": {
                "total_events_analyzed": total_events,
                "events_where_gate_triggered": gate_triggered,
                "false_positives": false_positives,
                "gate_success_rate": round(gate_triggered / total_events, 4),
                "fit_verdict": fit_verdict,
                "fit_bonus_applied": fit_verdict == "in_distribution",
            },
        }

    except Exception as e:  # pylint: disable=broad-except
        return {
            "score": 0,
            "status": "error",
            "details": {"reason": f"exception: {e} (fail-closed)"},
        }


# ---------------------------------------------------------------------------
# Main — run_health_check
# ---------------------------------------------------------------------------

def run_health_check(*, data_dir: Path | None = None) -> dict:
    """
    Полная проверка здоровья портфеля.

    overall_score = 60% × Engine_A + 25% × Engine_B + 15% × Engine_C

    DataTrust и BEE присутствуют в результате как информационные поля,
    не входят в overall_score.

    Returns:
        {
            "LLM_FORBIDDEN": True,
            "generated_at": str,
            "version": str,
            "engine_health": {
                "A": {"engine": "A", "score": float, "weight": 0.60, ...},
                "B": {"engine": "B", "score": float, "weight": 0.25, ...},
                "C": {"engine": "C", "score": float, "weight": 0.15, ...},
            },
            "overall_score": float,       # 60A + 25B + 15C (0–100)
            "datatrust_health": {"score": float, ...},
            "bee_health": {"score": float, ...},
            "summary_level": str,         # "OK" | "WARNING" | "CRITICAL"
        }

    LLM_FORBIDDEN.
    """
    # LLM_FORBIDDEN
    _dir = data_dir or _DATA_DIR

    # Собрать health по каждому движку
    engine_results: dict[str, dict] = {}
    for eng in ("A", "B", "C"):
        result = get_engine_health(eng, data_dir=_dir)
        result["weight"] = _ENGINE_WEIGHTS[eng]
        engine_results[eng] = result

    # Взвешенный overall score: 60A + 25B + 15C
    overall_score = sum(
        engine_results[eng]["score"] * _ENGINE_WEIGHTS[eng]
        for eng in ("A", "B", "C")
    )
    overall_score = round(_clamp(overall_score), 2)

    # DataTrust и BEE health
    datatrust = get_datatrust_health(data_dir=_dir)
    bee = get_bee_health(data_dir=_dir)

    # Summary level
    if overall_score >= 80:
        level = "OK"
    elif overall_score >= 50:
        level = "WARNING"
    else:
        level = "CRITICAL"

    return {
        "LLM_FORBIDDEN": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": __version__,
        "engine_health": engine_results,
        "overall_score": overall_score,
        "datatrust_health": datatrust,
        "bee_health": bee,
        "summary_level": level,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    result = run_health_check()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    _sys.exit(0 if result["summary_level"] == "OK" else 1)
