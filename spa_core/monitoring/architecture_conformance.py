"""architecture_conformance.py — сторож соответствия флота конституции (ADR-066, Фаза 1).

Отвечает на вопрос, на который не отвечает ни один существующий сторож:
**соответствует ли работающий флот спроектированной архитектуре и замыкаются ли
петли потребления?** (deployment_drift — «тот ли код», deployment_acceptance —
«способен ли стартовать», agent_health — «жив ли процесс», rules_watchdog —
«соблюдены ли риск-правила»; см. таблицу в .claude/rules/deployment.md.)

Конституция — `architecture/manifest.json` (ADR-066 Фаза 0). Проверки:

  B1  флот ↔ манифест в обе стороны:
        загружен, в манифесте нет            → CRITICAL (инцидент swarm_dwell 2026-08-05)
        загружен при intent=retired          → CRITICAL (зомби)
        загружен при intent=designed         → CRITICAL (активация мимо ADR)
        intent=active, не загружен           → CRITICAL (мёртвый по конституции)
        intent=active, plist не персистентен → WARN     (не переживёт ребут — 2026-08-05)
        intent=unresolved                    → WARN weak (дрейф без решения; стареет)
  B2  свежесть активных артефактов по SLO (generated_at из содержимого, иначе mtime)
        → WARN (инцидент agent_registry: 19 дней протухания никто не заметил)
  B3  замыкание потребления: продукт агента с consumer_required обязан иметь СВЕЖИЙ
        ресит в data/consumption_receipts.jsonl → WARN (ядро аудита: 12 io_* в никуда)
  B5  манифест сам соответствует фактам plist'ов (перегенерация без дрейфа;
        на хосте без ~/Library/LaunchAgents/com.spa.* — честный UNCHECKED)

Семантика вердикта (инвариант 2, refusal-first): `OK` ТОЛЬКО когда всё вычислено
и прошло. Невычисленное — UNCHECKED, не «прошло». Слабые (weak) находки СТАРЕЮТ:
после WEAK_AGE_DAYS уходят из findings в aged (видимы, не красят) — урок
«irreversible UNCHECKED starves the queue». Сильные не стареют.

Exit: 0 OK · 1 WARN/UNCHECKED · 2 CRITICAL. Выход: data/architecture_conformance.json
(атомарно). Tier-1 push НАМЕРЕННО отсутствует: whitelist push_policy — закрытый
контракт внимания владельца (R4); доставка находок владельцу — мост «находка→
карточка» (ADR-066 Фаза 3). LLM_FORBIDDEN. Только stdlib. Время — вход (now=),
не окружение.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_PATH = os.path.join(REPO_ROOT, "architecture", "manifest.json")
REPORT_PATH = os.path.join(REPO_ROOT, "data", "architecture_conformance.json")
RECEIPTS_PATH = os.path.join(REPO_ROOT, "data", "consumption_receipts.jsonl")

WEAK_AGE_DAYS = 14
SUBPROC_TIMEOUT = 20
_TS_FIELDS = ("generated_at", "updated_at", "timestamp", "last_updated")

EXIT_BY_OVERALL = {"OK": 0, "UNCHECKED": 1, "WARN": 1, "CRITICAL": 2}


# ── сбор фактов (в тестах всё инъектируется) ─────────────────────────────────

def gather_fleet() -> set[str] | None:
    """Метки com.spa.*, реально загруженные в launchd. None = НЕ ИЗМЕРЕНО."""
    try:
        out = subprocess.run(["launchctl", "list"], capture_output=True,
                             text=True, timeout=SUBPROC_TIMEOUT)
        if out.returncode != 0:
            return None
        fleet = set()
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].startswith("com.spa."):
                fleet.add(parts[2])
        return fleet
    except Exception:
        return None


def _parse_iso(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def artifact_timestamp(rel_path: str, root: str = REPO_ROOT) -> dt.datetime | None:
    """Отметка свежести артефакта: содержимое (generated_at и родня) прежде mtime —
    mtime лжёт при синхронизациях/checkout. Нет файла → None."""
    full = os.path.join(root, rel_path)
    if not os.path.exists(full):
        return None
    if full.endswith(".json"):
        try:
            data = json.load(open(full))
            if isinstance(data, dict):
                for f in _TS_FIELDS:
                    raw = data.get(f)
                    # date-only метка («2026-08-06») парсится как полночь и
                    # ЗАВЫШАЕТ возраст до 24ч — ложный stale-WARN каждую ночь
                    # (инцидент 02:39 07.08). Дата без времени точнее mtime НЕ
                    # является — падаем на mtime.
                    if isinstance(raw, str) and "T" not in raw:
                        continue
                    ts = _parse_iso(raw)
                    if ts:
                        return ts
        except Exception:
            pass  # нечитаемый JSON — честно падаем на mtime
    return dt.datetime.fromtimestamp(os.path.getmtime(full), tz=dt.timezone.utc)


def load_receipts(path: str = RECEIPTS_PATH) -> dict[str, dt.datetime]:
    """artifact → отметка САМОГО СВЕЖЕГО ресита потребления. Нет файла → {}."""
    latest: dict[str, dt.datetime] = {}
    if not os.path.exists(path):
        return latest
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = _parse_iso(rec.get("consumed_at"))
                art = rec.get("artifact")
                if art and ts and (art not in latest or ts > latest[art]):
                    latest[art] = ts
    except Exception:
        pass
    return latest


def _manifest_drift_problems() -> list[str] | None:
    """B5: перегенерировать манифест из фактов plist'ов. None = НЕ ИЗМЕРИМО здесь."""
    try:
        import glob
        import importlib.util
        gen_path = os.path.join(REPO_ROOT, "scripts", "build_architecture_manifest.py")
        spec = importlib.util.spec_from_file_location("bam", gen_path)
        gen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gen)
        if not glob.glob(os.path.join(gen.LAUNCH_AGENTS_DIR, "com.spa.*.plist")):
            return None  # не прод-хост
        rc = gen.main([])  # --check (дефолт), молча в stdout
        return [] if rc == 0 else ["manifest --check вернул дрейф (см. build_architecture_manifest.py)"]
    except Exception as e:  # noqa: BLE001
        return [f"B5 упал: {e}"]


# ── ядро (чистое: все входы — параметры) ─────────────────────────────────────

def _finding(key: str, check: str, severity: str, cls: str, message: str) -> dict:
    return {"key": key, "check": check, "severity": severity, "class": cls,
            "message": message}


def run_checks(manifest: dict,
               fleet: set[str] | None,
               ts_of,                      # rel_path -> datetime|None
               receipts: dict[str, dt.datetime],
               now: dt.datetime,
               prev_first_seen: dict[str, str] | None = None,
               drift_problems: list[str] | None = None,
               drift_measured: bool = False) -> dict:
    findings: list[dict] = []
    unchecked: list[dict] = []
    agents = manifest.get("agents", [])
    by_label = {a["label"]: a for a in agents}

    # B1 — флот ↔ манифест
    if fleet is None:
        unchecked.append({"check": "B1_fleet", "reason": "launchctl недоступен — флот НЕ ИЗМЕРЕН"})
    else:
        for label in sorted(fleet):
            a = by_label.get(label)
            if a is None:
                findings.append(_finding(
                    f"B1:unknown:{label}", "B1", "CRITICAL", "strong",
                    f"{label} загружен, в манифесте ОТСУТСТВУЕТ (класс swarm_dwell 2026-08-05)"))
            elif a["intent"] == "retired":
                findings.append(_finding(
                    f"B1:zombie:{label}", "B1", "CRITICAL", "strong",
                    f"{label} работает при intent=retired"))
            elif a["intent"] == "designed":
                findings.append(_finding(
                    f"B1:premature:{label}", "B1", "CRITICAL", "strong",
                    f"{label} работает при intent=designed — активация мимо ADR"))
            elif a["intent"] == "unresolved":
                findings.append(_finding(
                    f"B1:unresolved_running:{label}", "B1", "WARN", "weak",
                    f"{label} работает при intent=unresolved — намерение никем не решено"))
        for a in agents:
            if a["intent"] != "active":
                continue
            if a["label"] not in fleet:
                findings.append(_finding(
                    f"B1:dead:{a['label']}", "B1", "CRITICAL", "strong",
                    f"{a['label']}: intent=active, но НЕ загружен во флоте"))
            elif not a.get("reboot_safe"):
                findings.append(_finding(
                    f"B1:reboot_unsafe:{a['label']}", "B1", "WARN", "strong",
                    f"{a['label']} работает, но plist не персистентен "
                    f"({a.get('plist_source')}) — не переживёт ребут"))

    # B2 — свежесть активных артефактов
    for art in manifest.get("artifacts", []):
        if art.get("status") != "active":
            continue
        path = art["path"]
        ts = ts_of(path)
        if ts is None:
            findings.append(_finding(
                f"B2:missing:{path}", "B2", "WARN", "strong",
                f"{path}: активный артефакт отсутствует на диске"))
            continue
        age_h = (now - ts).total_seconds() / 3600.0
        slo = art.get("slo_hours") or 0
        if slo and age_h > slo:
            findings.append(_finding(
                f"B2:stale:{path}", "B2", "WARN", "strong",
                f"{path}: возраст {age_h:.1f}ч > SLO {slo}ч "
                f"(класс agent_registry: 19 дней молчаливого протухания)"))

    # B3 — замыкание потребления
    for art in manifest.get("artifacts", []):
        if art.get("status") != "active":
            continue
        producer = art.get("producer")
        if producer and by_label.get(producer, {}).get("consumer_required"):
            path = art["path"]
            ts = receipts.get(path)
            slo = art.get("slo_hours") or 26
            if ts is None:
                findings.append(_finding(
                    f"B3:no_consumption:{path}", "B3", "WARN", "strong",
                    f"{path}: consumer_required, но НИ ОДНОГО ресита потребления "
                    f"(ядро аудита 2026-08-05: отчёты в никуда)"))
            elif (now - ts).total_seconds() / 3600.0 > slo:
                findings.append(_finding(
                    f"B3:consumption_stale:{path}", "B3", "WARN", "strong",
                    f"{path}: последний ресит старше SLO {slo}ч — потребитель замолчал"))

    # B5 — манифест соответствует фактам plist'ов
    if not drift_measured:
        unchecked.append({"check": "B5_manifest",
                          "reason": "хост без ~/Library/LaunchAgents/com.spa.* — дрейф НЕ ИЗМЕРЕН"})
    else:
        for p in (drift_problems or []):
            findings.append(_finding(f"B5:drift:{p[:80]}", "B5", "WARN", "strong",
                                     f"манифест ↔ факты: {p}"))

    # первое появление + старение слабых
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
        "overall": overall,
        "exit_code": EXIT_BY_OVERALL[overall],
        "counts": {"critical": sum(1 for f in kept if f["severity"] == "CRITICAL"),
                   "warn": sum(1 for f in kept if f["severity"] == "WARN"),
                   "aged": len(aged), "unchecked": len(unchecked)},
        "fleet_size": (len(fleet) if fleet is not None else None),
        "manifest_agents": len(agents),
        "findings": kept,
        "aged": aged,
        "unchecked": unchecked,
    }


# ── обвязка ──────────────────────────────────────────────────────────────────

def _prev_first_seen(report_path: str = REPORT_PATH) -> dict[str, str]:
    try:
        prev = json.load(open(report_path))
        out = {}
        for f in prev.get("findings", []) + prev.get("aged", []):
            if f.get("key") and f.get("first_seen"):
                out[f["key"]] = f["first_seen"]
        return out
    except Exception:
        return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ADR-066 architecture conformance watchdog")
    ap.add_argument("--run", "--once", action="store_true", dest="run",
                    help="один прогон против живой системы")
    ap.add_argument("--exit-zero", action="store_true",
                    help="плановый launchd-режим: exit 0, если проверка ВЫПОЛНИЛАСЬ "
                         "(вердикт — в отчёте). Иначе exit 1 у сторожа с находками "
                         "неотличим для agent_health от «агент сломан» и маскирует "
                         "настоящие падения. Крах по-прежнему ≠ 0.")
    ap.add_argument("--report", default=REPORT_PATH)
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0

    manifest = json.load(open(MANIFEST_PATH))
    fleet = gather_fleet()
    receipts = load_receipts()
    drift = _manifest_drift_problems()
    now = dt.datetime.now(dt.timezone.utc)
    report = run_checks(manifest, fleet, artifact_timestamp, receipts, now,
                        prev_first_seen=_prev_first_seen(args.report),
                        drift_problems=drift, drift_measured=drift is not None)

    from spa_core.utils.atomic import atomic_save
    atomic_save(report, args.report)

    c = report["counts"]
    print(f"architecture_conformance: {report['overall']} — critical={c['critical']} "
          f"warn={c['warn']} aged={c['aged']} unchecked={c['unchecked']} "
          f"(флот {report['fleet_size']}, манифест {report['manifest_agents']})")
    for f in report["findings"][:30]:
        print(f"  [{f['severity']}] {f['message']}")
    return 0 if args.exit_zero else report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
