"""future_stamp_detector.py — отметка артефакта ИЗ БУДУЩЕГО это порча, а не находка.

Контракт **C3(d)** ADR-580 (RM-TRUTH-01), по следу INC-1: прод-агент `com.spa.decision_loop`
зовёт G97-зонд (`artifact_stamp_clock_doors.py`) в одноразовом дереве; зонд выставляет
`SPA_STAMP_*`, но не `SPA_DATA_DIR`/`SPA_LIVE_ROOT`, и производитель, резолвящий путь через
`spa_core.utils.live_paths`, уводит запись в прод. `owner_decision_pending.json` получил
`generated_at: 2041-11-23T19:53:29Z` — якорь инъекции зонда — и простоял в проде 33 минуты,
пока `agent_health` не перезаписал его собственным циклом. Рецензия `docs/rm_truth/REVIEW_1.md`
(п. 1, амендмент C3(d)): «OWNER_CONTROL_HEALTH must flag future-dated stamps ... That detector
would have caught INC-1 in minutes.»

Этот модуль — ТОЛЬКО ЧТЕНИЕ. Он не чинит утечку (её закрывает `live_paths.live_root()` —
C8(a)) и не зовёт производителей — он сканирует УЖЕ ЛЕЖАЩИЕ на диске JSON-артефакты и
называет те, чья отметка обогнала часы больше чем на допуск.

## Три исхода (инв. #17), а не одно число

* **``OK``** — каталог прочитан, отметок из будущего нет. Измерено и равно нулю.
* **``CORRUPT``** — каталог прочитан, хотя бы одна отметка из будущего найдена. Измерено,
  находка есть.
* **``UNCHECKED``** — каталог не прочитан (не существует, нет прав, ``glob`` упал). НЕ
  ИЗМЕРЕНО, с названной причиной — не ``OK`` и не ноль находок.

``now`` — ВХОД, а не стенные часы (`.claude/rules/deployment.md`, «Время в тестах»): вызывающий
обязан передать его явно, иначе прогон, завязанный на календарь машины, стал бы бомбой.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

#: Ключи отметки, в порядке опроса. Тот же порядок, что у `_artifact_stamp_clock_probe`
#: (G97) — два прибора обязаны видеть одну и ту же отметку одинаково.
#: ``updated_at`` добавлен F13 (ADR-580 §C3(d), REVIEW_1 amendment): реальный
#: `data/telegram_bot_capabilities.json` (маячок бота, область OWNER_CONTROL_HEALTH)
#: несёт отметку под ИМЕННО этим именем — без ключа файл не читался этим прибором
#: ВООБЩЕ, молча, что и обнажил замер 2026-10-05 на живой копии.
STAMP_KEYS = ("generated_at", "as_of", "timestamp", "generated", "measured_at", "updated_at")

#: Допуск часов по умолчанию: инъекция/перекос NTP не есть порча, разница в часах — есть.
DEFAULT_SKEW = timedelta(minutes=10)

#: Артефакты области OWNER_CONTROL_HEALTH (C3 ADR-580): маячок бота, журнал решений
#: владельца (push-журнал/«push_state») и отчёт «путь вверх» — ровно тот файл, который
#: получил отметку 2041 года в INC-1. НЕ `equity_curve_daily.json`/`resilience_status.json`
#: и прочее PRODUCT_DATA_HEALTH/STUDIO_OS_HEALTH — у них свой, отдельно откалиброванный
#: допуск (`agent_health_monitor.CLOCK_SKEW_H`), и смешивать области значило бы давать
#: ОДНОМУ факту два разных вердикта.
OWNER_CONTROL_FILES = (
    "owner_decision_pending.json",
    "telegram_bot_capabilities.json",
    "telegram_owner_decisions.json",
)

OK = "OK"
CORRUPT = "CORRUPT"
UNCHECKED = "UNCHECKED"


def _read_stamp(doc: object) -> tuple[Optional[str], Optional[str]]:
    """Отметка документа и ИМЯ ключа, под которым она найдена.

    Не словарь либо ни одного известного ключа ⇒ ``(None, None)`` — отсутствие
    отметки есть самостоятельное значение, а не повод падать.
    """
    if not isinstance(doc, dict):
        return None, None
    for key in STAMP_KEYS:
        if key in doc and doc[key] is not None:
            return str(doc[key]), key
    return None, None


def _parse_ts(raw: str) -> Optional[datetime]:
    """ISO-8601, включая ``Z``. Не разобралось ⇒ ``None`` — не наш предмет, не авария.

    F13 (ADR-580 §C3(d), REVIEW_1 amendment): больше НЕ подставляет UTC голой
    (``tzinfo is None``) отметке. Писатель, выпустивший наивное МЕСТНОЕ время
    (например +02:00), под старым допущением выглядел бы на два часа «из
    будущего» и получал ложный CORRUPT — ровно та подмена, которую инвариант
    #17 запрещает в обратную сторону (угадывание вместо честного «не измерено»).
    Пояс не назван ⇒ сравнивать нельзя; разбор пояса — забота вызывающего
    (`scan_data_dir`, отдельный третий исход на файл), не этой функции.
    """
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except (ValueError, AttributeError):
        return None


def scan_data_dir(data_dir: Path | str, *, now: datetime,
                  skew: timedelta = DEFAULT_SKEW,
                  pattern: str = "*.json",
                  filenames: Optional[List[str]] = None) -> Dict[str, object]:
    """Просканировать JSON-артефакты ``data_dir`` верхнего уровня на отметку из будущего.

    Не рекурсивный НАРОЧНО: `data/` несёт тысячи файлов, а предмет контракта — отметка
    КОНКРЕТНОГО артефакта, который кто-то читает как «текущее состояние» (ровно класс
    `owner_decision_pending.json`), а не произвольный вложенный журнал.

    ``filenames`` — ИМЕНОВАННЫЙ список вместо ``pattern``: у каждой области C3 (ADR-580)
    своя граница. Областной читатель (например ``OWNER_CONTROL_HEALTH``, п. ниже) обязан
    видеть ТОЛЬКО свои артефакты — иначе отметка `equity_curve_daily.json`, у которой уже
    есть СВОЙ, отдельно настроенный и менее строгий допуск (`CLOCK_SKEW_H` в
    `agent_health_monitor`), получит ВТОРОЙ, более строгий вердикт от этого прибора и
    прочитается как более серьёзная находка, хотя предмет контракта тот же факт. Пустой
    список (а не ``None``) ⇒ ни одного файла не выбрано — это ЗАКОНЧЕННЫЙ замер по пустому
    населению (``OK``, не ``UNCHECKED``), а не повод падать на пустом входе.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    root = Path(data_dir)
    result: Dict[str, object] = {
        "checked_at": now.isoformat(),
        "skew_minutes": round(skew.total_seconds() / 60.0, 2),
        "data_dir": str(root),
        "files_scanned": 0,
        "stamps_read": 0,
        "corrupt": [],
        # F13 (ADR-580 §C3(d), REVIEW_1 amendment, инв. #17): файл, который
        # прибор НЕ сравнил с часами, — именованный третий исход, а не тишина.
        # ``reason`` ∈ {"no_stamp" (ни один STAMP_KEYS не нашёлся),
        # "unparseable" (значение есть, ISO-8601 не разобрался),
        # "naive" (пояс не назван — угадывать UTC запрещено, см. `_parse_ts`)}.
        "unchecked_files": [],
        "status": UNCHECKED,
        "reason": None,
    }
    try:
        if not root.is_dir():
            # `Path.glob` на несуществующем каталоге тихо отдаёт пустой перебор —
            # без этой проверки «каталога нет» и «каталог пуст» слились бы в один
            # и тот же `OK`, а это ровно та подмена, против которой написан инв. #17.
            result["reason"] = f"каталог не существует: {root}"
            return result
        if filenames is not None:
            files = sorted(p for p in (root / name for name in filenames) if p.is_file())
        else:
            files = sorted(p for p in root.glob(pattern) if p.is_file())
    except OSError as exc:
        result["reason"] = f"каталог не прочитан: {type(exc).__name__}: {exc}"
        return result

    result["files_scanned"] = len(files)
    threshold = now + skew
    corrupt: List[dict] = []
    unchecked_files: List[dict] = []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            # Не JSON / не прочитан — не наш предмет: не каждый файл в data/ им обязан быть.
            continue
        stamp_raw, stamp_key = _read_stamp(doc)
        if stamp_raw is None:
            unchecked_files.append({"path": path.name, "reason": "no_stamp"})
            continue
        parsed = _parse_ts(stamp_raw)
        if parsed is None:
            unchecked_files.append({"path": path.name, "stamp_key": stamp_key,
                                    "stamp": stamp_raw, "reason": "unparseable"})
            continue
        if parsed.tzinfo is None:
            # F13: наивная отметка — пояс не назван, угадывать UTC запрещено
            # (см. `_parse_ts`). Именованный третий исход, а не молчаливый OK.
            unchecked_files.append({"path": path.name, "stamp_key": stamp_key,
                                    "stamp": stamp_raw, "reason": "naive"})
            continue
        result["stamps_read"] = int(result["stamps_read"]) + 1
        if parsed > threshold:
            corrupt.append({
                "path": path.name,
                "stamp_key": stamp_key,
                "stamp": stamp_raw,
                "ahead_minutes": round((parsed - now).total_seconds() / 60.0, 1),
            })

    result["corrupt"] = corrupt
    result["unchecked_files"] = unchecked_files
    result["status"] = CORRUPT if corrupt else OK
    return result


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: ``python3 -m spa_core.monitoring.future_stamp_detector [--data-dir PATH]``.

    Коды возврата: 0 — OK, 1 — CORRUPT (находки названы), 2 — НЕ ИЗМЕРЕНО.
    """
    import argparse

    from spa_core.utils.live_paths import live_data_dir

    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.monitoring.future_stamp_detector")
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else live_data_dir()
    doc = scan_data_dir(data_dir, now=datetime.now(timezone.utc))
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    if doc["status"] == UNCHECKED:
        return 2
    return 1 if doc["status"] == CORRUPT else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(sys.argv[1:]))
