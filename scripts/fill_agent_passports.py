#!/usr/bin/env python3
"""Заполнить паспорта агентов в `architecture/manifest.json` — ИЗ ИСТОЧНИКОВ.

Паспорт (AI1 гл. 3/24) = деловая цель · метрика качества · эскалация.
Замер 2026-08-20: агентов 89, паспортов 0. Инструмент, который меряет полноту
(`spa_core/monitoring/agent_passports.py`), построен днём раньше — заполнять
было нечем и некому.

ГЛАВНОЕ ПРАВИЛО ЭТОГО ФАЙЛА: **ничего не выдумывать.** Паспорт на 89 агентов,
написанный от руки, — это 267 правдоподобных предложений, из которых проверить
нельзя ни одного; такой паспорт хуже пустого, потому что выглядит как знание.
Поэтому каждое поле выводится из того, что уже есть в репозитории, и если
источника нет — поле остаётся ПУСТЫМ, а агент попадает в список «нужен
владелец/автор» (fail-CLOSED, инвариант #2).

Откуда берётся каждое поле:

* **goal** — первая фраза docstring'а python-модуля, который запускает обёртка
  `scripts/agent_*.sh`. Docstring писал автор агента; это его формулировка, а
  не наша.
* **quality_metric** — из блока `produces` самого манифеста: артефакт и его
  `slo_hours`. Это ИЗМЕРИМАЯ метрика («артефакт свежее N часов»), уже
  используемая сторожами свежести, а не пожелание вроде «работает хорошо».
* **escalation** — из кода: модуль, вызывающий `push_critical`, эскалирует
  владельцу в Телеграм через `push_policy`; агент без такого вызова, но с
  артефактом под SLO, эскалирует молчанием — его ловит сторож свежести.
  Ни того, ни другого нет ⇒ поле пустое, эскалация НЕ ПРИДУМЫВАЕТСЯ.

Только stdlib. Пишет атомарно. `--check` ничего не пишет.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MANIFEST = REPO / "architecture" / "manifest.json"
FIELDS = ("goal", "quality_metric", "escalation")

# Три способа, которыми обёртки называют свой python-модуль. Порядок важен:
# `export MODULE=` встречается в обёртках нового образца, позиционный
# аргумент `agent_template.sh <имя> <модуль>` — в старых.
_MODULE_PATTERNS = (
    re.compile(r'export\s+MODULE\s*=\s*"([\w][\w.]*\.[\w]+)"'),
    re.compile(r"agent_template\.sh\s+\S+\s+([\w][\w.]*\.[\w]+)"),
    re.compile(r"-m\s+([\w][\w.]*\.[\w]+)"),
)


def module_of(program: str | None) -> str | None:
    """Python-модуль агента по его launchd-обёртке. Комментарии игнорируются.

    Комментарий — не свидетельство: строка «Generated from agent_template.sh»
    есть почти в каждой обёртке и при наивном поиске выдавала модуль
    «(canonical bash» для сорока агентов сразу.
    """
    if not program:
        return None
    wrapper = REPO / "scripts" / program
    if not wrapper.is_file():
        return None
    try:
        lines = wrapper.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for rx in _MODULE_PATTERNS:
            m = rx.search(s)
            if m:
                return m.group(1)
    return None


def _module_file(module: str) -> Path | None:
    f = REPO / (module.replace(".", "/") + ".py")
    return f if f.is_file() else None


_DOC_RX = re.compile(r'(?:^|\n)\s*[ruRU]?("""|\'\'\')(?P<body>.*?)\1', re.S)


def goal_from_docstring(module: str | None) -> str:
    """Первая фраза docstring'а — формулировка автора агента, не наша."""
    if not module:
        return ""
    f = _module_file(module)
    if not f:
        return ""
    try:
        src = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _DOC_RX.search(src)
    if not m:
        return ""
    body = m.group("body").strip()
    if not body:
        return ""
    first = body.split("\n\n")[0].replace("\n", " ").strip()
    # «agent_passports — у каждого агента...» → убрать техническое имя слева
    first = re.sub(r"^[\w.]+\s*[—–-]\s*", "", first)
    # обрезать по концу первого предложения, не разрывая «гл.3»
    cut = re.search(r"\.(?:\s|$)", first)
    if cut:
        first = first[: cut.start() + 1]
    first = re.sub(r"\s{2,}", " ", first).strip()
    return first[:300]


def quality_metric_from_produces(entry: dict) -> str:
    """Измеримая метрика из манифеста: артефакт + его SLO. Без SLO — пусто."""
    parts = []
    for p in entry.get("produces") or []:
        art, slo = p.get("artifact"), p.get("slo_hours")
        if art and slo:
            parts.append(f"{art} свежее {slo} ч")
    return "; ".join(parts)


def escalation_from_code(module: str | None, entry: dict) -> str:
    """Как об отказе узнаёт человек. Только то, что видно в коде/манифесте."""
    f = _module_file(module) if module else None
    if f:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src = ""
        if "push_critical" in src:
            return ("CRITICAL владельцу в Телеграм через push_policy "
                    "(дневной потолок; стоп-кран от него освобождён)")
    if quality_metric_from_produces(entry):
        return ("молчанием: протухший артефакт ловят сторожа свежести "
                "(artifact_freshness / agent_health) по SLO из манифеста")
    return ""


def derive(entry: dict) -> dict:
    module = module_of(entry.get("program"))
    return {
        "goal": goal_from_docstring(module),
        "quality_metric": quality_metric_from_produces(entry),
        "escalation": escalation_from_code(module, entry),
    }


def _dumps(manifest: dict) -> str:
    """Сериализация манифеста КАНОНИЧЕСКИМ сериализатором генератора.

    Не `atomic_save`: его умолчания — `indent=2` и `ensure_ascii=True`, и первая
    же запись переписала бы весь файл (1946 строк → 2391) и превратила бы всю
    кириллицу в `\\uXXXX` — 96 строк там, где на origin их ноль. Дифф на 4331
    строку вместо ~270 нечитаем для ревьюера, а экранированный текст нечитаем
    вообще ни для кого; тесты этого не ловят, потому что структура JSON при этом
    верна. Формат манифеста задан РОВНО в одном месте — `dumps()` генератора, —
    и берётся оттуда, а не переписывается здесь второй раз (одно имя — один
    объект).
    """
    spec = importlib.util.spec_from_file_location(
        "_bam_dumps", REPO / "scripts" / "build_architecture_manifest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.dumps(manifest)


def run(*, write: bool) -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    agents = data.get("agents", [])
    full = partial = empty = 0
    gaps: dict[str, list[str]] = {f: [] for f in FIELDS}
    # Агенты, у которых из источников выводится больше, чем записано в манифесте.
    # Появляются сами: кто-то дописал docstring модулю или докурировал produces —
    # и паспорт молча отстал. Это и делает `--check` гейтом, а не отчётом.
    stale: list[str] = []

    for a in agents:
        derived = derive(a)
        existing = a.get("passport") or {}
        # Существующее НЕ перетирается: если поле уже заполнено человеком,
        # оно ценнее выведенного автоматически.
        merged = {f: (str(existing.get(f) or "").strip() or derived[f]) for f in FIELDS}
        a["passport"] = merged
        have = sum(1 for f in FIELDS if merged[f])
        full += have == len(FIELDS)
        partial += 0 < have < len(FIELDS)
        empty += have == 0
        if merged != {f: str(existing.get(f) or "").strip() for f in FIELDS}:
            stale.append(a["label"])
        for f in FIELDS:
            if not merged[f]:
                gaps[f].append(a["label"])

    # Почему метрика не вывелась — это разные болезни, и лечатся они разно:
    # «манифест не докурирован» чинит куратор, «агент ничего не производит»
    # чинит автор агента. Одно число на двоих скрывало бы обе.
    uncurated = sum(1 for a in agents
                    if not (a.get("passport") or {}).get("quality_metric")
                    and a.get("curation") != "complete")
    report = {
        "total": len(agents),
        "full": full,
        "partial": partial,
        "empty": empty,
        "gaps": {f: len(v) for f, v in gaps.items()},
        "metric_gap_due_to_uncurated_manifest": uncurated,
        "stale": sorted(set(stale)),
        "needs_author": sorted(set(gaps["goal"])),
    }
    if write:
        sys.path.insert(0, str(REPO))
        from spa_core.utils.atomic import atomic_save_text
        atomic_save_text(_dumps(data), str(MANIFEST))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="только отчёт, ничего не писать")
    args = ap.parse_args()
    r = run(write=not args.check)
    print(json.dumps({k: v for k, v in r.items()
                      if k not in ("needs_author", "stale")},
                     ensure_ascii=False, indent=2))
    if r["needs_author"]:
        print(f"\nбез деловой цели ({len(r['needs_author'])}) — у обёртки не читается "
              f"python-модуль или у модуля нет docstring'а:")
        for label in r["needs_author"]:
            print("  ·", label)
        print("\nЭто НЕ ошибка скрипта, а честный список: цель такому агенту "
              "должен написать его автор или владелец.")
    if args.check and r["stale"]:
        print(f"\nМАНИФЕСТ ОТСТАЛ ОТ ИСТОЧНИКОВ ({len(r['stale'])}): у этих агентов "
              "выводится больше, чем записано.", file=sys.stderr)
        for label in r["stale"]:
            print("  ·", label, file=sys.stderr)
        print("\nЗапустите `python3 scripts/fill_agent_passports.py` и закоммитьте "
              "манифест.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
