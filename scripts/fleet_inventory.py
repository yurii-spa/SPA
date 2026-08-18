#!/usr/bin/env python3
"""fleet_inventory.py — инвентаризация флота ПО РЕПОЗИТОРИЮ (то, что измеримо без Mac).

Зачем ещё один сторож, когда есть `fleet_parity_check` и `architecture_conformance`.
Каждый из них честно отвечает на СВОЙ вопрос и молчит про остальные:

  • `scripts/fleet_parity_check.py`      — установщик ↔ plist'ы ↔ RETIRED_LABELS.
    Манифеста (`architecture/manifest.json`) НЕ ВИДИТ ВООБЩЕ, обёрток не видит,
    реестра не видит.
  • `spa_core/monitoring/architecture_conformance.py` — манифест ↔ ЖИВОЙ флот
    (`launchctl` + `~/Library/LaunchAgents`). Вне Mac обе стороны недоступны:
    прогон из облака печатает «флот None», B5 уходит в UNCHECKED — то есть про
    расхождение манифеста с plist'ами В РЕПО он не говорит ничего.

Ниша этого файла — ровно то, что измеримо из чекаута, БЕЗ launchctl: четыре
объявления флота обязаны сходиться между собой.

  MANIFEST  — `architecture/manifest.json` → `agents[].label` (конституция, ADR-066)
  PLIST     — `com.spa.*.plist` в `scripts/` и `launchd/` (файлы в дереве)
  WRAPPER   — `scripts/agent_*.sh` (точки входа, которые запускает launchd)
  REGISTRY  — `data/agent_registry.json` → `agents[].label` (снимок с Mac, git-tracked)

Классы расхождений (жёсткие — красят в DRIFT):
  manifest_without_plist      — манифест объявляет агента, plist'а в дереве нет
  orphan_plist_not_in_manifest— plist есть, в конституции агента нет (класс «26 сирот»)
  duplicate_plist_label       — один label двумя файлами (scripts/ И launchd/):
                                какой из них поставится — зависит от строки установщика
  wrapper_without_agent       — обёртка `agent_*.sh`, которую не запускает ни один агент
  manifest_program_missing    — манифест объявляет `program`, файла нет → агент мёртв (exit 126/127)
  registry_unknown_agent      — реестр знает агента, которого нет ни в манифесте, ни в RETIRED

Мягкие классы (называются, не красят): `wrapper_of_retired`, `wrapper_is_tool`,
`registry_record_of_retired`, `manifest_without_registry`.

FAIL-CLOSED (требование, из-за которого файл и написан). «Не смогли прочитать» НЕ
равно «расхождений нет». Каждый источник несёт свой `status`:
  read      — прочитан, сравнения по нему действительны;
  unreadable— файла нет / битый JSON → производные классы = `null`, вердикт UNCHECKED;
  stale     — прочитан, но устарел (реестр генерится НА MAC из `launchctl`; в чекауте
              он по построению отстаёт) → производные классы = `null`, вердикт UNCHECKED.
Пустой список `[]` означает «проверено, чисто»; `null` — «не проверено». Молчание
никогда не выдаётся за успех.

Время — ВХОД (`now=`), не окружение: возраст реестра считается от переданных часов.
Детерминированно, только stdlib, LLM запрещён. Ничего не устанавливает и не снимает
(правило доставки п.6) — только читает дерево и печатает.

Чего этот файл НЕ измеряет и измерить не может (только на Mac):
  `launchctl list | grep com.spa`      — кто реально загружен и с каким кодом выхода
  `ls ~/Library/LaunchAgents/com.spa.*`— что реально установлено (persistent через ребут)
  `python3 scripts/print_stale_agent_restarts.py` — какой долгожитель держит старый код
Эти вопросы выведены в блок `not_measurable_here` отчёта ВМЕСТЕ С КОМАНДАМИ.

Exit: 0 — OK · 1 — UNCHECKED (что-то не прочитано) · 2 — DRIFT (есть жёсткий класс).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PLIST_DIRS = ("scripts", "launchd")
_LABEL_PREFIXES = ("com.spa.", "com.studiobridge.")

# Обёртки, которые НЕ являются агентом по решению, а не по недосмотру. Причина
# обязана быть названа здесь: пополнять эту таблицу, чтобы погасить находку у
# настоящего агента, — запрещено (инвариант 16).
NON_AGENT_WRAPPERS = {
    "agent_template.sh": "шаблон обёртки, из него копируют новые (не запускается launchd)",
    "agent_static_probe.sh": "проверка долгожителя БЕЗ запуска (.claude/rules/deployment.md)",
    "agent_status.sh": "ручная справка о состоянии агентов, вызывается человеком",
}

# Жёсткие классы: любой непустой → DRIFT.
HARD_CLASSES = (
    "manifest_without_plist",
    "orphan_plist_not_in_manifest",
    "duplicate_plist_label",
    "wrapper_without_agent",
    "manifest_program_missing",
    "registry_unknown_agent",
)
SOFT_CLASSES = (
    "wrapper_of_retired",
    "wrapper_is_tool",
    "registry_record_of_retired",
    "manifest_without_registry",
)

NOT_MEASURABLE_HERE = [
    {"question": "кто из агентов реально загружен и с каким кодом выхода",
     "command": "launchctl list | grep com.spa"},
    {"question": "что реально установлено и переживёт ребут",
     "command": "ls ~/Library/LaunchAgents/com.spa.*.plist"},
    {"question": "исполняет ли живой долгожитель код из дерева",
     "command": "python3 scripts/print_stale_agent_restarts.py"},
    {"question": "способен ли флот стартовать после изменения дерева",
     "command": "python3 -m spa_core.monitoring.deployment_acceptance"},
]


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ─────────────────────────── источники (каждый возвращает {status, ...}) ───────────────────────────

def read_manifest(root: Path) -> dict:
    path = root / "architecture" / "manifest.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return {"status": "unreadable", "reason": f"{path}: {e}", "agents": {}}
    agents = data.get("agents")
    if not isinstance(agents, list):
        return {"status": "unreadable", "reason": f"{path}: agents не список", "agents": {}}
    out = {}
    for a in agents:
        label = a.get("label")
        if not label:
            return {"status": "unreadable", "reason": f"{path}: запись без label", "agents": {}}
        out[label] = {"intent": a.get("intent"), "program": a.get("program"),
                      "plist_source": a.get("plist_source")}
    return {"status": "read", "reason": "", "agents": out}


def read_plists(root: Path) -> dict:
    found: dict[str, list[str]] = {}
    seen_dir = False
    for d in _PLIST_DIRS:
        dp = root / d
        if not dp.is_dir():
            continue
        seen_dir = True
        for p in sorted(dp.iterdir()):
            if p.suffix != ".plist":
                continue
            if not p.name.startswith(_LABEL_PREFIXES):
                continue
            found.setdefault(p.name[: -len(".plist")], []).append(f"{d}/{p.name}")
    if not seen_dir:
        return {"status": "unreadable", "reason": "ни scripts/, ни launchd/ не существует", "labels": {}}
    return {"status": "read", "reason": "", "labels": found}


def read_wrappers(root: Path) -> dict:
    dp = root / "scripts"
    if not dp.is_dir():
        return {"status": "unreadable", "reason": "scripts/ не существует", "wrappers": []}
    names = sorted(p.name for p in dp.iterdir()
                   if p.name.startswith("agent_") and p.name.endswith(".sh"))
    return {"status": "read", "reason": "", "wrappers": names}


def read_registry(root: Path, *, now: datetime | None = None,
                  max_age_hours: float = 48.0) -> dict:
    path = root / "data" / "agent_registry.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        return {"status": "unreadable", "reason": f"{path}: {e}", "labels": [], "age_hours": None}
    agents = data.get("agents")
    if not isinstance(agents, list):
        return {"status": "unreadable", "reason": f"{path}: agents не список", "labels": [],
                "age_hours": None}
    labels = sorted({a.get("label") for a in agents if a.get("label")})
    gen = _parse_ts(data.get("generated_at", ""))
    if gen is None:
        return {"status": "unreadable", "reason": f"{path}: нечитаемый generated_at",
                "labels": labels, "age_hours": None}
    age = (_now(now) - gen).total_seconds() / 3600.0
    if age > max_age_hours:
        return {"status": "stale", "labels": labels, "age_hours": round(age, 1),
                "reason": (f"снимок с Mac от {data.get('generated_at')} старше "
                           f"{max_age_hours}ч (возраст {age:.1f}ч) — судить по нему нельзя")}
    return {"status": "read", "reason": "", "labels": labels, "age_hours": round(age, 1)}


def retired_labels() -> set:
    from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
    return set(RETIRED_LABELS)


# ─────────────────────────────────────── сборка отчёта ───────────────────────────────────────

def build_inventory(root: Path | str = ROOT, *, now: datetime | None = None,
                    registry_max_age_hours: float = 48.0,
                    sources: dict | None = None) -> dict:
    root = Path(root)
    src = sources or {
        "manifest": read_manifest(root),
        "plist": read_plists(root),
        "wrapper": read_wrappers(root),
        "registry": read_registry(root, now=now, max_age_hours=registry_max_age_hours),
    }
    man, pls, wrp, reg = src["manifest"], src["plist"], src["wrapper"], src["registry"]
    try:
        retired = retired_labels()
        retired_status = "read"
        retired_reason = ""
    except Exception as e:  # импорт сломан → судить о «списанных» нельзя
        retired, retired_status, retired_reason = set(), "unreadable", f"RETIRED_LABELS: {e}"

    man_ok = man["status"] == "read"
    pls_ok = pls["status"] == "read"
    wrp_ok = wrp["status"] == "read"
    reg_ok = reg["status"] == "read"
    ret_ok = retired_status == "read"

    findings: dict[str, list | None] = {k: None for k in HARD_CLASSES + SOFT_CLASSES}

    man_labels = set(man["agents"]) if man_ok else set()
    plist_labels = set(pls["labels"]) if pls_ok else set()

    if man_ok and pls_ok:
        findings["manifest_without_plist"] = sorted(man_labels - plist_labels)
        findings["orphan_plist_not_in_manifest"] = sorted(plist_labels - man_labels)
    if pls_ok:
        findings["duplicate_plist_label"] = sorted(
            f"{lbl} ({', '.join(files)})" for lbl, files in pls["labels"].items() if len(files) > 1)
    if man_ok and wrp_ok:
        programs = {v.get("program") for v in man["agents"].values() if v.get("program")}
        missing = sorted(p for p in programs
                         if p.startswith("agent_") and p.endswith(".sh")
                         and p not in set(wrp["wrappers"]))
        findings["manifest_program_missing"] = missing
        unused = [w for w in wrp["wrappers"] if w not in programs]
        tools, of_retired, orphaned = [], [], []
        for w in unused:
            if w in NON_AGENT_WRAPPERS:
                tools.append(f"{w} — {NON_AGENT_WRAPPERS[w]}")
                continue
            short = w[len("agent_"):-len(".sh")]
            if ret_ok and any(r.split(".")[-1] == short for r in retired):
                of_retired.append(w)
            else:
                orphaned.append(w)
        findings["wrapper_is_tool"] = sorted(tools)
        findings["wrapper_of_retired"] = sorted(of_retired) if ret_ok else None
        findings["wrapper_without_agent"] = sorted(orphaned) if ret_ok else None
    if man_ok and reg_ok and ret_ok:
        reg_labels = set(reg["labels"])
        findings["registry_unknown_agent"] = sorted(reg_labels - man_labels - retired)
        findings["registry_record_of_retired"] = sorted((reg_labels - man_labels) & retired)
        findings["manifest_without_registry"] = sorted(man_labels - reg_labels)

    hard_hits = {k: v for k, v in findings.items() if k in HARD_CLASSES and v}
    unchecked = sorted(k for k, v in findings.items() if v is None)
    if hard_hits:
        status = "DRIFT"
    elif unchecked:
        status = "UNCHECKED"
    else:
        status = "OK"

    return {
        "model": "fleet_inventory",
        "generated_at": _now(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "deterministic": True,
        "llm_forbidden": True,
        "scope": "repo-only (launchctl НЕ используется by design)",
        "status": status,
        "counts": {
            "manifest": len(man_labels) if man_ok else None,
            "plist_labels": len(plist_labels) if pls_ok else None,
            "plist_files": (sum(len(v) for v in pls["labels"].values()) if pls_ok else None),
            "wrappers": len(wrp["wrappers"]) if wrp_ok else None,
            "registry": len(reg["labels"]) if reg["status"] in ("read", "stale") else None,
            "retired": len(retired) if ret_ok else None,
        },
        "sources": {
            "manifest": {"status": man["status"], "reason": man["reason"]},
            "plist": {"status": pls["status"], "reason": pls["reason"]},
            "wrapper": {"status": wrp["status"], "reason": wrp["reason"]},
            "registry": {"status": reg["status"], "reason": reg["reason"],
                         "age_hours": reg.get("age_hours")},
            "retired_labels": {"status": retired_status, "reason": retired_reason},
        },
        "findings": findings,
        "unchecked_classes": unchecked,
        "not_measurable_here": NOT_MEASURABLE_HERE,
        "note": ("Четыре объявления флота (манифест / plist'ы / обёртки / реестр) обязаны сходиться. "
                 "null в findings = НЕ ПРОВЕРЕНО (источник не прочитан или устарел), [] = проверено и "
                 "чисто. Живой флот измеряется только на Mac — см. not_measurable_here."),
    }


def _print(rep: dict) -> None:
    c = rep["counts"]
    print(f"fleet inventory: {rep['status']}  (манифест {c['manifest']} / plist "
          f"{c['plist_labels']} label'ов в {c['plist_files']} файлах / обёрток {c['wrappers']} / "
          f"реестр {c['registry']} / retired {c['retired']})")
    for name, s in rep["sources"].items():
        if s["status"] != "read":
            print(f"  источник {name}: {s['status']} — {s['reason']}")
    for k in HARD_CLASSES:
        v = rep["findings"][k]
        if v is None:
            print(f"  [UNCHECKED] {k}: не проверено")
        elif v:
            print(f"  [DRIFT] {k} ({len(v)}):")
            for item in v:
                print(f"      {item}")
    for k in SOFT_CLASSES:
        v = rep["findings"][k]
        if v:
            print(f"  [инфо] {k} ({len(v)}): {', '.join(v)}")
        elif v is None:
            print(f"  [UNCHECKED] {k}: не проверено")
    print("  измеримо ТОЛЬКО на Mac:")
    for q in rep["not_measurable_here"]:
        print(f"      {q['question']}  →  {q['command']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Инвентаризация флота по репозиторию (без launchctl)")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    ap.add_argument("--write", metavar="PATH", help="атомарно записать отчёт в файл")
    ap.add_argument("--registry-max-age-hours", type=float, default=48.0)
    args = ap.parse_args(argv)

    rep = build_inventory(registry_max_age_hours=args.registry_max_age_hours)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        _print(rep)
    if args.write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(rep, args.write)
        print(f"  → записано {args.write}")
    return {"OK": 0, "UNCHECKED": 1, "DRIFT": 2}[rep["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
