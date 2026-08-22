"""Protection Lab — нормализованная схема кризисного сценария + загрузка/валидация.

# LLM_FORBIDDEN

Сценарий состоит из двух частей:

1. **Датасет** (факты): id, окно UTC, таймлайн с флагом ``observed``
   (наблюдаемый факт с источником / вывод-приближение), рыночный удар,
   стейблкоины, DeFi-эффекты, причины, цепочка заражения, источники,
   ``confidence_notes``. Числа без источника в датасете запрещены —
   валидатор требует непустые ``sources`` и помечает недоказанное.

2. **Replay-спека** (машинная часть, опциональна): длительность в днях и
   список шоков, из которых движок детерминированно разворачивает состояние
   рынка на каждый день. Допущения маппинга (например, «morpho_steakhouse
   в 2022 не существовал — применяем канал yearn-vault impairment»)
   обязаны быть перечислены в ``assumptions`` — молчаливых прокси нет.

Виды шоков (``Shock.kind``):
    peg          {symbol, path: [[day, price], ...]}         — кусочно-линейный путь цены
    apy          {protocol, apy_pct, from_day, to_day}        — годовая доходность в окне
    tvl          {protocol, tvl_usd, from_day, to_day}        — TVL в окне (для floor-сигнала)
    freeze       {protocol, from_day, to_day}                 — вывод НЕДОСТУПЕН (окно вкл-вкл)
    halt         {protocol, from_day, to_day}                 — freeze + доходность не начисляется
    capital_loss {protocol, day, loss_pct}                    — одноразовое обесценение принципала
    liquidity    {from_day, to_day, exit_haircut_pct, gas_cost_usd} — рыночная цена выхода

Все дни — индексы 0..duration_days-1 относительно ``start_date``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"

VALID_SHOCK_KINDS = {
    "peg", "apy", "tvl", "freeze", "halt", "capital_loss", "liquidity",
}

VALID_EVENT_CLASSES = {
    "market_crash", "stablecoin_depeg", "protocol_exploit",
    "cefi_counterparty", "liquidity_oracle_infra", "systemic_contagion",
}


@dataclass
class Shock:
    """Один шок replay-спеки. ``params`` — kind-специфичный словарь (см. модуль-док)."""

    kind: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplaySpec:
    """Машинная часть сценария: как развернуть рынок по дням."""

    duration_days: int
    start_date: str  # "YYYY-MM-DD" — историческая дата, а не wall clock
    shocks: List[Shock] = field(default_factory=list)
    # Базовые условия вне шоков: {protocol: {"apy_pct": float, "tvl_usd": float}}
    base: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # Явные допущения маппинга исторического события на сегодняшнюю книгу.
    assumptions: List[str] = field(default_factory=list)
    # protocol → символ экспозиции принципала (default USDC задаёт книга)
    exposure_symbols: Dict[str, str] = field(default_factory=dict)


@dataclass
class Scenario:
    """Нормализованный кризисный сценарий (датасет + опциональная replay-спека)."""

    id: str
    name: str
    event_class: List[str]
    window_utc: Dict[str, str]
    speed: str
    summary: str
    timeline: List[dict]
    market_impact: Dict[str, Any]
    stablecoins: List[dict]
    defi_impact: Dict[str, Any]
    causes: Dict[str, Any]
    contagion: List[str]
    recovery: Dict[str, Any]
    sources: List[dict]
    confidence_notes: str
    data_availability: Dict[str, Any] = field(default_factory=dict)
    replay: Optional[ReplaySpec] = None
    schema_version: int = SCHEMA_VERSION
    synthetic: bool = False

    @property
    def has_replay(self) -> bool:
        return self.replay is not None


# ─── Валидация ────────────────────────────────────────────────────────────────


def _err(errors: List[str], sid: str, msg: str) -> None:
    errors.append(f"{sid}: {msg}")


def validate_scenario_dict(raw: dict) -> List[str]:
    """Проверить сырой dict сценария. Возвращает список ошибок (пусто = валиден).

    Fail-CLOSED: загрузчик отказывается отдавать сценарий с ошибками —
    лучше не иметь сценария, чем молча считать по кривому.
    """
    errors: List[str] = []
    sid = str(raw.get("id", "<no-id>"))

    for key in ("id", "name", "event_class", "window_utc", "summary",
                "timeline", "causes", "sources", "confidence_notes"):
        if not raw.get(key):
            _err(errors, sid, f"обязательное поле пустое или отсутствует: {key}")

    for cls in raw.get("event_class", []):
        if cls not in VALID_EVENT_CLASSES:
            _err(errors, sid, f"неизвестный event_class: {cls}")

    # Таймлайн: отсортирован, каждая запись несёт флаг observed.
    timeline = raw.get("timeline", [])
    prev_ts = ""
    for i, entry in enumerate(timeline):
        ts = str(entry.get("ts", ""))
        if not ts:
            _err(errors, sid, f"timeline[{i}]: пустой ts")
        if "observed" not in entry:
            _err(errors, sid, f"timeline[{i}]: нет флага observed (факт или вывод?)")
        if ts and prev_ts and ts < prev_ts:
            _err(errors, sid, f"timeline[{i}]: ts {ts} раньше предыдущего {prev_ts}")
        if ts:
            prev_ts = ts

    # Источники: у реального (не синтетического) сценария их минимум 3,
    # каждый с url и указанием, ЧТО он подтверждает.
    if not raw.get("synthetic", False):
        sources = raw.get("sources", [])
        if len(sources) < 3:
            _err(errors, sid, f"историческому сценарию нужно ≥3 источников, есть {len(sources)}")
        for i, src in enumerate(sources):
            if not src.get("url"):
                _err(errors, sid, f"sources[{i}]: нет url")
            if not src.get("supports"):
                _err(errors, sid, f"sources[{i}]: не указано, что подтверждает (supports)")

    # Арифметика драдаунов: где есть from/to/pct — проверяем согласованность.
    for asset, impact in (raw.get("market_impact") or {}).items():
        if not isinstance(impact, dict):
            continue
        frm = impact.get("from_usd")
        to = impact.get("to_usd")
        pct = impact.get("drawdown_pct")
        if isinstance(frm, (int, float)) and isinstance(to, (int, float)) \
                and isinstance(pct, (int, float)) and frm > 0:
            implied = (frm - to) / frm * 100.0
            if abs(implied - abs(pct)) > 3.0:  # допуск 3 п.п. на разночтения источников
                _err(errors, sid,
                     f"market_impact[{asset}]: drawdown_pct={pct} не сходится с "
                     f"from/to (расчёт {implied:.1f}%)")

    # Replay-спека.
    replay = raw.get("replay")
    if replay is not None:
        dur = replay.get("duration_days")
        if not isinstance(dur, int) or dur <= 0:
            _err(errors, sid, "replay.duration_days должен быть положительным int")
            dur = 0
        if not replay.get("start_date"):
            _err(errors, sid, "replay.start_date обязателен")
        for i, shock in enumerate(replay.get("shocks", [])):
            kind = shock.get("kind")
            params = shock.get("params", {})
            if kind not in VALID_SHOCK_KINDS:
                _err(errors, sid, f"replay.shocks[{i}]: неизвестный kind {kind!r}")
                continue
            days: List[int] = []
            if kind == "peg":
                path = params.get("path", [])
                if not params.get("symbol"):
                    _err(errors, sid, f"replay.shocks[{i}]: peg без symbol")
                if len(path) < 2:
                    _err(errors, sid, f"replay.shocks[{i}]: peg.path нужно ≥2 точек")
                last_d = -1
                for point in path:
                    if not (isinstance(point, list) and len(point) == 2):
                        _err(errors, sid, f"replay.shocks[{i}]: peg.path точка не [day, price]")
                        continue
                    d, price = point
                    days.append(int(d))
                    if int(d) <= last_d:
                        _err(errors, sid, f"replay.shocks[{i}]: peg.path дни не возрастают")
                    last_d = int(d)
                    if not (isinstance(price, (int, float)) and 0.0 <= price <= 2.0):
                        _err(errors, sid, f"replay.shocks[{i}]: peg цена {price!r} вне [0, 2]")
            elif kind == "capital_loss":
                days.append(int(params.get("day", -1)))
                loss = params.get("loss_pct")
                if not (isinstance(loss, (int, float)) and 0.0 < loss <= 1.0):
                    _err(errors, sid, f"replay.shocks[{i}]: capital_loss.loss_pct {loss!r} вне (0, 1]")
                if not params.get("protocol"):
                    _err(errors, sid, f"replay.shocks[{i}]: capital_loss без protocol")
            else:
                days.extend([int(params.get("from_day", 0)), int(params.get("to_day", 0))])
                if kind in ("apy", "tvl", "freeze", "halt") and not params.get("protocol"):
                    _err(errors, sid, f"replay.shocks[{i}]: {kind} без protocol")
            for d in days:
                if dur and not (0 <= d < dur):
                    _err(errors, sid, f"replay.shocks[{i}]: день {d} вне [0, {dur})")

    return errors


# ─── Загрузка ─────────────────────────────────────────────────────────────────


def scenario_from_dict(raw: dict) -> Scenario:
    """Собрать Scenario из провалидированного dict. Бросает ValueError на ошибках."""
    errors = validate_scenario_dict(raw)
    if errors:
        raise ValueError("невалидный сценарий:\n  " + "\n  ".join(errors))

    replay = None
    if raw.get("replay") is not None:
        r = raw["replay"]
        replay = ReplaySpec(
            duration_days=int(r["duration_days"]),
            start_date=str(r["start_date"]),
            shocks=[Shock(kind=s["kind"], params=dict(s.get("params", {})))
                    for s in r.get("shocks", [])],
            base={k: dict(v) for k, v in (r.get("base") or {}).items()},
            assumptions=list(r.get("assumptions", [])),
            exposure_symbols=dict(r.get("exposure_symbols", {})),
        )

    return Scenario(
        id=str(raw["id"]),
        name=str(raw["name"]),
        event_class=list(raw["event_class"]),
        window_utc=dict(raw["window_utc"]),
        speed=str(raw.get("speed", "")),
        summary=str(raw["summary"]),
        timeline=list(raw["timeline"]),
        market_impact=dict(raw.get("market_impact") or {}),
        stablecoins=list(raw.get("stablecoins") or []),
        defi_impact=dict(raw.get("defi_impact") or {}),
        causes=dict(raw["causes"]),
        contagion=list(raw.get("contagion") or []),
        recovery=dict(raw.get("recovery") or {}),
        sources=list(raw["sources"]),
        confidence_notes=str(raw["confidence_notes"]),
        data_availability=dict(raw.get("data_availability") or {}),
        replay=replay,
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        synthetic=bool(raw.get("synthetic", False)),
    )


def load_scenario(path: Path | str) -> Scenario:
    """Загрузить и провалидировать один JSON-файл сценария."""
    p = Path(path)
    with open(p, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    scenario = scenario_from_dict(raw)
    return scenario


def load_all_scenarios(directory: Path | str | None = None) -> Dict[str, Scenario]:
    """Загрузить всю библиотеку сценариев (отсортировано по id, детерминизм).

    Fail-CLOSED: один невалидный файл валит всю загрузку с именем файла —
    молча пропускать сценарии запрещено.
    """
    d = Path(directory) if directory is not None else SCENARIOS_DIR
    result: Dict[str, Scenario] = {}
    for path in sorted(d.glob("*.json")):
        try:
            scenario = load_scenario(path)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path.name}: {exc}") from exc
        if scenario.id in result:
            raise ValueError(f"{path.name}: дубликат id {scenario.id}")
        result[scenario.id] = scenario
    return result
