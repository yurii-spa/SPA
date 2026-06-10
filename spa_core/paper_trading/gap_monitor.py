"""
MP-009: Gap Monitor — детектор пропущенных дней paper trading цикла.
Запускается как standalone скрипт или импортируется.
Пишет data/gap_monitor.json атомарно.
Алерт: если последний бар equity_curve старше 26 часов → gap detected.
"""
import json, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
EQUITY_FILE = DATA_DIR / "equity_curve_daily.json"
GAP_STATUS_FILE = DATA_DIR / "gap_monitor.json"
GAP_THRESHOLD_HOURS = 26  # сутки + 2ч буфер для launchd jitter

def check_gaps() -> dict:
    now = datetime.now(timezone.utc)
    result = {
        "checked_at": now.isoformat(),
        "gap_detected": False,
        "last_entry_date": None,
        "hours_since_last_entry": None,
        "status": "ok",
        "message": ""
    }

    if not EQUITY_FILE.exists():
        result.update({"gap_detected": True, "status": "no_data",
                        "message": "equity_curve_daily.json не найден"})
        _write(result)
        return result

    try:
        doc = json.loads(EQUITY_FILE.read_text())
    except Exception as e:
        result.update({"gap_detected": True, "status": "parse_error",
                        "message": str(e)})
        _write(result)
        return result

    # Поддержка двух форматов: документ cycle_runner {"is_demo":..., "daily":[...]}
    # (is_demo на уровне документа) и плоский список записей.
    if isinstance(doc, dict):
        entries = doc.get("daily") or []
        default_demo = bool(doc.get("is_demo", True))
    else:
        entries = doc if isinstance(doc, list) else []
        default_demo = True

    real = [e for e in entries
            if isinstance(e, dict) and not e.get("is_demo", default_demo)]
    if not real:
        result.update({"gap_detected": True, "status": "no_real_entries",
                        "message": "Нет реальных (is_demo:false) записей"})
        _write(result)
        return result

    # Последняя запись — по полю date или timestamp
    def parse_dt(e):
        for k in ("timestamp", "date", "ts"):
            if k in e:
                try:
                    return datetime.fromisoformat(e[k].replace("Z", "+00:00"))
                except:
                    pass
        return None

    last_dt = max((parse_dt(e) for e in real if parse_dt(e)), default=None)
    if last_dt is None:
        result.update({"gap_detected": True, "status": "no_timestamp",
                        "message": "Нет разбираемого timestamp"})
        _write(result)
        return result

    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)

    hours_ago = (now - last_dt).total_seconds() / 3600
    result["last_entry_date"] = last_dt.isoformat()
    result["hours_since_last_entry"] = round(hours_ago, 2)

    if hours_ago > GAP_THRESHOLD_HOURS:
        result.update({
            "gap_detected": True,
            "status": "gap",
            "message": f"Последний бар {hours_ago:.1f}ч назад — цикл пропустил день"
        })
    else:
        result.update({"status": "ok", "message": f"Последний бар {hours_ago:.1f}ч назад — норма"})

    _write(result)
    return result

def _write(data: dict):
    tmp = GAP_STATUS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(GAP_STATUS_FILE)

if __name__ == "__main__":
    r = check_gaps()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r["gap_detected"]:
        import sys; sys.exit(1)
