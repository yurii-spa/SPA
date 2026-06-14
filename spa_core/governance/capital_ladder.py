#!/usr/bin/env python3
"""SPA Capital Ladder enforcement (MP-505) — «капитал следует за треком» как код.

Кодифицирует лестницу ARCHITECTURE_v2 §8 (L0 paper → L5 institutional) поверх
РЕАЛЬНЫХ данных трека:

| Ступень | AUM cap | Условие подъёма |
|---|---|---|
| L0 paper          | $100K virtual | — (стартовая)                                          |
| L1 pilot          | $50K real     | 30 дней paper-трека, E2E harness зелёный, Safe настроен |
| L2 own            | $1M           | 90 дней без инцидентов, APY ≥ benchmark+1пп, drill kill-switch |
| L3 friends        | $5M           | аудит #1, юр. структура, страховой буфер 0.5% AUM      |
| L4 external       | $25M          | 12 мес трека, аудит #2, bug bounty, Proof-of-Track     |
| L5 institutional  | $100M+        | 24 мес трека, 3 аудита, команда 5+, SOC-процедуры      |

Правила (§8):
* Подъём по ступени — ТОЛЬКО ADR + Owner approval. Модуль никогда не
  поднимает ступень сам: он лишь вычисляет eligibility (advisory-гейт).
* Автоматический спуск: инцидент ≥ 1% AUM → минус одна ступень немедленно.
  Детектор инцидента — по реальному data/equity_curve_daily.json: дневная
  просадка equity ≥ 1% (close-to-close ``daily_return_pct`` ≤ −1% ИЛИ
  внутридневная open→low ≥ 1%). Единицы — проценты (0.0087 = 0.0087%),
  как пишет cycle_runner.

Входы (фактические файлы data/, все опциональны — отсутствие/битость это
blocker/note, а не исключение):
* ``data/equity_curve_daily.json``      — дневные бары equity (инциденты, трек).
* ``data/paper_trading_status.json``    — days_running, current_equity.
* ``data/golive_status.json``           — вердикт anti-demo гейта MP-006.
* ``data/capital_ladder_attestations.json`` — ручные аттестации Owner'а
  (аудиты, Safe, harness, ADR-approval) — то, что НЕ выводится из данных.

Выход: ``data/capital_ladder_status.json`` (атомарная запись tmp+os.replace),
история переходов с ротацией ≤500.

Интеграция с go-live гейтом — advisory и standalone: golive_checker (MP-006)
имеет фиксированный набор критериев без расширяемого реестра, поэтому этот
модуль НЕ модифицирует его, а потребляет его персистентный вердикт
``data/golive_status.json`` как гейт подъёма L0→L1. cycle_runner не трогается.

Scope / safety: LLM FORBIDDEN — детерминированная логика, stdlib only,
никакой сети. Чистые функции с инжектируемыми входами; запись только в
собственный статус-файл.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

STATUS_FILENAME = "capital_ladder_status.json"
ATTESTATIONS_FILENAME = "capital_ladder_attestations.json"
EQUITY_FILENAME = "equity_curve_daily.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
GOLIVE_STATUS_FILENAME = "golive_status.json"

INCIDENT_THRESHOLD_PCT = 1.0  # инцидент ≥ 1% AUM → автоспуск (ARCHITECTURE_v2 §8)
HISTORY_MAX = 500             # ротация истории переходов и обработанных инцидентов


# ─── Декларация лестницы (ARCHITECTURE_v2 §8) ────────────────────────────────


@dataclass(frozen=True)
class LadderLevel:
    """Одна ступень Capital Ladder."""

    level: int
    code: str
    name: str
    aum_cap_usd: float
    requirements: tuple[str, ...]  # человекочитаемые условия подъёма НА эту ступень

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "name": self.name,
            "aum_cap_usd": self.aum_cap_usd,
            "requirements": list(self.requirements),
        }


LADDER: tuple[LadderLevel, ...] = (
    LadderLevel(0, "L0", "paper", 100_000.0, ()),
    LadderLevel(
        1, "L1", "pilot", 50_000.0,
        ("30 дней живого paper-трека", "E2E harness зелёный", "Safe настроен"),
    ),
    LadderLevel(
        2, "L2", "own", 1_000_000.0,
        ("90 дней live без инцидентов", "APY ≥ benchmark+1пп",
         "drill kill-switch пройден"),
    ),
    LadderLevel(
        3, "L3", "friends", 5_000_000.0,
        ("аудит #1 пройден", "юр. структура", "страховой буфер 0.5% AUM"),
    ),
    LadderLevel(
        4, "L4", "external", 25_000_000.0,
        ("12 мес трека", "аудит #2", "bug bounty", "Proof-of-Track on-chain"),
    ),
    LadderLevel(
        5, "L5", "institutional", 100_000_000.0,
        ("24 мес трека", "3 аудита", "команда 5+", "SOC-подобные процедуры"),
    ),
)

MIN_LEVEL = 0
MAX_LEVEL = len(LADDER) - 1

# Гейты подъёма НА ступень target_level: (gate_name, kind)
#   kind="auto"   — детерминированно проверяется по данным трека;
#   kind="attest" — ручная аттестация Owner'а (data/capital_ladder_attestations.json),
#                   из данных репо честно НЕ выводима.
CLIMB_GATES: dict[int, tuple[tuple[str, str], ...]] = {
    1: (
        ("golive_ready", "auto"),            # anti-demo гейт MP-006 (golive_status.json)
        ("track_days_ge_30", "auto"),
        ("e2e_harness_green", "attest"),
        ("safe_configured", "attest"),
    ),
    2: (
        ("track_days_ge_90", "auto"),
        ("no_incident_days_ge_90", "auto"),
        ("apy_ge_benchmark_plus_1pp", "attest"),
        ("kill_switch_drill_passed", "attest"),
    ),
    3: (
        ("audit_1_passed", "attest"),
        ("legal_structure", "attest"),
        ("insurance_buffer_0_5pct", "attest"),
    ),
    4: (
        ("track_days_ge_365", "auto"),
        ("audit_2_passed", "attest"),
        ("bug_bounty_live", "attest"),
        ("proof_of_track_onchain", "attest"),
    ),
    5: (
        ("track_days_ge_730", "auto"),
        ("audits_3_passed", "attest"),
        ("team_5_plus", "attest"),
        ("soc_procedures", "attest"),
    ),
}

# Подъём всегда требует ADR + Owner approval (§8) — добавляется к любому target.
OWNER_APPROVAL_GATE = ("owner_approval_adr", "attest")

_TRACK_DAY_GATES = {
    "track_days_ge_30": 30,
    "track_days_ge_90": 90,
    "track_days_ge_365": 365,
    "track_days_ge_730": 730,
}


# ─── Atomic IO helpers (паттерн golive_checker / kill_switch) ────────────────


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Записывает JSON атомарно: tmpfile в той же папке + os.replace."""
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


def _read_json(path: Path) -> Any:
    """Читает JSON терпимо: нет файла / битый файл → None, никогда не raise."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _num(value: Any) -> float | None:
    """Число или None (bool — не число)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_date(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ─── Чистые функции: инциденты ───────────────────────────────────────────────


def detect_incidents(
    daily: Any, threshold_pct: float = INCIDENT_THRESHOLD_PCT
) -> list[dict]:
    """Детектор инцидентов ≥ threshold% AUM по дневным барам equity.

    Чистая функция: вход — список баров cycle_runner'а (поля в процентах:
    ``daily_return_pct``; ``open_equity``/``low_equity`` в USD). Инцидент дня:
      * close-to-close: daily_return_pct ≤ −threshold, ИЛИ
      * intraday: (open_equity − low_equity) / open_equity * 100 ≥ threshold.
    Ровно threshold (1.0%) — это уже инцидент (критерий «≥»).
    Возвращает детерминированный список {date, loss_pct, kind}, отсортированный
    по дате; мусорные бары молча пропускаются.
    """
    incidents: list[dict] = []
    if not isinstance(daily, list):
        return incidents
    for bar in daily:
        if not isinstance(bar, dict):
            continue
        date = _parse_date(bar.get("date"))
        if date is None:
            continue
        loss_pct: float | None = None
        kind = ""
        ret = _num(bar.get("daily_return_pct"))
        if ret is not None and -ret >= threshold_pct:
            loss_pct, kind = -ret, "close_to_close"
        open_e, low_e = _num(bar.get("open_equity")), _num(bar.get("low_equity"))
        if open_e is not None and low_e is not None and open_e > 0:
            intraday = (open_e - low_e) / open_e * 100.0
            if intraday >= threshold_pct and (loss_pct is None or intraday > loss_pct):
                loss_pct, kind = intraday, "intraday"
        if loss_pct is not None:
            incidents.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "loss_pct": round(loss_pct, 6),
                    "kind": kind,
                }
            )
    incidents.sort(key=lambda i: i["date"])
    return incidents


def apply_auto_demotions(
    current_level: int, new_incidents: list[dict]
) -> tuple[int, list[dict]]:
    """Автоспуск §8: минус одна ступень за каждый НОВЫЙ инцидент, пол — L0.

    Чистая функция: (уровень, инциденты) → (новый уровень, записи переходов).
    На L0 спускаться некуда — инцидент фиксируется записью без смены уровня.
    """
    level = max(MIN_LEVEL, min(MAX_LEVEL, int(current_level)))
    transitions: list[dict] = []
    for inc in sorted(new_incidents, key=lambda i: str(i.get("date", ""))):
        target = max(MIN_LEVEL, level - 1)
        transitions.append(
            {
                "from_level": level,
                "to_level": target,
                "kind": "auto_demotion" if target < level else "incident_at_floor",
                "reason": (
                    f"incident >= {INCIDENT_THRESHOLD_PCT}% AUM on "
                    f"{inc.get('date')} (loss {inc.get('loss_pct')}%, "
                    f"{inc.get('kind')})"
                ),
                "incident": dict(inc),
            }
        )
        level = target
    return level, transitions


def days_since_last_incident(
    incidents: list[dict], now: datetime
) -> int | None:
    """Дней с последнего инцидента; None — инцидентов не было вовсе."""
    latest: datetime | None = None
    for inc in incidents if isinstance(incidents, list) else []:
        dt = _parse_date(inc.get("date")) if isinstance(inc, dict) else None
        if dt is not None and (latest is None or dt > latest):
            latest = dt
    if latest is None:
        return None
    return max(0, (now - latest).days)


# ─── Чистые функции: гейты подъёма ───────────────────────────────────────────


@dataclass
class ClimbVerdict:
    """Advisory-вердикт «можно ли подняться на следующую ступень»."""

    from_level: int
    to_level: int | None
    eligible: bool
    gates: dict[str, bool] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "from_level": self.from_level,
            "to_level": self.to_level,
            "eligible": self.eligible,
            "gates": dict(self.gates),
            "blockers": list(self.blockers),
            "note": "advisory only: подъём = ADR + Owner approval (§8), "
                    "модуль ступень НЕ поднимает",
        }


def evaluate_climb(
    current_level: int,
    *,
    golive_ready: bool,
    track_days: int | None,
    days_no_incident: int | None,
    attestations: dict | None,
) -> ClimbVerdict:
    """Гейты подъёма на ступень current_level+1 (чистая, инжектируемые входы).

    auto-гейты — по данным трека; attest-гейты — только из аттестаций Owner'а
    (отсутствие аттестации = честный FAIL, модуль ничего не «додумывает»).
    """
    level = max(MIN_LEVEL, min(MAX_LEVEL, int(current_level)))
    if level >= MAX_LEVEL:
        return ClimbVerdict(
            from_level=level,
            to_level=None,
            eligible=False,
            blockers=["already at top level L5 institutional"],
        )
    target = level + 1
    att = attestations if isinstance(attestations, dict) else {}
    gates: dict[str, bool] = {}
    blockers: list[str] = []
    for name, kind in CLIMB_GATES[target] + (OWNER_APPROVAL_GATE,):
        if kind == "attest":
            ok = att.get(name) is True
            if not ok:
                blockers.append(
                    f"{name}: not attested by Owner in {ATTESTATIONS_FILENAME}"
                )
        elif name == "golive_ready":
            ok = golive_ready is True
            if not ok:
                blockers.append(
                    f"golive_ready: anti-demo gate (MP-006) not READY "
                    f"({GOLIVE_STATUS_FILENAME})"
                )
        elif name in _TRACK_DAY_GATES:
            need = _TRACK_DAY_GATES[name]
            ok = isinstance(track_days, int) and track_days >= need
            if not ok:
                blockers.append(
                    f"{name}: track is {track_days if track_days is not None else 'unknown'}"
                    f" days, need >= {need}"
                )
        elif name == "no_incident_days_ge_90":
            ok = days_no_incident is None or days_no_incident >= 90
            if not ok:
                blockers.append(
                    f"no_incident_days_ge_90: last incident {days_no_incident} "
                    f"days ago, need >= 90"
                )
        else:  # неизвестный auto-гейт — честный FAIL, не угадываем
            ok = False
            blockers.append(f"{name}: unknown auto gate")
        gates[name] = ok
    return ClimbVerdict(
        from_level=level,
        to_level=target,
        eligible=all(gates.values()),
        gates=gates,
        blockers=blockers,
    )


# ─── Состояние / persistence ─────────────────────────────────────────────────


def load_state(data_dir: Path) -> dict:
    """Состояние лестницы; битый/отсутствующий файл → дефолт L0 (paper).

    L0 — единственная ступень без условий (§8: «текущая»), а реальный трек
    репо — paper (execution_mode=read_only_simulation), так что дефолт честен.
    """
    doc = _read_json(Path(data_dir) / STATUS_FILENAME)
    level = MIN_LEVEL
    processed: list[str] = []
    history: list[dict] = []
    if isinstance(doc, dict):
        raw_level = doc.get("current_level")
        if isinstance(raw_level, int) and MIN_LEVEL <= raw_level <= MAX_LEVEL:
            level = raw_level
        raw_proc = doc.get("processed_incident_dates")
        if isinstance(raw_proc, list):
            processed = [str(d) for d in raw_proc if _parse_date(d) is not None]
        raw_hist = doc.get("history")
        if isinstance(raw_hist, list):
            history = [h for h in raw_hist if isinstance(h, dict)]
    return {"current_level": level, "processed_incident_dates": processed,
            "history": history}


@dataclass
class LadderResult:
    """Итог одного прогона capital ladder."""

    level: LadderLevel
    demotions: list[dict]
    incidents_total: int
    climb: ClimbVerdict
    aum_usd: float | None
    notes: list[str]
    timestamp: str

    def summary(self) -> str:
        lines = [
            "─" * 56,
            f"CAPITAL LADDER (ARCHITECTURE_v2 §8)   [{self.timestamp}]",
            "─" * 56,
            f"  level: {self.level.code} {self.level.name} "
            f"(AUM cap ${self.level.aum_cap_usd:,.0f})",
            f"  aum: {'$%s' % format(self.aum_usd, ',.2f') if self.aum_usd is not None else 'unknown'}",
            f"  incidents >= {INCIDENT_THRESHOLD_PCT}% AUM in track: {self.incidents_total}",
        ]
        if self.demotions:
            lines.append("  AUTO-DEMOTIONS this run:")
            lines.extend(
                f"    • L{t['from_level']} → L{t['to_level']}: {t['reason']}"
                for t in self.demotions
            )
        if self.climb.to_level is None:
            lines.append("  climb: at top of ladder")
        else:
            lines.append(
                f"  climb to L{self.climb.to_level}: "
                f"{'ELIGIBLE (advisory; needs ADR+Owner)' if self.climb.eligible else 'NOT ELIGIBLE'}"
                f" ({sum(self.climb.gates.values())}/{len(self.climb.gates)} gates pass)"
            )
            lines.extend(f"    [{'PASS' if ok else 'FAIL'}] {g}"
                         for g, ok in self.climb.gates.items())
        for n in self.notes:
            lines.append(f"  note: {n}")
        lines.append("─" * 56)
        return "\n".join(lines)


class CapitalLadder:
    """Enforcement лестницы L0–L5 поверх реального трека (MP-505)."""

    def __init__(
        self,
        data_dir: str | os.PathLike | None = None,
        now: datetime | None = None,
    ) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)

    # ── входы ─────────────────────────────────────────────────────────────

    def _gather_inputs(self, notes: list[str]) -> dict:
        equity = _read_json(self.data_dir / EQUITY_FILENAME)
        daily = equity.get("daily") if isinstance(equity, dict) else None
        if not isinstance(daily, list):
            daily = []
            notes.append(f"{EQUITY_FILENAME}: missing/unreadable — no incident scan")
        pt = _read_json(self.data_dir / PT_STATUS_FILENAME)
        track_days: int | None = None
        aum: float | None = None
        if isinstance(pt, dict):
            raw_days = pt.get("days_running")
            if isinstance(raw_days, int) and raw_days >= 0:
                track_days = raw_days
            aum = _num(pt.get("current_equity"))
        else:
            notes.append(f"{PT_STATUS_FILENAME}: missing/unreadable")
        if track_days is None:
            # fallback: длина дневного ряда equity
            track_days = len([b for b in daily if isinstance(b, dict)]) or None
            if track_days is not None:
                notes.append("track_days: fallback to equity daily bar count")
        if aum is None and isinstance(equity, dict):
            aum = _num((equity.get("summary") or {}).get("end_equity")) \
                if isinstance(equity.get("summary"), dict) else None
        golive = _read_json(self.data_dir / GOLIVE_STATUS_FILENAME)
        golive_ready = isinstance(golive, dict) and golive.get("ready") is True
        if not isinstance(golive, dict):
            notes.append(f"{GOLIVE_STATUS_FILENAME}: missing/unreadable — "
                         "golive_ready treated as False (advisory MP-006 gate)")
        att = _read_json(self.data_dir / ATTESTATIONS_FILENAME)
        if not isinstance(att, dict):
            att = {}
        return {
            "daily": daily,
            "track_days": track_days,
            "aum": aum,
            "golive_ready": golive_ready,
            "attestations": att,
        }

    # ── публичное API ─────────────────────────────────────────────────────

    def run(self, write: bool = True) -> LadderResult:
        """Полный прогон: инциденты → автоспуск → гейты подъёма → статус.

        Никогда не raise на битых/отсутствующих данных — это notes/blockers.
        ``write=False`` (--check) — только вычисление, без записи.
        """
        notes: list[str] = []
        inputs = self._gather_inputs(notes)
        state = load_state(self.data_dir)
        incidents = detect_incidents(inputs["daily"])
        processed = set(state["processed_incident_dates"])
        new_incidents = [i for i in incidents if i["date"] not in processed]
        level_idx, demotions = apply_auto_demotions(
            state["current_level"], new_incidents
        )
        ts = self.now.isoformat()
        for t in demotions:
            t["ts"] = ts
        climb = evaluate_climb(
            level_idx,
            golive_ready=inputs["golive_ready"],
            track_days=inputs["track_days"],
            days_no_incident=days_since_last_incident(incidents, self.now),
            attestations=inputs["attestations"],
        )
        level = LADDER[level_idx]
        result = LadderResult(
            level=level,
            demotions=demotions,
            incidents_total=len(incidents),
            climb=climb,
            aum_usd=inputs["aum"],
            notes=notes,
            timestamp=ts,
        )
        if write:
            history = (state["history"] + demotions)[-HISTORY_MAX:]
            processed_dates = sorted(
                set(state["processed_incident_dates"])
                | {i["date"] for i in new_incidents}
            )[-HISTORY_MAX:]
            doc = {
                "source": "capital_ladder",
                "is_demo": False,
                "updated_at": ts,
                "incident_threshold_pct": INCIDENT_THRESHOLD_PCT,
                "current_level": level.level,
                "level_code": level.code,
                "level_name": level.name,
                "aum_cap_usd": level.aum_cap_usd,
                "aum_usd": inputs["aum"],
                "track_days": inputs["track_days"],
                "incidents_total": len(incidents),
                "last_incident": incidents[-1] if incidents else None,
                "climb": climb.to_dict(),
                "ladder": [lvl.to_dict() for lvl in LADDER],
                "processed_incident_dates": processed_dates,
                "history": history,
                "notes": notes,
            }
            _atomic_write_json(self.data_dir / STATUS_FILENAME, doc)
        return result


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="capital_ladder",
        description="Capital Ladder L0-L5 enforcement (MP-505, ARCHITECTURE_v2 §8).",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--check", action="store_true",
        help="вычислить ступень/гейты без записи статуса",
    )
    group.add_argument(
        "--run", action="store_true",
        help="прогон с автоспуском и записью data/capital_ladder_status.json",
    )
    parser.add_argument("--data-dir", default=None, help="override data directory")
    args = parser.parse_args(argv)

    result = CapitalLadder(data_dir=args.data_dir).run(write=bool(args.run))
    print(result.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
