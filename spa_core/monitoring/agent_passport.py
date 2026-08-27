"""Паспорт агента — обязательное описание функции (ADR-154, гл. 03 «Бизнес, понятный машинам»).

Агент без паспорта не является элементом системы: у него нет объявленной цели, прав,
формата результата и условий передачи человеку. Книга формулирует это резко и точно —
«если роль не получает понятный вход или её результат никто не использует, это не элемент
системы, а отдельная демонстрация».

Замер 27.08 по `architecture/manifest.json`: из 95 агентов **полный паспорт у 24**,
частичный у 47, отсутствует у 24. То есть три четверти флота описаны не до конца, и
понять, кто из них в потоке ценности, нельзя.

Три состояния, а не два (инвариант #17). «Частичный паспорт» — не «есть» и не «нет»:
это начатая и брошенная работа, и её надо видеть отдельно, иначе она вечно будет
считаться либо готовой, либо несуществующей.
"""
from __future__ import annotations

import json
import os
from typing import Iterable

#: Поля паспорта. Порядок — из главы 03: цель · как измеряется качество · кому эскалировать ·
#: что разрешено · что запрещено. Формат результата и входы живут в `produces`/`consumes`
#: самого агента, поэтому здесь не дублируются.
REQUIRED_FIELDS: tuple[str, ...] = ("goal", "quality_metric", "escalation", "rights", "limits")

FULL = "full"
PARTIAL = "partial"
MISSING = "missing"


def passport_state(agent: dict) -> str:
    """Состояние паспорта одного агента: full / partial / missing."""
    p = agent.get("passport") or {}
    if not isinstance(p, dict):
        return MISSING
    filled = [k for k in REQUIRED_FIELDS if str(p.get(k) or "").strip()]
    if len(filled) == len(REQUIRED_FIELDS):
        return FULL
    return PARTIAL if filled else MISSING


def missing_fields(agent: dict) -> list[str]:
    """Каких именно полей не хватает — чтобы отказ был исполнимым, а не «нет паспорта»."""
    p = agent.get("passport") or {}
    if not isinstance(p, dict):
        return list(REQUIRED_FIELDS)
    return [k for k in REQUIRED_FIELDS if not str(p.get(k) or "").strip()]


def load_agents(manifest_path: str | None = None) -> list[dict]:
    path = manifest_path or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "architecture", "manifest.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("agents") or []


def audit(agents: Iterable[dict] | None = None) -> dict:
    """Сводка по флоту. Числа, а не прилагательные — иначе прогресс не измерить."""
    ags = list(agents) if agents is not None else load_agents()
    buckets: dict[str, list[str]] = {FULL: [], PARTIAL: [], MISSING: []}
    for a in ags:
        buckets[passport_state(a)].append(str(a.get("label") or "?"))
    return {
        "total": len(ags),
        "full": len(buckets[FULL]),
        "partial": len(buckets[PARTIAL]),
        "missing": len(buckets[MISSING]),
        "labels": buckets,
    }


def check_agent(label: str, manifest_path: str | None = None) -> tuple[bool, str]:
    """Гейт установки: пускать ли агента во флот.

    Возвращает (ok, причина). Отказ обязан НАЗЫВАТЬ недостающие поля: «нет паспорта» —
    это диагноз без лечения, и такой отказ обходят, а не исполняют.

    Незнакомый агент — тоже отказ (fail-CLOSED): «его нет в манифесте» значит, что решение
    о нём не принималось, а не что он безобиден.
    """
    for a in load_agents(manifest_path):
        if a.get("label") == label:
            st = passport_state(a)
            if st == FULL:
                return True, "паспорт полный"
            miss = ", ".join(missing_fields(a))
            return False, f"паспорт {'частичный' if st == PARTIAL else 'отсутствует'}: нет полей — {miss}"
    return False, f"агента {label} нет в architecture/manifest.json — решение о нём не принималось"


if __name__ == "__main__":
    r = audit()
    print(f"  агентов: {r['total']}")
    print(f"   полный паспорт : {r['full']:3d}")
    print(f"   частичный      : {r['partial']:3d}")
    print(f"   НЕТ паспорта   : {r['missing']:3d}")
