#!/usr/bin/env python3
"""Связность базы знаний — числом, а не ощущением (ADR-154).

Зачем. 27.08 сессия трижды не нашла существующее: ADR-125 о старте трёх пакетов, файлы
`hy/lp_paper_trading.json`, ключ `daily_history`. Каждый раз вывод был «этого нет», а
правильный — «я не знаю, где смотреть». Общая причина одна: **к этим файлам не ведёт ни
одной ссылки**, и найти их можно только угадав имя.

Замер того же дня: 1150 заметок, 841 связь, **1064 сироты** — девять из десяти документов
не связаны ни с чем. Обратная сторона: три индекса дают 257 связей из 841, то есть доступ
к решениям держится на нескольких файлах, и их устаревание рвёт его целиком (в тот же день
пушер остановил отправку локального `INDEX.md` с 43 строками вместо 111).

Что считаем и почему именно это:

* **сироты** — на них никто не ссылается; их находят угадыванием, то есть случайно;
* **концентраторы** — через них проходит доступ; это точки отказа знания;
* **связность** — доля узлов, до которых есть путь: одно число для брифинга.

Обсидиан рисует те же связи; здесь та же правда, но числом — картинку в брифинг не положишь.
Учитываются ОБА написания: `[[wiki]]` и обычные markdown-ссылки на `.md` (их у нас
большинство — 3288 против 41, и первый замер, смотревший только на wiki, дал неверный ответ).

Только stdlib. Атомарная запись через `atomic_save`.
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
from typing import Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

OUTPUT = os.path.join(ROOT, "data", "knowledge_graph.json")

#: Каталоги вне разбора: копии дерева и карантин исказили бы счёт дублями.
SKIP_DIRS = {".git", "worktrees", "node_modules", ".obsidian", "attic", "archive"}

#: Обе формы ссылки. Первая группа — `[[wiki]]`, вторая — `[текст](путь.md)`.
_LINK = re.compile(r"\[\[([^\]|#]+)|\]\(([^)]+?\.md)[^)]*\)")


def _iter_notes(root: str) -> Iterable[str]:
    for cur, dirs, files in os.walk(root):
        # `.claude/` НЕ исключается: там живут обязательные правила, и без них замер
        # считал бы связность всего, кроме главного (замер 27.08 — четыре правила
        # безопасности не попадали в граф вовсе). Остальные скрытые каталоги пропускаем.
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and (d == ".claude" or not d.startswith("."))]
        for fn in files:
            if fn.endswith(".md"):
                yield os.path.relpath(os.path.join(cur, fn), root)


def _targets(text: str, src: str) -> list[str]:
    out = []
    for m in _LINK.finditer(text):
        t = (m.group(1) or m.group(2) or "").strip()
        if not t:
            continue
        # Относительная ссылка разрешается от каталога источника; wiki-ссылка —
        # по имени, как это делает сам Obsidian.
        out.append(os.path.normpath(os.path.join(os.path.dirname(src), t))
                   if "/" in t else t)
    return out


def build(root: str | None = None) -> dict:
    root = root or ROOT
    nodes, edges = [], []
    for rel in _iter_notes(root):
        nodes.append(rel)
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        edges.extend((rel, t) for t in _targets(text, rel))

    node_set = set(nodes)
    deg_in = collections.Counter(b for _, b in edges)
    deg_out = collections.Counter(a for a, _ in edges)
    # Сирота — узел, на который не ссылается НИКТО. Считаем по обоим написаниям цели:
    # ссылка может указывать полным путём или голым именем.
    # Wiki-ссылка пишется БЕЗ расширения (`[[b]]` при файле `b.md`) — сопоставляем
    # оба написания, иначе связанная заметка ложно считается сиротой (замер 27.08).
    by_name = collections.Counter()
    for tgt, n in deg_in.items():
        base = os.path.basename(str(tgt))
        by_name[base] += n
        if not base.endswith(".md"):
            by_name[base + ".md"] += n
    # Что НЕ является знанием и потому не участвует в счёте связности:
    #   nimbalyst-local/ — очередь задач (531 «сирота» на замере 27.08);
    #   data/            — runtime-артефакты, их пишут агенты, а не люди (68);
    #   reports/         — разовые выгрузки.
    # Смысл вычета один: метрика, состоящая из НОРМЫ, учит себя не читать — тот же
    # дефект был у сторожа дрейфа. Каталоги названы ЯВНО, а не отфильтрованы по
    # признаку: иначе завтра под правило попадёт настоящее знание и исчезнет молча.
    NOT_KNOWLEDGE = ("nimbalyst-local", "data", "reports")
    knowledge = {x for x in node_set if x.split(os.sep)[0] not in NOT_KNOWLEDGE}
    orphans = sorted(x for x in knowledge
                     if not deg_in.get(x) and not by_name.get(os.path.basename(x)))
    # Разбивка по областям — чтобы кучу можно было разбирать, а не смотреть.
    by_area: dict[str, int] = {}
    for x in orphans:
        area = x.split(os.sep)[0] if os.sep in x else "(корень)"
        by_area[area] = by_area.get(area, 0) + 1

    linked = len(knowledge) - len(orphans)
    # Обязательные правила — отдельно от общей связности. Общая может быть любой;
    # НЕДОСТИЖИМОЕ ПРАВИЛО — дефект: сессия узнает о нём только угадав путь.
    # `CLAUDE.md` в список НЕ входит: он корень, его загружают по соглашению, а не по
    # ссылке — требовать ссылку на него значило бы искать вход в дом изнутри дома.
    # Меряем то, что от корня достижимо: правила области.
    mandatory = sorted(n for n in node_set if n.startswith(".claude/rules/"))
    unreachable = [n for n in mandatory
                   if not deg_in.get(n) and not by_name.get(os.path.basename(n))]
    return {
        "notes": len(knowledge),
        "notes_all": len(node_set),
        "orphans_by_area": dict(sorted(by_area.items(), key=lambda kv: -kv[1])),
        "mandatory_rules": len(mandatory),
        "mandatory_unreachable": unreachable,
        "links": len(edges),
        "linked": linked,
        "orphans": len(orphans),
        # Одно число для брифинга: доля документов, до которых ведёт хоть одна ссылка.
        "connectivity_pct": round(100.0 * linked / len(knowledge), 1) if knowledge else 0.0,
        "hubs": [{"note": f, "out": n} for f, n in deg_out.most_common(8)],
        "most_cited": [{"note": str(f), "in": n} for f, n in deg_in.most_common(8)],
        "orphan_sample": orphans[:40],
    }


def main() -> int:
    rep = build()
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(OUTPUT, rep)
    except Exception:  # noqa: BLE001
        with open(OUTPUT, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=1)
    print(f"  заметок {rep['notes']} · связей {rep['links']} · "
          f"связность {rep['connectivity_pct']}% · сирот {rep['orphans']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
