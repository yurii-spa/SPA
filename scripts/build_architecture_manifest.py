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
  без флагов  сверить манифест с фактами; расхождение → отчёт + exit 2;
              измерить нечем (plist объявлен в репо, но каталог сюда не
              синкается) → exit 1, а НЕ 0 и не 2 — см. `compute_drift`
              (флага `--check` НЕТ: argparse ответит `unrecognized arguments`;
               до цикла #264 так было написано и здесь, и в находке B5)
  --write     обновить механические поля / посеять новых агентов (курация не трогается)

Замер отдан наружу функцией `measure()`: сторож `architecture_conformance` (B5) читает
диагноз строками, а не кодом возврата (цикл #264 — находка, не сообщавшая НИЧЕГО).

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
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MANIFEST = os.path.join(REPO_ROOT, "architecture", "manifest.json")
DEFAULT_REGISTRY = os.path.join(REPO_ROOT, "data", "agent_registry.json")
LAUNCH_AGENTS_DIR = os.path.expanduser("~/Library/LaunchAgents")
# Префикс `plist_source` для plist'а, лежащего В РЕПО (см. _scan_plists).
REPO_SRC_PREFIX = "repo:"
# Ветка-конституция: тот же ref, что у курации в architecture_conformance (B6).
CURATION_REF = "origin/main"
GIT_TIMEOUT = 10

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


def default_plist_dirs() -> list[str]:
    """~/Library/LaunchAgents, затем repo launchd/ и scripts/ (страховка от сирот)."""
    return [LAUNCH_AGENTS_DIR,
            os.path.join(REPO_ROOT, "launchd"),
            os.path.join(REPO_ROOT, "scripts")]


def _path_on_ref(root: str, ref: str, rel: str) -> bool:
    """Есть ли `rel` в дереве `ref`. False — и «файла нет», и «спросить не у кого»
    (не репозиторий, нет ветки, git недоступен): для ЕДИНСТВЕННОГО читателя этой
    функции оба ответа значат одно — доказательства нет, значит молчать нельзя.
    Отдельная проверка разрешимости ref здесь стояла и была снята как мёртвая:
    мутация «убрать её» не покрасила ни одного теста — `git cat-file` на
    неразрешимом ref отвечает тем же отказом (замер цикла #267)."""
    try:
        out = subprocess.run(["git", "cat-file", "-e", f"{ref}:{rel}"], cwd=root,
                             capture_output=True, text=True, timeout=GIT_TIMEOUT)
    except Exception:  # noqa: BLE001
        return False
    return out.returncode == 0


def unmeasurable_missing_plist(cur_entry: dict, new_entry: dict,
                               root: str | None = None,
                               ref: str | None = None) -> str | None:
    """Факта нет — потому что plist СТЁРЛИ, или потому что это дерево его не получает?

    Возвращает причину (str), если ДОКАЗАНО второе; иначе None ⇒ строка остаётся
    дрейфом, как была. Доказательство требует всех четырёх условий сразу, и каждое
    сужает в сторону молчания только там, где судить не по чему:

    1. перегенерация не нашла plist НИГДЕ (`plist_source is None`) — иначе факт
       есть, и расхождение настоящее (например, репо-plist доехал до LaunchAgents);
    2. манифест сам объявляет источником путь В РЕПО (`repo:<rel>`) — пропажа из
       `~/Library/LaunchAgents` остаётся фактом о ФЛОТЕ и молчания не заслуживает;
    3. этого пути нет в рабочем дереве;
    4. на `ref` он ЕСТЬ — то есть файл не удалён, а не доехал сюда (и «спросить
       не у кого» здесь тоже значит «нет доказательства», см. `_path_on_ref`).

    Замер 2026-08-16 (прод, цикл #267): `com.spa.site_freshness` объявлен как
    `repo:launchd/com.spa.site_freshness.plist`; на origin файл есть, в прод-дереве
    нет — `code_sync_from_origin.sh` возит только `spa_core/ scripts/ tests/`.
    Сторож печатал три строки «→ None» и звучал как дрейф механики, хотя мерил
    ГРАНИЦУ СИНХРОНИЗАЦИИ. Ложная находка кормит мост карточками владельцу.

    Fail-CLOSED: git недоступен, ref не разрешается или файла нет и на `ref` —
    остаётся дрейф. Замолчать можно только по положительному доказательству.
    """
    root = root or REPO_ROOT
    ref = ref or CURATION_REF
    if new_entry.get("plist_source") is not None:
        return None
    src = cur_entry.get("plist_source")
    if not isinstance(src, str) or not src.startswith(REPO_SRC_PREFIX):
        return None
    rel = src[len(REPO_SRC_PREFIX):]
    if not rel or os.path.exists(os.path.join(root, rel)):
        return None
    if not _path_on_ref(root, ref, rel):
        return None
    return (f"{rel} есть на {ref}, но НЕТ в этом рабочем дереве — механика "
            f"НЕ ИЗМЕРЕНА (синхронизация возит только spa_core/ scripts/ tests/). "
            f"Это свойство дерева, а не факт о флоте")


def compute_drift(current: dict, rebuilt: dict, manifest_path: str,
                  root: str | None = None,
                  ref: str | None = None) -> tuple[list[str], list[str]]:
    """Чем манифест на диске расходится с перегенерацией из фактов.

    Возвращает `(drift, unmeasurable)`: первое — расхождение, второе — то, что
    в ЭТОМ дереве измерить нечем (см. `unmeasurable_missing_plist`). Разделение
    нужно потому, что читатель у них разный: дрейф — находка сторожа (и карточка
    от моста), «не измерено» — раздел `unchecked`, который вердикт не зеленит.

    Отдельной функцией — потому что диагноз нужен НЕ только человеку у терминала.
    `architecture_conformance` (B5) до цикла #264 видел от этого скрипта ровно код
    возврата и подставлял в находку текст «manifest --check вернул дрейф», в котором
    не было ни агента, ни поля, ни направления, а названный флаг вообще не
    существует. Три готовые строки печатались в stdout и пропадали.
    """
    drift: list[str] = []
    unmeasurable: list[str] = []
    if not os.path.exists(manifest_path):
        return ["манифест отсутствует — запустить --write"], unmeasurable
    if dumps(current) == dumps(rebuilt):
        return drift, unmeasurable
    cur = {a["label"]: a for a in current.get("agents", [])}
    new = {a["label"]: a for a in rebuilt["agents"]}
    for label in sorted(set(cur) | set(new)):
        if label not in cur:
            drift.append(f"{label}: агент есть в фактах, нет в манифесте")
        elif label not in new:
            drift.append(f"{label}: агент в манифесте, в фактах не найден")
        else:
            diffs = [k for k in MECHANICAL_FIELDS
                     if cur[label].get(k) != new[label].get(k)]
            if not diffs:
                continue
            why = unmeasurable_missing_plist(cur[label], new[label], root, ref)
            if why:
                # ОДНА строка на агента: три поля «→ None» имеют одну причину,
                # и три строки «не измерено» об одном и том же — тот же шум,
                # от которого лечимся (ключ находки уже группируется по агенту).
                unmeasurable.append(f"{label}: {why}")
                continue
            for k in diffs:
                drift.append(f"{label}: {k} {cur[label].get(k)!r} → {new[label].get(k)!r}")
    if not drift and not unmeasurable:
        drift.append("недиагностированное расхождение сериализации — запустить --write")
    return drift, unmeasurable


def measure(manifest_path: str = DEFAULT_MANIFEST,
            registry_path: str = DEFAULT_REGISTRY,
            plist_dirs: list[str] | None = None,
            root: str | None = None,
            ref: str | None = None) -> dict:
    """Один замер «манифест ↔ факты»: без stdout, без записи, без sys.exit.

    Возвращает `{plists, current, rebuilt, problems, drift, unmeasurable}`.
    Пусты `problems` и `drift` ⇔ `main()` в режиме сверки вернул бы 0 — это ОДИН
    источник вердикта для CLI и для сторожа. `unmeasurable` вердикт НЕ зеленит:
    у CLI это код 1 (предупреждение), у сторожа — раздел `unchecked`.
    """
    plists = _scan_plists(plist_dirs or default_plist_dirs())
    registry = _load_registry(registry_path)
    current = _load_manifest(manifest_path)
    rebuilt = build(current, plists, registry)
    drift, unmeasurable = compute_drift(current, rebuilt, manifest_path, root, ref)
    return {"plists": plists, "current": current, "rebuilt": rebuilt,
            "problems": validate(rebuilt, plists),
            "drift": drift, "unmeasurable": unmeasurable}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--plist-dir", action="append", default=None,
                    help="каталог(и) plist; дефолт: ~/Library/LaunchAgents, "
                         "затем repo launchd/ и scripts/ (страховка от сирот)")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)

    m = measure(args.manifest, args.registry, args.plist_dir)
    rebuilt, problems = m["rebuilt"], m["problems"]

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

    # режим сверки (без флагов): манифест обязан совпадать с перегенерацией и быть валидным
    drift, unmeasurable = m["drift"], m["unmeasurable"]
    for p in problems + drift:
        print(f"DRIFT: {p}")
    for u in unmeasurable:
        print(f"НЕ ИЗМЕРЕНО: {u}")
    if problems or drift:
        print(f"ИТОГ: манифест НЕ соответствует фактам "
              f"({len(problems)} схемных, {len(drift)} дрейфовых, "
              f"{len(unmeasurable)} не измерено)")
        return 2
    if unmeasurable:
        # Не 0: «нечем измерить» — это не «сошлось». И не 2: расхождения не
        # доказано, а ложная тревога стоит внимания владельца (карточка
        # `inbox-prod-storozh-arhitektury-chitaet-fail-ko`).
        print(f"НЕ ИЗМЕРЕНО ПОЛНОСТЬЮ: {len(unmeasurable)} агент(ов) — "
              f"остальное соответствует фактам ({len(rebuilt['agents'])} агентов)")
        return 1
    print(f"OK: манифест соответствует фактам ({len(rebuilt['agents'])} агентов)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
