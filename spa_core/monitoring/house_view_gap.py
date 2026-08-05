"""house_view_gap.py — расхождение «что видит офис» vs «что держит книга» (ADR-066, Контур C1).

Аудит 2026-08-05 нашёл разрыв, который не измерял НИКТО: 12 аналитиков `io_*` и
`io_chief_investment` каждый день честно производят house_view — постуру, конфликты,
возможности с evidence-уровнем, — а сверять это с ФАКТИЧЕСКОЙ аллокацией не поручено ни
одному сторожу. Дашборд `/admin/investment-os` смотреть никто не обязан, оркестратор
house_view не читал вовсе. Продукт без обязательного потребителя деградирует молча —
класс дефекта известен (fail-OPEN мониторы #29–#38, aggressive_lab, «90 % аналитики спит»).

Этот модуль отвечает ровно на один вопрос и **больше ни на что**:

    расходится ли то, что офис ВИДИТ, с тем, что книга ДЕРЖИТ, — и назван ли отказ?

**Только сверка.** Ни одной строки, двигающей капитал: ни RiskPolicy, ни kill-switch, ни
аллокатора здесь нет и быть не может (ADR-066 P5). Выход — файл-отчёт
`data/house_view_gap.json`; дальше его читает мост «находка→карточка» (Контур C2).
Расхождение — это НЕ приказ переложить деньги; это факт, что решение нигде не названо.

Проверки (каждая рождена конкретным фактом 2026-08-05, см. тесты — положительные контроли):

  G1  возможность офиса (evidence ≥ L3) не в книге И отказ нигде не назван → WARN
        живой факт: house_view держит aerodrome_usdc_lp 8.5 % и pendle_pt_susde 8.0 %
        (L3), книга их не держит, и в `allocation_rationale.json` их нет ни в
        blocked_protocols, ни в below_median_cap — то есть отказ никем не произнесён.
        **Названный отказ находкой НЕ является** — это и есть честная работа (контроль
        в обратную сторону: morpho_steakhouse ограничен below_median_cap и молчит).
  G2  негативный сигнал по протоколу, который книга ДЕРЖИТ → CRITICAL (RED/BLOCK)
        либо WARN weak (WARN-сигнал: информативен, но стареет — P2, иначе очередь
        забивается неустранимыми «жёлтыми»)
  G3  постура офиса RED, а книга без запаса кэша сверх буфера → WARN
  G4  простой капитала сверх буфера не объяснён (ADR-055: «кэш обязан быть объяснён
        каждый цикл») → WARN; живой факт 2026-08-05: unexplained_pct = 10 %,
        status=named_not_quantified — то же, что agent_health зовёт «capital-efficiency LAZY»

Честность (инвариант 2 / ADR-066 P2): `OK` — ТОЛЬКО когда всё вычислено и прошло.
Протухший house_view, отсутствующая книга, нечитаемый rationale ⇒ UNCHECKED по этой
проверке, а не молчаливое «всё хорошо». Слабые находки стареют (WEAK_AGE_DAYS),
сильные — нет.

Формат находок ПОБУКВЕННО совпадает с `architecture_conformance` (key/check/severity/
class/message/first_seen): мост C2 потребляет оба отчёта одним кодом, а не двумя.

Exit: 0 OK · 1 WARN/UNCHECKED · 2 CRITICAL. LLM_FORBIDDEN. Только stdlib.
Время — вход (`now=`), не окружение (правило `.claude/rules/deployment.md`).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import (
    REPO_ROOT,
    WEAK_AGE_DAYS,
    _parse_iso,
)

REPORT_PATH = os.path.join(REPO_ROOT, "data", "house_view_gap.json")

HOUSE_VIEW_REL = os.path.join("data", "investment_os", "chief_investment.json")
POSITIONS_REL = os.path.join("data", "current_positions.json")
RATIONALE_REL = os.path.join("data", "allocation_rationale.json")
SIGNALS_REL = os.path.join("data", "analytics_signals_blocking.json")
RED_TEAM_REL = os.path.join("data", "investment_os", "red_team.json")

# Свежесть входов. house_view производится ежедневно (SLO манифеста 26ч); сверка
# по протухшему входу — это сверка с прошлым, а не с настоящим ⇒ UNCHECKED.
HOUSE_VIEW_SLO_H = 26.0
POSITIONS_SLO_H = 26.0

# Ниже L3 — не «возможность», а гипотеза; требовать по ней названного отказа
# значило бы плодить бумагу (ADR-066: дисциплина против спама начинается здесь).
MIN_EVIDENCE_LEVEL = 3

EXIT_BY_OVERALL = {"OK": 0, "UNCHECKED": 1, "WARN": 1, "CRITICAL": 2}

# Сигналы, при которых удержание протокола — капитал-релевантная находка.
STRONG_NEGATIVE = ("RED", "BLOCK", "BLOCKING", "CRITICAL")
WEAK_NEGATIVE = ("WARN", "WARNING", "CAUTION", "YELLOW")


# ── чтение входов (в тестах всё инъектируется) ───────────────────────────────

def _load_json(rel_path: str, root: str = REPO_ROOT):
    """Прочитать JSON-артефакт. Нет файла / битый JSON → None (не {} — разница
    между «пусто» и «не прочитано» здесь несущая: она даёт UNCHECKED)."""
    full = os.path.join(root, rel_path)
    try:
        with open(full, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _finding(key: str, check: str, severity: str, cls: str, message: str) -> dict:
    return {"key": key, "check": check, "severity": severity, "class": cls,
            "message": message}


def _evidence_rank(level) -> int | None:
    """'L3' → 3. Не разобрано → None (не 0: неизвестный уровень ≠ худший)."""
    if not isinstance(level, str):
        return None
    s = level.strip().upper()
    if len(s) >= 2 and s[0] == "L" and s[1:].isdigit():
        return int(s[1:])
    return None


def _age_hours(ts: dt.datetime | None, now: dt.datetime) -> float | None:
    return None if ts is None else (now - ts).total_seconds() / 3600.0


def held_protocols(positions_doc) -> dict[str, float] | None:
    """{протокол: usd} по НЕНУЛЕВЫМ позициям. None = книга не прочитана."""
    if not isinstance(positions_doc, dict):
        return None
    raw = positions_doc.get("positions")
    if not isinstance(raw, dict):
        return None
    out: dict[str, float] = {}
    for name, amount in raw.items():
        try:
            usd = float(amount)
        except (TypeError, ValueError):
            continue
        if usd > 0:
            out[str(name)] = usd
    return out


def refusal_vocabulary(rationale_doc) -> set[str] | None:
    """Все имена протоколов, чей отказ где-либо НАЗВАН аллокатором.

    Источники (ADR-060/061 — «каждый отказ назван»): blocked_protocols в атрибуции
    кэша, below_median_cap, evidence-списки теневого решения, ноги последнего хода.
    None = rationale не прочитан (⇒ вопрос «назван ли отказ» НЕ ИЗМЕРЕН, и это не
    то же самое, что «не назван»).
    """
    if not isinstance(rationale_doc, dict):
        return None
    named: set[str] = set()

    for row in rationale_doc.get("below_median_cap") or []:
        if isinstance(row, dict) and row.get("protocol"):
            named.add(str(row["protocol"]))

    cash = rationale_doc.get("cash")
    if isinstance(cash, dict):
        for row in cash.get("attribution") or []:
            if isinstance(row, dict):
                named |= _names_in_reason(row.get("reason"))

    shadow = rationale_doc.get("decision_shadow")
    if isinstance(shadow, dict):
        ev = shadow.get("evidence")
        if isinstance(ev, dict):
            for lst in ev.values():
                if isinstance(lst, list):
                    named |= {str(x) for x in lst if isinstance(x, str)}
        for r in shadow.get("reasons") or []:
            named |= _names_in_reason(r)

    hist = rationale_doc.get("history")
    if isinstance(hist, dict) and isinstance(hist.get("last_move_legs"), dict):
        named |= {str(k) for k in hist["last_move_legs"]}

    return named


def _names_in_reason(reason) -> set[str]:
    """Достать имена протоколов из строки-причины вида
    ``blocked_protocols:['frax', 'sdai']``. Никакого угадывания: берём только то,
    что стоит в кавычках после двоеточия."""
    if not isinstance(reason, str) or ":" not in reason:
        return set()
    tail = reason.split(":", 1)[1]
    out: set[str] = set()
    for quote in ("'", '"'):
        parts = tail.split(quote)
        for i in range(1, len(parts), 2):
            token = parts[i].strip()
            if token:
                out.add(token)
    return out


def negative_signals(signals_doc, red_team_doc=None) -> dict[str, tuple[str, str]]:
    """{протокол: (severity_hint, человекочитаемая причина)} по негативным сигналам.

    severity_hint ∈ {'strong','weak'}: strong — RED/BLOCK (капитал-релевантно),
    weak — WARN/жёлтый (информативно, стареет). Сильный сигнал вытесняет слабый —
    иначе жёлтый по тому же протоколу маскировал бы красный.
    """
    out: dict[str, tuple[str, str]] = {}

    if isinstance(signals_doc, dict) and isinstance(signals_doc.get("protocols"), dict):
        for proto, row in signals_doc["protocols"].items():
            if not isinstance(row, dict):
                continue
            sig = str(row.get("signal") or "").strip().upper()
            reason = str(row.get("reason") or sig)
            if sig in STRONG_NEGATIVE:
                out[str(proto)] = ("strong", f"сигнал {sig}: {reason}")
            elif sig in WEAK_NEGATIVE and out.get(str(proto), ("", ""))[0] != "strong":
                out[str(proto)] = ("weak", f"сигнал {sig}: {reason}")

    # Угрозы red-team (data/investment_os/red_team.json) — всегда сильные.
    if isinstance(red_team_doc, dict):
        tp = red_team_doc.get("threat_posture")
        value = tp.get("value") if isinstance(tp, dict) else None
        threats = value.get("threats") if isinstance(value, dict) else None
        for t in threats if isinstance(threats, list) else []:
            proto = None
            if isinstance(t, dict):
                proto = t.get("protocol") or t.get("target") or t.get("name")
            if proto:
                detail = t.get("description") or t.get("reason") or t.get("threat") or ""
                out[str(proto)] = ("strong", f"red-team: {detail or t}".strip())

    return out


# ── ядро (чистое: все входы — параметры, время — вход) ───────────────────────

def run_checks(house_view_doc,
               positions_doc,
               rationale_doc,
               signals_doc,
               now: dt.datetime,
               prev_first_seen: dict[str, str] | None = None,
               red_team_doc=None) -> dict:
    findings: list[dict] = []
    unchecked: list[dict] = []

    house_view = None
    if isinstance(house_view_doc, dict):
        hv = house_view_doc.get("house_view")
        if isinstance(hv, dict):
            house_view = hv

    # Свежесть house_view: сверка по протухшему офису — сверка с прошлым.
    hv_age = _age_hours(_parse_iso((house_view_doc or {}).get("generated_at")
                                   if isinstance(house_view_doc, dict) else None), now)
    if house_view is None:
        unchecked.append({"check": "house_view",
                          "reason": f"{HOUSE_VIEW_REL}: house_view не прочитан — "
                                    f"сверка офис↔книга НЕ ВЫПОЛНЕНА"})
    elif hv_age is None:
        unchecked.append({"check": "house_view",
                          "reason": f"{HOUSE_VIEW_REL}: нет generated_at — свежесть офиса "
                                    f"НЕ ИЗМЕРЕНА, сверка не засчитывается"})
        house_view = None
    elif hv_age > HOUSE_VIEW_SLO_H:
        unchecked.append({"check": "house_view",
                          "reason": f"{HOUSE_VIEW_REL}: возраст {hv_age:.1f}ч > SLO "
                                    f"{HOUSE_VIEW_SLO_H}ч — сверка была бы с прошлым, не с настоящим"})
        house_view = None

    held = held_protocols(positions_doc)
    pos_age = _age_hours(_parse_iso((positions_doc or {}).get("generated_at")
                                    if isinstance(positions_doc, dict) else None), now)
    if held is None:
        unchecked.append({"check": "book",
                          "reason": f"{POSITIONS_REL}: позиции не прочитаны — что держит "
                                    f"книга, НЕ ИЗМЕРЕНО"})
    elif pos_age is not None and pos_age > POSITIONS_SLO_H:
        unchecked.append({"check": "book",
                          "reason": f"{POSITIONS_REL}: возраст {pos_age:.1f}ч > SLO "
                                    f"{POSITIONS_SLO_H}ч — книга протухла"})
        held = None

    named_refusals = refusal_vocabulary(rationale_doc)

    # G1 — возможность офиса не в книге и отказ не назван
    if house_view is not None and held is not None:
        if named_refusals is None:
            unchecked.append({"check": "G1",
                              "reason": f"{RATIONALE_REL} не прочитан — «назван ли отказ» "
                                        f"НЕ ИЗМЕРЕНО (молчание ≠ отказ назван)"})
        else:
            for opp in house_view.get("top_opportunities") or []:
                if not isinstance(opp, dict):
                    continue
                raw_value = opp.get("value")
                value = raw_value if isinstance(raw_value, dict) else {}
                proto = value.get("protocol")
                if not proto:
                    continue
                proto = str(proto)
                rank = _evidence_rank(opp.get("evidence_level"))
                if rank is None:
                    unchecked.append({"check": "G1",
                                      "reason": f"возможность {proto}: evidence_level "
                                                f"{opp.get('evidence_level')!r} не разобран — "
                                                f"НЕ ИЗМЕРЕНО"})
                    continue
                if rank < MIN_EVIDENCE_LEVEL:
                    continue
                if proto in held:
                    continue
                if proto in named_refusals:
                    continue  # отказ назван — это честная работа, а не находка
                apy = value.get("apy_pct")
                findings.append(_finding(
                    f"G1:unrefused_opportunity:{proto}", "G1", "WARN", "strong",
                    f"офис видит возможность {proto} "
                    f"{apy if apy is not None else '?'}% (evidence "
                    f"L{rank}), книга её НЕ держит, и отказ нигде не назван "
                    f"({RATIONALE_REL}: ни blocked_protocols, ни below_median_cap)"))

    # G2 — негативный сигнал по протоколу, который книга держит
    if held is not None:
        negatives = negative_signals(signals_doc, red_team_doc)
        if signals_doc is None:
            unchecked.append({"check": "G2",
                              "reason": f"{SIGNALS_REL} не прочитан — сигналы по "
                                        f"удерживаемым протоколам НЕ ИЗМЕРЕНЫ"})
        for proto in sorted(held):
            hit = negatives.get(proto)
            if not hit:
                continue
            strength, reason = hit
            if strength == "strong":
                findings.append(_finding(
                    f"G2:held_red:{proto}", "G2", "CRITICAL", "strong",
                    f"книга держит {proto} на ${held[proto]:,.0f}, а офис по нему "
                    f"КРАСНЫЙ — {reason}"))
            else:
                findings.append(_finding(
                    f"G2:held_warn:{proto}", "G2", "WARN", "weak",
                    f"книга держит {proto} на ${held[proto]:,.0f} при жёлтом сигнале "
                    f"офиса — {reason}"))

    # G3 — постура RED, а книга без запаса кэша
    if house_view is not None:
        posture = str(house_view.get("overall_posture") or "").strip().upper()
        cash = (rationale_doc or {}).get("cash") if isinstance(rationale_doc, dict) else None
        if posture == "RED":
            if not isinstance(cash, dict) or cash.get("excess_pct") is None:
                unchecked.append({"check": "G3",
                                  "reason": "постура RED, но запас кэша НЕ ИЗМЕРЕН "
                                            f"({RATIONALE_REL} без cash.excess_pct)"})
            else:
                try:
                    excess = float(cash["excess_pct"])
                except (TypeError, ValueError):
                    excess = None
                if excess is None:
                    unchecked.append({"check": "G3",
                                      "reason": "постура RED, cash.excess_pct не разобран — "
                                                "НЕ ИЗМЕРЕНО"})
                elif excess <= 0:
                    findings.append(_finding(
                        "G3:red_posture_no_headroom", "G3", "WARN", "strong",
                        f"офис объявил постуру RED, а книга развёрнута без запаса "
                        f"сверх буфера (excess_pct={excess}) — расхождение не названо"))

    # G4 — простой капитала сверх буфера не объяснён (ADR-055)
    if isinstance(rationale_doc, dict):
        cash = rationale_doc.get("cash")
        if isinstance(cash, dict):
            raw = cash.get("unexplained_pct")
            try:
                unexplained = float(raw) if raw is not None else None
            except (TypeError, ValueError):
                unexplained = None
            if raw is not None and unexplained is None:
                unchecked.append({"check": "G4",
                                  "reason": f"cash.unexplained_pct={raw!r} не разобран — "
                                            f"объяснённость простоя НЕ ИЗМЕРЕНА"})
            elif unexplained is not None and unexplained > 0:
                findings.append(_finding(
                    "G4:unexplained_cash", "G4", "WARN", "strong",
                    f"простой капитала {unexplained:.4g}% сверх буфера НЕ объяснён "
                    f"(status={cash.get('status')!r}) — ADR-055 требует называть, что "
                    f"биндит кэш, каждый цикл"))
        else:
            unchecked.append({"check": "G4",
                              "reason": f"{RATIONALE_REL} без секции cash — объяснённость "
                                        f"простоя НЕ ИЗМЕРЕНА"})
    else:
        unchecked.append({"check": "G4",
                          "reason": f"{RATIONALE_REL} не прочитан — объяснённость простоя "
                                    f"НЕ ИЗМЕРЕНА"})

    # первое появление + старение слабых (P2)
    prev_first_seen = prev_first_seen or {}
    now_iso = now.isoformat()
    aged: list[dict] = []
    kept: list[dict] = []
    for f in findings:
        f["first_seen"] = prev_first_seen.get(f["key"], now_iso)
        first = _parse_iso(f["first_seen"]) or now
        age_days = (now - first).total_seconds() / 86400.0
        if f["class"] == "weak" and age_days > WEAK_AGE_DAYS:
            f["aged_out"] = True
            aged.append(f)
        else:
            kept.append(f)

    if any(f["severity"] == "CRITICAL" for f in kept):
        overall = "CRITICAL"
    elif kept:
        overall = "WARN"
    elif unchecked:
        overall = "UNCHECKED"
    else:
        overall = "OK"

    return {
        "generated_at": now_iso,
        "adr": "ADR-066",
        "contour": "C1",
        "overall": overall,
        "exit_code": EXIT_BY_OVERALL[overall],
        "counts": {"critical": sum(1 for f in kept if f["severity"] == "CRITICAL"),
                   "warn": sum(1 for f in kept if f["severity"] == "WARN"),
                   "aged": len(aged), "unchecked": len(unchecked)},
        "held_protocols": (sorted(held) if held is not None else None),
        "house_view_posture": (house_view or {}).get("overall_posture") if house_view else None,
        "findings": kept,
        "aged": aged,
        "unchecked": unchecked,
        "note": "Только сверка. Расхождение — не приказ двигать капитал, а факт, что "
                "решение нигде не названо. RiskPolicy/kill-switch не затронуты (ADR-066 P5).",
    }


# ── обвязка ──────────────────────────────────────────────────────────────────

def _prev_first_seen(report_path: str = REPORT_PATH) -> dict[str, str]:
    try:
        with open(report_path, encoding="utf-8") as fh:
            prev = json.load(fh)
        out = {}
        for f in prev.get("findings", []) + prev.get("aged", []):
            if f.get("key") and f.get("first_seen"):
                out[f["key"]] = f["first_seen"]
        return out
    except Exception:  # noqa: BLE001
        return {}


def build_report(root: str = REPO_ROOT, now: dt.datetime | None = None,
                 report_path: str = REPORT_PATH) -> dict:
    return run_checks(
        _load_json(HOUSE_VIEW_REL, root),
        _load_json(POSITIONS_REL, root),
        _load_json(RATIONALE_REL, root),
        _load_json(SIGNALS_REL, root),
        now or dt.datetime.now(dt.timezone.utc),
        prev_first_seen=_prev_first_seen(report_path),
        red_team_doc=_load_json(RED_TEAM_REL, root),
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="ADR-066 C1 — сверка house_view офиса с фактической аллокацией")
    ap.add_argument("--run", "--once", action="store_true", dest="run",
                    help="один прогон против живых артефактов")
    ap.add_argument("--exit-zero", action="store_true",
                    help="плановый режим: exit 0, если сверка ВЫПОЛНИЛАСЬ (вердикт — "
                         "в отчёте). Иначе находка неотличима от сломанного модуля.")
    ap.add_argument("--report", default=REPORT_PATH)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0

    report = build_report(report_path=args.report)

    from spa_core.utils.atomic import atomic_save
    atomic_save(report, args.report)

    c = report["counts"]
    print(f"house_view_gap: {report['overall']} — critical={c['critical']} warn={c['warn']} "
          f"aged={c['aged']} unchecked={c['unchecked']} "
          f"(постура {report['house_view_posture']}, книга "
          f"{len(report['held_protocols']) if report['held_protocols'] is not None else '?'} поз.)")
    for f in report["findings"][:30]:
        print(f"  [{f['severity']}] {f['message']}")
    for u in report["unchecked"][:10]:
        print(f"  [UNCHECKED] {u['check']}: {u['reason']}")
    return 0 if args.exit_zero else report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
