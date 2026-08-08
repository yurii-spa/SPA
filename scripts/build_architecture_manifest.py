#!/usr/bin/env python3
"""build_architecture_manifest.py — генератор/страж манифеста архитектуры (ADR-066, Фаза 0).

Манифест `architecture/manifest.json` — машиночитаемая конституция флота: намерение
(intent) каждого агента, его продукты с SLO свежести и обязательные потребители.
Генератор НЕ выдумывает намерение — он сводит МЕХАНИКУ (plist'ы + реестр) и сохраняет
КУРИРОВАННЫЕ поля нетронутыми. Правда о намерении вносится руками через git.

Разделение полей на агенте:
  МЕХАНИЧЕСКИЕ (перезаписываются генератором из фактов):
    plist_source   — "launch_agents" | "repo:<путь>" | null (нет plist-файла)
    reboot_safe    — plist лежит в ~/Library/LaunchAgents (переживёт ребут)
    schedule       — распарсенное расписание plist ("daemon"/"interval:300s"/"calendar:08:00"/…)
    program        — исполняемый скрипт (basename)
  КУРИРОВАННЫЕ (генератор сохраняет как есть; сеет дефолт только для НОВОГО агента):
    layer          — product | dev | infra
    role           — monitoring | allocation | analytics | reporting | research | swarm | …
    intent         — active | designed | retired | unresolved
                     ("unresolved" — честное «никто не решал»: живёт в реестре, не загружен,
                      retired не помечен. Фаза 1 обязана поднимать по нему находку.)
    produces       — [{"artifact": path, "slo_hours": N}]
    consumes       — [path, …]
    consumer_required — продукт ОБЯЗАН иметь читателя (ресит потребления, Фаза 2)
    governed_by    — [ADR-ссылки]
    curation       — "complete" | "partial" | "none" (машиночитаемая честность:
                      produces=[] при curation!="complete" значит «не курировано»,
                      а не «ничего не производит»)
    notes          — свободный текст

Режимы:
  --check (дефолт)  сверить манифест с фактами; расхождение → отчёт + exit 2
  --write           обновить механические поля / посеять новых агентов (курация не трогается)

Идемпотентность: --write без изменения фактов даёт байт-в-байт тот же файл (timestamp'ов
в манифесте нет намеренно). LLM_FORBIDDEN. Только stdlib. Атомарная запись.

Инциденты, ради которых существует каждая проверка (positive controls в
spa_core/tests/test_architecture_manifest.py):
  - 2026-08-05: artifact_freshness / swarm_dwell загружены БЕЗ реестра и без
    персистентного plist (не переживут ребут) — 19 дней никто не заметил;
  - 2026-08-05: checkpoint-7day / novel_edge_rnd не загружены и не retired — молчаливый дрейф;
  - 2026-07-17: agent_registry.json протух — реестр сам объявлен артефактом со SLO.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import glob
import json
import os
import plistlib
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(REPO_ROOT, "architecture", "manifest.json")
DEFAULT_REGISTRY = os.path.join(REPO_ROOT, "data", "agent_registry.json")
LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")

INTENTS = ("active", "designed", "retired", "unresolved")
LAYERS = ("product", "dev", "infra")
CURATION = ("complete", "partial", "none")

MECHANICAL_FIELDS = ("plist_source", "reboot_safe", "schedule", "program")
CURATED_DEFAULTS = {
    "layer": "product",
    "role": "unknown",
    "intent": "unresolved",
    "produces": [],
    "consumes": [],
    "consumer_required": False,
    "governed_by": [],
    "curation": "none",
    "notes": "",
}


def _parse_schedule(pl: dict) -> str:
    if pl.get("KeepAlive"):
        return "daemon"
    if pl.get("WatchPaths"):
        return "event:watchpaths"
    if "StartInterval" in pl:
        return f"interval:{int(pl['StartInterval'])}s"
    cal = pl.get("StartCalendarInterval")
    if cal:
        entries = cal if isinstance(cal, list) else [cal]
        parts = []
        for e in entries:
            hh = e.get("Hour")
            mm = e.get("Minute", 0)
            wd = e.get("Weekday")
            token = f"{hh:02d}:{mm:02d}" if hh is not None else f"minute:{mm}"
            if wd is not None:
                token = f"wd{wd}·{token}"
            parts.append(token)
        return "calendar:" + ",".join(sorted(parts))
    return "manual"


def _parse_program(pl: dict) -> str:
    args = pl.get("ProgramArguments") or ([pl["Program"]] if pl.get("Program") else [])
    # осмысленное имя: последний .sh/.py аргумент, иначе argv0
    for a in reversed(args):
        base = os.path.basename(str(a))
        if base.endswith((".sh", ".py")):
            return base
    return os.path.basename(str(args[0])) if args else ""


def _scan_plists(dirs: list[str]) -> dict[str, dict]:
    """label -> механика. Первый каталог в списке имеет приоритет при дублях."""
    out: dict[str, dict] = {}
    for d in dirs:
        for path in sorted(glob.glob(os.path.join(d, "com.spa.*.plist"))):
            if path.endswith(".bak"):
                continue
            try:
                with open(path, "rb") as f:
                    pl = plistlib.load(f)
            except Exception as e:  # повреждённый plist — это находка, не молчание
                out.setdefault("__errors__", {}).setdefault("parse", []).append(
                    f"{path}: {e}")
                continue
            label = pl.get("Label") or os.path.basename(path)[:-len(".plist")]
            if label in out:
                continue
            in_la = os.path.realpath(d) == os.path.realpath(LAUNCH_AGENTS_DIR)
            src = "launch_agents" if in_la else "repo:" + os.path.relpath(path, REPO_ROOT)
            out[label] = {
                "plist_source": src,
                "reboot_safe": in_la,
                "schedule": _parse_schedule(pl),
                "program": _parse_program(pl),
            }
    return out


def _load_registry(path: str) -> dict[str, dict]:
    try:
        data = json.load(open(path))
    except Exception:
        return {}
    # 2026-08-08, решение владельца «шесть — выводить» (карточка
    # `own-31-desyat-agentov-v-reestre-bez-flota`): ВЫВЕДЕННЫЙ агент — это не
    # факт о работающем флоте, и манифест не обязан держать под него запись.
    #
    # Раньше запись с `retired: true` продолжала считаться фактом, поэтому
    # реестр «обещал больше, чем есть»: пять записей (bot_commands,
    # daily-paper-report, httpserver, telegram_daily, telegram_weekly) не имели
    # ни plist, ни программы, ни строки в launchctl — только собственную запись
    # о том, что они выведены.
    #
    # Отдельно: если у выведенного агента ВСЁ ЕЩЁ есть plist, он остаётся
    # фактом. Тогда расхождение настоящее — «объявлен выведенным, но
    # разворачивается» — и его гасить нельзя.
    return {a["label"]: a for a in data.get("agents", [])
            if a.get("label") and not a.get("retired")}


def _load_manifest(path: str) -> dict:
    if not os.path.exists(path):
        return {"schema_version": 1, "adr": "ADR-066", "agents": [],
                "artifacts": [], "designed_architectures": []}
    return json.load(open(path))


def build(manifest: dict, plists: dict[str, dict], registry: dict[str, dict]) -> dict:
    """Новый манифест: механика из фактов, курация — из старого манифеста."""
    plists = {k: v for k, v in plists.items() if k != "__errors__"}
    old = {a["label"]: a for a in manifest.get("agents", [])}
    labels = sorted(set(plists) | set(registry) | set(old))
    agents = []
    for label in labels:
        prev = old.get(label, {})
        entry = {"label": label}
        # механика: есть plist — из plist'а; нет — честные null/False
        mech = plists.get(label)
        if mech:
            entry.update(mech)
        else:
            entry.update({"plist_source": None, "reboot_safe": False,
                          "schedule": None, "program": None})
        # курация: сохранить как есть; для нового агента — посеять
        for k, default in CURATED_DEFAULTS.items():
            entry[k] = prev.get(k, default)
        # сид для НОВОГО агента из реестра (не перетирает существующую курацию).
        # active сеется ТОЛЬКО по персистентному plist (~/Library/LaunchAgents):
        # plist в репо — не свидетельство работы (инцидент auto_push/cpa_daily 2026-08-05,
        # 7 репо-остатков выглядели бы «живыми»). Репо-plist без LA ⇒ unresolved.
        if label not in old:
            reg = registry.get(label, {})
            if reg.get("retired"):
                entry["intent"] = "retired"
            elif mech and mech["reboot_safe"]:
                entry["intent"] = "active"
            if reg.get("role"):
                entry["role"] = reg["role"]
        agents.append(entry)
    manifest = dict(manifest)
    manifest["agents"] = agents
    manifest.setdefault("artifacts", [])
    manifest.setdefault("designed_architectures", [])
    return manifest


def validate(manifest: dict, plists: dict[str, dict]) -> list[str]:
    """Схема + согласованность намерения с фактами. Возвращает список проблем."""
    problems: list[str] = []
    perrs = plists.get("__errors__", {}).get("parse", [])
    for e in perrs:
        problems.append(f"plist не парсится: {e}")
    plist_labels = {k for k in plists if k != "__errors__"}
    seen = set()
    for a in manifest.get("agents", []):
        label = a.get("label", "<без label>")
        if label in seen:
            problems.append(f"{label}: дубль в манифесте")
        seen.add(label)
        if a.get("intent") not in INTENTS:
            problems.append(f"{label}: intent={a.get('intent')!r} вне {INTENTS}")
        if a.get("layer") not in LAYERS:
            problems.append(f"{label}: layer={a.get('layer')!r} вне {LAYERS}")
        if a.get("curation") not in CURATION:
            problems.append(f"{label}: curation={a.get('curation')!r} вне {CURATION}")
        if a.get("intent") == "active" and label not in plist_labels:
            problems.append(f"{label}: intent=active, но plist-файла нет")
        if (a.get("intent") == "retired" and label in plist_labels
                and plists[label]["plist_source"] == "launch_agents"):
            problems.append(f"{label}: intent=retired, но персистентный plist "
                            f"всё ещё в ~/Library/LaunchAgents")
        if a.get("consumer_required") and not a.get("produces"):
            problems.append(f"{label}: consumer_required без единого produces")
    for label in sorted(plist_labels - seen):
        problems.append(f"{label}: plist существует, в манифесте отсутствует "
                        f"(инцидент swarm_dwell 2026-08-05)")
    agent_labels = seen
    for art in manifest.get("artifacts", []):
        p = art.get("path", "<без path>")
        if art.get("status") not in ("active", "planned"):
            problems.append(f"artifact {p}: status={art.get('status')!r} вне (active|planned)")
        prod = art.get("producer")
        if prod is not None and prod not in agent_labels:
            problems.append(f"artifact {p}: producer {prod} не объявлен в agents")
        if art.get("status") == "active" and not (
                isinstance(art.get("slo_hours"), (int, float)) and art["slo_hours"] > 0):
            problems.append(f"artifact {p}: active без положительного slo_hours")
    return problems


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--plist-dir", action="append", default=None,
                    help="каталог(и) plist; дефолт: ~/Library/LaunchAgents, "
                         "затем repo launchd/ и scripts/ (страховка от сирот)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    dirs = args.plist_dir or [LAUNCH_AGENTS_DIR,
                              os.path.join(REPO_ROOT, "launchd"),
                              os.path.join(REPO_ROOT, "scripts")]
    plists = _scan_plists(dirs)
    registry = _load_registry(args.registry)
    current = _load_manifest(args.manifest)
    rebuilt = build(current, plists, registry)
    problems = validate(rebuilt, plists)

    if args.write:
        text = dumps(rebuilt)
        os.makedirs(os.path.dirname(args.manifest), exist_ok=True)
        tmp = args.manifest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, args.manifest)
        print(f"написан {args.manifest}: агентов {len(rebuilt['agents'])}")
        for p in problems:
            print(f"  ПРОБЛЕМА: {p}")
        return 2 if problems else 0

    # --check: манифест обязан совпадать с перегенерацией и быть валидным
    drift = []
    if not os.path.exists(args.manifest):
        drift.append("манифест отсутствует — запустить --write")
    elif dumps(current) != dumps(rebuilt):
        cur = {a["label"]: a for a in current.get("agents", [])}
        new = {a["label"]: a for a in rebuilt["agents"]}
        for label in sorted(set(cur) | set(new)):
            if label not in cur:
                drift.append(f"{label}: агент есть в фактах, нет в манифесте")
            elif label not in new:
                drift.append(f"{label}: агент в манифесте, в фактах не найден")
            else:
                for k in MECHANICAL_FIELDS:
                    if cur[label].get(k) != new[label].get(k):
                        drift.append(f"{label}: {k} {cur[label].get(k)!r} → {new[label].get(k)!r}")
        if not drift:
            drift.append("недиагностированное расхождение сериализации — запустить --write")
    for p in problems + drift:
        print(f"DRIFT: {p}")
    if problems or drift:
        print(f"ИТОГ: манифест НЕ соответствует фактам "
              f"({len(problems)} схемных, {len(drift)} дрейфовых)")
        return 2
    print(f"OK: манифест соответствует фактам ({len(rebuilt['agents'])} агентов)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
