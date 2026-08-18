#!/usr/bin/env python3
"""Прогон приёмки стоит — это ПЛАТО набора или ПОМЕХА?

Зачем этот файл существует
--------------------------
14.08 цикл #226 замерил, что два предписанных прогона рядом «почти останавливаются»
(~2 байта за 15 минут против 18 332 байт за 60 с у одиночного) и записал вывод:
прогоны сериализует какой-то общий ресурс вне worktree, приёмку надо гонять по очереди.

18.08 цикл #289 перемерил и получил ДРУГОЙ ответ. Оба замера верны по своим числам;
разошлись вопросы. Прирост лога сравнивали в РАЗНЫХ МЕСТАХ набора: «быстрая» цифра
снята на участке, где тест занимает миллисекунды, «мёртвая» — там, где ШЕСТЬ тестов
идут 151 секунду. Одиночный прогон без единого соседа встаёт на том же месте ровно
так же (замер: тестов 9577 в момент t=150 с и те же 9577 в t=270 с, соседей нет).
Отсюда и «оба замерли на 8 %»: не помеха, а ОДНО И ТО ЖЕ плато, до которого оба
прогона доезжают примерно одновременно.

Настоящая цена соседства измерена apples-to-apples, на одной и той же цели:
151 с соло → 227 с, когда рядом идёт второй такой же (×1.5), и 291 с под внешней
загрузкой в 4 ядра (×1.9). То есть два прогона рядом заканчиваются за 227 с против
302 с по очереди — правило «гонять по очереди» сделало бы приёмку МЕДЛЕННЕЕ.

Класс дефекта — тот же, что ведётся в STATE отдельным разделом: сторож (здесь —
замер) честно отвечает на свой вопрос, а читают его как ответ на нужный. Поэтому
лечение — не правило, а ИНСТРУМЕНТ: спросить у стоящего прогона, на каком тесте он
стоит, и сверить с базой ИЗМЕРЕННЫХ плато.

Контракт
--------
Вход — только файлы и числа, часов инструмент не читает (время у него ВХОД):
  --progress   stdout прогона `pytest -q` (точки/буквы + « [ NN%]»);
  --collected  stdout `pytest --collect-only -q` теми же целями и в том же порядке;
  --stalled-for  сколько секунд файл прогресса НЕ РОС (меряет вызывающий);
  --baseline   spa_core/tests/acceptance_plateau_baseline.json.

Вердикты и коды возврата:
  0  PLATEAU              — стоим на измеренном плато и в пределах его бюджета: ЖДАТЬ;
  1  CONTENTION_CANDIDATE — плато не объясняет остановку: ИСКАТЬ ПОМЕХУ;
  2  UNMEASURED           — нечем ответить (fail-CLOSED; «не измерено» ≠ «всё хорошо»).

Только stdlib, сети нет, ничего не пишет.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Символы, которыми pytest -q отмечает ЗАВЕРШЁННЫЙ тест. Один символ — один тест.
PROGRESS_CHARS = set(".sxXfFEupP")

PLATEAU = "PLATEAU"
CONTENTION = "CONTENTION_CANDIDATE"
UNMEASURED = "UNMEASURED"

_EXIT = {PLATEAU: 0, CONTENTION: 1, UNMEASURED: 2}


def completed_tests(progress_text: str) -> int:
    """Сколько тестов ЗАВЕРШЕНО, по stdout `pytest -q`.

    Считаются только строки, целиком состоящие из символов прогресса (после снятия
    хвоста « [ NN%]»). Всё остальное — заголовки, предупреждения, сводка — не в счёт:
    иначе слово `passed` в сводке добавило бы шесть несуществующих тестов.
    """
    total = 0
    for raw in progress_text.splitlines():
        line = raw.rstrip()
        if line.endswith("]") and "[" in line:
            line = line[: line.rindex("[")]
        line = line.strip()
        if not line:
            continue
        if all(ch in PROGRESS_CHARS for ch in line):
            total += len(line)
    return total


def collected_ids(collected_text: str) -> list[str]:
    """Упорядоченный список идентификаторов тестов из `pytest --collect-only -q`."""
    ids: list[str] = []
    for raw in collected_text.splitlines():
        line = raw.strip()
        if "::" not in line or line.startswith(("=", "-", "ERROR", "warning")):
            continue
        ids.append(line)
    return ids


def file_of(test_id: str) -> str:
    return test_id.split("::", 1)[0]


def load_baseline(raw: Any) -> dict[str, dict[str, Any]]:
    """Читает базу плато. Запись без ЗАМЕРА не принимается — она и есть дефект.

    Требуются `solo_seconds` (> 0), `budget_seconds` (>= solo_seconds) и непустой
    `evidence`. Плато, объявленное без числа и без доказательства, — это ровно то
    поверье, которое инструмент заведён опровергать; принять его значило бы
    научить инструмент молчать по чужому слову.
    """
    if not isinstance(raw, dict):
        raise ValueError("база плато: ожидался объект")
    plateaus = raw.get("plateaus")
    if not isinstance(plateaus, dict):
        raise ValueError("база плато: нет объекта `plateaus`")
    out: dict[str, dict[str, Any]] = {}
    for path, entry in plateaus.items():
        if not isinstance(entry, dict):
            raise ValueError(f"база плато: запись `{path}` не объект")
        solo = entry.get("solo_seconds")
        budget = entry.get("budget_seconds")
        evidence = entry.get("evidence")
        if not isinstance(solo, (int, float)) or solo <= 0:
            raise ValueError(f"база плато: `{path}` без замера `solo_seconds`")
        if not isinstance(budget, (int, float)) or budget < solo:
            raise ValueError(
                f"база плато: `{path}` — `budget_seconds` меньше замера `solo_seconds`"
            )
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"база плато: `{path}` без доказательства `evidence`")
        out[path] = {"solo_seconds": float(solo), "budget_seconds": float(budget),
                     "evidence": evidence.strip()}
    return out


def diagnose(progress_text: str, collected_text: str, stalled_for_s: float,
             baseline: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Чистое суждение: где стоим и объясняет ли это плато. Часов не читает."""
    if stalled_for_s < 0:
        return {"verdict": UNMEASURED, "reason": "отрицательное время простоя — не измерено",
                "completed": None, "current": None}

    ids = collected_ids(collected_text)
    if not ids:
        return {"verdict": UNMEASURED, "reason": "список собранных тестов пуст — сверять не с чем",
                "completed": None, "current": None}

    done = completed_tests(progress_text)
    if done >= len(ids):
        return {"verdict": UNMEASURED,
                "reason": (f"завершено {done} при собранных {len(ids)} — прогресс и список "
                           f"не об одном прогоне"),
                "completed": done, "current": None}

    current = ids[done]
    path = file_of(current)
    entry = baseline.get(path)
    if entry is None:
        return {"verdict": CONTENTION, "completed": done, "current": current, "file": path,
                "stalled_for_s": stalled_for_s, "budget_s": None,
                "reason": (f"файл `{path}` в базе измеренных плато не значится — "
                           f"остановку объяснить нечем, искать помеху")}
    if stalled_for_s > entry["budget_seconds"]:
        return {"verdict": CONTENTION, "completed": done, "current": current, "file": path,
                "stalled_for_s": stalled_for_s, "budget_s": entry["budget_seconds"],
                "reason": (f"плато `{path}` замерено в {entry['solo_seconds']:.0f} с, бюджет "
                           f"{entry['budget_seconds']:.0f} с — стоим {stalled_for_s:.0f} с, "
                           f"это дольше плато")}
    return {"verdict": PLATEAU, "completed": done, "current": current, "file": path,
            "stalled_for_s": stalled_for_s, "budget_s": entry["budget_seconds"],
            "reason": (f"плато `{path}`: замерено {entry['solo_seconds']:.0f} с СОЛО, "
                       f"стоим {stalled_for_s:.0f} с — прогон исправен, ждать"),
            "evidence": entry["evidence"]}


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--progress", required=True, help="stdout прогона `pytest -q`")
    ap.add_argument("--collected", required=True, help="stdout `pytest --collect-only -q`")
    ap.add_argument("--stalled-for", required=True, type=float,
                    help="секунд без роста файла прогресса (меряет вызывающий)")
    ap.add_argument("--baseline", default=str(
        Path(__file__).resolve().parents[1] / "tests" / "acceptance_plateau_baseline.json"))
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    try:
        baseline = load_baseline(json.loads(_read(args.baseline)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"verdict": UNMEASURED, "reason": f"база плато не прочитана: {exc}",
                  "completed": None, "current": None}
    else:
        try:
            result = diagnose(_read(args.progress), _read(args.collected),
                              args.stalled_for, baseline)
        except OSError as exc:
            result = {"verdict": UNMEASURED, "reason": f"вход не прочитан: {exc}",
                      "completed": None, "current": None}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"вердикт: {result['verdict']}")
        print(f"  {result['reason']}")
        if result.get("current"):
            print(f"  стоим на: {result['current']}")
        if result.get("evidence"):
            print(f"  замер: {result['evidence']}")
    return _EXIT[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
