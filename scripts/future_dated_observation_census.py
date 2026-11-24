#!/usr/bin/env python3
"""Перепись секций панели владельца, чья отметка наблюдения стоит ВПЕРЁД судящих часов.

**Зачем.** `mission_control._meta()` низводит состояние до `STALE`, когда возраст
наблюдения БОЛЬШЕ порога: `age > stale_after_min`. На ОТРИЦАТЕЛЬНОМ возрасте это
сравнение ложно ВСЕГДА, то есть отметка, помеченная вперёд относительно часов,
читается как свежая — и чем грубее расхождение, тем надёжнее она выглядит свежей
(замер ADR-1078: `age_min=-89119.5` при пороге 1560, состояние `HEALTHY`).
Карточка `inbox-vozrast-nablyudeniya-byvaet-otritsatelny` требовала порядок
«СПЕРВА население, ПОТОМ правка»: правка `_meta` задевает ВСЕ секции панели
владельца, и красить её, не зная цены, — та же ошибка в другую сторону.

**Почему дешёвая ось не годится.** «Есть ли в коде сравнение `age > порог`»
назовёт все зовы `_meta` поголовно — сравнение у них ОДНО и общее. Поверхность
есть СОСТОЯНИЕ живого дерева `data/`, а не свойство текста, поэтому перепись
СОБИРАЕТ модель и пересчитывает возраст у каждой секции.

**Дерево — ВХОД, и выбор ПЕЧАТАЕТСЯ.** Из worktree живого `data/` нет по
построению (§ `.claude/rules/deployment.md`), а умолчание `MCInputs.repo` — дерево
ЗАПУЩЕННОГО кода. Молча подставить чужое дерево хуже ошибки: читатель не узнает,
о чьём `data/` ему ответили.

**Исходы (инв. #17) — три, и они различимы:**

* **0** — находок нет: ни одна секция не стои́т впереди часов дальше допуска;
* **1** — НАХОДКА: секция впереди часов дальше допуска (поимённо, с возрастом);
* **2** — НЕ ИЗМЕРЕНО с названной причиной (модель не собралась · в модели нет
  ни одной секции объявленной формы). Ноль секций НЕ выдаётся за «чисто»:
  перепись, не нашедшая поверхности, отвечает о СВОЕЙ немочи.

Прибор только ЧИТАЕТ: ни один сторож, артефакт и файл им не изменяется.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]

# launchd и оболочка зовут СКРИПТ ПО ПУТИ, и тогда `sys.path[0]` — каталог
# `scripts/`, а не корень репозитория (§ `.claude/rules/deployment.md`, ADR-148).
# Без этой строки ввоз падает, и перепись честно отвечает «НЕ ИЗМЕРЕНО» о СВОЕЙ
# немочи вместо вопроса, который ей задали.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

#: Допуск читается ИЗ дома, а не назначается здесь: та же величина, которой уже
#: судят `readiness_scopes`/`company_truth`. Своя копия числа развела бы ответ
#: переписи с ответом панели ровно на разницу двух литералов.
try:  # pragma: no cover - ввоз мерится отдельным исходом ниже
    from spa_core.studio_os.readiness_scopes import FUTURE_SKEW_MINUTES
except Exception:  # noqa: BLE001
    FUTURE_SKEW_MINUTES = None  # type: ignore[assignment]

OK, FINDING, UNMEASURED = 0, 1, 2

AHEAD_BEYOND = "ВПЕРЁД ЧАСОВ ДАЛЬШЕ ДОПУСКА"
AHEAD_WITHIN = "впереди часов в пределах допуска"
BEHIND = "позади часов"
NO_STAMP = "отметки наблюдения нет"


def classify(age_min: Optional[float], tolerance: float) -> str:
    """Род ОДНОЙ секции. Отрицательный возраст — не «свежо» и не «протухло»."""
    if age_min is None:
        return NO_STAMP
    if age_min >= 0:
        return BEHIND
    return AHEAD_WITHIN if -age_min <= tolerance else AHEAD_BEYOND


def sections(model: Any) -> list[dict]:
    """Все секции модели, несущие конверт `_meta` с полем возраста.

    Форма объявлена `mission_control._meta`; секция без поля `age_min` в
    население НЕ входит, и это граница ОХВАТА, а не замер её пустоты.
    """
    found: list[dict] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            meta = node.get("_meta")
            if isinstance(meta, dict) and "age_min" in meta:
                found.append({"path": path or "root", "state": meta.get("state"),
                              "age_min": meta.get("age_min"),
                              "stale_after_min": meta.get("stale_after_min"),
                              "observed_at": meta.get("observed_at")})
            for key, value in node.items():
                if key == "_meta":
                    continue
                walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(model, "")
    return found


def run(repo: Path, now: Optional[datetime] = None) -> tuple[int, list[str]]:
    out: list[str] = []
    if FUTURE_SKEW_MINUTES is None:
        return UNMEASURED, ["НЕ ИЗМЕРЕНО: допуск `readiness_scopes.FUTURE_SKEW_MINUTES` не ввозится — "
                            "своего числа перепись не назначает"]
    tolerance = float(FUTURE_SKEW_MINUTES)
    try:
        from spa_core.studio_os import mission_control as mc
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, [f"НЕ ИЗМЕРЕНО: модель не ввозится — {type(exc).__name__}: {exc}"]

    out.append(f"дерево НАЗВАНО: {repo} (живое `data/` читается отсюда)")
    out.append(f"допуск: {tolerance:g} мин ← readiness_scopes.FUTURE_SKEW_MINUTES")
    try:
        model = mc.build(mc.MCInputs(repo=repo, now=now))
    except Exception as exc:  # noqa: BLE001
        return UNMEASURED, out + [f"НЕ ИЗМЕРЕНО: модель не собралась — {type(exc).__name__}: {exc}"]

    rows = sections(model)
    if not rows:
        return UNMEASURED, out + ["НЕ ИЗМЕРЕНО: в модели нет ни одной секции объявленной формы "
                                  "(`_meta` с полем `age_min`) — ноль секций это НЕ «чисто»"]

    kinds: dict[str, list[dict]] = {}
    for row in rows:
        kinds.setdefault(classify(row["age_min"], tolerance), []).append(row)

    out.append(f"секций объявленной формы: {len(rows)} · "
               + " · ".join(f"{k} {len(v)}" for k, v in sorted(kinds.items())))

    # Впереди часов В ПРЕДЕЛАХ допуска находкой НЕ является и замалчиванием тоже:
    # это измеренный род, и его печать — единственное, что отличает «такого нет»
    # от «не смотрели».
    for row in kinds.get(AHEAD_WITHIN, []):
        out.append(f"  · {row['path']}: {row['age_min']} мин (в пределах допуска, "
                   f"состояние {row['state']}) — окно чтения сборки, не расхождение часов")
    for row in kinds.get(NO_STAMP, []):
        out.append(f"  · {row['path']}: отметки нет (состояние {row['state']})")

    findings = kinds.get(AHEAD_BEYOND, [])
    for row in findings:
        out.append(f"  ⚠️ НАХОДКА {row['path']}: возраст {row['age_min']} мин при пороге "
                   f"{row['stale_after_min']} · состояние {row['state']} · отметка {row['observed_at']} — "
                   "порог на отрицательном возрасте не срабатывает НИКОГДА")
    if findings:
        out.append(f"НАХОДОК: {len(findings)} — секция впереди судящих часов дальше допуска "
                   "читается как свежая")
        return FINDING, out
    out.append("✅ находок нет: ни одна секция не стои́т впереди часов дальше допуска")
    return OK, out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Перепись секций панели владельца с отметкой ВПЕРЁД судящих часов "
                    "(карточка inbox-vozrast-nablyudeniya-byvaet-otritsatelny, ADR-1078).")
    ap.add_argument("--repo", default=None,
                    help="дерево, чьё живое `data/` читать (по умолчанию — дерево ЗАПУЩЕННОГО кода; "
                         "выбор ПЕЧАТАЕТСЯ)")
    ap.add_argument("--now", default=None,
                    help="момент, от которого считать возраст, ISO-8601 (по умолчанию стенные часы)")
    args = ap.parse_args([] if argv is None else argv)

    repo = Path(args.repo).resolve() if args.repo else REPO
    if args.repo is None:
        print(f"🧭 дерево НЕ НАЗВАНО — взято УМОЛЧАНИЕ (дерево запущенного кода): {repo}")
    now = None
    if args.now is not None:
        try:
            now = datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        except ValueError:
            print(f"НЕ ИЗМЕРЕНО: `--now` не разбирается: {args.now!r}", file=sys.stderr)
            return UNMEASURED
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

    code, lines = run(repo, now)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
