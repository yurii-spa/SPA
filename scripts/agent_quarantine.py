#!/usr/bin/env python3
"""agent_quarantine.py — агента не удаляют, его ОТКЛАДЫВАЮТ. И смотрят, кто закричит.

**Решение владельца 2026-08-28.** Флот вырос до 85 активных агентов, и никто не может
сказать, кто из них ещё нужен. Удалять вслепую нельзя, оставлять всё — значит вечно платить
за то, что никем не читается. Владелец предложил третий путь: **не удалять, а откладывать в
`attic/`**. Если кто-то закричит «пропал агент» — вернуть одной командой. Крик и есть
доказательство нужности; молчание — доказательство обратного.

Это не уборка, а ИЗМЕРИТЕЛЬНЫЙ ПРИБОР: другого способа узнать, нужен ли агент, у нас нет.

Замер 28.08 (`PRODUCES` объявлены у 61 из 72): у **32** агентов продукт читает код, у **12**
потребитель — владелец через Телеграм, и у **17** не потребляет никто. Важно: первая версия
замера объявила кандидатами `artifact_freshness`, `watchdog`, `self_heal`, `cycle_health` —
потому что спрашивала «кто читает ФАЙЛ в коде», а у монитора потребитель человек. Ошибку
поймали до того, как что-то выключили; в этом инструменте канал «потребитель — владелец»
учитывается наравне с кодом.

**Инструмент устроен как отказ, а не как действие.** Он гораздо чаще говорит «нет»:

1. агента нет в манифесте ⇒ отказ (решение о нём не принималось — тем более не нам его гасить);
2. агент в защищённом списке (деньги, трек, стоп-кран, go-live) ⇒ отказ ВСЕГДА, без флагов;
3. продукт агента кто-то потребляет ⇒ отказ;
4. потребление НЕ УДАЛОСЬ ИЗМЕРИТЬ ⇒ отказ (fail-CLOSED: «не знаю» это не «никто»);
5. нет plist или он уже в карантине ⇒ отказ.

Каждый карантин записывается в реестр с датой, причиной, замером на момент решения и ГОТОВОЙ
командой возврата. Возврат — одна команда, и он не требует помнить ничего.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
ATTIC = REPO / "attic" / "agents"
REGISTRY = ATTIC / "QUARANTINE.json"

#: Трогать НЕЛЬЗЯ ни при каких флагах. Список намеренно широкий: цена ложного
#: выключения здесь — деньги и трек, а цена лишнего агента — только шум.
PROTECTED_ROLES = {"allocation", "execution"}
PROTECTED_LABELS = {
    "com.spa.daily_cycle", "com.spa.orchestrator", "com.spa.apiserver",
    "com.spa.cloudflared", "com.spa.agent_health", "com.spa.portfolio_monitor",
    "com.spa.golive_freshness", "com.spa.intraday_equity", "com.spa.threat_reactor",
    "com.spa.self_heal", "com.spa.watchdog", "com.spa.rules_watchdog",
    "com.spa.artifact_freshness", "com.spa.rtmr_sense", "com.spa.telegram_bot",
    "com.spa.autopush", "com.spa.auto_push", "com.spa.daily_backup",
    "com.spa.weekly_backup", "com.spa.cycle_health", "com.spa.cycle_gap_monitor",
}
#: Слова в имени/цели, при которых отказываем даже если агента нет в списке выше.
PROTECTED_WORDS = ("kill", "emergency", "equity", "position", "risk", "backup", "track")


class Refused(Exception):
    """Отказ карантина. Сообщение обязано НАЗЫВАТЬ причину, а не просто «нельзя»."""


def _now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry() -> dict:
    if REGISTRY.is_file():
        try:
            return json.loads(REGISTRY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"quarantined": {}}
    return {"quarantined": {}}


def save_registry(reg: dict) -> None:
    ATTIC.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, REGISTRY)


def agent_entry(label: str, manifest_path: Path | None = None) -> dict:
    path = manifest_path or REPO / "architecture" / "manifest.json"
    try:
        agents = json.loads(path.read_text(encoding="utf-8")).get("agents") or []
    except (OSError, ValueError) as exc:
        raise Refused(f"манифест не читается ({exc}) — измерить нечем, отказ") from exc
    for a in agents:
        if a.get("label") == label:
            return a
    raise Refused(f"{label} нет в architecture/manifest.json — решение о нём не принималось")


def check_protected(label: str, entry: dict) -> None:
    if label in PROTECTED_LABELS:
        raise Refused(f"{label} в защищённом списке (деньги/трек/стоп-кран) — не карантинится никогда")
    if entry.get("role") in PROTECTED_ROLES:
        raise Refused(f"{label}: роль {entry['role']} защищена — не карантинится")
    hay = f"{label} {entry.get('role','')} {(entry.get('passport') or {}).get('goal','')}".lower()
    for w in PROTECTED_WORDS:
        if w in hay:
            raise Refused(f"{label}: в имени/цели слово «{w}» — соседство с деньгами или треком, отказ")


def check_daemon(label: str, entry: dict) -> None:
    """У демона потребитель приходит ПО СЕТИ, а не по файлу.

    Замер 29.08 предложил в кандидаты `com.spa.familyfund` — сервер API инвесторов:
    его `data/investors.json` действительно никто не читает из кода, потому что
    читают его по HTTP, а такого канала у нас нет вовсе. Отсутствие читателей файла
    у демона не доказывает НИЧЕГО, и выключение стоило бы живой службы.
    """
    if str(entry.get("schedule") or "").strip().lower() == "daemon":
        raise Refused(
            f"{label}: это демон — его потребитель приходит по сети, а не по файлу; "
            f"отсутствие читателей артефакта о нужности не говорит")


def check_unconsumed(label: str, measure) -> dict:
    """`measure(label)` обязана вернуть {'consumers': N, 'measured': bool}."""
    try:
        m = measure(label)
    except Exception as exc:                              # noqa: BLE001 — отказ важнее типа
        raise Refused(f"{label}: потребление НЕ измерено ({exc}) — «не знаю» это не «никто»") from exc
    if not m.get("measured"):
        raise Refused(f"{label}: потребление НЕ измерено — fail-CLOSED, отказ")
    if m.get("applicable") is False:
        raise Refused(
            f"{label}: агент объявил, что артефактов не производит — «ноль читателей» "
            f"у ничего это тавтология, а не улика. Годность такой службы мерится "
            f"доступностью/фактом отправки, и вопрос к владельцу другой")
    if m.get("consumers"):
        raise Refused(f"{label}: продукт потребляют ({m['consumers']}) — карантин отменён")
    return m


def quarantine(label: str, reason: str, measure, *, now=None, runner=subprocess.run,
               dry_run: bool = False) -> dict:
    entry = agent_entry(label)
    check_protected(label, entry)
    check_daemon(label, entry)
    m = check_unconsumed(label, measure)
    if dry_run:
        # Проверка инструмента не имеет права ДЕЙСТВОВАТЬ: см. докстринг `_live_measure`.
        return {"dry_run": True, "label": label, "would_quarantine": True, "measurement": m}

    reg = load_registry()
    if label in reg.get("quarantined", {}):
        raise Refused(f"{label} уже в карантине с {reg['quarantined'][label]['at']}")

    plist = LAUNCH_AGENTS / f"{label}.plist"
    was_loaded = plist.is_file()
    ATTIC.mkdir(parents=True, exist_ok=True)
    moved_to = None
    if was_loaded:
        runner(["launchctl", "bootout", f"gui/{os.getuid()}/{label}"], capture_output=True)
        moved_to = str((ATTIC / f"{label}.plist").relative_to(REPO))
        shutil.move(str(plist), str(ATTIC / f"{label}.plist"))

    reg.setdefault("quarantined", {})[label] = {
        "at": _now(now), "reason": reason,
        "measurement": m, "was_loaded": was_loaded,
        "plist_in_attic": moved_to,
        "restore": f"python3 scripts/agent_quarantine.py restore {label}",
        "schedule_was": entry.get("schedule"), "role": entry.get("role"),
    }
    save_registry(reg)
    return reg["quarantined"][label]


def restore(label: str, *, runner=subprocess.run) -> dict:
    reg = load_registry()
    rec = reg.get("quarantined", {}).get(label)
    if not rec:
        raise Refused(f"{label} не числится в карантине — возвращать нечего")
    src = ATTIC / f"{label}.plist"
    if rec.get("was_loaded"):
        if not src.is_file():
            raise Refused(f"{label}: plist не найден в attic — возврат невозможен, разбирать руками")
        LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(LAUNCH_AGENTS / f"{label}.plist"))
        runner(["launchctl", "bootstrap", f"gui/{os.getuid()}",
                str(LAUNCH_AGENTS / f"{label}.plist")], capture_output=True)
    del reg["quarantined"][label]
    save_registry(reg)
    return rec


def _live_measure(label: str) -> dict:
    """Настоящий замер потребления по ЧЕТЫРЁМ каналам.

    Первая редакция этой функции возвращала `consumers: 0` ВСЕГДА — то есть главная
    проверка инструмента была заглушкой, которая не могла отказать по существу. Поймано
    собственной «пробой отказа» 28.08: проба реально отложила живого агента
    (`com.spa.swarm_dwell`, возвращён немедленно). Отсюда же и `--dry-run` ниже:
    проверка инструмента не имеет права действовать.
    """
    import sys
    sys.path.insert(0, str(REPO))
    from spa_core.monitoring.artifact_consumers import consumers_of
    return consumers_of(label, REPO)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quarantine", help="отложить агента в attic")
    q.add_argument("label"); q.add_argument("--reason", required=True)
    q.add_argument("--dry-run", action="store_true",
                   help="только вердикт, НИЧЕГО не трогать")
    r = sub.add_parser("restore", help="вернуть агента из attic")
    r.add_argument("label")
    sub.add_parser("list", help="кто сейчас в карантине")
    args = ap.parse_args()

    if args.cmd == "list":
        reg = load_registry()
        qd = reg.get("quarantined", {})
        if not qd:
            print("в карантине никого")
            return 0
        for label, rec in sorted(qd.items()):
            print(f"  {label}  с {rec['at']}  — {rec['reason']}")
            print(f"      вернуть: {rec['restore']}")
        return 0
    try:
        if args.cmd == "quarantine":
            rec = quarantine(args.label, args.reason, _live_measure, dry_run=args.dry_run)
            if rec.get("dry_run"):
                print(f"ПРОШЁЛ БЫ карантин: {args.label} (ничего не тронуто)")
                print(f"  замер: {rec['measurement'].get('by_channel')}")
            else:
                print(f"отложен: {args.label}\n  вернуть: {rec['restore']}")
        else:
            restore(args.label)
            print(f"возвращён: {args.label}")
    except Refused as exc:
        print(f"ОТКАЗ: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
