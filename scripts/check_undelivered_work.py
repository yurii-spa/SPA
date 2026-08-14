#!/usr/bin/env python3
"""scripts/check_undelivered_work.py — «объявил владение → доставил ли на origin?».

**Зачем.** Сессия объявляет владение файлами (`scripts/log_session_change.py`), работает в
изолированном worktree (протокол §3.4 это ОБЯЗЫВАЕТ), пишет отчёт в `docs/STATE.md` и журнал
**как о доставленной работе** — и умирает до пуша. Отчёт остаётся, кода на `origin/main` нет.
За одни сутки 30.07 так осиротела работа четырёх сессий подряд (#41 `pid31439`, #42 `pid38822`,
#43 `pid50691`/`pid54926`), и каждый раз это находила СЛЕДУЮЩАЯ сессия — вручную, пофайлово.
Радиус: следующая сессия строит решения на STATE, который врёт о состоянии origin; работа
теряется вместе с `/tmp`-worktree; осиротевший фикс успевает разойтись с тестами (цикл #44:
доставленный «как есть», он сделал бы CI на main красным).

**Что делает.** Детерминированно, read-only, только stdlib, **без сети** (`git fetch` не
вызывается — базовый ref берётся таким, каким он лежит локально):

1. читает последние N записей `data/session_changes.jsonl`;
2. отсеивает работу, которая ещё может быть в процессе: **подтверждённо активную** сессию
   (`ps -p <pid> -o lstart=` показывает процесс, стартовавший ДО объявления) и **свежие**
   объявления моложе окна ожидания (`--grace-hours`, по умолчанию 3);
3. для остальных сверяет каждый объявленный файл с базовым ref (`origin/main`) во ВСЕХ
   рабочих деревьях репозитория (хост + линкованные worktree — работа сироты лежит именно
   там): нет на базе → ``absent``; есть незакоммиченная правка, которой нет ни в текущем
   `origin/main`, ни в его истории для этого пути → ``differs``;
4. **отдельным вопросом** сверяет КАРТОЧКИ: карточка в НЕтерминальном статусе, лежащая в
   рабочем дереве и отсутствующая на базе, — находка (`card_findings`). Это не частный
   случай пункта 3: карточку, созданную посреди цикла, никто не объявляет, и разбор
   объявлений её не увидит по построению (цикл #140, карточка
   `inbox-kartochka-sozdannaya-posredi-tsikla-ne-d`);
5. печатает находки и **отдельно** всё, что измерить не удалось.

**Почему окно ожидания, а не только `ps`.** По умолчанию `log_session_change.py` пишет
`pid<os.getpid()>` **однократного CLI-процесса**, поэтому «процесса нет» НЕ доказывает, что
сессия умерла, — этот вывод здесь и не делается. Отсутствие процесса лишь снимает подтверждение
активности; решает возраст объявления. Отсюда формулировка находки: «объявлено N часов назад,
на origin этого нет» — проверяемый факт.

**Основной критерий, когда он есть — долгоживущий процесс сессии** (`session_pid` +
`session_pid_start`, карточка `agent-durable-session-id`): сессия, у которой такой процесс
есть (`scripts/agent_orchestrator.sh` — его оболочка ждёт весь цикл), объявляет его
`SPA_SESSION_PID`, и тогда активность именно ИЗМЕРЯЕТСЯ — включая идентификаторы без pid
(`cycle49`, `cycle61`), которые до этого не измерялись НИКОГДА. Совпадение времени старта —
проверка личности процесса (переиспользованный pid не читается как живая сессия). Окно
ожидания остаётся запасным критерием для записей без этих полей — а их большинство.

**Молчать о записи вправе только ДОВЕРЕННАЯ личность проверки** — названная сессией явно
(`SPA_SESSION_ID`). Личность `pid<os.getpid()>` выведена из pid однократной CLI-команды, и по
ней пропуск «это мы сами» был бы fail-OPEN: совпадение с чужим идентификатором молча выронило
бы чужое объявление. Так уже случилось на Linux-раннере (pid 4242 = фикстура `pid4242`, `rc 0`
вместо `2`; цикл #223 починил тест, цикл #224 — прод). См. `session_state`.

**fail-CLOSED (инв. #2).** «Не смог измерить» никогда не сворачивается в «всё доставлено»:
нет `git` / нет базового ref / `ps` не отработал / путь вне репозитория / битая метка времени →
раздел «НЕ ИЗМЕРЕНО» и код возврата 2. Коды: **0** — всё измерено и всё доставлено; **1** —
есть находки (всё измерено); **2** — что-то не измерено (перебивает 1).

**Осознанные границы (это СИГНАЛ к ручной сверке, не автомат):**
- «объявленный файл» ≠ «файл, который сессия реально изменила» (владение объявляется авансом),
  поэтому находка может быть и про работу, которую сессия просто не начала;
- **рабочее дерево нельзя привязать к сессии.** Правка в `/tmp/spa_wt_*` не подписана; кто её
  оставил — не измеряется. Поэтому одинаковые находки схлопываются, а объявившие перечисляются
  списком (`also_declared_by`), без выдуманной атрибуции;
- **чего проверка НЕ увидит:** правку файла, который уже есть на базе, если её worktree удалён
  (следов не осталось). Измерено 30.07 на историческом прогоне: из пяти артефактов циклов
  #41–#43 нашлись все, кроме `tests/test_autopush_idempotent.py`, чей worktree к тому моменту
  исчез. Новые файлы (``absent``) ловятся всегда — их отсутствие на базе самодостаточно;
- базовый ref не обновляется (нет сети): устаревший `origin/main` даёт ЛОЖНЫЕ находки, а не
  ложную тишину — направление ошибки выбрано намеренно.
Никакой авто-доставки чужой работы здесь нет и не будет.

**Журнал берётся из ГЛАВНОГО рабочего дерева** (`main_worktree` / `shared_log`, цикл #54): `data/`
в `.gitignore`, поэтому запущенная из обязательного по §3.4 worktree проверка читала СВОЙ пустой
журнал и отвечала «НЕ ИЗМЕРЕНО» о любой сессии. Явный `--log`/`--root` по-прежнему главнее.

    python3 scripts/check_undelivered_work.py                 # последние 20 записей
    python3 scripts/check_undelivered_work.py --all --json
    python3 scripts/check_undelivered_work.py --base 299b3c871 --all   # исторический разбор
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = ROOT / "data" / "session_changes.jsonl"
DEFAULT_BASE = "origin/main"
DEFAULT_LAST = 20

# Объявление всегда пишется ПОСЛЕ старта процесса, но метка записи (UTC) и вывод `ps`
# (локальное время) приводятся к одной шкале конвертацией — допуск на неточность конвертации.
CLOCK_SKEW = timedelta(seconds=120)
DEFAULT_GRACE_HOURS = 3.0

ACTIVE, NOT_CONFIRMED, UNKNOWN = "active", "not_confirmed", "unknown"
DELIVERED, ABSENT, DIFFERS, UNMEASURED = "delivered", "absent", "differs", "unmeasured"

_PID_RE = re.compile(r"^pid(\d+)$")


# ── внешние команды (подменяются в тестах) ───────────────────────────────────

def _git(cwd, *args: str):
    """(rc, stdout, stderr). Никогда не бросает — «git не отработал» это тоже измерение."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        p = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, env=env)
    except (OSError, subprocess.SubprocessError) as exc:      # нет git в PATH и т.п.
        return 127, "", f"git недоступен: {exc}"
    return p.returncode, p.stdout, p.stderr


def _ps_lstart(pid: int):
    """(rc, stdout) для `ps -p <pid> -o lstart=`. rc=1 — процесса нет; 127 — `ps` не отработал."""
    try:
        p = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="],
                           capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return p.returncode, p.stdout


# ── разбор журнала объявлений ────────────────────────────────────────────────

def read_entries(log_path, last):
    """Последние `last` записей (None = все). Возвращает (записи, число битых строк)."""
    path = Path(log_path)
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    if last is not None:
        rows = rows[-last:]
    return rows, bad


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_lstart(value: str):
    """`ps -o lstart=` → aware datetime. Формат локальный ('Wed Jul 30 10:59:54 2026')."""
    try:
        naive = datetime.strptime(value.strip(), "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None
    return naive.astimezone()          # naive → локальная зона → сравнимо с UTC-меткой


# ── жива ли сессия ───────────────────────────────────────────────────────────

DURABLE_KEYS = ("session_pid", "session_pid_start")


def durable_fields(entry):
    """Подмножество ключей записи, описывающих долгоживущий процесс сессии (может быть пусто).

    Нужно тем, кто строит СИНТЕТИЧЕСКУЮ запись для `session_state` (шаг 0b собирает её из
    (session, ts)): без этих полей улучшение до них просто не доезжает."""
    return {k: entry[k] for k in DURABLE_KEYS if isinstance(entry, dict) and k in entry}


def _durable_state(entry, ts, ps):
    """None — сессия долгоживущего процесса не объявляла; иначе (state, измерение словами).

    **Основной критерий активности** (карточка `agent-durable-session-id`). `session` по
    умолчанию — pid ОДНОКРАТНОЙ CLI-команды, умирающий вместе с ней, поэтому `ps` по нему
    бессодержателен для ЛЮБОЙ записи, а id без pid (`cycle49`, `cycle61`) не измерялся вовсе.
    `session_pid` пишет `log_session_change.durable_process` только когда процесс подтверждён
    в момент записи, вместе с его временем старта.

    Совпадение старта — это проверка ЛИЧНОСТИ процесса: без неё переиспользованный ОС pid
    читался бы как живая сессия (ложный ACTIVE ⇒ шаг 0a молча пропустил бы недоставленную
    работу). Расхождение старта — не «не измерено», а измеренный факт «это другой процесс»."""
    if not isinstance(entry, dict) or "session_pid" not in entry:
        return None
    raw = entry.get("session_pid")
    pid = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    if pid is None and isinstance(raw, str) and raw.strip().isdigit():
        pid = int(raw.strip())
    if pid is None or pid <= 1:
        return UNKNOWN, (f"session_pid={raw!r} не разобран как pid процесса — "
                         "активность не измерена")

    rc, out = ps(pid)
    if rc == 1:
        return NOT_CONFIRMED, (f"долгоживущий процесс сессии pid{pid} завершился "
                               "(активность не подтверждена)")
    if rc != 0:
        return UNKNOWN, f"`ps -p {pid}` не отработал (rc={rc}) — активность не измерена"
    if not str(out).strip():
        return UNKNOWN, f"`ps -p {pid}` вернул пустой ответ — активность не измерена"
    started = _parse_lstart(out)
    if started is None:
        return UNKNOWN, (f"pid{pid} существует, но время старта не разобрано: "
                         f"{str(out).strip()!r} — активность не измерена")

    recorded_raw = entry.get("session_pid_start")
    if recorded_raw is None:
        # Долгоживущий pid без записанного старта: сверяемся с объявлением, как для pid-id.
        if started > ts + CLOCK_SKEW:
            return NOT_CONFIRMED, (f"pid{pid} занят ДРУГИМ процессом: старт "
                                   f"{started.isoformat()} позже объявления {ts.isoformat()}")
        return ACTIVE, f"долгоживущий процесс сессии pid{pid} жив (старт {started.isoformat()})"
    recorded = _parse_lstart(str(recorded_raw))
    if recorded is None:
        return UNKNOWN, (f"записанное время старта pid{pid} не разобрано: "
                         f"{str(recorded_raw)!r} — активность не измерена")
    if abs((started - recorded).total_seconds()) > CLOCK_SKEW.total_seconds():
        return NOT_CONFIRMED, (f"pid{pid} занят ДРУГИМ процессом: старт {started.isoformat()} "
                               f"вместо записанного {recorded.isoformat()}")
    return ACTIVE, (f"долгоживущий процесс сессии pid{pid} жив — тот же процесс "
                    f"(старт {started.isoformat()})")


def session_state(entry, self_session, ps=_ps_lstart, self_session_trusted=True):
    """(ACTIVE|NOT_CONFIRMED|UNKNOWN, измерение словами).

    ACTIVE — активность ПОДТВЕРЖДЕНА (это мы сами; объявленный сессией долгоживущий процесс
    жив; либо живой процесс из pid-идентификатора, стартовавший до объявления).
    NOT_CONFIRMED — подтверждения нет; это НЕ вывод «сессия умерла» (см. докстринг модуля),
    решает возраст объявления. UNKNOWN — измерить не смогли.

    Порядок: своя сессия → долгоживущий процесс записи (**основной критерий**) → pid из
    идентификатора (как раньше, для записей без новых полей). Окно ожидания у вызывающих
    остаётся запасным критерием и не трогается.

    **`self_session_trusted` — доверенная ли личность проверки.** Пропуск «это мы сами»
    имеет право молчать о записи, поэтому он допустим ТОЛЬКО по личности, которую сессия
    назвала явно (`SPA_SESSION_ID`). Личность вида `pid<os.getpid()>` выведена из pid
    ОДНОКРАТНОЙ CLI-команды и доверенной не является: совпадение такого pid'а с чужим
    идентификатором молча выронило бы чужое объявление из отчёта — fail-OPEN внутри
    сторожа, который весь построен как fail-CLOSED. Это не гипотеза: на Linux-раннере
    прогон получил pid **4242**, совпавший с фикстурой `pid4242`, и проверка вернула
    «всё измерено» вместо «не измерено» (цикл #223; тест починили тогда же, прод — нет).
    При недоверенной личности запись меряется ОБЫЧНЫМИ правилами, а совпадение
    называется вслух; находкой она становится по возрасту объявления, а не автоматически.
    """
    session = str(entry.get("session") or "")
    if session and session == self_session:
        if self_session_trusted:
            return ACTIVE, "это текущая сессия"
        state, why = _measured_session_state(entry, session, ps)
        return state, (f"идентификатор совпал с личностью этой проверки ({self_session}), но "
                       f"она выведена из pid однократного процесса и доверенной не является "
                       f"(нет SPA_SESSION_ID) — меряем запись как чужую: {why}")

    return _measured_session_state(entry, session, ps)


def _measured_session_state(entry, session, ps=_ps_lstart):
    """Измерение активности записи без ветки «это мы сами» (см. `session_state`)."""
    ts = _parse_ts(entry.get("ts"))
    if ts is None:
        return UNKNOWN, (f"метка времени записи не разобрана: {entry.get('ts')!r} — "
                         "возраст объявления не измерен")

    durable = _durable_state(entry, ts, ps)
    if durable is not None:
        return durable

    m = _PID_RE.match(session)
    if not m:
        return UNKNOWN, (f"идентификатор сессии {session!r} не содержит pid — "
                         "активность процесса не измерена")
    pid = int(m.group(1))

    rc, out = ps(pid)
    if rc == 1:
        return NOT_CONFIRMED, f"процесса pid{pid} нет (активность не подтверждена)"
    if rc != 0:
        return UNKNOWN, f"`ps -p {pid}` не отработал (rc={rc}) — активность не измерена"
    if not out.strip():
        return UNKNOWN, f"`ps -p {pid}` вернул пустой ответ — активность не измерена"

    started = _parse_lstart(out)
    if started is None:
        return UNKNOWN, (f"pid{pid} существует, но время старта не разобрано: "
                         f"{out.strip()!r} — активность не измерена")

    if started > ts + CLOCK_SKEW:
        return NOT_CONFIRMED, (f"pid{pid} занят ДРУГИМ процессом: старт {started.isoformat()} "
                               f"позже объявления {ts.isoformat()}")
    return ACTIVE, f"pid{pid} жив (старт {started.isoformat()})"


# ── путь → путь внутри репозитория ───────────────────────────────────────────

def _git_common_dir(cwd, git=_git):
    rc, out, _ = git(cwd, "rev-parse", "--git-common-dir")
    if rc != 0 or not out.strip():
        return None
    p = Path(out.strip())
    return (p if p.is_absolute() else Path(cwd) / p).resolve()


def main_worktree(start=ROOT, git=_git):
    """(корень ГЛАВНОГО рабочего дерева, None) либо (None, причина).

    **Зачем.** Протокол ОБЯЗЫВАЕТ автономный цикл работать в изолированном worktree (§3.4), а
    `data/` лежит в `.gitignore` ⇒ внутри worktree общего состояния сессий НЕТ: журнал
    объявлений там либо отсутствует, либо это свежесозданный пустой файл. Значит и запись, и
    чтение «кто чем занят» из worktree попадают в одноразовое дерево и исчезают вместе с ним.
    Измерено 31.07 на осиротевшем цикле #52: сессия объявила владение ПО ПРОТОКОЛУ, но запись
    легла в `/private/tmp/spa_wt_c52/data/session_changes.jsonl`, а хост-журнал её не видел
    (карточка `agent-claim-without-announce-is-invisible` диагностировала это как «сессия не
    объявила» — объявление БЫЛО, невидимым его сделал путь).

    `git worktree list --porcelain` перечисляет главное дерево ПЕРВЫМ (документированный
    порядок), линкованные worktree — после него. Главное дерево и есть общий корень.
    """
    rc, out, err = git(start, "worktree", "list", "--porcelain")
    if rc != 0:
        return None, (f"`git worktree list` завершился rc={rc}: {err.strip()[:200]!r} — "
                      f"главное рабочее дерево не определено")
    for line in out.splitlines():
        if line.startswith("worktree "):
            p = Path(line.split(" ", 1)[1].strip())
            if not p.is_dir():
                return None, f"главного рабочего дерева нет на диске: {p}"
            return p.resolve(), None
    return None, "`git worktree list` не назвал ни одного рабочего дерева"


def shared_log(start=ROOT, git=_git):
    """(путь к ОБЩЕМУ журналу объявлений, причина-если-не-разрешилось).

    Не разрешилось → путь относительно этого файла, как было раньше: в хост-репо он верный, а
    в worktree даёт пустой журнал, и оба шага честно скажут «НЕ ИЗМЕРЕНО» (fail-CLOSED). То
    есть неудача резолва никогда не превращается в «всё доставлено» / «карточка свободна»."""
    root, err = main_worktree(start, git)
    if root is None:
        return DEFAULT_LOG, err
    return root / "data" / "session_changes.jsonl", None


REAP_LEDGER_NAME = "worktree_reap_log.jsonl"
# Вердикты, при которых снятое дерево не уносило с собой работу (см. reap_stale_worktrees.py).
REAP_EXPLAINED = {"delivered", "superseded"}


def read_reap_ledger(root):
    """({путь снятого дерева: запись}, причина-если-не-прочитано).

    **Зачем.** Уборка мёртвых деревьев (`scripts/reap_stale_worktrees.py`) убирает осадок
    находок — и на её месте появился бы худший класс: объявленный путь внутри снятого дерева
    даёт «измерить нечем» и код 2 НАВСЕГДА. Квитанция — измерение, сделанное тогда, когда
    дерево ещё было: пофайловый вердикт плюс путь архива.

    Ослабления нет: пропуск получает только путь, названный в квитанции `delivered` или
    `superseded`. Нет квитанции · нет пути в ней · вердикт другой — прежнее «не измерено» /
    находка. Отсутствие журнала — норма (уборку могли ни разу не запускать), причиной оно не
    становится."""
    path = Path(root) / "data" / REAP_LEDGER_NAME
    if not path.exists():
        return {}, None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {}, f"журнал снятых рабочих деревьев не прочитан ({path}): {exc}"
    rows, bad = {}, 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        wt = obj.get("worktree")
        if wt:
            rows[str(Path(wt))] = obj          # последняя запись о дереве главнее
    return rows, (f"битых строк в журнале снятых деревьев: {bad}" if bad else None)


def reaped_state(path_str, ledger, root, base_ref, git=_git):
    """(вердикт, объяснение) для объявленного пути внутри СНЯТОГО дерева, либо (None, None).

    Вердикты: ``delivered`` — снятие было измерено и работа объяснена; ``absent`` — путь в
    квитанции не назван, а на базе такого файла нет вовсе (это находка, а не тишина);
    ``unmeasured`` — квитанция называет путь недоставленным (снятия такого дерева быть не
    должно, но если оно случилось — молчать нельзя)."""
    p = Path(str(path_str))
    if not p.is_absolute():
        return None, None
    for wt, row in ledger.items():
        prefix = wt.rstrip("/") + os.sep
        variants = {str(p), str(p).replace("/private/tmp/", "/tmp/", 1),
                    str(p).replace("/tmp/", "/private/tmp/", 1)}
        hit = next((v for v in variants if v.startswith(prefix)), None)
        if hit is None:
            continue
        rel = hit[len(prefix):]
        state = (row.get("paths") or {}).get(rel)
        where = f"дерево снято {row.get('ts')} по правилу уборки, архив: {row.get('archive')}"
        if state in REAP_EXPLAINED:
            return DELIVERED, f"{where}; содержимое пути объяснено при снятии ({state})"
        if state is not None:
            return UNMEASURED, (f"{where}, НО путь помечен при снятии как {state!r} — "
                                "снятие такого дерева правилом не предусмотрено")
        rc, _, _ = git(root, "cat-file", "-e", f"{base_ref}:{rel}")
        if rc != 0:
            return ABSENT, (f"{where}, путь в квитанции не назван, и на {base_ref} такого "
                            f"файла нет вовсе")
        return DELIVERED, (f"{where}; путь при снятии не расходился с {base_ref} "
                           "(правки в дереве не было)")
    return None, None


def resolve_rel(path_str, root, git=_git):
    """(repo-relative POSIX-путь, None) либо (None, причина). Тот же принцип, что в пушере:
    принадлежность ТОМУ ЖЕ репозиторию определяется по общему git-каталогу."""
    p = Path(str(path_str))
    if not p.is_absolute():
        return p.as_posix(), None

    root = Path(root).resolve()
    try:
        return p.resolve().relative_to(root).as_posix(), None
    except ValueError:
        pass

    probe = p if p.is_dir() else p.parent          # `git -C` хочет каталог, не файл
    climbed = not probe.is_dir()                   # пришлось лезть выше — каталогов уже нет
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    if not probe.is_dir() or probe == probe.parent:
        return None, (f"путь вне хост-репо, каталога больше нет (worktree удалён?): {path_str}")

    ours = _git_common_dir(root, git)
    theirs = _git_common_dir(probe, git)
    if ours is None or theirs is None or ours != theirs:
        # Две РАЗНЫЕ причины с одинаковым исходом «измерить нельзя», и называть их одинаково
        # нечестно. Если каталогов объявленного пути уже нет, а уцелевший предок — не наш
        # репозиторий, то дело не в чужом репозитории: рабочее дерево УДАЛЕНО вместе с
        # работой. Прежний текст «путь не принадлежит этому репозиторию» звучал как ошибка
        # объявления (кто-то объявил чужой файл), тогда как это потеря своего.
        # Вердикт не меняется — по-прежнему «не измерено» (код 2): доехала ли работа, из
        # удалённого дерева не узнать. Меняется только то, что сессия об этом прочитает.
        if climbed:
            return None, (f"рабочее дерево удалено вместе с объявленным путём — доставку "
                          f"измерить нечем: {path_str}")
        return None, f"путь не принадлежит этому репозиторию: {path_str}"

    rc, top, _ = git(probe, "rev-parse", "--show-toplevel")
    if rc != 0 or not top.strip():
        return None, f"не удалось определить корень worktree для {path_str}"
    try:
        return p.resolve().relative_to(Path(top.strip()).resolve()).as_posix(), None
    except ValueError:
        return None, f"путь вне найденного корня worktree: {path_str}"


# ── файл: есть ли он на базе и тот ли он ─────────────────────────────────────

def list_checkouts(root, git=_git):
    """(живые рабочие деревья, [мёртвые регистрации], причина-если-не-разрешилось).

    Осиротевшая работа лежит ИМЕННО в worktree (протокол §3.4 обязывает там работать), а в
    хост-дереве её нет — пуш идёт прямо в origin через API, локальный git дрейфует. Сверка
    только с хост-деревом такую правку не увидит (проверено на историческом прогоне).

    **Мёртвая регистрация ≠ рабочее дерево.** Каталог остался, а git-привязка мертва: файл
    `.git` внутри дерева исчез, служебная запись в `.git/worktrees/` осталась. Признак «каталог
    существует» (`p.is_dir()`) такое дерево пропускал в сверку, git-вызов в нём падал, и
    `collect_diff_sets` честно писал «рабочее дерево с базой НЕ сверено».
    Замер 06.08 (карточка `inbox-shag-0a-iz-worktree-daet-18-strok-ne-izm`): 16 таких
    регистраций давали **18 строк «НЕ ИЗМЕРЕНО» и код 2** на пустом месте, и разбирать их
    следующая сессия обязана руками — то есть очень скоро перестанет читать вовсе, а однажды
    в этих же строках окажется настоящая находка (класс «необратимое „не измерено“ морит
    очередь»).

    Различаются ДВА состояния, и это не педантизм, а разные вопросы:

    - **git сам объявил запись `prunable`** — это его собственный вердикт о СВОЁМ реестре,
      мерить там нечего: перед нами не чекаут, а остатки файлов. Такая регистрация НАЗЫВАЕТСЯ
      (одной строкой на каталог, с причиной от git), но «не измерено» из неё не делается.
    - **git считает дерево живым, а привязка не читается** — вот это не объяснено ничем, и
      остаётся `unmeasured` (код 2), как было. Ослабления нет: fail-CLOSED снимается ровно
      там, где авторитетный источник — сам git — сказал, что мерить нечего.

    Каталоги мёртвых регистраций из СВЕРКИ исключаются, но не из поиска карточек:
    `scan_tracker_cards` читает файловую систему, а не git, и остатки трекера в таком каталоге
    по-прежнему видит (покрытие сторожа карточек не сужается)."""
    rc, out, err = git(root, "worktree", "list", "--porcelain")
    if rc != 0:
        return None, [], f"`git worktree list` завершился rc={rc}: {err.strip()[:200]!r}"

    dirs, dead = [], []
    path, prunable = None, None

    def flush():
        if path is None or not path.is_dir():
            return
        if prunable is not None:
            reason = prunable.strip() or "git пометил запись prunable без пояснения"
            dead.append({"path": str(path), "prunable": True,
                         "reason": f"git пометил регистрацию prunable: {reason}"})
            return
        # git считает дерево живым — проверяем, читается ли привязка.
        prc, _, perr = git(path, "rev-parse", "--git-dir")
        if prc != 0:
            dead.append({"path": str(path), "prunable": False,
                         "reason": f"git считает дерево живым, но привязка не читается: "
                                   f"`rev-parse --git-dir` rc={prc} {perr.strip()[:120]!r}"})
            return
        dirs.append(path)

    for line in out.splitlines():
        if line.startswith("worktree "):
            flush()
            path, prunable = Path(line.split(" ", 1)[1].strip()), None
        elif line == "prunable" or line.startswith("prunable "):
            prunable = line[len("prunable"):]
    flush()

    if Path(root) not in dirs:
        dirs.insert(0, Path(root))
    return dirs, dead, None


def collect_diff_sets(base_ref, checkouts, git=_git):
    """{чекаут: множество путей с НЕЗАКОММИЧЕННОЙ работой, которой нет на базе}.

    Пересечение двух множеств, по два вызова git на чекаут:
    - ``diff --name-only HEAD`` — что в этом дереве изменено руками (собственно работа
      сессии: пуш идёт прямо в origin через API, локально работа так и остаётся правкой);
    - ``diff --name-only <base>`` — что расходится с origin.

    Пересечение обязательно: заброшенный worktree стоит на СТАРОМ коммите и расходится с
    origin в сотнях файлов, к которым никто не притрагивался. Без пересечения живой прогон
    дал 45 находок на 12 записях — почти все ложные (измерено 30.07).

    Новые файлы, не попавшие в индекс, `git diff` не покажет — но их и нет на базе,
    так что они ловятся проверкой `cat-file` как ``absent``."""
    sets, failed = {}, []
    for loc in checkouts:
        rc, dirty, err = git(loc, "-c", "core.quotepath=false", "diff", "--name-only", "HEAD")
        if rc != 0:
            failed.append(f"{loc}: `git diff HEAD` rc={rc} {err.strip()[:120]!r}")
            continue
        rc, vs_base, err = git(loc, "-c", "core.quotepath=false", "diff", "--name-only", base_ref)
        if rc != 0:
            failed.append(f"{loc}: `git diff {base_ref}` rc={rc} {err.strip()[:120]!r}")
            continue
        sets[str(loc)] = ({ln for ln in dirty.split("\n") if ln}
                          & {ln for ln in vs_base.split("\n") if ln})
    return sets, failed


def _blob_sha(path):
    """git-хеш содержимого файла, посчитанный локально (без вызова git)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(data))
    h.update(data)
    return h.hexdigest()


def origin_blob_history(root, base_ref, rel, git=_git):
    """Все версии (blob-хеши) этого пути в истории базового ref. None — прочитать не удалось."""
    rc, out, _ = git(root, "log", "--format=%H", "--raw", "--no-abbrev", "--no-renames",
                     base_ref, "--", rel)
    if rc != 0:
        return None
    shas = set()
    for line in out.splitlines():
        if line.startswith(":"):
            parts = line.split()
            if len(parts) >= 4:
                shas.add(parts[3])
    return shas


def file_state(root, base_ref, rel, git=_git, diff_sets=None):
    """(состояние, объяснение, список рабочих деревьев с расхождением)."""
    rc, _, err = git(root, "cat-file", "-e", f"{base_ref}:{rel}")
    if rc != 0:
        local = "" if (Path(root) / rel).exists() else "; локально файла тоже нет"
        return ABSENT, f"на {base_ref} файла нет{local}", []

    differing = sorted(loc for loc, paths in (diff_sets or {}).items() if rel in paths)
    if differing:
        return (DIFFERS,
                f"есть на {base_ref}, но содержимое отличается в: {', '.join(differing)}",
                differing)
    return DELIVERED, f"совпадает с {base_ref} во всех рабочих деревьях", []


# ── карточки: «создана → доставлена?» ────────────────────────────────────────
#
# Второй вопрос, НЕ сводимый к первому. Первый спрашивает «объявленное доехало?» и по
# построению видит только то, что кто-то объявил. Карточка, созданная ПОСРЕДИ цикла, не
# объявляется никогда: `orchestrator_queue.py create` пишет её в трекер ТОГО дерева, чья
# копия скрипта запущена (измерено циклом #140: копия из worktree пишет в worktree, копия
# из хост-дерева — в хост-дерево, cwd не влияет), а списки файлов на пуш собираются по
# рабочему дереву цикла. Живой случай: `inbox-audit-prigodnosti-ne-videl-186-modulei-t`
# создана 19:34, уже ПОСЛЕ финального объявления цикла #138 в 19:18 («ДОСТАВЛЕН» — честного,
# он доставил ровно то, что было в его дереве); на origin её не было, она лежала
# неотслеживаемой в хост-дереве и нашлась случайной сверкой имён, а не сторожем.
#
# Свежести здесь НЕТ намеренно (в отличие от объявлений): шаг 0a исполняется в НАЧАЛЕ цикла,
# и карточки этого цикла в этот момент ещё не существует ⇒ любая находка — про прошлые
# циклы. Возраст файла в находку выводится, чтобы своя минуту назад созданная карточка
# опознавалась глазом, но тишиной она не покупается (fail-CLOSED).

TRACKER_REL = "nimbalyst-local/tracker"
BOARD_NAME = "_BOARD.md"          # производный индекс, пересобирается целиком — не карточка
# Отработанная карточка. Список шире набора шага 0b (там он про снятие захвата, здесь — про
# доставку): карточку, осознанно закрытую без доставки, находкой звать не за что.
CARD_TERMINAL_STATUSES = {"done", "ingested", "owner-done", "rejected", "archived"}


def card_status(text: str):
    """Значение top-level ``status:`` из frontmatter карточки, либо None.

    Свой минимальный разбор (как в `build_tracker_board.py` / `check_card_claim.py`):
    скрипт остаётся stdlib-only и не тянет `spa_core`. Читается ТОЛЬКО блок frontmatter —
    строка `status:` в теле карточки статусом не является."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None                      # без frontmatter статуса нет — и это не «терминальная»
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip() or raw[:1].isspace():
            continue
        key, sep, val = raw.partition(":")
        if sep and key.strip() == "status":
            v = val.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            return v or None
    return None


def base_card_names(root, base_ref, git=_git):
    """(множество имён файлов карточек на базовом ref, None) либо (None, причина).

    Пустой перечень — тоже отказ, а не «на базе карточек нет»: в норме их сотни, и пустое
    множество сделало бы находкой КАЖДУЮ карточку (fail-CLOSED в обе стороны)."""
    rc, out, err = git(root, "ls-tree", "-r", "--name-only", base_ref, "--", f"{TRACKER_REL}/")
    if rc != 0:
        return None, (f"`git ls-tree {base_ref} -- {TRACKER_REL}/` rc={rc} "
                      f"{err.strip()[:160]!r} — состав карточек на базе НЕ измерен")
    names = {ln.rsplit("/", 1)[-1] for ln in out.splitlines() if ln.strip().endswith(".md")}
    if not names:
        return None, (f"на {base_ref} в {TRACKER_REL}/ не нашлось ни одной карточки — "
                      "так не бывает в норме; сверка карточек НЕ выполнена (иначе находкой "
                      "стала бы каждая карточка)")
    return names, None


def scan_tracker_cards(checkouts):
    """({имя файла: {"statuses": {…}, "trees": [...], "age_hours": …}}, [причины «не измерено»]).

    Карточка ищется во ВСЕХ рабочих деревьях по той же причине, что и файлы: цикл работает в
    worktree (§3.4), и осиротевшая карточка лежит именно там."""
    cards, problems = {}, []
    now = datetime.now(timezone.utc)
    for loc in checkouts:
        d = Path(loc) / TRACKER_REL
        if not d.is_dir():
            # Чекаут без трекера — законное состояние (герметичный чекаут, старый worktree,
            # частичный клон). Терять здесь нечего: вопрос сторожа — «лежит ли В ДЕРЕВЕ
            # карточка, которой нет на базе», а в этом дереве карточек нет вовсе.
            continue
        try:
            files = sorted(d.glob("*.md"))
        except OSError as exc:
            problems.append(f"{d}: каталог карточек нечитаем ({exc.__class__.__name__}) — "
                            "карточки этого дерева НЕ сверены")
            continue
        for p in files:
            if p.name == BOARD_NAME:
                continue
            try:
                text = p.read_text(encoding="utf-8")
                mtime = p.stat().st_mtime
            except OSError as exc:
                problems.append(f"{p}: карточка нечитаема ({exc.__class__.__name__}) — "
                                "её статус НЕ измерен")
                continue
            rec = cards.setdefault(p.name, {"statuses": set(), "trees": [], "age_hours": None})
            rec["statuses"].add(card_status(text))
            rec["trees"].append(str(loc))
            age = round((now - datetime.fromtimestamp(mtime, timezone.utc)).total_seconds() / 3600, 2)
            rec["age_hours"] = age if rec["age_hours"] is None else min(rec["age_hours"], age)
    return cards, problems


def undelivered_cards(root, base_ref, checkouts, git=_git):
    """([находки], [не измерено]) — карточки в НЕтерминальном статусе, которых нет на базе."""
    findings, unmeasured = [], []
    cards, problems = scan_tracker_cards(checkouts)
    for pr in problems:
        unmeasured.append({"session": None, "path": None, "reason": pr})
    if not cards:
        # Ни одной карточки ни в одном рабочем дереве — сверять нечего, и отказ здесь был бы
        # ложной тревогой: недоставленной может оказаться только та карточка, что ЛЕЖИТ в
        # дереве. Порядок важен — сперва «есть ли что сверять», и лишь потом требование
        # к базе: обратный порядок красил бы любой чекаут без трекера (измерено на 15
        # герметичных тестах шага 0a, которые так и покраснели).
        return findings, unmeasured

    names, err = base_card_names(root, base_ref, git=git)
    if names is None:
        unmeasured.append({"session": None, "path": TRACKER_REL, "reason": err})
        return findings, unmeasured

    for name in sorted(cards):
        if name in names:
            continue
        rec = cards[name]
        statuses = rec["statuses"]
        # Статус может расходиться между деревьями — тогда карточка считается НЕтерминальной
        # (терминальность обязана быть единодушной), иначе одно устаревшее дерево гасило бы находку.
        if statuses and all((s or "").strip().lower() in CARD_TERMINAL_STATUSES for s in statuses):
            continue
        shown = "/".join(sorted((s or "(нет status:)") for s in statuses)) or "(нет status:)"
        findings.append({
            "card": name[:-3] if name.endswith(".md") else name,
            "file": f"{TRACKER_REL}/{name}",
            "status": shown,
            "trees": sorted(set(rec["trees"])),
            "age_hours": rec["age_hours"],
            "reason": f"карточки нет на {base_ref} — создана и не доставлена",
        })
    return findings, unmeasured


# ── сборка отчёта ────────────────────────────────────────────────────────────

def build_report(entries, root, base_ref, self_session, ps=_ps_lstart, git=_git,
                 malformed_lines=0, log_path=None, now=None,
                 grace_hours=DEFAULT_GRACE_HOURS, self_session_trusted=True):
    root = Path(root)
    now = now or datetime.now(timezone.utc)
    grace = timedelta(hours=grace_hours)
    findings, unmeasured, fresh, stale_copies, card_findings = [], [], [], [], []
    reaped = []
    seen, hist_cache = {}, {}
    reap_ledger, ledger_error = read_reap_ledger(root)
    report = {
        "base_ref": base_ref,
        "base_sha": None,
        "log": str(log_path) if log_path else None,
        "grace_hours": grace_hours,
        "entries_checked": len(entries),
        "sessions_active": 0,
        "sessions_checked": 0,
        "findings": findings,
        "card_findings": card_findings,
        "fresh": fresh,
        "stale_copies": stale_copies,
        "reaped": reaped,
        "unmeasured": unmeasured,
        "dead_worktrees": [],
        "exit_code": 0,
    }

    if ledger_error:
        unmeasured.append({"session": None, "path": None,
                           "reason": f"{ledger_error} — измерения снятых деревьев НЕ прочитаны"})

    if malformed_lines:
        unmeasured.append({"session": None, "path": None,
                           "reason": f"битых строк в журнале объявлений: {malformed_lines} "
                                     "(записи не разобраны, что в них объявляли — неизвестно)"})

    rc, sha, err = git(root, "rev-parse", "--verify", f"{base_ref}^{{commit}}")
    if rc != 0:
        unmeasured.append({"session": None, "path": None,
                           "reason": f"базовый ref {base_ref!r} не разрешается в коммит "
                                     f"({err.strip()[:200]!r}) — сверка с origin НЕ ВЫПОЛНЕНА"})
        report["exit_code"] = 2
        return report
    report["base_sha"] = sha.strip()

    checkouts, dead_worktrees, err = list_checkouts(root, git=git)
    if checkouts is None:
        unmeasured.append({"session": None, "path": None,
                           "reason": f"{err} — сверка только с хост-деревом была бы "
                                     "ложно-успокоительной, поэтому не выполняется"})
        report["exit_code"] = 2
        return report
    report["checkouts"] = [str(c) for c in checkouts]

    # Мёртвая регистрация: git-привязки нет, сверять нечего. Названа отдельной строкой на
    # каталог (не молчание), а «не измерено» из неё делается только там, где git СЧИТАЕТ
    # дерево живым — то есть где непонятность настоящая. См. list_checkouts.
    report["dead_worktrees"] = [d for d in dead_worktrees if d["prunable"]]
    for d in dead_worktrees:
        if not d["prunable"]:
            unmeasured.append({"session": None, "path": d["path"], "reason": d["reason"]})

    diff_sets, diff_failures = collect_diff_sets(base_ref, checkouts, git=git)
    for f in diff_failures:                      # чекаут не сравнён — сказать это вслух
        unmeasured.append({"session": None, "path": None,
                           "reason": f"{f} — рабочее дерево с базой НЕ сверено"})

    # Второй вопрос: карточка, созданная посреди цикла, не объявляется никогда, поэтому
    # разбор объявлений ниже её не увидит по построению (см. блок «карточки» выше).
    # Каталоги мёртвых регистраций сюда ВХОДЯТ: карточки ищутся по файловой системе, git там
    # не нужен, и сузить покрытие сторожа карточек эта правка не должна.
    cf, cu = undelivered_cards(root, base_ref,
                              checkouts + [Path(d["path"]) for d in dead_worktrees], git=git)
    card_findings.extend(cf)
    unmeasured.extend(cu)

    for entry in entries:
        state, why = session_state(entry, self_session, ps=ps,
                                   self_session_trusted=self_session_trusted)
        if state == ACTIVE:
            report["sessions_active"] += 1
            continue
        if state == UNKNOWN:
            unmeasured.append({"session": entry.get("session"), "path": None, "reason": why})
            continue

        ts = _parse_ts(entry.get("ts"))          # разобрана: иначе был бы UNKNOWN выше
        age = now - ts
        if age < grace:
            fresh.append({"session": entry.get("session"), "ts": entry.get("ts"),
                          "age_hours": round(age.total_seconds() / 3600, 2),
                          "files": len(entry.get("files") or []),
                          "reason": f"{why}; объявлено {round(age.total_seconds()/3600, 2)}ч "
                                    f"назад — окно ожидания {grace_hours}ч ещё не истекло"})
            continue

        why = f"{why}; объявлено {round(age.total_seconds()/3600, 2)}ч назад"
        report["sessions_checked"] += 1
        for raw in entry.get("files") or []:
            rel, err = resolve_rel(raw, root, git=git)
            if rel is None:
                # Дерева нет — но, возможно, его СНИМАЛИ по правилу, и тогда измерение
                # осталось в квитанции (read_reap_ledger). Пропуск даётся только пути,
                # названному объяснённым; всё остальное идёт прежним путём.
                st, detail = reaped_state(raw, reap_ledger, root, base_ref, git=git)
                if st == DELIVERED:
                    reaped.append({"session": entry.get("session"), "path": str(raw),
                                   "reason": detail})
                    continue
                if st is not None:
                    if st == ABSENT:
                        findings.append({"session": entry.get("session"), "ts": entry.get("ts"),
                                         "path": str(raw), "state": ABSENT, "detail": detail,
                                         "session_state": why,
                                         "summary": (entry.get("summary") or "")[:160],
                                         "also_declared_by": []})
                    else:
                        unmeasured.append({"session": entry.get("session"), "path": str(raw),
                                           "reason": detail})
                    continue
                unmeasured.append({"session": entry.get("session"), "path": str(raw),
                                   "reason": err})
                continue
            st, detail, locs = file_state(root, base_ref, rel, git=git, diff_sets=diff_sets)
            if st == DELIVERED:
                continue

            if st == DIFFERS:
                # Локальная копия может быть просто СТАРОЙ: пуш идёт прямо в origin через API,
                # рабочее дерево остаётся с прежним содержимым навсегда («git push API drift»).
                # Отличить старую копию от потерянной работы можно точно: если хеш содержимого
                # уже встречался в истории origin для этого пути — это не потерянная работа.
                if rel not in hist_cache:        # STATE/журнал объявляют десятки сессий
                    hist_cache[rel] = origin_blob_history(root, base_ref, rel, git=git)
                known = hist_cache[rel]
                if known is not None:
                    unseen = [l for l in locs if (_blob_sha(Path(l) / rel) or "") not in known]
                    if not unseen:
                        stale_copies.append({"session": entry.get("session"), "path": rel,
                                             "reason": "содержимое рабочих деревьев уже есть в "
                                                       f"истории {base_ref} — устаревшая копия, "
                                                       "не потерянная работа"})
                        continue
                    detail = (f"есть на {base_ref}, но содержимого из {', '.join(unseen)} "
                              f"НЕТ в истории {base_ref} для этого файла")
            if st == UNMEASURED:
                unmeasured.append({"session": entry.get("session"), "path": rel,
                                   "reason": detail})
                continue

            # Один и тот же файл объявляют почти все сессии (STATE, журнал) — находка одна,
            # а объявившие перечисляются: кому принадлежит содержимое рабочего дерева,
            # измерить нельзя, и выдавать это за атрибуцию нечестно.
            key = (rel, st, detail)
            if key in seen:
                findings[seen[key]]["also_declared_by"].append(entry.get("session"))
                continue
            seen[key] = len(findings)
            findings.append({"session": entry.get("session"), "ts": entry.get("ts"),
                             "path": rel, "state": st, "detail": detail, "session_state": why,
                             "summary": (entry.get("summary") or "")[:160],
                             "also_declared_by": []})

    report["exit_code"] = 2 if unmeasured else (1 if (findings or card_findings) else 0)
    return report


# ── печать ───────────────────────────────────────────────────────────────────

def render(report) -> str:
    out = []
    base = report["base_ref"]
    sha = (report["base_sha"] or "?")[:9]
    out.append(f"Сверка «объявил → доставил» против {base} ({sha}); "
               f"записей: {report['entries_checked']}, "
               f"подтверждённо активных сессий: {report['sessions_active']}, "
               f"свежих (окно {report.get('grace_hours')}ч): {len(report.get('fresh') or [])}, "
               f"проверено: {report['sessions_checked']}")

    if report["findings"]:
        out.append("")
        out.append(f"⚠️  НЕ ДОСТАВЛЕНО ({len(report['findings'])}) — объявлено давно, "
                   f"активность не подтверждена, а объявленного на {base} нет:")
        for f in report["findings"]:
            mark = "отсутствует" if f["state"] == ABSENT else "отличается"
            out.append(f"  [{mark}] {f['path']}")
            out.append(f"      сессия {f['session']} ({f['ts']}): {f['session_state']}")
            out.append(f"      {f['detail']}")
            if f.get("also_declared_by"):
                out.append(f"      тот же файл объявляли ещё: {', '.join(f['also_declared_by'])}")
            if f["summary"]:
                out.append(f"      объявляла: {f['summary']}")

    if report.get("card_findings"):
        out.append("")
        out.append(f"🗂  КАРТОЧКИ НЕ ДОСТАВЛЕНЫ ({len(report['card_findings'])}) — есть в рабочем "
                   f"дереве в НЕтерминальном статусе, на {base} их нет:")
        for c in report["card_findings"]:
            out.append(f"  [{c['status']}] {c['card']}")
            out.append(f"      {c['reason']}; в деревьях: {', '.join(c['trees'])}")
            if c.get("age_hours") is not None:
                out.append(f"      файлу {c['age_hours']}ч — если это карточка ЭТОГО цикла, "
                           "добавь её в список пуша")

    if report["unmeasured"]:
        out.append("")
        out.append(f"❓ НЕ ИЗМЕРЕНО ({len(report['unmeasured'])}) — молчаливого «всё в порядке» "
                   "здесь не будет:")
        for u in report["unmeasured"]:
            where = f" · {u['path']}" if u.get("path") else ""
            out.append(f"  - {u.get('session') or '-'}{where}: {u['reason']}")

    if report.get("dead_worktrees"):
        out.append("")
        out.append(f"🧹 мёртвые регистрации рабочих деревьев ({len(report['dead_worktrees'])}) — "
                   "каталог остался, git-привязки нет; сверять нечего, но и молчать не о чем "
                   "(лечится осознанным `git worktree prune`):")
        for d in report["dead_worktrees"]:
            out.append(f"  - {d['path']}: {d['reason']}")

    if report.get("reaped"):
        out.append("")
        out.append(f"🧾 снятые деревья с квитанцией ({len(report['reaped'])}) — дерева нет, но "
                   "измерение сделано ДО снятия, и работа объяснена:")
        for r in report["reaped"]:
            out.append(f"  - {r.get('session') or '-'} · {r['path']}: {r['reason']}")

    if report.get("fresh"):
        out.append("")
        out.append(f"⏳ свежие объявления ({len(report['fresh'])}) — не находки, работа может идти:")
        for f in report["fresh"]:
            out.append(f"  - {f['session']} ({f['ts']}, файлов: {f['files']}): {f['reason']}")

    if not report["findings"] and not report["unmeasured"] and not report.get("card_findings"):
        out.append("✅ измерено полностью, всё доставлено")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only проверка: объявленная в session_changes.jsonl работа "
                    "мёртвых сессий — доехала ли она до origin. Сети не касается.")
    # Умолчания разрешаются в ГЛАВНОЕ рабочее дерево, а не в дерево этого файла: запущенный
    # из worktree (а протокол §3.4 обязывает работать именно там) шаг 0a иначе читает пустой
    # журнал и отвечает «НЕ ИЗМЕРЕНО» о ЛЮБОЙ сессии. Явный флаг по-прежнему главнее.
    ap.add_argument("--log", default=None, help="журнал объявлений (JSONL)")
    ap.add_argument("--root", default=None, help="корень репозитория для сверки")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"базовый ref (по умолчанию {DEFAULT_BASE})")
    ap.add_argument("--last", type=int, default=DEFAULT_LAST, help="сколько последних записей")
    ap.add_argument("--all", action="store_true", help="проверить весь журнал")
    ap.add_argument("--grace-hours", type=float, default=DEFAULT_GRACE_HOURS,
                    help="сколько часов после объявления считать работу возможно идущей "
                         f"(по умолчанию {DEFAULT_GRACE_HOURS})")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    shared_root, root_error = main_worktree()
    log_path = Path(args.log) if args.log else shared_log()[0]
    root = args.root or (str(shared_root) if shared_root else str(ROOT))

    if not log_path.exists():
        payload = {"base_ref": args.base, "base_sha": None, "log": str(log_path),
                   "grace_hours": args.grace_hours, "entries_checked": 0,
                   "sessions_active": 0, "sessions_checked": 0, "findings": [], "fresh": [],
                   "stale_copies": [],
                   "unmeasured": [{"session": None, "path": str(log_path),
                                   "reason": "журнала объявлений нет — сверка НЕ ВЫПОЛНЕНА"
                                             + (f"; главное рабочее дерево не определено: "
                                                f"{root_error}" if root_error else "")}],
                   "exit_code": 2}
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else render(payload))
        return 2

    entries, malformed = read_entries(log_path, None if args.all else args.last)
    # Доверенная личность — только явно названная сессией. `pid<os.getpid()>` — pid
    # ОДНОКРАТНОЙ CLI-команды: по нему пропускать чужие объявления нельзя (см. session_state).
    env_session = os.environ.get("SPA_SESSION_ID")
    self_session = env_session or f"pid{os.getpid()}"
    report = build_report(entries=entries, root=root, base_ref=args.base,
                          self_session=self_session, ps=_ps_lstart, git=_git,
                          malformed_lines=malformed, log_path=log_path,
                          grace_hours=args.grace_hours,
                          self_session_trusted=bool(env_session))
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
