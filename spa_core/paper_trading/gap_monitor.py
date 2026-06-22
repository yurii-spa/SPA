"""
MP-009: Gap Monitor — детектор пропущенных дней paper trading цикла.
MP-101: + CRITICAL-алерт в data/risk_alerts.json и детерминированная
        auto-recovery (попытка штатного paper-цикла под file-lock).

Запускается как standalone скрипт или импортируется.
Пишет data/gap_monitor.json атомарно.
Алерт: если последний бар equity_curve старше 26 часов → gap detected.

CLI:
    python3 -m spa_core.paper_trading.gap_monitor            # только детекция (как раньше)
    python3 -m spa_core.paper_trading.gap_monitor --recover  # детекция + 1 попытка recovery

STRICTLY READ-ONLY / paper trading only (SPA-BL-011): recovery лишь
запускает штатный run_cycle() из cycle_runner (read-only simulation) —
никаких реальных транзакций, execution/risk/wallet-код не импортируется.
"""
import json, os, time
from datetime import datetime, timezone
from pathlib import Path
from spa_core.utils.atomic import atomic_save, atomic_load, file_lock  # noqa: F401 — required by atomic migration policy

DATA_DIR = Path(__file__).parent.parent.parent / "data"
EQUITY_FILE = DATA_DIR / "equity_curve_daily.json"
GAP_STATUS_FILE = DATA_DIR / "gap_monitor.json"
GAP_THRESHOLD_HOURS = 26  # сутки + 2ч буфер для launchd jitter

# ─── MP-101: алерты + recovery ───────────────────────────────────────────────
RISK_ALERTS_FILE = DATA_DIR / "risk_alerts.json"
RECOVERY_LOCK_FILE = DATA_DIR / "gap_recovery.lock"
LOCK_STALE_SECONDS = 2 * 3600   # lock старше 2ч считается протухшим (упавший процесс)
ALERT_SOURCE = "gap_monitor"
ALERT_TYPE = "cycle_gap"
MAX_ALERTS = 200                # страховочный cap списка alerts

def check_day_gaps(entries: list) -> dict:
    """Проверить пропущенные дни в реальных (не warmup) записях equity curve.

    Берёт все записи без is_warmup/is_seed, сортирует по дате и ищет
    промежутки > 3 календарных дней (допускает пропуск выходных: Пт→Пн = 3 дня).

    Args:
        entries: список daily-баров из equity_curve_daily.json ["daily"].

    Returns:
        dict с ключами:
            has_gaps     — True, если найден хотя бы один пропуск > 3 дней.
            day_gaps     — список {"from": date, "to": date, "days_missed": int}.
            start_date   — первая реальная дата (str ISO) или None.
            days_count   — кол-во реальных дней.
    """
    from datetime import date as _date

    real = [e for e in entries
            if isinstance(e, dict)
            and not e.get("is_warmup", False)
            and not e.get("is_seed", False)]

    dates: list[_date] = []
    for e in real:
        for k in ("date", "timestamp", "ts"):
            v = e.get(k)
            if isinstance(v, str) and v:
                try:
                    dates.append(_date.fromisoformat(v[:10]))
                    break
                except ValueError:
                    pass

    dates = sorted(set(dates))

    if not dates:
        return {"has_gaps": False, "day_gaps": [], "start_date": None, "days_count": 0}

    day_gaps = []
    for i in range(1, len(dates)):
        delta = (dates[i] - dates[i - 1]).days
        if delta > 3:   # > 3 кал. дней — не укладывается в пропуск выходных
            day_gaps.append({
                "from": dates[i - 1].isoformat(),
                "to": dates[i].isoformat(),
                "days_missed": delta - 1,
            })

    return {
        "has_gaps": bool(day_gaps),
        "day_gaps": day_gaps,
        "start_date": dates[0].isoformat(),
        "days_count": len(dates),
    }


def check_gaps() -> dict:
    now = datetime.now(timezone.utc)
    result = {
        "checked_at": now.isoformat(),
        "gap_detected": False,
        "last_entry_date": None,
        "hours_since_last_entry": None,
        "status": "ok",
        "message": "",
        # --- поля детекции пропущенных дней (S0.1) ---
        "has_gaps": False,
        "day_gaps": [],
        "start_date": None,
        "days_count": 0,
    }

    if not EQUITY_FILE.exists():
        result.update({"gap_detected": True, "status": "no_data",
                        "message": "equity_curve_daily.json не найден"})
        return _finalize(result)

    try:
        doc = json.loads(EQUITY_FILE.read_text())
    except Exception as e:
        result.update({"gap_detected": True, "status": "parse_error",
                        "message": str(e)})
        return _finalize(result)

    # Поддержка двух форматов: документ cycle_runner {"is_demo":..., "daily":[...]}
    # (is_demo на уровне документа) и плоский список записей.
    if isinstance(doc, dict):
        entries = doc.get("daily") or []
        default_demo = bool(doc.get("is_demo", True))
    else:
        entries = doc if isinstance(doc, list) else []
        default_demo = True

    # Реальные записи: не demo И не warmup (S0.1: warmup исключены из трека)
    real = [e for e in entries
            if isinstance(e, dict)
            and not e.get("is_demo", default_demo)
            and not e.get("is_warmup", False)]
    if not real:
        result.update({"gap_detected": True, "status": "no_real_entries",
                        "message": "Нет реальных (is_demo:false, is_warmup:false) записей"})
        return _finalize(result)

    # --- S0.1: детекция пропущенных дней в истории трека ---
    day_gap_info = check_day_gaps(real)
    result.update(day_gap_info)

    # Последняя запись — по полю date или timestamp
    def parse_dt(e):
        for k in ("timestamp", "date", "ts"):
            if k in e:
                try:
                    return datetime.fromisoformat(e[k].replace("Z", "+00:00"))
                except Exception:
                    pass
        return None

    last_dt = max((parse_dt(e) for e in real if parse_dt(e)), default=None)
    if last_dt is None:
        result.update({"gap_detected": True, "status": "no_timestamp",
                        "message": "Нет разбираемого timestamp"})
        return _finalize(result)

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
    elif result["has_gaps"]:
        # Исторические пропуски в треке — gap_detected=True (критически для GoLive)
        n = len(result["day_gaps"])
        result.update({
            "gap_detected": True,
            "status": "history_gap",
            "message": f"Обнаружен(о) {n} пропуск(ов) в истории трека: {result['day_gaps']}",
        })
    else:
        result.update({"status": "ok", "message": f"Последний бар {hours_ago:.1f}ч назад — норма"})

    return _finalize(result)

def _write(data: dict):
    # LLM FORBIDDEN — deterministic atomic write
    atomic_save(data, str(GAP_STATUS_FILE))

def _finalize(result: dict) -> dict:
    """MP-101: сохранить результат детекции, перенеся recovery-историю из
    предыдущего снапшота (check_gaps перезаписывает файл целиком), и при
    gap_detected — синхронизировать CRITICAL-алерт. Никогда не бросает из-за
    алерта: детекция важнее побочного канала."""
    # AUD-10: read-merge-write under a cross-process lock so a concurrent
    # attempt_recovery() writing the `recovery` key is not clobbered.
    with file_lock(str(GAP_STATUS_FILE)):
        prev = _read_status()
        for k in ("recovery", "recovery_skip"):
            if k in prev and k not in result:
                result[k] = prev[k]
        _write(result)
    if result.get("gap_detected"):
        try:
            _upsert_gap_alert(result)
        except Exception:
            pass  # fail-open: алерт-канал не должен ломать детекцию
    else:
        # gap resolved → убрать stale cycle_gap алерты из risk_alerts.json
        try:
            _clear_gap_alerts()
        except Exception:
            pass  # fail-open
    return result

# ─── MP-101: CRITICAL-алерт в data/risk_alerts.json ─────────────────────────

def _read_status() -> dict:
    """Текущий gap_monitor.json (defensive: отсутствует/бит → {})."""
    try:
        doc = json.loads(GAP_STATUS_FILE.read_text())
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}

def _atomic_write_json(path: Path, obj) -> None:
    # LLM FORBIDDEN — delegate to canonical atomic_save
    atomic_save(obj, str(path))

def _load_alerts_doc() -> dict:
    """risk_alerts.json defensively; чужие алерты (export_data и др.) сохраняем."""
    try:
        doc = json.loads(RISK_ALERTS_FILE.read_text())
    except Exception:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    alerts = doc.get("alerts")
    doc["alerts"] = [a for a in alerts if isinstance(a, dict)] if isinstance(alerts, list) else []
    return doc

def _save_alerts_doc(alerts: list) -> None:
    """Пересборка документа в схеме export_data.py: generated_at/count/status/alerts."""
    alerts = alerts[-MAX_ALERTS:]
    _atomic_write_json(RISK_ALERTS_FILE, {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(alerts),
        "status": "critical" if any(a.get("severity") == "critical" for a in alerts)
                  else ("warning" if alerts else "ok"),
        "alerts": alerts,
    })

def _upsert_gap_alert(result: dict) -> None:
    """Дописать/обновить CRITICAL-алерт о gap за сегодняшний день.

    Дедупликация: на один UTC-день — ровно один алерт source=gap_monitor
    (повторная детекция обновляет существующую запись, не плодит дубль).
    severity = "critical" (lowercase — схема существующего писателя
    export_data.py, по ней же считается status документа).
    """
    day = (result.get("checked_at") or datetime.now(timezone.utc).isoformat())[:10]
    doc = _load_alerts_doc()
    alerts = doc["alerts"]
    payload = {
        "severity": "critical",
        "type": ALERT_TYPE,
        "source": ALERT_SOURCE,
        "protocol": "paper_cycle",
        "date": day,
        "message": result.get("message") or "Gap в equity curve — цикл пропустил день",
        "gap_status": result.get("status"),
        "hours_since_last_entry": result.get("hours_since_last_entry"),
        "created_at": result.get("checked_at"),
        "updated_at": result.get("checked_at"),
    }
    for i, a in enumerate(alerts):
        if a.get("source") == ALERT_SOURCE and a.get("date") == day:
            payload["created_at"] = a.get("created_at") or payload["created_at"]
            if "recovery" in a:  # не терять прикреплённый результат recovery
                payload["recovery"] = a["recovery"]
            alerts[i] = payload
            break
    else:
        alerts.append(payload)
    _save_alerts_doc(alerts)

def _attach_recovery_to_alert(day: str, recovery: dict) -> None:
    """Прикрепить результат recovery к сегодняшнему gap-алерту (если он есть).
    Ничего не создаёт: нет алерта за день → no-op."""
    doc = _load_alerts_doc()
    alerts = doc["alerts"]
    changed = False
    for a in alerts:
        if a.get("source") == ALERT_SOURCE and a.get("date") == day:
            a["recovery"] = recovery
            a["updated_at"] = datetime.now(timezone.utc).isoformat()
            changed = True
    if changed:
        _save_alerts_doc(alerts)

def _clear_gap_alerts() -> None:
    """Удалить все cycle_gap алерты из risk_alerts.json когда gap resolved.
    Вызывается из _finalize при status=ok (gap_detected=False).
    Fail-safe: если файл недоступен — no-op."""
    doc = _load_alerts_doc()
    alerts = doc["alerts"]
    filtered = [a for a in alerts if a.get("type") != ALERT_TYPE]
    if len(filtered) < len(alerts):
        _save_alerts_doc(filtered)

# ─── MP-101: auto-recovery (детерминированная, идемпотентная) ────────────────

def _today_bar_exists(day: str) -> bool:
    """Есть ли в equity_curve_daily.json бар за сегодняшний UTC-день."""
    try:
        doc = json.loads(EQUITY_FILE.read_text())
    except Exception:
        return False
    entries = doc.get("daily") or [] if isinstance(doc, dict) else (doc if isinstance(doc, list) else [])
    for e in entries:
        if not isinstance(e, dict):
            continue
        for k in ("date", "timestamp", "ts"):
            v = e.get(k)
            if isinstance(v, str) and v[:10] == day:
                return True
    return False

def _acquire_lock():
    """Эксклюзивный file-lock (O_CREAT|O_EXCL). Протухший (>LOCK_STALE_SECONDS,
    упавший процесс) lock снимается и берётся заново. None → занято."""
    RECOVERY_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(RECOVERY_LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({
                "pid": os.getpid(),
                "ts": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8"))
            return fd
        except FileExistsError:
            try:
                age = time.time() - RECOVERY_LOCK_FILE.stat().st_mtime
            except OSError:
                continue  # lock исчез между проверками — повторить попытку
            if age > LOCK_STALE_SECONDS:
                try:
                    RECOVERY_LOCK_FILE.unlink()
                except OSError:
                    pass
                continue
            return None  # живой lock — другой процесс уже восстанавливает
    return None

def _release_lock(fd) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        RECOVERY_LOCK_FILE.unlink()
    except OSError:
        pass

def _default_cycle():
    """Штатный paper-цикл (read-only simulation, никаких реальных транзакций).
    Ленивый импорт: детекция работает, даже если cycle_runner недоступен."""
    from spa_core.paper_trading.cycle_runner import run_cycle
    return run_cycle(write=True)

def _log_skip(record: dict) -> dict:
    """Записать пропуск recovery в gap_monitor.json (recovery_skip) и в алерт."""
    try:
        with file_lock(str(GAP_STATUS_FILE)):  # AUD-10: locked read-modify-write
            doc = _read_status()
            doc["recovery_skip"] = record
            if doc.get("checked_at"):
                _write(doc)
        _attach_recovery_to_alert(record["date"], record)
    except Exception:
        pass
    return record

def attempt_recovery(cycle_fn=None, now=None) -> dict:
    """MP-101: одна детерминированная попытка auto-recovery пропущенного дня.

    Если gap detected и сегодняшний бар отсутствует — запустить штатный
    paper-цикл (cycle_runner.run_cycle, PAPER TRADING ONLY) под file-lock.
    Максимум 1 попытка за запуск; повторный вызов в тот же день — skipped
    (идемпотентность). Результат пишется в gap_monitor.json и прикрепляется
    к CRITICAL-алерту. Падение цикла честно фиксируется как failure.

    Возвращает dict: ts/date/attempted/succeeded/skipped_reason/error.
    """
    now_dt = now or datetime.now(timezone.utc)
    today = now_dt.strftime("%Y-%m-%d")
    record = {
        "ts": now_dt.isoformat(),
        "date": today,
        "attempted": False,
        "succeeded": None,
        "skipped_reason": None,
        "error": None,
    }

    status = check_gaps()

    # Нет gap — recovery не нужна: ничего не пишем и не трогаем.
    if not status.get("gap_detected"):
        record["skipped_reason"] = "no_gap"
        return record

    # Сегодняшний бар уже есть (например, статус no_real_entries на demo-данных)
    # — повторный прогон цикла gap не вылечит.
    if _today_bar_exists(today):
        record["skipped_reason"] = "today_bar_exists"
        return _log_skip(record)

    # Идемпотентность: не более одной попытки в UTC-день.
    prev = _read_status().get("recovery")
    if isinstance(prev, dict) and prev.get("date") == today and prev.get("attempted"):
        record["skipped_reason"] = "already_attempted_today"
        return _log_skip(record)

    # Защита от двойного запуска (параллельный launchd/ручной прогон).
    lock_fd = _acquire_lock()
    if lock_fd is None:
        record["skipped_reason"] = "locked"
        return _log_skip(record)

    try:
        record["attempted"] = True
        try:
            (cycle_fn or _default_cycle)()
        except Exception as e:  # цикл недоступен/упал — честная фиксация failure
            record["succeeded"] = False
            record["error"] = f"{type(e).__name__}: {e}"

        post = check_gaps()  # пере-детекция после попытки
        if record["error"] is None:
            record["succeeded"] = not post.get("gap_detected", True)
            if not record["succeeded"]:
                record["error"] = "cycle_ran_but_gap_persists"
        record["gap_after_recovery"] = bool(post.get("gap_detected"))

        # Лог результата в gap_monitor.json … (AUD-10: locked read-modify-write)
        with file_lock(str(GAP_STATUS_FILE)):
            doc = _read_status() or dict(post)
            doc["recovery"] = record
            doc.pop("recovery_skip", None)
            _write(doc)
        # … и в сегодняшний CRITICAL-алерт (создан при детекции gap).
        try:
            _attach_recovery_to_alert(today, record)
        except Exception:
            pass
    finally:
        _release_lock(lock_fd)

    return record

# ─── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    """Без флагов — только детекция (поведение MP-009 не изменено).
    --recover — детекция + одна попытка auto-recovery (MP-101)."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="gap_monitor",
        description="Gap-monitor paper-трека: детекция пропущенного дня "
                    "(+ --recover: одна попытка штатного paper-цикла).",
    )
    parser.add_argument("--recover", action="store_true",
                        help="при gap попытаться запустить штатный paper-цикл "
                             "(file-lock, максимум 1 попытка за запуск)")
    args = parser.parse_args(argv)

    r = check_gaps()
    if args.recover:
        attempt_recovery()
        r = _read_status() or r  # финальное состояние после попытки
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 1 if r.get("gap_detected") else 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
