"""Сторож ОДНОГО вопроса: **падал ли флот РАЗОМ** — и когда именно.

Вопрос принадлежит только этому модулю, и до него на него не отвечал никто.
Соседи честно отвечают на свои — и ни один из их ответов не является ответом на
этот (`.claude/rules/deployment.md`, «зелёный ответ на один вопрос никогда не
означает ответа на два других»):

| Вопрос | Кто отвечает | Почему это НЕ ответ про массовое падение |
|---|---|---|
| Это тот код, который мы приняли? | `deployment_drift_monitor` | смотрит на дерево, не на флот |
| Способен ли флот стартовать? | `deployment_acceptance` | способность ≠ то, что случилось ночью |
| Агенты СЕЙЧАС живы? | `agent_health_monitor` | снимок настоящего; восстановившийся флот выглядит здоровым |
| Исполняет ли живой долгожитель код из дерева? | `agent_code_freshness` | про версию в памяти, не про падение |
| **Падал ли флот разом с прошлого взгляда?** | **этот модуль** | — |

ЧТО ИМЕННО ОСТАВАЛОСЬ НЕИЗМЕРЕННЫМ (замер 2026-08-18 по коду, не по отчёту).
В `agent_health_monitor` есть `detect_wake_storm` (строка 1268). Он отвечает на
близкий, но ДРУГОЙ вопрос: «сколько агентов ПРЯМО СЕЙЧАС несут ненулевой
last_exit». Двумя способами это мимо аварии 2026-08-04:

1. **Он пассажир того самого автобуса.** Шторм пробуждения гасит весь флот,
   включая `com.spa.agent_health`; в тот день `data/agent_health.json` был
   несвежим на 8 часов и рапортовал `healthy 69/69`, пока падали 39 агентов.
   Детектор, живущий внутри упавшего монитора, во время шторма не исполняется.
2. **Он видит только то, что ещё сломано.** Флот самовосстановился за 15 минут
   (`exit0` 22→33 за время аудита). После рестарта `launchctl` показывает
   `exit 0`, `status == OK`, и `detect_wake_storm` возвращает `None` — событие
   становится невидимым ЗАДНИМ ЧИСЛОМ. Пережитая авария не оставляет следа
   ни в одном сторожe, хотя дневной цикл 06:00Z она унесла.

ЧТО МЕРЯЕТ ЭТОТ МОДУЛЬ. Не состояние флота, а **улику на диске, которая
переживает и шторм, и восстановление**: обёртка `scripts/agent_template.sh`
на сдаче пишет в `/tmp/spa_<agent>.log` строку с СОБСТВЕННОЙ меткой времени

    [2026-08-04T07:00:14Z] WAKE_STORM_GIVEUP agent=<name> attempts=N last_fail=... repo=...

и выходит 75 (EX_TEMPFAIL). Маркер введён именно «чтобы мониторинг мог отличить
транзиентный шторм от логической ошибки» (комментарий в обёртке, строка 119) —
и его НЕ ЧИТАЛ НИКТО: `grep -rn WAKE_STORM_GIVEUP` по всему дереву даёт только
саму обёртку и тест, который «закрепляет токен, потому что мониторинг его
грепает» (`tests/test_agent_template_wake_storm.py:272`). Улика писалась в стол.

Поэтому здесь: собрать маркеры, сгруппировать по СВОЕЙ метке времени в окно
`window_s`, посчитать РАЗНЫЕ агенты в окне. `min_agents` и больше в одном окне —
это событие уровня флота, а не N независимых поломок.

ПОЧЕМУ ЭТО НЕ БУДЕТ ВЫКЛЮЧЕНО ЛЮДЬМИ (обратная сторона того же правила):
обычный перезапуск одного агента маркера не пишет ВООБЩЕ — молчание здесь
бесплатное. Даже настоящая одиночная сдача (`WAKE_STORM_GIVEUP` у одного
агента) тревоги не поднимает: «один агент упал» — вопрос `agent_health`, и
отвечать на него ещё раз значило бы размывать свой.

FAIL-CLOSED: каталог логов недоступен / файл нечитаем ⇒ `UNCHECKED`, никогда не
`OK`. «Не измерено» ≠ «шторма не было» — ровно тот класс, из-за которого
04.08 никто ничего не сказал.

ОТДЕЛЬНО — РАЗРЫВ НАБЛЮДЕНИЯ (замер 2026-08-19, тот же класс внутри самого
сторожа). Вопрос карточки звучит «падал ли флот разом **с прошлого взгляда**»,
а ретроспектива по уликам отвечает на другой: «за последние `lookback_h`».
Пока смотрят чаще, чем раз в `lookback_h`, это одно и то же; как только взгляд
пропущен — нет. А пропускается он ИМЕННО в шторм: 04.08 снимок `agent_health`
(единственный, кто спрашивает этого сторожа) был несвежим на 8 часов, потому
что монитор лежал вместе с флотом. Разрыв в сутки+ давал бы улику ЗА окном
ретроспективы и вердикт `OK` «шторма нет» — измеренный ноль, неотличимый от
флота, который не падал. Поэтому: если ПРЕДЫДУЩИЙ взгляд старше горизонта
ретроспективы, интервал между ними никем не осмотрен, и это `unchecked`
(WARNING), а не `OK`. Нечитаемый предыдущий отчёт — тоже `unchecked`, а не
«прошлого взгляда не было».

Время — ВХОД (`now`), а не окружение: и окно ретроспективы, и метки улик
сравниваются с переданным `now` (`.claude/rules/deployment.md`).

Только stdlib. Read-only: чтение логов; запись отчёта — только по явному
вызову `run()`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

# Каталог, куда обёртка и launchd пишут логи флота (`scripts/agent_template.sh`).
DEFAULT_LOG_DIR = Path("/tmp")

# Сколько РАЗНЫХ агентов в одном окне считается событием уровня флота.
# 2026-08-04T07:00:14-15Z: 39 агентов из 69 в одну минуту. Порог 5 — тот же,
# что у `agent_health_monitor.WAKE_STORM_MIN_AGENTS`; совпадение осознанное
# (одна авария), но пороги независимы: там про «сломано сейчас», здесь про
# «упало разом».
STORM_MIN_AGENTS = 5

# Ширина окна одновременности. Шторм пробуждения укладывался в одну секунду;
# 120 с даёт запас на разъезд launchd-расписаний, оставаясь далеко от
# «раскатанного» деплоя, где агенты перезапускаются минутами врозь.
STORM_WINDOW_S = 120

# Насколько назад смотрим. Улика устаревает по СВОЕЙ метке времени, поэтому
# отчёт не звенит вечно об одном и том же шторме — иначе его выключат.
LOOKBACK_H = 24.0

# Хвост файла, который читаем. Логи агентов растут; целиком их читать нельзя.
TAIL_BYTES = 256 * 1024

GIVEUP_TOKEN = "WAKE_STORM_GIVEUP"

# `[2026-08-04T07:00:14Z] WAKE_STORM_GIVEUP agent=self_heal attempts=3 ...`
_GIVEUP_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]\s*"
    + GIVEUP_TOKEN
    + r"(?:\s+agent=(?P<agent>\S+))?"
)

# Форма аварии ДО починки обёртки (04.08 обёртка ещё не умела сдаваться с
# маркером): launchd не смог запустить bash, python не увидел пакет. У этих
# строк собственной метки времени нет — время берём из mtime файла и честно
# помечаем источник, чтобы никто не принял оценку за замер.
LEGACY_SIGNATURES: Tuple[str, ...] = (
    "Interrupted system call",
    "getcwd: cannot access parent directories",
    "No module named 'spa_core'",
)

_LOG_GLOBS: Tuple[str, ...] = ("spa_*.log", "spa_*.launchd.err", "spa_*.launchd.out")


# ===========================================================================
# helpers
# ===========================================================================
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def label_from_log_name(name: str) -> str:
    """``spa_self_heal.launchd.err`` → ``self_heal``; ``spa_foo.log`` → ``foo``."""
    stem = name
    if stem.startswith("spa_"):
        stem = stem[len("spa_"):]
    for suffix in (".launchd.err", ".launchd.out", ".log"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem


def _parse_marker_ts(raw: str) -> Optional[datetime]:
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _read_tail(path: Path, tail_bytes: int = TAIL_BYTES) -> str:
    """Хвост файла текстом. Ошибка чтения — наверх, вызывающий пометит UNCHECKED."""
    with open(path, "rb") as fh:
        try:
            size = os.fstat(fh.fileno()).st_size
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
        except OSError:
            pass
        return fh.read().decode("utf-8", errors="replace")


# ===========================================================================
# scan
# ===========================================================================
def scan_evidence(log_dir: Path,
                  now: datetime,
                  lookback_h: float = LOOKBACK_H,
                  tail_bytes: int = TAIL_BYTES,
                  ) -> Tuple[List[dict], List[dict]]:
    """Собрать улики шторма из логов флота.

    Возвращает ``(events, unchecked)``. Событие — словарь с ``agent``, ``at``
    (ISO), ``time_source`` (``marker`` — собственная метка строки, ``mtime`` —
    оценка по файлу), ``kind`` и ``source``.

    Ничего не найдено при ЧИТАЕМОМ каталоге — это измеренный ноль. Каталог или
    файл нечитаем — это ``unchecked``, а не ноль (fail-CLOSED).
    """
    log_dir = Path(log_dir)
    events: List[dict] = []
    unchecked: List[dict] = []
    horizon = now - timedelta(hours=float(lookback_h))

    try:
        if not log_dir.is_dir():
            raise OSError(f"каталог логов не найден: {log_dir}")
        paths = sorted({p for pattern in _LOG_GLOBS for p in log_dir.glob(pattern)})
    except OSError as exc:
        unchecked.append({
            "check": "log_dir",
            "reason": f"каталог логов флота нечитаем ({exc}) — это НЕ «шторма не было»",
        })
        return events, unchecked

    for path in paths:
        label = label_from_log_name(path.name)
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            text = _read_tail(path, tail_bytes)
        except OSError as exc:
            unchecked.append({
                "check": f"log:{path.name}",
                "reason": f"файл нечитаем ({type(exc).__name__}) — улика не осмотрена",
            })
            continue

        seen_marker = False
        for m in _GIVEUP_RE.finditer(text):
            at = _parse_marker_ts(m.group("ts"))
            if at is None:
                continue
            seen_marker = True
            if at < horizon or at > now + timedelta(seconds=STORM_WINDOW_S):
                continue
            events.append({
                "agent": (m.group("agent") or label),
                "at": at.isoformat(),
                "time_source": "marker",
                "kind": GIVEUP_TOKEN,
                "source": path.name,
            })

        # Дошторменная форма без собственной метки: засчитываем только если сам
        # файл свежий, и помечаем, что время — оценка.
        if not seen_marker and mtime >= horizon:
            hit = next((s for s in LEGACY_SIGNATURES if s in text), None)
            if hit:
                events.append({
                    "agent": label,
                    "at": mtime.isoformat(),
                    "time_source": "mtime",
                    "kind": hit,
                    "source": path.name,
                })

    return events, unchecked


# ===========================================================================
# cluster
# ===========================================================================
def cluster_storm(events: List[dict],
                  window_s: int = STORM_WINDOW_S,
                  min_agents: int = STORM_MIN_AGENTS,
                  ) -> Optional[dict]:
    """Самое плотное окно одновременности. ``None``, если порог не взят.

    Считаются РАЗНЫЕ агенты, а не файлы: один агент, написавший маркер и в
    ``.log``, и в ``.launchd.err``, — это один упавший агент, а не два.
    """
    stamped: List[Tuple[datetime, dict]] = []
    for e in events:
        try:
            at = datetime.fromisoformat(str(e.get("at")))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        stamped.append((at, e))
    if not stamped:
        return None
    stamped.sort(key=lambda pair: pair[0])

    best: Optional[dict] = None
    for i, (start, _) in enumerate(stamped):
        window: Dict[str, dict] = {}
        for at, e in stamped[i:]:
            if (at - start).total_seconds() > float(window_s):
                break
            window.setdefault(str(e.get("agent")), e)
        if best is None or len(window) > int(best["count"]):
            best = {
                "count": len(window),
                "at": start.isoformat(),
                "window_s": int(window_s),
                "agents": sorted(window.keys()),
                "time_sources": sorted({str(e.get("time_source")) for e in window.values()}),
                "kinds": sorted({str(e.get("kind")) for e in window.values()}),
            }
    if best is None or int(best["count"]) < max(1, int(min_agents)):
        return None
    return best


# ===========================================================================
# verdict
# ===========================================================================
def coverage_gap(previous: Optional[dict],
                 now: datetime,
                 lookback_h: float = LOOKBACK_H,
                 ) -> Tuple[Optional[str], Optional[float], Optional[dict]]:
    """Осмотрен ли интервал МЕЖДУ прошлым взглядом и горизонтом ретроспективы.

    Возвращает ``(previous_look_iso, blind_gap_h, unchecked_entry)``.

    * предыдущего отчёта нет (``None``) — первый взгляд: сторож честно отвечает
      только за окно ретроспективы, разрыва ДОКАЗАТЬ нельзя ⇒ вердикт не трогаем;
    * предыдущий отчёт нечитаем / без времени ⇒ ``unchecked`` (это НЕ «взгляда
      не было»);
    * предыдущий взгляд старше ``now - lookback_h`` ⇒ между ними никто не
      смотрел, улики за тот интервал уже состарились ⇒ ``unchecked``.
    """
    if previous is None:
        return None, None, None
    if not isinstance(previous, dict):
        return None, None, {
            "check": "previous_look",
            "reason": "предыдущий отчёт нечитаем — интервал с прошлого взгляда не осмотрен",
        }
    raw = previous.get("timestamp")
    try:
        prev = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return None, None, {
            "check": "previous_look",
            "reason": (f"у предыдущего отчёта нет разбираемого времени ({raw!r}) — "
                       "интервал с прошлого взгляда не осмотрен"),
        }
    if prev.tzinfo is None:
        prev = prev.replace(tzinfo=timezone.utc)
    horizon = now - timedelta(hours=float(lookback_h))
    gap_h = round((horizon - prev).total_seconds() / 3600.0, 2)
    if gap_h <= 0:
        return prev.isoformat(), 0.0, None
    return prev.isoformat(), gap_h, {
        "check": "coverage_gap",
        "reason": (
            f"прошлый взгляд был {prev.isoformat()} — на {gap_h:g}ч раньше горизонта "
            f"ретроспективы ({lookback_h:g}ч): улики за этот интервал уже состарились, "
            "и «шторма нет» про него сказать НЕЛЬЗЯ"),
    }


def check_wake_storm(now: Optional[datetime] = None,
                     log_dir: Path | str = DEFAULT_LOG_DIR,
                     min_agents: int = STORM_MIN_AGENTS,
                     window_s: int = STORM_WINDOW_S,
                     lookback_h: float = LOOKBACK_H,
                     tail_bytes: int = TAIL_BYTES,
                     previous: Optional[dict] = None,
                     ) -> dict:
    """Вердикт про ОДИН вопрос: падал ли флот разом за последние ``lookback_h``.

    ``CRITICAL`` — шторм найден. ``WARNING`` — не измерено (fail-CLOSED).
    ``OK`` — измерено и шторма нет.

    ``previous`` — предыдущий отчёт этого же сторожа. Он превращает ответ «за
    сутки» в ответ «с прошлого взгляда»: пропущенный взгляд шире ретроспективы
    делает вердикт `WARNING`, а не `OK` (см. шапку модуля).
    """
    now = now or _utcnow()
    events, unchecked = scan_evidence(
        Path(log_dir), now, lookback_h=lookback_h, tail_bytes=tail_bytes)
    storm = cluster_storm(events, window_s=window_s, min_agents=min_agents)

    previous_look, blind_gap_h, gap_unchecked = coverage_gap(
        previous, now, lookback_h=lookback_h)
    if gap_unchecked is not None:
        unchecked.append(gap_unchecked)

    agents_seen = sorted({str(e.get("agent")) for e in events})
    issues: List[str] = []
    if storm:
        status = CRITICAL
        reason = (
            "ФЛОТ УПАЛ РАЗОМ: {n} агентов сдались в окне {w}с около {at} "
            "({kinds})".format(n=storm["count"], w=storm["window_s"],
                               at=storm["at"], kinds=", ".join(storm["kinds"]))
        )
        issues.append(reason)
        issues.append(
            "это событие уровня флота (сон/пробуждение хоста, сорванный деплой, "
            "снятый бит исполнения), а не {n} независимых поломок — и оно видно "
            "ДАЖЕ ПОСЛЕ восстановления".format(n=storm["count"]))
        if storm["time_sources"] == ["mtime"]:
            issues.append(
                "время события — ОЦЕНКА по mtime логов (дошторменная форма без "
                "собственной метки), не замер")
    elif unchecked:
        status = WARNING
        reason = "НЕ ИЗМЕРЕНО: улики шторма не осмотрены ({} причин)".format(len(unchecked))
        issues.append(reason)
    else:
        status = OK
        reason = (
            "шторма нет: за {h:g}ч сдач обёртки {n} (порог — {m} разных агентов "
            "в окне {w}с)".format(h=lookback_h, n=len(agents_seen),
                                  m=min_agents, w=window_s)
        )
        if agents_seen:
            # Одиночная сдача — НЕ наш вопрос: на «упал один агент» отвечает
            # `agent_health_monitor` (last_exit=75 ≠ 0). Называем факт, но
            # вердикт не трогаем, иначе сторож начнёт дублировать соседа.
            issues.append(
                "одиночные сдачи обёртки (не шторм, вопрос agent_health): "
                + ", ".join(agents_seen))

    return {
        "timestamp": now.isoformat(),
        "status": status,
        "reason": reason,
        "measured": not unchecked,
        # Чем именно ограничен ответ. `answers_since_last_look=False` — сторож
        # отвечает ТОЛЬКО за окно ретроспективы; это не то же самое, что «с
        # прошлого взгляда», и читатель обязан видеть разницу, а не догадываться.
        "previous_look": previous_look,
        "blind_gap_h": blind_gap_h,
        "answers_since_last_look": bool(previous_look is not None and not blind_gap_h),
        "storm": storm,
        "events": events,
        "agents_seen": agents_seen,
        "issues": issues,
        "unchecked": unchecked,
        "params": {
            "log_dir": str(log_dir),
            "min_agents": int(min_agents),
            "window_s": int(window_s),
            "lookback_h": float(lookback_h),
        },
    }


REPORT_FILENAME = "wake_storm_forensics.json"

# Отдельное значение для «предыдущий отчёт есть, но прочитать его не смогли».
# Не `None`: `None` означает «прошлого взгляда не было», и подменять им отказ
# чтения — тот же класс, что вся эта карточка.
_UNREADABLE_PREVIOUS = {"timestamp": None, "unreadable": True}


def load_previous(path: Path | str) -> Optional[dict]:
    """Предыдущий отчёт сторожа, если он есть.

    ``None`` — файла нет (первый взгляд). Файл есть, но не читается/не разбирается
    ⇒ возвращаем маркер нечитаемости, а не ``None``.
    """
    p = Path(path)
    try:
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _UNREADABLE_PREVIOUS


def run(now: Optional[datetime] = None,
        log_dir: Path | str = DEFAULT_LOG_DIR,
        data_dir: Optional[Path | str] = None,
        ) -> Tuple[dict, Optional[Path]]:
    """Посчитать и (если задан ``data_dir``) атомарно записать отчёт.

    Запись — только по явному ``data_dir``: сторож обязан уметь ответить, ничего
    не трогая. Незаписанный вердикт НЕ проглатывается (класс `_save` из той же
    карточки): ошибка записи поднимает статус до `WARNING` и попадает в
    `unchecked`.
    """
    if data_dir is None:
        # Без места для состояния «прошлого взгляда» не существует: отвечаем за
        # окно ретроспективы и говорим об этом полем, а не молчанием.
        return check_wake_storm(now=now, log_dir=log_dir), None

    path = Path(data_dir) / REPORT_FILENAME
    doc = check_wake_storm(now=now, log_dir=log_dir,
                           previous=load_previous(path))
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(path))
    except Exception as exc:  # noqa: BLE001 — молчаливая потеря вердикта запрещена
        doc["unchecked"].append({
            "check": "publish",
            "reason": f"вердикт не записан ({type(exc).__name__}: {exc})",
        })
        doc["published"] = False
        doc["measured"] = False
        if doc["status"] == OK:
            doc["status"] = WARNING
            doc["reason"] = "НЕ ИЗМЕРЕНО: вердикт не опубликован"
        return doc, None
    doc["published"] = True
    return doc, path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m spa_core.monitoring.wake_storm_forensics",
        description="Падал ли флот разом (шторм пробуждения) — по уликам на диске.")
    ap.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    ap.add_argument("--data-dir", default=None,
                    help="куда записать отчёт (по умолчанию — не писать)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    doc, _ = run(log_dir=args.log_dir, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(f"{doc['status']}: {doc['reason']}")
        for line in doc["issues"][1:]:
            print(f"  · {line}")
        for u in doc["unchecked"]:
            print(f"  [НЕ ИЗМЕРЕНО] {u['check']}: {u['reason']}")
    return {OK: 0, WARNING: 1, CRITICAL: 2}[doc["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
