"""CEO Agent v2 — стратегические решения недельного горизонта (SPA-V422 / MP-302).

ВАЖНО: это НЕ легаси ``ceo_agent.py`` (M4 message-bus координатор, который
использует ``orchestrator/graph.py`` — он не тронут). Это новый агент Phase 3
поверх agent runtime v1 (MP-301): запускается ТОЛЬКО через
:meth:`AgentRuntime.run_agent` с письменным мандатом ``ceo``
(``spa_core/agent_runtime/mandates/ceo.json``) — бюджет, forbidden-list и
деградация применяются guard'ом, обходов нет.

Что делает (KANBAN MP-302)
==========================
* Триггеры: **weekly** (>=7 дней с последней записи в
  ``data/ceo_decisions.json``) ИЛИ **drawdown >2%** от пика equity —
  :func:`should_run` чистая, ``now`` инжектируется.
* Контекст: читает РЕАЛЬНЫЕ файлы ``data/`` (``equity_curve_daily.json``,
  ``strategy_comparison.json``, ``regime_segmentation.json``); отсутствие или
  битость файла — честная пометка в контексте, НЕ падение.
* Решение: :class:`CeoDecision` (ts, snapshot_id, trigger,
  decision ∈ {keep_strategy, recommend_strategy_change, escalate}, reasoning,
  inputs_digest). Без LLM (``llm=None``) — детерминированная эвристика
  (drawdown >2% → escalate, иначе keep_strategy) с пометкой
  ``[degraded=true]`` в reasoning. С LLM — reasoning от callable, но decision
  ВАЛИДИРУЕТСЯ по enum: невалидный/битый ответ LLM → fallback на
  детерминистику.
* Лог: append в ``data/ceo_decisions.json`` (единственный allowed_output
  мандата) — атомарно (tmp + ``os.replace``), ротация последних
  :data:`DECISIONS_MAX_ENTRIES` записей.

КОНСТИТУЦИЯ (SPA-BL-011 / llm_forbidden_lint): LLM SDK здесь НЕ
импортируются — LLM-клиент инжектируется снаружи как callable (дефолт None).
CEO ничего не меняет: ни policy, ни whitelist, ни risk-limits, ни сделок —
только пишет решение в свой файл. Pure stdlib, без сети.

CLI (офлайн, без LLM)::

    python3 -m spa_core.agents.ceo_agent_v2 --check   # should_run + контекст
    python3 -m spa_core.agents.ceo_agent_v2 --run     # детерминированный прогон
    python3 -m spa_core.agents.ceo_agent_v2 --run --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from spa_core.agent_runtime import AgentRuntime
from spa_core.agent_runtime.budget import _atomic_write_json

log = logging.getLogger("spa.agents.ceo_agent_v2")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
DEFAULT_DECISIONS_PATH = DEFAULT_DATA_DIR / "ceo_decisions.json"

SCHEMA_VERSION = 1
AGENT_NAME = "ceo"

# Входные файлы контекста (реальные имена в data/ этого репо).
INPUT_FILES: Dict[str, str] = {
    "equity": "equity_curve_daily.json",
    "strategy_comparison": "strategy_comparison.json",
    "regime": "regime_segmentation.json",
}

# Enum решений CEO (KANBAN MP-302). Всё вне списка — невалидно.
VALID_DECISIONS: Tuple[str, ...] = (
    "keep_strategy",
    "recommend_strategy_change",
    "escalate",
)

TRIGGER_WEEKLY = "weekly"
TRIGGER_DRAWDOWN = "drawdown"
TRIGGER_FORCED = "forced"

WEEKLY_PERIOD_DAYS = 7
DRAWDOWN_TRIGGER_PCT = 2.0       # drawdown > 2% от пика equity → внеочередной запуск
DECISIONS_MAX_ENTRIES = 500      # ротация ceo_decisions.json
STATUS_NOT_DUE = "not_due"       # run_ceo: триггеры не сработали, агент не запускался
_MAX_REASONING_LEN = 4000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Чистое аналитическое ядро ───────────────────────────────────────────────


def compute_drawdown_pct(equity_points: List[float]) -> Optional[float]:
    """Текущий drawdown (%) от глобального пика до ПОСЛЕДНЕЙ точки. Pure.

    Пустой/невалидный ряд → None (нет данных — нет drawdown-триггера).
    Нечисловые точки пропускаются молча (битый ряд не валит агента).
    """
    points = [float(p) for p in (equity_points or [])
              if isinstance(p, (int, float)) and not isinstance(p, bool)]
    if not points:
        return None
    peak = max(points)
    if peak <= 0:
        return None
    last = points[-1]
    return max(0.0, (peak - last) / peak * 100.0)


def should_run(
    context: Dict[str, Any],
    decisions: List[Dict[str, Any]],
    now: datetime,
) -> Tuple[bool, Optional[str]]:
    """Надо ли запускать CEO. Чистая функция, ``now`` инжектируется.

    Приоритет триггеров: **drawdown** (>2% от пика — внеочередной запуск,
    даже если недели не прошло) → **weekly** (нет ни одной записи в
    ceo_decisions.json, битый ts последней записи, либо прошло >=7 дней).
    """
    dd = context.get("drawdown_pct")
    if isinstance(dd, (int, float)) and not isinstance(dd, bool) \
            and dd > DRAWDOWN_TRIGGER_PCT:
        return True, TRIGGER_DRAWDOWN

    last_ts: Optional[datetime] = None
    if decisions:
        raw_ts = decisions[-1].get("ts") if isinstance(decisions[-1], dict) else None
        if isinstance(raw_ts, str):
            try:
                last_ts = datetime.fromisoformat(raw_ts)
            except ValueError:
                last_ts = None
        if last_ts is not None and last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=timezone.utc)

    if last_ts is None:
        return True, TRIGGER_WEEKLY  # ни одного решения (или битый ts) — пора
    if now - last_ts >= timedelta(days=WEEKLY_PERIOD_DAYS):
        return True, TRIGGER_WEEKLY
    return False, None


# ─── Сбор контекста из data/ (read-only) ─────────────────────────────────────


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _equity_summary(raw: Any) -> Tuple[Dict[str, Any], List[float]]:
    """Компактная сводка equity_curve_daily + ряд точек equity."""
    points: List[float] = []
    summary: Dict[str, Any] = {}
    if isinstance(raw, dict):
        summary["generated_at"] = raw.get("generated_at")
        daily = raw.get("daily")
        if isinstance(daily, list):
            for row in daily:
                if not isinstance(row, dict):
                    continue
                value = row.get("equity", row.get("close_equity"))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    points.append(float(value))
        summary["num_days"] = len(points)
        if points:
            summary["last_equity"] = points[-1]
            summary["peak_equity"] = max(points)
    return summary, points


def _strategy_summary(raw: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if isinstance(raw, dict):
        summary["generated_at"] = raw.get("generated_at")
        strategies = raw.get("strategies")
        if isinstance(strategies, dict):
            summary["strategies"] = {
                name: (st.get("total_return_pct") if isinstance(st, dict) else None)
                for name, st in strategies.items()
            }
    return summary


def _regime_summary(raw: Any) -> Dict[str, Any]:
    summary: Dict[str, Any] = {}
    if isinstance(raw, dict):
        summary["generated_at"] = raw.get("generated_at")
        seg = raw.get("segmentation")
        if isinstance(seg, dict):
            summary["num_segments"] = seg.get("num_segments")
            segments = seg.get("segments")
            if isinstance(segments, list) and segments and isinstance(segments[-1], dict):
                last = segments[-1]
                summary["last_segment"] = {
                    "direction": last.get("direction"),
                    "return_pct": last.get("return_pct"),
                    "end_date": last.get("end_date"),
                }
    return summary


def gather_context(data_dir: Union[str, Path] = DEFAULT_DATA_DIR) -> Dict[str, Any]:
    """Собрать контекст CEO из РЕАЛЬНЫХ файлов data/. Read-only, не падает.

    Отсутствующий/битый файл → честная пометка в ``context["missing"]``,
    соответствующий вход — None. Возвращает также ``drawdown_pct`` (по ряду
    equity), детерминированные ``snapshot_id`` и ``inputs_digest``.
    """
    root = Path(data_dir)
    inputs: Dict[str, Any] = {}
    missing: List[str] = []
    equity_points: List[float] = []

    for key, filename in INPUT_FILES.items():
        path = root / filename
        if not path.is_file():
            inputs[key] = None
            missing.append(f"{key}: файл {filename} не найден")
            continue
        try:
            raw = _load_json(path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            inputs[key] = None
            missing.append(f"{key}: {filename} не читается ({type(exc).__name__}: {exc})")
            continue
        if key == "equity":
            inputs[key], equity_points = _equity_summary(raw)
        elif key == "strategy_comparison":
            inputs[key] = _strategy_summary(raw)
        else:
            inputs[key] = _regime_summary(raw)

    drawdown_pct = compute_drawdown_pct(equity_points)

    digest_payload = json.dumps(
        {"inputs": inputs, "missing": missing, "drawdown_pct": drawdown_pct},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    digest = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()

    return {
        "generated_at": _utc_now().isoformat(),
        "data_dir": str(root),
        "inputs": inputs,
        "missing": missing,
        "drawdown_pct": drawdown_pct,
        "snapshot_id": f"snap-{digest[:12]}",
        "inputs_digest": digest[:16],
    }


# ─── Решение ─────────────────────────────────────────────────────────────────


@dataclass
class CeoDecision:
    """Одно решение CEO — ровно то, что пишется в data/ceo_decisions.json."""

    ts: str
    snapshot_id: str
    trigger: str
    decision: str          # ∈ VALID_DECISIONS (валидируется в decide())
    reasoning: str
    inputs_digest: str
    degraded: bool = False  # True — решение принято без LLM (детерминистика)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schema_version"] = SCHEMA_VERSION
        return d


def _deterministic_decision(
    context: Dict[str, Any], note: str = ""
) -> Tuple[str, str]:
    """Детерминированная эвристика-заглушка (llm=None / fallback). Pure."""
    dd = context.get("drawdown_pct")
    prefix = "[degraded=true] " + (f"{note} " if note else "")
    if isinstance(dd, (int, float)) and not isinstance(dd, bool) \
            and dd > DRAWDOWN_TRIGGER_PCT:
        return "escalate", (
            f"{prefix}Детерминированная эвристика: drawdown {dd:.2f}% > "
            f"{DRAWDOWN_TRIGGER_PCT}% от пика equity — эскалация к человеку."
        )
    dd_text = f"{dd:.2f}%" if isinstance(dd, (int, float)) and not isinstance(dd, bool) \
        else "нет данных"
    extra = f" Отсутствуют входы: {'; '.join(context.get('missing', []))}." \
        if context.get("missing") else ""
    return "keep_strategy", (
        f"{prefix}Детерминированная эвристика: drawdown ({dd_text}) в пределах "
        f"{DRAWDOWN_TRIGGER_PCT}% — держим текущую стратегию.{extra}"
    )


def build_prompt(context: Dict[str, Any], trigger: str) -> str:
    """Промпт для инжектированного LLM-callable (текст, без SDK)."""
    return (
        "Ты — CEO Agent DeFi yield-оптимизатора SPA. Триггер запуска: "
        f"{trigger}. Контекст (equity / strategy_comparison / regime):\n"
        + json.dumps(context, ensure_ascii=False, indent=2, default=str)
        + "\n\nВыбери РОВНО одно решение из "
        + json.dumps(list(VALID_DECISIONS))
        + " и ответь СТРОГО JSON-объектом: "
        '{"decision": "<...>", "reasoning": "<краткое обоснование>"}. '
        "Ты только советуешь: policy, whitelist, risk-limits и транзакции "
        "вне твоего мандата."
    )


def _parse_llm_response(resp: Any) -> Optional[Tuple[str, str]]:
    """Распарсить и ПРОВАЛИДИРОВАТЬ ответ LLM. Невалидно → None (fallback)."""
    obj = resp
    if isinstance(resp, str):
        try:
            obj = json.loads(resp)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(obj, dict):
        return None
    decision = obj.get("decision")
    if decision not in VALID_DECISIONS:
        return None
    reasoning = obj.get("reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        reasoning = f"LLM выбрал {decision} (reasoning не предоставлен)"
    return decision, reasoning.strip()[:_MAX_REASONING_LEN]


def decide(
    context: Dict[str, Any],
    trigger: str,
    llm: Optional[Callable[..., Any]] = None,
    now_fn: Callable[[], datetime] = _utc_now,
) -> CeoDecision:
    """Принять решение CEO по контексту.

    ``llm=None`` (офлайн/деградация) → детерминированная эвристика с пометкой
    ``[degraded=true]``. С LLM — decision валидируется по
    :data:`VALID_DECISIONS`; исключение LLM или невалидный ответ →
    детерминированный fallback (честная пометка причины в reasoning).
    """
    degraded = True
    if llm is None:
        decision, reasoning = _deterministic_decision(context)
    else:
        try:
            resp = llm(build_prompt(context, trigger))
        except Exception as exc:  # битый клиент == отсутствующий клиент
            log.warning("ceo llm callable raised %s — deterministic fallback", exc)
            decision, reasoning = _deterministic_decision(
                context, note=f"(LLM упал: {type(exc).__name__} — fallback)"
            )
        else:
            parsed = _parse_llm_response(resp)
            if parsed is None:
                decision, reasoning = _deterministic_decision(
                    context, note="(ответ LLM не прошёл валидацию enum — fallback)"
                )
            else:
                decision, reasoning = parsed
                degraded = False

    return CeoDecision(
        ts=now_fn().isoformat(),
        snapshot_id=str(context.get("snapshot_id", "snap-unknown")),
        trigger=trigger,
        decision=decision,
        reasoning=reasoning,
        inputs_digest=str(context.get("inputs_digest", "")),
        degraded=degraded,
    )


# ─── Журнал решений (атомарно, ротация) ──────────────────────────────────────


def load_decisions(path: Union[str, Path] = DEFAULT_DECISIONS_PATH) -> List[Dict[str, Any]]:
    """Прочитать список решений. Битый/отсутствующий файл → []. Терпит и
    обёртку ``{"decisions": [...]}``, и голый JSON-список."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if isinstance(raw, dict) and isinstance(raw.get("decisions"), list):
        return [d for d in raw["decisions"] if isinstance(d, dict)]
    if isinstance(raw, list):
        return [d for d in raw if isinstance(d, dict)]
    return []


def append_decision(
    decision: Dict[str, Any],
    path: Union[str, Path] = DEFAULT_DECISIONS_PATH,
) -> List[Dict[str, Any]]:
    """Append решения в журнал: атомарно (tmp+os.replace), ротация последних
    :data:`DECISIONS_MAX_ENTRIES`. Возвращает итоговый список."""
    decisions = load_decisions(path)
    decisions.append(decision)
    decisions = decisions[-DECISIONS_MAX_ENTRIES:]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": _utc_now().isoformat(),
        "max_entries": DECISIONS_MAX_ENTRIES,
        "decisions": decisions,
    }
    _atomic_write_json(payload, Path(path))
    return decisions


# ─── Запуск ТОЛЬКО через AgentRuntime (мандат ceo) ───────────────────────────


def run_ceo(
    runtime: AgentRuntime,
    data_dir: Union[str, Path] = DEFAULT_DATA_DIR,
    decisions_path: Union[str, Path] = DEFAULT_DECISIONS_PATH,
    now_fn: Callable[[], datetime] = _utc_now,
    force: bool = False,
    tokens: int = 0,
) -> Dict[str, Any]:
    """Один цикл CEO через guard :meth:`AgentRuntime.run_agent` (мандат
    ``ceo``): бюджет/деградация/журнал runtime — НИКАКИХ обходов.

    Триггеры не сработали и ``force=False`` → ``status=not_due``, агент не
    запускается и токены не списываются. Решение пишется в
    ``decisions_path`` (дефолт — единственный allowed_output мандата).
    """
    context = gather_context(data_dir)
    decisions = load_decisions(decisions_path)
    due, trigger = should_run(context, decisions, now=now_fn())
    if not due:
        if not force:
            return {
                "agent": AGENT_NAME,
                "status": STATUS_NOT_DUE,
                "result": None,
                "reason": "триггеры weekly/drawdown не сработали (см. --force)",
                "trigger": None,
                "ts": now_fn().isoformat(),
            }
        trigger = TRIGGER_FORCED

    def _fn(llm: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
        decision = decide(context, trigger, llm=llm, now_fn=now_fn)
        append_decision(decision.to_dict(), decisions_path)
        return decision.to_dict()

    result = runtime.run_agent(AGENT_NAME, _fn, tokens=tokens)
    result["trigger"] = trigger
    return result


def _offline_runtime() -> AgentRuntime:
    """Runtime для офлайн-CLI: LLM-клиента НЕТ (llm=None), но probe возвращает
    True — guard не уходит в skip и вызывает агента с ``llm=None``, т.е.
    детерминированную эвристику. Бюджет/мандат/журнал runtime работают штатно;
    это явная операторская команда, а не плановый запуск оркестратора."""
    return AgentRuntime(llm=None, llm_probe=lambda: True)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m spa_core.agents.ceo_agent_v2",
        description="CEO Agent v2 (MP-302): weekly/drawdown триггеры, "
                    "решения в data/ceo_decisions.json. Офлайн, без LLM.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="показать should_run и собранный контекст")
    mode.add_argument("--run", action="store_true",
                      help="офлайн-прогон (детерминистика, llm=None) через AgentRuntime")
    parser.add_argument("--force", action="store_true",
                        help="с --run: запустить, даже если триггеры не сработали")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                        help="директория с входными файлами (default: data/)")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS_PATH),
                        help="путь журнала решений (default: data/ceo_decisions.json)")
    args = parser.parse_args(argv)

    if args.check:
        context = gather_context(args.data_dir)
        decisions = load_decisions(args.decisions)
        due, trigger = should_run(context, decisions, now=_utc_now())
        print(json.dumps(
            {"should_run": due, "trigger": trigger,
             "decisions_logged": len(decisions), "context": context},
            ensure_ascii=False, indent=2, default=str,
        ))
        return 0

    result = run_ceo(
        _offline_runtime(),
        data_dir=args.data_dir,
        decisions_path=args.decisions,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
