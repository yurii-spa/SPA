"""evidence_staleness_monitor.py — кто-нибудь наконец СПРАШИВАЕТ лестницу устаревания.

# LLM_FORBIDDEN

Канал без единого потребителя
=============================
`spa_core/governance/evidence_staleness.py` построен решением владельца
(**ADR-167**, 2026-08-29, вариант 1): протокол, наблюдение по которому старше
168 ч, уходит в де-риск; а если ненаблюдаемыми стали ВСЕ держимые протоколы
разом — это симптом НАШЕЙ поломки, и канал обязан поднять **тревогу**, а не
эвакуировать книгу.

Замер 2026-09-05 (цикл #494): у модуля **НОЛЬ вызовов** вне собственных тестов.

    grep -rn evidence_staleness --exclude-dir=.git .   →   только tests/ и docs/

То есть решение владельца принято, канал написан, 22 теста зелены — и он
не отвечает никому, потому что его никто не спрашивает. Тревога по массовой
слепоте не может прозвучать: некому нажать. Это ровно тот класс, что и
ADR-209 («измеритель построен, до реестра не доехал»), только здесь молчит
не измеритель, а объявленная владельцем РЕАКЦИЯ.

Почему это не гипотеза, а сегодняшнее состояние
===============================================
2026-09-05 17:44Z единственный источник всех живых APY/TVL — `yields.llama.fi/pools`
— отдавал **HTTP 200 с телом `GET,HEAD`** (8 байт, `content-type: application/json`,
`age: 856` — то есть кешировано их CDN). Генератор разобрал это верно и честно
(`feed_reachable: false`, `live_count: 0`, у каждого адаптера `live_apy_fresh: false`,
`live_apy_as_of` СОХРАНЁН на момент реального наблюдения 06:00Z — перенос
последнего наблюдения работает как задумано).

Живая книга в тот момент: наблюдения 11.8 ч ⇒ `FRESH` ⇒ действие `NONE`. Верно.
Но если фид не оживёт ещё ~30 ч, ВСЕ держимые протоколы уйдут из `FRESH`, канал
вернёт `MASS_BLINDNESS`, — и об этом сегодня не узнал бы никто.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ — первым абзацем
========================================================
**Делает:** каждый цикл спрашивает канал на ЖИВОЙ книге и НАЗЫВАЕТ ответ
(пункты 3 и 4 карточки `agent-derisk-po-slepote-podklyuchit-k-rebalansu`:
«`MASS_BLINDNESS` не трогает аллокацию вообще и поднимает тревогу» ·
«каждое срабатывание называет протокол, возраст наблюдения и сумму»).

**НЕ делает:** не трогает целевую аллокацию, не двигает капитал, не отменяет
и не назначает ребаланс. Пункты 1–2 той же карточки (`HARD_STALE` ⇒ целевой
вес 0; де-риск-нога в обход экономического гейта) — **money-path, owner-gated**,
и остаются на карточке. Сторож только НАЗЫВАЕТ — тот же порядок, что у
`pool_identity_collision` и `apy_composition`.

Третий исход обязателен
=======================
Нечитаемый вход, отсутствующий артефакт, пустая книга — это **`UNCHECKED`
с названной причиной**, а не «OK». «Не измерено», выданное за «всё хорошо», —
fail-OPEN тише красного, и именно на нём этот проект уже обжигался
(`.claude/rules/deployment.md`, класс «не измерено, выданное за ответ»).

Деньги без часов наблюдения
===========================
Отдельной строкой называется капитал в стадии `UNKNOWN_AGE`: у такого ключа
нет отметки наблюдения вообще, и канал его в де-риск НЕ берёт **по построению**
(сокращать по незнанию возраста — угадывание). Значит и после того, как
money-path-нога будет подключена, эти деньги останутся лестнице невидимы.
Замер 05.09: `fluid_usdc` — **$20 000, 21 % книги** (`live_apy_as_of: null`).
Сам ключ уже стои́т у владельца по другому поводу
(`owner-decision-dva-imeni-odin-kontrakt-20-deneg-stoyat`); здесь он назван
как ТРЕТЬЯ грань того же корня, а не как новый вопрос.

stdlib · детерминирован · часы инъектируются · ничего не двигает.

    python3 -m spa_core.monitoring.evidence_staleness_monitor
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.governance import evidence_staleness as es  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

REPO_ROOT = _REPO_ROOT
REPORT_REL = os.path.join("data", "evidence_staleness.json")

OK = "OK"
WARN = "WARNING"
CRITICAL = "CRITICAL"
UNCHECKED = "UNCHECKED"


def _read_json(path: str) -> tuple[object, str | None]:
    """``(документ, причина_отказа)``. Никогда не поднимает — отказ ИМЕНУЕТСЯ."""
    if not os.path.exists(path):
        return None, f"нет файла {os.path.basename(path)}"
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return None, f"{os.path.basename(path)} не прочитан: {exc}"


def _held_from(doc: object) -> tuple[dict, str | None]:
    """Держимые суммы из ``current_positions.json``.

    Пустая книга — НЕ «всё свежо»: мерить нечего, и это третий исход.
    """
    if not isinstance(doc, dict):
        return {}, f"current_positions.json не объект, а {type(doc).__name__}"
    pos = doc.get("positions")
    if not isinstance(pos, dict):
        return {}, (f"current_positions.json: 'positions' имеет тип "
                    f"{type(pos).__name__}, ожидался объект")
    held = {str(k): float(v) for k, v in pos.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0}
    if not held:
        return {}, "книга пуста — устаревание наблюдения мерить не на чем"
    return held, None


def _observed_from(doc: object) -> tuple[dict, str | None]:
    """``{протокол: отметка НАБЛЮДЕНИЯ}`` из ``adapter_status.json``.

    Берём ``live_apy_as_of`` — время, когда значение было НАБЛЮДЕНО, а не время
    записи файла: перенос последнего наблюдения обязан стареть на своих часах
    (ADR-167; `last_updated` при переносе честно обновляется на «сейчас», и
    судить по нему значило бы объявить перенесённое значение свежим).
    """
    if not isinstance(doc, dict):
        return {}, f"adapter_status.json не объект, а {type(doc).__name__}"
    ad = doc.get("adapters")
    if not isinstance(ad, dict):
        return {}, (f"adapter_status.json: 'adapters' имеет тип "
                    f"{type(ad).__name__}, ожидался объект")
    return {str(k): (v.get("live_apy_as_of") if isinstance(v, dict) else None)
            for k, v in ad.items()}, None


def run(root: str = REPO_ROOT, *, now: dt.datetime | None = None,
        write: bool = True, data_dir: str | None = None) -> dict:
    """Спросить канал ADR-167 на живой книге и составить отчёт."""
    now = now or dt.datetime.now(dt.timezone.utc)
    base = data_dir or os.path.join(root, "data")

    unchecked: list[str] = []
    pos_doc, why = _read_json(os.path.join(base, "current_positions.json"))
    if why:
        unchecked.append(why)
    st_doc, why = _read_json(os.path.join(base, "adapter_status.json"))
    if why:
        unchecked.append(why)

    held, why = _held_from(pos_doc) if pos_doc is not None else ({}, None)
    if why:
        unchecked.append(why)
    observed, why = _observed_from(st_doc) if st_doc is not None else ({}, None)
    if why:
        unchecked.append(why)

    if unchecked:
        # Нечего мерить ⇒ говорим это вслух. Не «OK», не ноль, не скип.
        report = {
            "generated_at": now.isoformat(),
            "generated_by": "spa_core.monitoring.evidence_staleness_monitor",
            "schema_version": 1,
            "overall": UNCHECKED,
            "action": None,
            "reason": "; ".join(unchecked),
            "counts": {"fresh": 0, "soft_stale": 0, "hard_stale": 0,
                       "unknown_age": 0, "unchecked": len(unchecked)},
            "usd": {"fresh": 0.0, "soft_stale": 0.0, "hard_stale": 0.0,
                    "unknown_age": 0.0, "total": 0.0},
            "protocols": [],
            "to_derisk": [],
            "unchecked": unchecked,
            "ladder": {"soft_stale_h": es.SOFT_STALE_H, "hard_stale_h": es.HARD_STALE_H},
        }
        if write:
            atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
        return report

    decision = es.decide(held, observed, now=now)

    rows = [x.to_dict() for x in decision.all_protocols]
    by_stage = {s: [r for r in rows if r["stage"] == s]
                for s in (es.FRESH, es.SOFT_STALE, es.HARD_STALE, es.UNKNOWN_AGE)}
    counts = {
        "fresh": len(by_stage[es.FRESH]),
        "soft_stale": len(by_stage[es.SOFT_STALE]),
        "hard_stale": len(by_stage[es.HARD_STALE]),
        "unknown_age": len(by_stage[es.UNKNOWN_AGE]),
        "unchecked": 0,
    }
    usd = {k: round(sum(r["held_usd"] for r in v), 2)
           for k, v in (("fresh", by_stage[es.FRESH]),
                        ("soft_stale", by_stage[es.SOFT_STALE]),
                        ("hard_stale", by_stage[es.HARD_STALE]),
                        ("unknown_age", by_stage[es.UNKNOWN_AGE]))}
    usd["total"] = round(sum(r["held_usd"] for r in rows), 2)

    # Массовая слепота — симптом НАШЕЙ поломки: тревога, но капитал не трогаем.
    # HARD_STALE — названный, но НЕ исполненный де-риск: исполнение money-path.
    if decision.action == es.ACTION_MASS_BLINDNESS:
        overall = CRITICAL
    elif decision.action == es.ACTION_DERISK:
        overall = CRITICAL
    elif counts["soft_stale"] or counts["unknown_age"]:
        overall = WARN
    else:
        overall = OK

    report = {
        "generated_at": now.isoformat(),
        "generated_by": "spa_core.monitoring.evidence_staleness_monitor",
        "schema_version": 1,
        "overall": overall,
        "action": decision.action,
        "reason": decision.reason,
        "counts": counts,
        "usd": usd,
        "protocols": rows,
        "to_derisk": [x.to_dict() for x in decision.to_derisk],
        "unchecked": [],
        "ladder": {"soft_stale_h": es.SOFT_STALE_H, "hard_stale_h": es.HARD_STALE_H},
    }
    if write:
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    """0 — норма · 1 — предупреждение · 2 — тревога ИЛИ не измерено (fail-CLOSED)."""
    if report["overall"] in (CRITICAL, UNCHECKED):
        return 2
    return 1 if report["overall"] == WARN else 0


def main(argv=None, now: dt.datetime | None = None) -> int:  # noqa: D103
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать книгу и писать отчёт в ЧУЖОЙ каталог (обычно <прод>/data)")
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)

    report = run(root=args.root, now=now, write=not args.no_write, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code(report)

    c, u = report["counts"], report["usd"]
    print(f"устаревание наблюдения (ADR-167): {report['overall']} · действие "
          f"{report['action']} — свежих {c['fresh']} · мягких {c['soft_stale']} · "
          f"жёстких {c['hard_stale']} · без часов {c['unknown_age']}")
    for line in report["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {line}")
    if report["action"] == es.ACTION_MASS_BLINDNESS:
        print(f"   [ТРЕВОГА] {report['reason']}")
        print("   капитал НЕ трогаем: эвакуировать книгу по собственной аварии "
              "хуже, чем подождать (ADR-167)")
    for r in report["to_derisk"]:
        print(f"   [ДЕ-РИСК НАЗВАН] {r['protocol']}: ${r['held_usd']:,.0f} — {r['reason']}")
    if report["to_derisk"]:
        print("   исполнение — money-path, owner-gated: карточка "
              "`agent-derisk-po-slepote-podklyuchit-k-rebalansu`. Сторож только НАЗЫВАЕТ")
    if c["unknown_age"]:
        names = ", ".join(sorted(r["protocol"] for r in report["protocols"]
                                 if r["stage"] == es.UNKNOWN_AGE))
        print(f"   [БЕЗ ЧАСОВ] ${u['unknown_age']:,.0f} стоит на ключах без отметки "
              f"наблюдения ({names}) — лестница их не видит ПО ПОСТРОЕНИЮ")
    if report["overall"] == OK:
        print(f"   вся книга (${u['total']:,.0f}) наблюдается свежее "
              f"{report['ladder']['soft_stale_h']:.0f} ч")
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
