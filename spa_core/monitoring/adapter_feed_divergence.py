"""adapter_feed_divergence.py — два артефакта ОДНОГО цикла говорят о ОДНОМ протоколе разное.

Вопрос, на который не отвечал ни один сторож
============================================
Про адаптеры уже спрашивают трёх сторожей, и каждый честно отвечает на СВОЙ вопрос:

| вопрос | кто отвечает | чего НЕ проверяет |
|---|---|---|
| фид вообще жив? | `adapter_watchdog` | сходятся ли два фида между собой |
| число живое или литерал? | провенанс `tvl_source`/`live_apy` ВНУТРИ одного артефакта | второй артефакт |
| адаптер импортируется? | `deployment_acceptance` | что он отдаёт |

Ни один не спрашивает: **`data/adapter_status.json` и
`data/adapter_orchestrator_status.json` — говорят ли они об одном протоколе одно и
то же.** Замер 2026-08-26 22:0xZ (цикл #389), оба файла произведены с разницей
0.6 секунды одним дневным циклом:

    pendle:  adapter_status  apy 8.0    live_apy=null  tier 2   tvl $500 000 000 (static)
             orchestrator    apy 13.9673 live_data=true tier T3  tvl $6 151 592   (live)

Один протокол, один цикл, **1.75× по доходности и РАЗНЫЙ ТИР** — а тир решает
потолок концентрации (T2 20 % против T3). Это `pendle`, то есть 20 % книги, и
ровно то число, которое диагностика CIO (`docs/research/RS-portfolio-cio-diagnosis.md`)
назвала «единственные $20k, ранжированные по наблюдённому числу». Дефект D6 ADR-060
описан 02.08 и жив 25 дней спустя ДОСЛОВНО — потому что его никто не мерил повторно:
находка была записана в карточку, а не в сторожа.

Что этот модуль НЕ делает
=========================
Не выбирает победивший источник, не двигает капитал, не гейтит исполнение и не
трогает RiskPolicy. **Только называет расхождение.** Выбор источника для 20 % книги —
решение владельца (карточка), а не автономная правка.

Почему расхождения разделены по РОДУ (главное решение дизайна)
==============================================================
Свалить всё в «фиды разошлись» значило бы соврать в двух местах сразу.

* ``live_vs_live`` — **обе** стороны заявляют живое наблюдение, а числа разные.
  Только это — противоречие двух наблюдений, и только оно поднимает инвариант 2
  (fail-CLOSED при расхождении фидов). CRITICAL.
* ``literal_vs_live`` — одна сторона живая, вторая подставила ``fallback``, потому
  что не получила чтения. Это **не** спор наблюдений: вторая сторона не наблюдала
  ничего. Ровно это уточнение стоит дословно в карточке D6
  (`agent-tuner-constraints-drift-and-feed-divergence`), и потерять его нельзя —
  иначе починка поедет не туда. WARN.
* ``both_literal`` — не наблюдал НИКТО, и потребитель видит два литерала. Числа могут
  совпасть до знака, и «сошлось» будет означать «одинаково выдумано». INFO, но
  вслух: молчание здесь неотличимо от согласия двух измерений.
* ``tier_mismatch`` — стороны кладут протокол в РАЗНЫЕ тиры. Отдельный род, потому
  что последствие другое: тир — это потолок концентрации, а не число в отчёте.

**TVL сравнивается ЧИСЛОМ только когда обе стороны заявили ``live``.** Иначе
сравнивались бы литерал и наблюдение, и сторож краснел бы каждый день на 6 из 8
протоколов — на состоянии, которое УЖЕ названо и УЖЕ решено (ADR-053: константа
порог TVL не проходит; карточка про $12B у aave_v3 открыта). Сторож, который каждый
день кричит о решённом, обучает себя игнорировать: расхождение провенанса пишется
как ``tvl_provenance`` (INFO), а не как противоречие.

Чем измеряется «один цикл» (иначе сравниваются два МОМЕНТА, а не два фида)
=========================================================================
Если артефакты произведены далеко друг от друга, разные числа — нормальная жизнь
рынка, а не расхождение фидов. Поэтому:

* разрыв отметок больше ``MAX_SKEW_S`` ⇒ вся сверка ``UNCHECKED`` (``snapshot_skew``),
  вердикт не выносится вовсе;
* любой вход старше ``MAX_AGE_S`` ⇒ ``UNCHECKED`` (``stale_input``) — сторож не имеет
  права говорить в настоящем времени о вчерашнем снимке (урок #222);
* возраст не измерен ⇒ это ГОВОРИТСЯ, а не подразумевается свежим.

Время — ВХОД (``now=``), а не окружение: правило `.claude/rules/deployment.md`.

Fail-CLOSED
===========
Файла нет / JSON битый / нет секции адаптеров ⇒ ``UNCHECKED`` и код возврата 2.
**Пересечение пусто («ни одного общего протокола») ⇒ CRITICAL, а не чистый зачёт:**
сторож, которому нечего было сравнить, обязан отличаться от сторожа, который сравнил
и не нашёл расхождений.

Коды возврата: 0 — сошлось · 1 — есть WARN · 2 — CRITICAL или UNCHECKED.
LLM_FORBIDDEN. Только stdlib. Читает read-only, пишет ОДИН свой артефакт.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso
from spa_core.utils.atomic import atomic_save

REPORT_REL = os.path.join("data", "adapter_feed_divergence.json")
STATUS_REL = os.path.join("data", "adapter_status.json")
ORCH_REL = os.path.join("data", "adapter_orchestrator_status.json")

#: Максимальный разрыв между отметками двух артефактов, при котором они ещё считаются
#: снимками ОДНОГО такта. Замер 26.08: 0.6 с (оба пишет дневной цикл подряд). Потолок
#: взят с запасом на медленный опрос адаптеров (`duration_sec` оркестратора ~1.2 с,
#: полный опрос 34 адаптеров исполнения — минуты), но не настолько большим, чтобы
#: под него подлез снимок соседнего часа.
MAX_SKEW_S = 900.0

#: Старше этого — сверка отказывается судить. 26 ч: такт дневного цикла (24 ч) плюс
#: запас, тот же порядок, что `slo_hours: 26` у артефактов дневного цикла в манифесте.
MAX_AGE_S = 26 * 3600.0

#: Допуск сравнения доходности, процентных пунктов. Обе стороны печатают округлённое
#: до 4 знаков, поэтому шум округления — единицы 1e-4; порог на два порядка выше него
#: и на два порядка ниже наблюдённого расхождения (5.97 пп).
APY_TOLERANCE_PP = 0.01

#: Допуск сравнения TVL, доля. Живые TVL двух независимых опросов одного пула
#: расходятся на движении блока; 1 % — шум, больше — разные предметы.
TVL_TOLERANCE_FRAC = 0.01

CRITICAL, WARN, INFO, UNCHECKED = "CRITICAL", "WARN", "INFO", "UNCHECKED"


def _load(rel: str, root: str):
    """``(data, reason)`` — ``reason`` непуст ⇒ вход НЕ прочитан (fail-CLOSED)."""
    path = os.path.join(root, rel)
    try:
        with open(path) as fh:
            return json.load(fh), ""
    except FileNotFoundError:
        return None, f"файла нет на диске: {rel}"
    except (OSError, ValueError) as e:  # noqa: BLE001
        return None, f"{rel} не прочитан: {e}"


def _norm_tier(value) -> str | None:
    """``1``/``"1"``/``"T1"`` → ``"T1"``. Неузнанное — ``None`` («не измерено»).

    Две стороны пишут тир РАЗНЫМ типом (исполнение — целым, оркестратор — строкой),
    и сравнение без нормализации объявило бы расхождением любую пару.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return f"T{int(value)}"
    text = str(value).strip().upper()
    if not text:
        return None
    if text.startswith("T") and text[1:].isdigit():
        return text
    if text.isdigit():
        return f"T{int(text)}"
    return None


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _observed_apy_status(entry: dict) -> tuple[float | None, float | None]:
    """Сторона `adapter_status.json`: ``(наблюдённое, предъявленное потребителю)``.

    Наблюдённым считается ТОЛЬКО ``live_apy``; ``apy`` может быть равен ему, а может
    быть ``fallback_apy`` — по самому ``apy`` эти два случая неразличимы, и именно на
    этой неразличимости построен fail-OPEN провенанс, найденный ADR-060 §1.2.
    """
    return _num(entry.get("live_apy")), _num(entry.get("apy"))


def _observed_apy_orch(entry: dict) -> tuple[float | None, float | None]:
    """Сторона оркестратора: наблюдённым считается ``apy_pct`` при ``live_data: true``."""
    shown = _num(entry.get("apy_pct"))
    return (shown if entry.get("live_data") is True else None), shown


def _finding(protocol: str, kind: str, severity: str, message: str, **extra) -> dict:
    rec = {"protocol": protocol, "kind": kind, "severity": severity, "message": message}
    rec.update(extra)
    return rec


def _compare_protocol(protocol: str, s: dict, o: dict) -> list[dict]:
    """Все расхождения по одному протоколу. Нечитаемая сторона ⇒ ``UNCHECKED``-запись."""
    out: list[dict] = []

    # ── доходность ───────────────────────────────────────────────────────────
    s_live, s_shown = _observed_apy_status(s)
    o_live, o_shown = _observed_apy_orch(o)
    if s_shown is None or o_shown is None:
        out.append(_finding(
            protocol, "apy", UNCHECKED,
            f"{protocol}: доходность не измерена — "
            f"adapter_status={'нет числа' if s_shown is None else s_shown}, "
            f"orchestrator={'нет числа' if o_shown is None else o_shown}",
            adapter_status_apy=s_shown, orchestrator_apy=o_shown))
    elif s_live is not None and o_live is not None:
        delta = abs(s_live - o_live)
        if delta > APY_TOLERANCE_PP:
            out.append(_finding(
                protocol, "apy_live_vs_live", CRITICAL,
                f"{protocol}: ОБА фида заявляют живое наблюдение и не сходятся — "
                f"adapter_status {s_live} пп против orchestrator {o_live} пп "
                f"(разница {round(delta, 4)} пп). Это противоречие ДВУХ наблюдений: "
                f"инвариант 2 требует fail-CLOSED, а потребитель выбирает молча",
                adapter_status_apy=s_live, orchestrator_apy=o_live,
                delta_pp=round(delta, 4)))
    elif s_live is None and o_live is None:
        out.append(_finding(
            protocol, "apy_both_literal", INFO,
            f"{protocol}: живого наблюдения доходности нет НИ У ОДНОЙ стороны — "
            f"потребителю предъявлены два литерала ({s_shown} пп и {o_shown} пп). "
            f"Совпадение чисел здесь означало бы «одинаково выдумано», а не согласие",
            adapter_status_apy=s_shown, orchestrator_apy=o_shown))
    else:
        live_side, live_val = ("orchestrator", o_live) if s_live is None else ("adapter_status", s_live)
        dead_side, dead_val = ("adapter_status", s_shown) if s_live is None else ("orchestrator", o_shown)
        delta = abs(live_val - dead_val)
        if delta > APY_TOLERANCE_PP:
            out.append(_finding(
                protocol, "apy_literal_vs_live", WARN,
                f"{protocol}: {live_side} наблюдает {live_val} пп, а {dead_side} "
                f"предъявляет литерал {dead_val} пп (разница {round(delta, 4)} пп). "
                f"Это НЕ спор двух наблюдений — вторая сторона не наблюдала ничего; "
                f"починка — дать ей фид, а не выбрать число",
                live_side=live_side, live_apy=live_val,
                literal_side=dead_side, literal_apy=dead_val,
                delta_pp=round(delta, 4)))

    # ── тир (потолок концентрации, а не строка в отчёте) ─────────────────────
    s_tier, o_tier = _norm_tier(s.get("tier")), _norm_tier(o.get("tier"))
    if s_tier is None or o_tier is None:
        out.append(_finding(
            protocol, "tier", UNCHECKED,
            f"{protocol}: тир не измерен — adapter_status={s.get('tier')!r}, "
            f"orchestrator={o.get('tier')!r}",
            adapter_status_tier=s.get("tier"), orchestrator_tier=o.get("tier")))
    elif s_tier != o_tier:
        out.append(_finding(
            protocol, "tier_mismatch", WARN,
            f"{protocol}: стороны кладут протокол в РАЗНЫЕ тиры — "
            f"adapter_status {s_tier}, orchestrator {o_tier}. Тир — это потолок "
            f"концентрации, а не подпись: два ответа означают два разных потолка "
            f"на один и тот же капитал",
            adapter_status_tier=s_tier, orchestrator_tier=o_tier))

    # ── TVL: числом — только когда ОБЕ стороны заявили живое ─────────────────
    s_tvl_live = str(s.get("tvl_source") or "").lower() == "live"
    o_tvl_live = str(o.get("tvl_source") or "").lower() == "live"
    s_tvl, o_tvl = _num(s.get("tvl_usd")), _num(o.get("tvl_usd"))
    if s_tvl_live and o_tvl_live:
        if s_tvl is None or o_tvl is None:
            out.append(_finding(
                protocol, "tvl", UNCHECKED,
                f"{protocol}: обе стороны заявили живой TVL, но числа нет — "
                f"adapter_status={s.get('tvl_usd')!r}, orchestrator={o.get('tvl_usd')!r}",
                adapter_status_tvl=s.get("tvl_usd"), orchestrator_tvl=o.get("tvl_usd")))
        else:
            base = max(abs(s_tvl), abs(o_tvl))
            if base > 0 and abs(s_tvl - o_tvl) / base > TVL_TOLERANCE_FRAC:
                out.append(_finding(
                    protocol, "tvl_live_vs_live", CRITICAL,
                    f"{protocol}: ОБА фида заявляют живой TVL и не сходятся — "
                    f"adapter_status ${s_tvl:,.0f} против orchestrator ${o_tvl:,.0f}. "
                    f"Порог TVL проверяется ТОЛЬКО живым числом (ADR-053), "
                    f"а живых чисел здесь два",
                    adapter_status_tvl=s_tvl, orchestrator_tvl=o_tvl))
    elif s_tvl_live != o_tvl_live:
        live_side = "orchestrator" if o_tvl_live else "adapter_status"
        out.append(_finding(
            protocol, "tvl_provenance", INFO,
            f"{protocol}: живой TVL есть только у стороны {live_side} "
            f"(adapter_status ${s_tvl if s_tvl is not None else float('nan'):,.0f} "
            f"[{s.get('tvl_source')}], orchestrator "
            f"${o_tvl if o_tvl is not None else float('nan'):,.0f} "
            f"[{o.get('tvl_source')}]). Состояние НАЗВАНО и решено (ADR-053: "
            f"константа порог не проходит) — здесь оно только зафиксировано, "
            f"противоречием наблюдений не является",
            adapter_status_tvl=s_tvl, orchestrator_tvl=o_tvl,
            adapter_status_tvl_source=s.get("tvl_source"),
            orchestrator_tvl_source=o.get("tvl_source")))
    return out


def _protocols(status_doc, orch_doc) -> tuple[dict, dict, list[str]]:
    """``(по_имени_из_adapter_status, по_имени_из_оркестратора, причины)``."""
    reasons: list[str] = []
    s_map: dict = {}
    raw_s = (status_doc or {}).get("adapters")
    if isinstance(raw_s, dict):
        s_map = {k: v for k, v in raw_s.items() if isinstance(v, dict)}
    else:
        reasons.append("adapter_status.json: секции `adapters` нет или она не объект — "
                       "сравнивать нечем")
    o_map: dict = {}
    raw_o = (orch_doc or {}).get("adapters")
    if isinstance(raw_o, list):
        for rec in raw_o:
            if isinstance(rec, dict) and rec.get("protocol"):
                o_map[str(rec["protocol"])] = rec
    else:
        reasons.append("adapter_orchestrator_status.json: секции `adapters` нет или она "
                       "не список — сравнивать нечем")
    return s_map, o_map, reasons


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, data_dir: str | None = None) -> dict:
    """Сверить два артефакта и вернуть отчёт (он же пишется в ``REPORT_REL``)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")

    def _rel(rel: str) -> str:
        return os.path.join(base, os.path.basename(rel))

    findings: list[dict] = []
    unchecked: list[str] = []
    inputs: dict = {}

    docs = {}
    for key, rel in (("adapter_status", STATUS_REL), ("orchestrator", ORCH_REL)):
        path = _rel(rel)
        try:
            with open(path) as fh:
                docs[key] = json.load(fh)
        except FileNotFoundError:
            docs[key] = None
            unchecked.append(f"{os.path.basename(rel)}: файла нет на диске ({path})")
        except (OSError, ValueError) as e:  # noqa: BLE001
            docs[key] = None
            unchecked.append(f"{os.path.basename(rel)}: не прочитан — {e}")
        stamp = _parse_iso((docs[key] or {}).get("generated_at")
                           if isinstance(docs[key], dict) else None)
        inputs[key] = {
            "path": os.path.basename(rel),
            "generated_at": stamp.isoformat() if stamp else None,
            "age_s": round((now - stamp).total_seconds(), 1) if stamp else None,
        }

    stamps = {k: _parse_iso(v["generated_at"]) for k, v in inputs.items()}
    if all(docs.values()):
        for key, stamp in stamps.items():
            if stamp is None:
                unchecked.append(
                    f"{key}: отметка `generated_at` не прочитана — сказать, об одном ли "
                    f"такте идёт речь, НЕЧЕМ (сверка не выносится)")
            elif (now - stamp).total_seconds() > MAX_AGE_S:
                unchecked.append(
                    f"{key}: снимку {round((now - stamp).total_seconds() / 3600, 1)} ч "
                    f"при потолке {round(MAX_AGE_S / 3600, 1)} ч — сторож отказывается "
                    f"судить о фидах по вчерашнему снимку (stale_input)")
        if all(stamps.values()):
            skew = abs((stamps["adapter_status"] - stamps["orchestrator"]).total_seconds())
            if skew > MAX_SKEW_S:
                unchecked.append(
                    f"snapshot_skew: артефакты произведены с разрывом {round(skew, 1)} с "
                    f"при потолке {MAX_SKEW_S} с — разные числа означали бы разные МОМЕНТЫ, "
                    f"а не разные фиды; сверка не выносится")

    s_map = o_map = {}
    if not unchecked:
        s_map, o_map, reasons = _protocols(docs["adapter_status"], docs["orchestrator"])
        unchecked.extend(reasons)

    shared = sorted(set(s_map) & set(o_map)) if not unchecked else []
    if not unchecked and not shared:
        findings.append(_finding(
            "-", "no_overlap", CRITICAL,
            f"общих протоколов у двух артефактов НЕТ вовсе "
            f"(adapter_status: {len(s_map)}, orchestrator: {len(o_map)}) — "
            f"сравнивать было нечего. Это НЕ чистый зачёт: сторож, которому нечего "
            f"сравнить, обязан отличаться от сторожа, который сравнил и не нашёл"))

    for protocol in shared:
        findings.extend(_compare_protocol(protocol, s_map[protocol], o_map[protocol]))

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "warn": sum(1 for f in findings if f["severity"] == WARN),
        "info": sum(1 for f in findings if f["severity"] == INFO),
        "unchecked": len(unchecked) + sum(1 for f in findings if f["severity"] == UNCHECKED),
    }
    if counts["unchecked"]:
        overall = UNCHECKED
    elif counts["critical"]:
        overall = CRITICAL
    elif counts["warn"]:
        overall = WARN
    else:
        overall = "OK"

    report = {
        "generated_at": now.isoformat(),
        "generated_by": "spa_core/monitoring/adapter_feed_divergence.py",
        "schema_version": 1,
        "overall": overall,
        "counts": counts,
        "compared_protocols": shared,
        "findings": findings,
        "unchecked": unchecked,
        "inputs": inputs,
    }
    if write:
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    """0 — сошлось · 1 — есть WARN · 2 — CRITICAL или UNCHECKED (fail-CLOSED).

    Отчёта без счётчиков быть не должно, и потому именно здесь — самое удобное место
    соврать. Привычное ``report.get("counts") or {}`` превратило бы «отчёт не тот /
    отчёта нет» в **ноль находок**, то есть в код возврата 0 — «сошлось». Это ровно тот
    класс, ради которого сторож и заведён (инвариант #17: отсутствие наблюдения обязано
    иметь СВОЁ значение, а не сливаться с благополучием), и храповик
    ``test_absent_observation_ratchet`` поймал его в первом же прогоне ЗДЕСЬ.
    Нет счётчиков ⇒ 2, а не 0.
    """
    counts = report.get("counts")
    if not isinstance(counts, dict):
        return 2
    if counts.get("unchecked") or counts.get("critical"):
        return 2
    if counts.get("warn"):
        return 1
    return 0


def main(argv=None, *, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать оба артефакта и писать отчёт в ЧУЖОЙ каталог "
                         "(обычно <прод>/data)")
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)

    report = run(root=args.root, now=now, write=not args.no_write,
                 data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code(report)

    c = report["counts"]
    print(f"сверка двух фидов адаптеров: {report['overall']} "
          f"(critical={c['critical']} warn={c['warn']} info={c['info']} "
          f"unchecked={c['unchecked']}); протоколов сверено: "
          f"{len(report['compared_protocols'])}")
    for line in report["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {line}")
    for f in report["findings"]:
        print(f"   [{f['severity']}] {f['message']}")
    if report["overall"] == "OK":
        print("   расхождений нет — оба артефакта говорят о каждом общем протоколе одно и то же")
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
