#!/usr/bin/env python3
"""Сторож Телеграма: замечает поломку и чинит ЕДИНСТВЕННЫМ безопасным способом.

Задание владельца 2026-08-08: *«чтобы Телеграм постоянно кто-то проверял на поломки, и если
что-то поломалось — само чинилось»*.

Почему понадобился ещё один сторож, хотя их уже три
------------------------------------------------------------------------------
08.08 бот трое суток исполнял код от 5 августа: кнопки, доставленные 7-го, не работали, и
владелец узнал об этом сам. Все существующие сторожа отвечали ЧЕСТНО и мимо:

* `deployment_drift_monitor` — «в дереве тот код, который приняли» (правда);
* `deployment_acceptance` — «флот способен стартовать» (правда);
* `agent_health_monitor` — «процесс жив» (правда, pid на месте);
* `self_heal` — оживляет KeepAlive-сервер **только когда pid == 0**, а тут pid был.

Ни один не отвечал на вопрос «работает ли Телеграм НА САМОМ ДЕЛЕ». Это наш родовой класс
дефектов (fail-OPEN monitor): страж отвечает на свой вопрос, а читают его как ответ на нужный.

Чем этот сторож НЕ является
------------------------------------------------------------------------------
Раньше в репозитории лежал `spa_core/monitoring/telegram_watcher.py`, и включать его было
нельзя по двум причинам:

1. он сам зовёт `getUpdates` — тот же вызов, которым живёт бот. Второй поллер на одном токене
   даёт 409-конфликты и КРАДЁТ у бота нажатия владельца (ровно авария 08.08);
2. чинить он предлагает через `devtools/auto_fixer`, который просит Claude переписать
   прод-код. **LLM в мониторинге запрещён инвариантом #3**, а авто-правка кода опаснее той
   поломки, которую лечит.

17.08 он СПИСАН решением владельца (карточка `own-55-vtoroi-chitatel-komand-v-telegram`,
ВАРИАНТ 1): модуль, его plist и его тесты удалены — читать очередь он больше не может даже
случайным запуском. Причины выше оставлены не как история, а как правило: следующий сторож
Телеграма обязан быть устроен ТАК ЖЕ, как этот, — по следам, а не по очереди.

Здесь нет ни одного `getUpdates`: сторож смотрит на СЛЕДЫ бота (маячок, процессы, launchd),
а не разговаривает с Telegram от его имени.

Что именно проверяется — и почему каждая проверка нужна
------------------------------------------------------------------------------
============================  =============================================================
Проверка                      Какую реальную аварию ловит
============================  =============================================================
job загружен, pid != 0        бот умер и launchd не поднял (это же ловит `self_heal`)
ровно ОДИН поллер             два поллера на токене → 409, нажатия теряются (авария гейта 08.08)
маячок свежий                 процесс жив, но не крутит цикл (завис) ⇒ нажатия не обработать
маячок умеет alert_actions    бот старый: кнопки будут, а обработать их некому
процесс НЕ старше кода        авария 08.08: доставлено, но не исполняется
============================  =============================================================

Починка — ОДНА, и она обратимая
------------------------------------------------------------------------------
`launchctl kickstart -k com.spa.telegram_bot`. Больше сторож не умеет ничего: не убивает чужие
процессы, не правит файлы, не трогает risk-логику, не переустанавливает агентов.

Дисциплина починки (иначе сторож сам становится аварией):

* **Не чинить, если поллеров больше одного.** Перезапуск добавил бы третий. Дубль — сигнал
  владельцу, а не повод действовать.
* **Предохранитель:** не более ``MAX_RESTARTS_PER_WINDOW`` перезапусков за скользящий час.
  Крашлуп не должен превратиться в шторм перезапусков.
* **Проверять результат.** После перезапуска ждём маячок; не вернулся — это провал починки,
  о нём говорим вслух, а не молчим «перезапустили, значит починили».
* **Fail-CLOSED:** не смогли ИЗМЕРИТЬ (нет доступа к launchctl/ps/файлу) — статус UNKNOWN и
  НИКАКИХ действий. «Не знаю» никогда не значит «всё хорошо» и не значит «чини».

Почему тревога дойдёт, даже когда бот лежит
------------------------------------------------------------------------------
Отправка сообщения — stateless POST, она НЕ требует поллера; поллер нужен только чтобы
принимать нажатия. Значит «бот не отвечает на кнопки» и «владельцу не дозвониться» — разные
поломки, и о первой можно honestly сообщить вторым каналом.

stdlib, детерминированно, **LLM запрещён** (инвариант #3).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spa_core.utils.atomic import atomic_save

_REPO_ROOT = Path(__file__).resolve().parents[2]

LABEL = "com.spa.telegram_bot"
BOT_MODULE = "spa_core.telegram.bot"
STATE_PATH = _REPO_ROOT / "data" / "telegram_health.json"
BEACON_PATH = _REPO_ROOT / "data" / "telegram_bot_capabilities.json"

#: Маячок обновляется каждый виток long-poll (~30с). Порог с большим запасом: сеть Telegram
#: может подвиснуть на минуту, и это не повод дёргать бота.
BEACON_MAX_AGE_S = 300
REQUIRED_CAPABILITY = "alert_actions"

#: Модули, чьё изменение требует перезапуска бота: их код живёт ВНУТРИ вечного процесса.
WATCHED_MODULES = (
    "spa_core/telegram/bot.py",
    "spa_core/telegram/router.py",
    "spa_core/telegram/owner_decisions.py",
    "spa_core/telegram/alert_actions.py",
    "spa_core/telegram/menus.py",
    "spa_core/telegram/prefs.py",
    "spa_core/telegram/i18n.py",
)
#: Запас на саму доставку: файл записан, процесс стартует секундой позже — это не «старый код».
STALE_CODE_GRACE_S = 120

#: Предохранитель: сколько перезапусков за скользящее окно допустимо.
MAX_RESTARTS_PER_WINDOW = 3
RESTART_WINDOW_S = 3600
#: Сколько ждать маячок после перезапуска, прежде чем признать починку неудавшейся.
BEACON_WAIT_AFTER_RESTART_S = 90

SUBPROC_TIMEOUT = 15

OK, WARN, CRITICAL, UNKNOWN = "OK", "WARNING", "CRITICAL", "UNKNOWN"
#: Порядок серьёзности. UNKNOWN стоит рядом с CRITICAL намеренно: «не смогли измерить» — это
#: не «хорошо», это отсутствие ответа, и оно обязано быть видно.
_RANK = {OK: 0, WARN: 1, UNKNOWN: 2, CRITICAL: 3}


@dataclass
class Finding:
    check: str
    status: str
    detail: str
    #: Можно ли лечить это перезапуском. Дубль поллеров — НЕЛЬЗЯ (добавит третий).
    restart_helps: bool = False
    #: ПЛАНОВОЕ следствие нашей же доставки, а не поломка снаружи. Такое чинится
    #: молча: владельца зовут, когда нужен ОН, а не когда система отработала штатно.
    #: Ставится ТОЛЬКО там, где причина заведомо самодельная (см. `_check_stale_code`).
    routine: bool = False


@dataclass
class Report:
    status: str = OK
    findings: List[Finding] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    checked_at: str = ""

    def add(self, f: Finding) -> None:
        self.findings.append(f)
        if _RANK[f.status] > _RANK[self.status]:
            self.status = f.status

    def to_dict(self) -> Dict:
        return {
            "schema_version": 1,
            "status": self.status,
            "checked_at": self.checked_at,
            "findings": [
                {"check": f.check, "status": f.status, "detail": f.detail}
                for f in self.findings
            ],
            "actions": self.actions,
        }


# ── измерения (каждое умеет сказать «не знаю») ───────────────────────────────


def _run(args: Sequence[str]) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(list(args), capture_output=True, text=True,
                              timeout=SUBPROC_TIMEOUT)
    except Exception:  # noqa: BLE001 — не смогли спросить систему ⇒ «не знаю»
        return None


def launchd_pid(label: str = LABEL) -> Optional[int]:
    """pid задания launchd; 0 — загружено, но не запущено; ``None`` — не смогли измерить."""
    r = _run(["launchctl", "list"])
    if r is None or r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-1] == label:
            try:
                return int(parts[0])
            except ValueError:
                return 0
    return -1  # задание вообще не загружено — отличимо от «загружено, pid 0»


def poller_pids(module: str = BOT_MODULE) -> Optional[List[int]]:
    """pid'ы python-процессов, крутящих модуль бота. ``None`` — не смогли измерить.

    Ищем именно `python … -m <модуль>`: bash-обёртка тоже несёт имя модуля в командной
    строке, и посчитав её, мы бы вечно видели «два поллера» там, где он один.
    """
    r = _run(["ps", "-eo", "pid=,command="])
    if r is None or r.returncode != 0:
        return None
    pids: List[int] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or module not in line:
            continue
        try:
            pid_s, cmd = line.split(None, 1)
        except ValueError:
            continue
        if re.search(r"(^|/)python[0-9.]*\s", cmd + " ") and " -m " in cmd:
            try:
                pids.append(int(pid_s))
            except ValueError:
                continue
    return pids


def process_age_s(pid: int) -> Optional[float]:
    """Сколько секунд процесс живёт. ``None`` — не смогли измерить."""
    r = _run(["ps", "-o", "etime=", "-p", str(pid)])
    if r is None or r.returncode != 0 or not r.stdout.strip():
        return None
    return _parse_etime(r.stdout.strip())


def _parse_etime(text: str) -> Optional[float]:
    """``[[dd-]hh:]mm:ss`` → секунды."""
    text = text.strip()
    days = 0
    if "-" in text:
        d, _, text = text.partition("-")
        try:
            days = int(d)
        except ValueError:
            return None
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        h, m, s = 0, nums[0], nums[1]
    elif len(nums) == 3:
        h, m, s = nums
    else:
        return None
    return days * 86400 + h * 3600 + m * 60 + s


def read_beacon(path: Optional[Path] = None) -> Optional[Dict]:
    try:
        return json.loads((path or BEACON_PATH).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — нет/битый маячок = его нет
        return None


def newest_watched_mtime(root: Optional[Path] = None,
                         modules: Sequence[str] = WATCHED_MODULES) -> Optional[float]:
    """Самое свежее время правки модулей бота. ``None`` — ни одного не нашли (не измерили)."""
    base = root or _REPO_ROOT
    stamps = []
    for rel in modules:
        p = base / rel
        try:
            stamps.append(p.stat().st_mtime)
        except OSError:
            continue
    return max(stamps) if stamps else None


# ── проверка целиком ─────────────────────────────────────────────────────────


def check(
    *,
    now: Optional[datetime] = None,
    beacon_path: Optional[Path] = None,
    root: Optional[Path] = None,
) -> Report:
    """Собрать отчёт о здоровье Телеграма. Ничего не чинит и никогда не бросает."""
    dt = now or datetime.now(timezone.utc)
    rep = Report(checked_at=dt.isoformat())

    pid = launchd_pid()
    if pid is None:
        rep.add(Finding("launchd", UNKNOWN, "не смогли спросить launchctl"))
    elif pid == -1:
        rep.add(Finding("launchd", CRITICAL, f"задание {LABEL} не загружено в launchd"))
    elif pid == 0:
        rep.add(Finding("launchd", CRITICAL, "задание загружено, но процесс не запущен",
                        restart_helps=True))
    else:
        rep.add(Finding("launchd", OK, f"задание работает, pid {pid}"))

    pids = poller_pids()
    if pids is None:
        rep.add(Finding("поллеры", UNKNOWN, "не смогли перечислить процессы"))
    elif len(pids) > 1:
        # Перезапуск тут ЗАПРЕЩЁН: он добавит третий поллер к двум конфликтующим.
        rep.add(Finding("поллеры", CRITICAL,
                        f"поллеров {len(pids)} (pid {', '.join(map(str, pids))}) — "
                        f"409-конфликты, нажатия владельца теряются; чинить руками",
                        restart_helps=False))
    elif not pids:
        rep.add(Finding("поллеры", CRITICAL, "ни одного процесса бота", restart_helps=True))
    else:
        rep.add(Finding("поллеры", OK, f"ровно один, pid {pids[0]}"))

    doc = read_beacon(beacon_path)
    if doc is None:
        rep.add(Finding("маячок", CRITICAL,
                        "маячка нет — бот не объявляет, что умеет обрабатывать нажатия "
                        "(так выглядела авария 08.08)", restart_helps=True))
    else:
        stamped = _beacon_time(doc)
        if stamped is None:
            rep.add(Finding("маячок", CRITICAL, "в маячке нет разбираемой отметки времени",
                            restart_helps=True))
        else:
            age = (dt - stamped).total_seconds()
            if age < 0 or age > BEACON_MAX_AGE_S:
                rep.add(Finding("маячок", CRITICAL,
                                f"маячку {age:.0f}с (норма ≤ {BEACON_MAX_AGE_S}) — "
                                f"процесс есть, но цикл не крутится",
                                restart_helps=True))
            elif REQUIRED_CAPABILITY not in (doc.get("capabilities") or []):
                rep.add(Finding("маячок", CRITICAL,
                                f"бот не умеет «{REQUIRED_CAPABILITY}» — старый код",
                                restart_helps=True))
            else:
                rep.add(Finding("маячок", OK, f"свежий ({age:.0f}с), умеет обрабатывать нажатия"))

    rep.add(_check_stale_code(pids, dt, root))

    return rep


def _beacon_time(doc: Dict) -> Optional[datetime]:
    try:
        stamped = datetime.fromisoformat(str(doc.get("updated_at")))
    except Exception:  # noqa: BLE001
        return None
    return stamped if stamped.tzinfo else stamped.replace(tzinfo=timezone.utc)


def _check_stale_code(pids: Optional[List[int]], dt: datetime,
                      root: Optional[Path]) -> Finding:
    """Авария 08.08: процесс жив, но исполняет код, набранный ДО доставки.

    Сравниваем момент старта процесса с самой свежей правкой модулей бота. Это единственная
    проверка, которая вообще способна заметить «доставлено, но не исполняется».
    """
    if not pids or len(pids) != 1:
        return Finding("свежесть кода", UNKNOWN, "нет ровно одного процесса — сравнивать нечего")
    age = process_age_s(pids[0])
    if age is None:
        return Finding("свежесть кода", UNKNOWN, "не смогли узнать возраст процесса")
    mtime = newest_watched_mtime(root)
    if mtime is None:
        return Finding("свежесть кода", UNKNOWN, "не нашли ни одного модуля бота")
    started = dt.timestamp() - age
    lag = mtime - started
    if lag > STALE_CODE_GRACE_S:
        return Finding(
            "свежесть кода", CRITICAL,
            f"процесс стартовал на {lag / 3600:.1f}ч РАНЬШЕ последней правки кода бота — "
            f"исполняется старое (доставлено, но не работает)",
            restart_helps=True,
            # ПЛАНОВОЕ: этот «сбой» рождает наша собственная доставка — синк кода с origin
            # идёт перед КАЖДЫМ циклом, и любая правка семи модулей бота делает живой процесс
            # старым по построению. Владелец тут не нужен: перезапуск лечит это полностью и
            # без него. Замер 13.08: 14 перезапусков ⇒ ровно 26 сообщений владельцу, и НИ ОДНО
            # не требовало его действия. Обнаружение и починка не тронуты — молчит только вызов.
            routine=True,
        )
    return Finding("свежесть кода", OK, "процесс новее последней правки кода")


# ── починка ──────────────────────────────────────────────────────────────────


def _load_state(path: Optional[Path] = None) -> Dict:
    try:
        doc = json.loads((path or STATE_PATH).read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            doc.setdefault("restarts", [])
            return doc
    except Exception:  # noqa: BLE001
        pass
    return {"schema_version": 1, "restarts": []}


def _save_state(doc: Dict, path: Optional[Path] = None) -> None:
    p = path or STATE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(doc, str(p))


def restarts_in_window(state: Dict, now_ts: float) -> int:
    return len([t for t in state.get("restarts", [])
                if isinstance(t, (int, float)) and now_ts - t <= RESTART_WINDOW_S])


def kickstart(label: str = LABEL) -> bool:
    uid = str(os.getuid())
    r = _run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"])
    return bool(r and r.returncode == 0)


def heal(
    report: Report,
    *,
    now: Optional[datetime] = None,
    state_path: Optional[Path] = None,
    beacon_path: Optional[Path] = None,
    dry_run: bool = False,
    wait_for_beacon: bool = True,
) -> Report:
    """Починить, если поломка лечится перезапуском. Возвращает тот же отчёт с ``actions``.

    Ничего не делает, если: всё в порядке · поломка не лечится перезапуском (дубль поллеров) ·
    измерить не удалось (UNKNOWN) · сработал предохранитель.
    """
    dt = now or datetime.now(timezone.utc)
    healable = [f for f in report.findings if f.status == CRITICAL and f.restart_helps]
    blockers = [f for f in report.findings if f.status == CRITICAL and not f.restart_helps]

    if not healable:
        if blockers:
            report.actions.append(
                "перезапуск НЕ применён: поломка им не лечится — " +
                "; ".join(f.detail for f in blockers))
        return report
    if blockers:
        # Дубль поллеров + мёртвый маячок: перезапуск добавит третий процесс. Не трогаем.
        report.actions.append(
            "перезапуск ЗАБЛОКИРОВАН: сначала руками устранить — " +
            "; ".join(f.detail for f in blockers))
        return report

    state = _load_state(state_path)
    fired = restarts_in_window(state, dt.timestamp())
    if fired >= MAX_RESTARTS_PER_WINDOW:
        report.actions.append(
            f"перезапуск НЕ применён: предохранитель — уже {fired} за час "
            f"(предел {MAX_RESTARTS_PER_WINDOW}); это крашлуп, его лечит человек")
        return report

    if dry_run:
        report.actions.append("сухой прогон: перезапустил бы " + LABEL)
        return report

    if not kickstart():
        report.actions.append("перезапуск НЕ УДАЛСЯ: launchctl kickstart вернул ошибку")
        return report

    state.setdefault("restarts", []).append(dt.timestamp())
    state["restarts"] = state["restarts"][-50:]
    _save_state(state, state_path)
    report.actions.append(f"перезапущен {LABEL} (причина: " +
                          "; ".join(f.check for f in healable) + ")")

    if wait_for_beacon and not _beacon_came_back(beacon_path):
        report.actions.append(
            f"ПОЧИНКА НЕ ПОДТВЕРЖДЕНА: маячок не вернулся за {BEACON_WAIT_AFTER_RESTART_S}с — "
            f"бот не поднялся, нужен человек")
        report.status = CRITICAL
    else:
        report.actions.append("починка подтверждена: маячок вернулся")
    return report


def _beacon_came_back(beacon_path: Optional[Path] = None,
                      deadline_s: int = BEACON_WAIT_AFTER_RESTART_S) -> bool:
    """Ждём СВЕЖИЙ маячок. Проверяем результат, а не факт вызова kickstart."""
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        doc = read_beacon(beacon_path)
        if doc is not None:
            stamped = _beacon_time(doc)
            if stamped is not None:
                age = (datetime.now(timezone.utc) - stamped).total_seconds()
                if 0 <= age <= BEACON_MAX_AGE_S:
                    return True
        time.sleep(3)
    return False


# ── тревога владельцу ────────────────────────────────────────────────────────


#: Заголовок тела на КАЖДЫЙ статус. Раньше здесь было двоичное «CRITICAL или всё
#: остальное», и сообщение о выздоровлении уехало владельцу с телом «⚠️ не всё измерено»
#: (замерено 08.08 13:15). Три статуса — три заголовка; забыть один больше нельзя.
_HEAD_BY_STATUS: Dict[str, str] = {
    CRITICAL: "🚨 <b>Телеграм-бот сломан</b>",
    UNKNOWN: "❔ <b>Телеграм-бот: проверить не удалось</b>",
    WARN: "🟡 <b>Телеграм-бот: есть замечания</b>",
    OK: "✅ <b>Телеграм-бот работает</b>",
}


#: Признак того, что починка СРАБОТАЛА и подтверждена.
HEALED_MARK = "починка подтверждена"


def healed_and_confirmed(report: Report) -> bool:
    """Сломалось, но уже починено и проверено — к моменту чтения всё работает."""
    return any(HEALED_MARK in a for a in report.actions)


def is_routine_selfheal(report: Report) -> bool:
    """Штатная отработка на нашей же доставке — владельцу звонить НЕ о чем.

    Истина, только когда сошлось ВСЁ сразу:
    * починка проведена И подтверждена маячком (не «позвал kickstart», а «бот отвечает»);
    * КАЖДАЯ непройденная проверка помечена `routine`, т.е. её причина заведомо наша.

    `UNKNOWN` сюда не попадает by design: «не смогли измерить» — это отсутствие ответа,
    а не штатность, и оно обязано доехать до владельца (fail-CLOSED, тот же принцип, что
    и в `_RANK`). Одна не-`routine` красная проверка рядом — тоже отменяет молчание:
    сообщение уедет целиком, со всеми находками.

    Зачем вообще: сторож честно ловил «доставлено, но не исполняется» и честно чинил —
    и каждый раз звал владельца посмотреть на успешно отработавшую автоматику. За 08–13.08
    это дало 26 из 30 непрошеных сообщений; ровно на это владелец и пожаловался
    («ты опять пишешь мне, что всё починил… и опять по кругу»). Гасится ВЫЗОВ владельца,
    не проверка: находка, перезапуск, отчёт на диске и код возврата остаются как были,
    а сам факт уезжает в дайджест.
    """
    if not healed_and_confirmed(report):
        return False
    failed = [f for f in report.findings if f.status != OK]
    return bool(failed) and all(f.routine for f in failed)


def alert_text(report: Report, *, with_head: bool = True) -> str:
    """Человеческий текст тревоги. Строится ТОЛЬКО из измеренного.

    Самоизлечившийся инцидент НЕ подаётся как «🚨 сломан»: к моменту, когда владелец читает
    сообщение, всё уже работает, и тревожный тон здесь — ровно та лишняя ругань, на которую
    он жаловался. Факты при этом не прячутся: что именно ломалось и что сделано — ниже,
    дословно. Разница только в том, зовут ли владельца ЧИНИТЬ.
    """
    head = ("🔧 <b>Телеграм-бот: было сломано, починил сам</b>"
            if healed_and_confirmed(report) else _HEAD_BY_STATUS[report.status])
    # `with_head=False` — когда шапку ставит `push_policy`: две шапки подряд владелец
    # читает как сбой оформления, а не как подробность.
    lines = [head, ""] if with_head else []
    for f in report.findings:
        if f.status == OK:
            continue
        mark = {CRITICAL: "🔴", UNKNOWN: "❔", WARN: "🟡"}.get(f.status, "•")
        lines.append(f"{mark} {f.check}: {f.detail}")
    if report.actions:
        lines += ["", "<b>Что сделано:</b>"] + [f"• {a}" for a in report.actions]
    return "\n".join(lines)


def incident_fingerprint(report: Report) -> str:
    """Отпечаток КОНКРЕТНОЙ поломки: отсортированные имена непройденных проверок.

    Нужен, чтобы дедуп не съел ДРУГУЮ аварию. Сторож просыпается каждые 5 минут; без
    отпечатка «зависший маячок» вчера оставил бы класс в состоянии «плохо», и сегодняшний
    «два поллера» ушёл бы в тишину как «всё ещё плохо». Замерено в проде на `core_agent_down`.
    """
    return ",".join(sorted(f"{f.check}:{f.status}" for f in report.findings
                           if f.status != OK)) or "ok"


def notify(report: Report, *, now: Optional[datetime] = None) -> bool:
    """Сказать владельцу — ЧЕРЕЗ единственную разрешённую точку (`push_policy`).

    Почему не напрямую в транспорт: у Телеграма один авторитет на непрошеные сообщения
    (CI-страж `test_telegram_single_authority`), и он же даёт дедуп. Сторож просыпается
    каждые 5 минут — без дедупа одна поломка превратилась бы в 288 сообщений в сутки, и
    владелец отключил бы уведомления вместе с настоящими тревогами.

    Отправка не требует поллера (stateless POST), поэтому тревога о мёртвом боте дойдёт:
    «кнопки не работают» и «владельцу не дозвониться» — разные поломки.
    """
    try:
        from spa_core.telegram import push_policy

        if report.status == OK:
            # ВЫХОД из тревоги — обязателен, и он такой же явный, как вход.
            # Урок ADR-070 п.4: `kill_switch` висел в «плохо» с 04.07, потому что вход был,
            # а выхода не было — следующее срабатывание уехало бы в тишину как «всё ещё плохо».
            # Страж `test_alert_recovery_stuck_events` требует именно `push_policy.resolve(`.
            return bool(push_policy.resolve(
                "telegram_down",
                "Телеграм-бот снова работает",
                alert_text(report, with_head=False),
                now=now,
            ))
        if is_routine_selfheal(report):
            # Штатная отработка: в дайджест, не в чат. Владелец увидит это в дневной
            # сводке — факт не исчезает, исчезает ЗВОНОК. Вход в тревогу не записываем
            # намеренно: без «плохо» `push_policy.resolve` через 5 минут сам промолчит
            # (нормализует состояние и вернёт False), и парный ✅ не уедет. Именно пара
            # «🚨 починил» + «✅ работает» и составляла весь поток.
            push_policy.enqueue_digest(
                "telegram_down",
                "Телеграм-бот перезапущен после доставки кода",
                alert_text(report, with_head=False),
                severity=report.status,
                reason="routine_selfheal",
            )
            return False
        title = ("Телеграм-бот: было сломано, починил сам"
                 if healed_and_confirmed(report) else "Телеграм-бот сломан")
        return bool(push_policy.push_critical(
            "telegram_down",
            report.status,
            title,
            alert_text(report, with_head=False),
            dedup_key=incident_fingerprint(report),
            now=now,
        ))
    except Exception:  # noqa: BLE001 — молчание канала не должно ронять сторожа
        return False


def run(*, dry_run: bool = False, notify_owner: bool = True) -> Report:
    """Проверить → починить → записать → сказать. Точка входа агента."""
    report = check()
    report = heal(report, dry_run=dry_run)
    try:
        _write_report(report)
    except Exception:  # noqa: BLE001 — не смогли записать отчёт: это не повод не сказать
        pass
    # Зовём ВСЕГДА, решает `push_policy`: она одна знает предыдущее состояние и потому
    # умеет то, чего не умеет сторож, — прислать «снова работает» ровно один раз, на
    # переходе плохо→хорошо. Своя проверка «слать ли» здесь была бы вторым авторитетом,
    # который разъедется с первым.
    if notify_owner:
        notify(report)
    return report


def _write_report(report: Report) -> None:
    doc = _load_state()
    doc["last_report"] = report.to_dict()
    _save_state(doc)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    report = run(dry_run="--dry-run" in args,
                 notify_owner="--no-notify" not in args)
    print(f"telegram_health: {report.status}")
    for f in report.findings:
        print(f"  [{f.status}] {f.check}: {f.detail}")
    for a in report.actions:
        print(f"  → {a}")
    return {OK: 0, WARN: 1, UNKNOWN: 1, CRITICAL: 2}[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
