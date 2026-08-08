"""Сторож ЗАСТРЯВШЕГО замка дневного цикла — вопрос, на который не отвечал никто.

Дневной цикл берёт эксклюзивный замок (`data/daily_cycle.lock`), чтобы два прогона
не записали один день трека вдвоём. Замок работает. Но он снимается **только по
возрасту файла** (`CYCLE_LOCK_STALE_SECONDS` = 2 ч) и никогда не спрашивает, жив ли
держатель, — хотя номер процесса записан внутри самого файла.

Наблюдено дважды за 2026-08-08 на живом проде:

| | инцидент 1 | инцидент 2 |
|---|---|---|
| замок взят | 03:34:29Z, pid 99899 | 10:04:57Z, pid 98535 |
| держатель | **мёртв** | **мёртв** |
| отказов подряд | 18 из 20 вызовов | 12+ (замер 11:13Z) |
| запас до планового цикла | 26 мин | — |

Снаружи это выглядело как `com.spa.daily_cycle last_exit=2` — то есть **точно так же,
как авария**. Три существующих сторожа честно отвечали каждый на свой вопрос и ни один
не отвечал на нужный:

| вопрос | кто отвечает | что говорил 08.08 |
|---|---|---|
| цикл давно не отрабатывал? | `agent_health` cycle-freshness | ничего: цикл отработал в 09:52 |
| код в проде тот? | `deployment_drift` | ничего: код совпадал |
| агент вернул ненулевой код? | `agent_health` last_exit | ⚠️ WARN — и для «защитил трек», и для «сломался» |

Здесь — четвёртый вопрос: **замок держит труп?** Это не догадка и не оценка: номер
процесса лежит в файле, живость измеряется одним системным вызовом.

**Сторож НИЧЕГО не чинит и не трогает замок.** Правка самого замка — money-path
(влияет на то, когда цикл получает право писать в живой трек) и ждёт решения владельца
в карточке `owner-decision-zamok-dnevnogo-tsikla-ne-sprashivaet-zhi`. Отчётность —
не money-path, и молчать о трупе, пока решается вопрос, оснований нет.

Fail-CLOSED: «живость не измерена» НИКОГДА не хранится как «в порядке» — это отдельное
состояние `unchecked` со своим голосом. Точно так же «сколько было отказов» при
нечитаемом логе — `None`, а не `0`: ноль читается как «вреда не было».
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

__all__ = [
    "CYCLE_LOCK_FILE",
    "CYCLE_LOCK_STALE_SECONDS",
    "CycleLockVerdict",
    "check_cycle_lock",
    "count_refusals",
    "STATE_NO_LOCK",
    "STATE_HELD_ALIVE",
    "STATE_HELD_DEAD",
    "STATE_HELD_EXPIRED",
    "STATE_UNCHECKED",
]

# ── Пороги ──────────────────────────────────────────────────────────────────
# ВТОРАЯ КОПИЯ ЗНАЧЕНИЙ ЦИКЛА — и это осознанно: импортировать
# ``spa_core.paper_trading.cycle_runner`` из монитора нельзя (тянет money-path
# зависимости в read-only слой, инвариант #6). Копия не свободна: расхождение
# краснит parity-тест `test_cycle_lock_watch.py::test_thresholds_match_cycle_runner`,
# который импортирует цикл напрямую. Тот же приём, что монитор==RiskConfig.
CYCLE_LOCK_FILE = "daily_cycle.lock"
CYCLE_LOCK_STALE_SECONDS = 2 * 3600

# Лог обёртки launchd: `run_daily_paper_cycle.sh` пишет сюда строки вида
# `[2026-08-08T10:05:38Z] cycle_runner exit=2`.
DEFAULT_REFUSAL_LOG = "/tmp/spa_daily_cycle.launchd.out"

STATE_NO_LOCK = "no_lock"
STATE_HELD_ALIVE = "held_alive"
STATE_HELD_DEAD = "held_dead"
STATE_HELD_EXPIRED = "held_expired"
STATE_UNCHECKED = "unchecked"

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"

_REFUSAL_RE = re.compile(
    r"\[(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\]\s*cycle_runner exit=(?P<code>\d+)"
)


@dataclass
class CycleLockVerdict:
    """Вердикт сторожа. ``issue`` пуст ⇒ говорить не о чем."""

    state: str
    severity: str
    detail: str
    pid: Optional[int] = None
    held_since: Optional[str] = None
    age_seconds: Optional[float] = None
    clears_in_seconds: Optional[float] = None
    refusals_since_lock: Optional[int] = None
    issue: Optional[str] = None
    notes: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "severity": self.severity,
            "detail": self.detail,
            "pid": self.pid,
            "held_since": self.held_since,
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 1),
            "clears_in_seconds": (
                None if self.clears_in_seconds is None else round(self.clears_in_seconds, 1)
            ),
            "refusals_since_lock": self.refusals_since_lock,
            "notes": list(self.notes),
        }


def _pid_alive(pid: int) -> Optional[bool]:
    """``True``/``False``/``None`` — жив / мёртв / измерить не удалось.

    ``None`` — самостоятельный ответ, а не «наверное, жив»: без прав на сигнал
    (чужой пользователь, песочница) утверждать нечего.

    Осознанное огрубление: номера процессов переиспользуются, поэтому «жив» может
    означать «жив кто-то другой с тем же номером». Ошибка при этом идёт в
    БЕЗОПАСНУЮ сторону — сторож промолчит там, где мог бы крикнуть, но никогда не
    объявит трупом работающий цикл (а на это решение опирается только отчёт).
    """
    if pid is None or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # процесс есть, сигнал не наш — существование доказано
    except OSError:
        return None


def count_refusals(
    log_path: str | Path,
    since: Optional[datetime],
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Сколько раз цикл ОТКАЗАЛ (``exit=2``) с момента взятия замка.

    ``None`` — «не измерено» (лога нет / не читается / момент взятия неизвестен).
    Ноль возвращается ТОЛЬКО когда лог прочитан и отказов в нём действительно нет:
    молчаливый ноль читался бы как «вреда не было».
    """
    if since is None:
        return None
    try:
        text = Path(log_path).read_text(errors="replace")
    except OSError:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    n = 0
    for m in _REFUSAL_RE.finditer(text):
        if m.group("code") != "2":
            continue
        try:
            ts = datetime.strptime(m.group("ts"), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue
        if since <= ts <= now:
            n += 1
    return n


def _parse_ts(raw) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_cycle_lock(
    data_dir: str | Path,
    now: Optional[datetime] = None,
    *,
    pid_alive: Callable[[int], Optional[bool]] = _pid_alive,
    refusal_log: str | Path = DEFAULT_REFUSAL_LOG,
    stale_seconds: float = CYCLE_LOCK_STALE_SECONDS,
) -> CycleLockVerdict:
    """Прочитать замок дневного цикла и сказать, что он значит. Ничего не пишет."""
    if now is None:
        now = datetime.now(timezone.utc)
    path = Path(data_dir) / CYCLE_LOCK_FILE

    try:
        raw = path.read_text()
    except FileNotFoundError:
        return CycleLockVerdict(
            state=STATE_NO_LOCK, severity=OK,
            detail="замка нет — цикл никем не занят",
        )
    except OSError as exc:
        return CycleLockVerdict(
            state=STATE_UNCHECKED, severity=WARNING,
            detail=f"замок есть, но не читается ({exc}) — занятость НЕ ИЗМЕРЕНА",
            issue=("cycle lock UNCHECKED: файл замка не читается — «не измерено» "
                   "не означает «свободен»"),
        )

    try:
        mtime = path.stat().st_mtime
        age = now.timestamp() - mtime
    except OSError:
        age = None

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("не объект")
    except (ValueError, TypeError):
        return CycleLockVerdict(
            state=STATE_UNCHECKED, severity=WARNING, age_seconds=age,
            detail="замок есть, содержимое не разбирается — держателя НЕ ИЗМЕРИТЬ",
            issue=("cycle lock UNCHECKED: содержимое замка не разбирается — "
                   "живость держателя измерить нечем"),
        )

    pid = payload.get("pid")
    if not isinstance(pid, int):
        pid = None
    held_since = payload.get("ts") if isinstance(payload.get("ts"), str) else None
    since_dt = _parse_ts(held_since)
    refusals = count_refusals(refusal_log, since_dt, now)

    def _refusal_words() -> str:
        if refusals is None:
            return "отказов с тех пор — НЕ ИЗМЕРЕНО (лог обёртки не прочитан)"
        return f"отказов цикла с тех пор: {refusals}"

    # Протухший замок снимается СЛЕДУЮЩИМ же вызовом цикла, кем бы он ни был занят,
    # — поэтому возраст судится раньше живости: дальше замок уже никого не держит.
    if age is not None and age > stale_seconds:
        return CycleLockVerdict(
            state=STATE_HELD_EXPIRED, severity=WARNING, pid=pid, held_since=held_since,
            age_seconds=age, clears_in_seconds=0.0, refusals_since_lock=refusals,
            detail=(f"замок протух ({age / 60:.0f} мин > {stale_seconds / 60:.0f}) — "
                    f"следующий вызов снимет его сам; {_refusal_words()}"),
            issue=(f"cycle lock протух: держатель pid={pid} не снял замок, "
                   f"{age / 60:.0f} мин; " + _refusal_words()),
        )

    clears_in = None if age is None else max(0.0, stale_seconds - age)

    if pid is None:
        return CycleLockVerdict(
            state=STATE_UNCHECKED, severity=WARNING, held_since=held_since,
            age_seconds=age, clears_in_seconds=clears_in, refusals_since_lock=refusals,
            detail="в замке нет номера процесса — живость держателя измерить нечем",
            issue=("cycle lock UNCHECKED: в замке нет номера процесса — "
                   "живость держателя измерить нечем"),
        )

    alive = pid_alive(pid)

    if alive is True:
        return CycleLockVerdict(
            state=STATE_HELD_ALIVE, severity=OK, pid=pid, held_since=held_since,
            age_seconds=age, clears_in_seconds=clears_in, refusals_since_lock=refusals,
            detail=(f"цикл идёт: держатель pid={pid} жив"
                    + (f" ({age / 60:.0f} мин)" if age is not None else "")
                    + " — отказы остальных вызовов ЗАКОННЫ, трек защищён"),
        )

    if alive is None:
        return CycleLockVerdict(
            state=STATE_UNCHECKED, severity=WARNING, pid=pid, held_since=held_since,
            age_seconds=age, clears_in_seconds=clears_in, refusals_since_lock=refusals,
            detail=f"живость держателя pid={pid} измерить не удалось — НЕ ИЗМЕРЕНО",
            issue=(f"cycle lock UNCHECKED: живость держателя pid={pid} измерить не "
                   "удалось — это не «всё в порядке»"),
        )

    mins = "" if clears_in is None else f", сам снимется через {clears_in / 60:.0f} мин"
    return CycleLockVerdict(
        state=STATE_HELD_DEAD, severity=CRITICAL, pid=pid, held_since=held_since,
        age_seconds=age, clears_in_seconds=clears_in, refusals_since_lock=refusals,
        detail=(f"замок держит МЁРТВЫЙ процесс pid={pid} (взят {held_since or '?'}"
                f"{mins}) — каждый вызов дневного цикла до тех пор ОТКАЗЫВАЕТ; "
                f"{_refusal_words()}"),
        issue=(f"cycle lock застрял: держатель pid={pid} МЁРТВ, замок взят "
               f"{held_since or '?'}{mins} — дневной цикл отказывает каждому вызову "
               f"(это не авария цикла и не защита: это труп в дверях); "
               + _refusal_words()),
    )
