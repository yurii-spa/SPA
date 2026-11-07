#!/usr/bin/env python3
"""spa_core/monitoring/undelivered_run_trace.py — «у НЕДОСТАВЛЕННОЙ работы был ли ЗЕЛЁНЫЙ ПРОГОН?»

**Зачем.** Четыре цикла подряд законченная работа ночевала незакоммиченной и поднималась
следующим циклом: #1046→#1047, #1050→#1051→#1052, #1053→#1054. Ось РАБОЧЕГО ДЕРЕВА
(`orphan_sweep`, ADR-929/930) эту работу НАХОДИТ — то есть прибор исправен, а теряется она
ПОСЛЕ последней правки и ДО пуша. Заказ G924 п. 3 / G925 п. 2 спрашивает следующее:

    у скольких таких деревьев между последним байтом работы и смертью сессии остался
    ЗЕЛЁНЫЙ ПРОГОН без доставки, и различимо ли по СЛЕДУ «сессия умерла» от
    «сессия решила не доставлять».

**Чем это НЕ мерится, и это измерено, а не предположено.**

* ``card_state: done`` в объявлении — НЕГОДЕН. Замер #1052: у `cycle-92496` объявление ровно
  одно, оно несёт ``done`` в 12:01:57Z, а последний байт работы записан в 12:10:54Z — через
  8 мин 57 с ПОСЛЕ «готово», и доставки не было вовсе.
* Поле ``verified`` объявления — НЕГОДНО ПО ПОСТРОЕНИЮ, и это сильнее, чем «ненадёжно».
  `log_session_change.py` зовут ДО правок (протокол §3.4: «объяви владение до правок»),
  поэтому ``verified`` написан АВАНСОМ — он описывает прогон, которого на момент записи
  ещё не было. Спрашивать его значило бы читать НАМЕРЕНИЕ как НАБЛЮДЕНИЕ.
* Вывод прогона — НЕДОСТИЖИМ. Замер #1054: осиротевший `pytest` (pid 89731, 4 ч 10 мин,
  заказчик `cycle-42875` мёртв) держал stdout/stderr в UNLINKED временных файлах харнесса
  мёртвой сессии: ``lsof`` их называет, файловая система — уже нет. Вердикт такого прогона
  нельзя прочитать НИКОМУ и НИКОГДА.

**Чем мерится.** Единственный ДОЛГОВЕЧНЫЙ след прогона в дереве — кэш `pytest`
(`.pytest_cache/v/cache/`), и он переживает смерть сессии вместе с деревом:

* ``nodeids`` — список собранных прогоном имён. Пишется плагином кэша в
  ``pytest_sessionfinish``, то есть его отметка есть время ЗАВЕРШЕНИЯ прогона, а его длина —
  ОХВАТ прогона;
* ``lastfailed`` — имена упавших. Падений не было ⇒ файла нет либо он пуст.

Отсюда ЧЕТЫРЕ двери, у каждой свой вопрос и свой третий исход (инв. #17):

====================  ==========================================================
дверь                 вопрос, на который она отвечает
====================  ==========================================================
``run_door``          прогон в этом дереве ЗАВЕРШАЛСЯ, и упал ли он
``order_door``        прогон завершился ПОСЛЕ последнего байта работы или ДО
``scope_door``        СКОЛЬКО имён прогон собрал (зелёный без охвата — зелёный
                      ответ на свой вопрос, а не на нужный)
``intent_door``       объявляла ли сессия ОТКАЗ доставлять (поле ``dropped``)
``process_door``      держит ли дерево ЖИВОЙ ПРОЦЕСС прямо сейчас (ADR-938):
                      сужает ``unmeasured`` первой двери, НЕ отменяя его и НЕ
                      утверждая, что живой держатель есть идущий прогон
====================  ==========================================================

**Почему охват — отдельная дверь, а не примечание.** «Зелёно» у батареи из 13 имён и
«зелёно» у предписанного набора в ≈96 000 — разные утверждения, и склеить их значило бы
повторить дефект, против которого написана половина правил репозитория. Прибор охват
НАЗЫВАЕТ и НЕ СУДИТ: порога «достаточного охвата» у него нет, потому что замера такого
порога нет ни у кого.

**Почему «сессия умерла» НЕ является исходом.** Доказать смерть нечем: номер процесса
переработан ОС, объявления о смерти никто не пишет. Поэтому ``intent_door`` отвечает только
``declined`` (отказ ОБЪЯВЛЕН полем ``dropped``) либо ``undeclared`` — и ``undeclared`` есть
«не измерено», а не «умерла». Тот же порядок, что у ``flight_verdict`` в `orphan_sweep`:
«брошена» исходом не является (ADR-924).

**Чего прибор НЕ видит, и это названо вслух.** Прогон, УБИТЫЙ до конца, кэша не пишет —
плагин зовётся в ``pytest_sessionfinish``. Значит «следа нет» покрывает сразу два разных
мира: прогона не было вовсе И прогон не доехал до вердикта. Развести их этой дверью
нельзя, и прибор их не разводит — он отвечает ``unmeasured`` с названной причиной. Ровно
такой случай и был у #1053: кэш дерева доставки несёт зелёный прогон 18:33:07Z, а
ЧЕТЫРЁХЧАСОВОЙ прогон в соседнем дереве `_run` был жив и вердикта не дал.

**Поправка ADR-938 (заказ G926 п. 3): один из двух миров ИЗМЕРИМ, и именно он.** Прогон,
который ещё идёт, держит ЖИВОЙ процесс — о нём можно спросить ОС, и живой четырёхчасовой
прогон #1053 был бы назван ЭТОЙ дверью. Поэтому ``process_door`` сужает ``unmeasured``
первой двери до «сейчас не идёт», а не отменяет его: прогон, убитый час назад, не оставил
НИ кэша, НИ процесса, и измерить его нечем по-прежнему. Дверь спрашивает ДВЕ пробы
(командные строки и рабочие каталоги), у каждой своя канарейка — СВОЙ номер процесса
обязан быть в снимке, иначе ответ есть «не измерено», а не «никого».

**Запуск с флагом ``-p no:cacheprovider`` следа не оставляет** — ещё один вход в
``unmeasured``. Прибор только ЧИТАЕТ: ни одного байта ни в одно дерево он не пишет
(кроме своего отчёта, и только когда его об этом просят).

Коды возврата::

    0  ни одного дерева с недоставленной работой И завершённым прогоном
    1  население НЕПУСТО — перечислено
    2  НЕ ИЗМЕРЕНО (поверхность деревьев не прочитана)

ADR-937.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from spa_core.monitoring import orphan_sweep as sweep_mod  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_REL = Path(".pytest_cache/v/cache")
NODEIDS = CACHE_REL / "nodeids"
LASTFAILED = CACHE_REL / "lastfailed"

# Объявленные исходы каждой двери. Перечень — ОБЪЯВЛЕНИЕ, с которым сверяется тест:
# дверь, вернувшая имя вне своего списка, краснит сторожа, а не проезжает молча.
RUN_OUTCOMES = ("green", "red", "unmeasured")
ORDER_OUTCOMES = ("run_covers_work", "run_predates_work", "unmeasured")
SCOPE_OUTCOMES = ("named", "unmeasured")
INTENT_OUTCOMES = ("declined", "undeclared", "unmeasured")
PROCESS_OUTCOMES = ("live", "none", "unmeasured")
NAMING_OUTCOMES = ("named", "none", "unmeasured")


def parse_now(raw: Optional[str]) -> datetime:
    """Момент — ВХОД, а не окружение (`.claude/rules/deployment.md`, приём №1).

    Неразбираемое и пустое значение — ОТКАЗ с причиной, а не молчаливый возврат к
    стенным часам (инв. #17): подстановка часов сделала бы «якорь не приняли»
    неотличимым от «якорь приняли».
    """
    if raw is None:
        return datetime.now(timezone.utc)
    text = raw.strip()
    if not text:
        raise ValueError("--now пуст: это не момент, а отсутствие момента")
    try:
        got = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"--now не разобран ({text!r}): {exc}") from exc
    return got if got.tzinfo else got.replace(tzinfo=timezone.utc)


def _stamp(epoch: Optional[float]) -> Optional[str]:
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> tuple[Optional[str], Optional[str]]:
    """Текст файла либо ``None`` с ПРИЧИНОЙ. Пустая строка — не то же, что «не прочитан»."""
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, "файла нет"
    except OSError as exc:
        return None, f"не прочитан: {exc}"
    except UnicodeDecodeError as exc:
        return None, f"не декодируется: {exc}"


def _mtime(path: Path) -> Optional[float]:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def run_door(tree: Path, *, read_text=None, mtime_probe=None) -> dict:
    """Прогон в этом дереве ЗАВЕРШАЛСЯ, и упал ли он.

    Опора — кэш `pytest`. ``nodeids`` пишется в ``pytest_sessionfinish``, поэтому его
    наличие есть свидетельство ЗАВЕРШЁННОГО прогона, а отметка — время завершения.
    ``lastfailed`` пуст или отсутствует ⇒ падений последний завершённый прогон не оставил.

    Кэша нет ⇒ ``unmeasured``, и причина названа. Это НЕ «прогона не было»: убитый прогон
    кэша не пишет, и запуск с ``-p no:cacheprovider`` тоже.
    """
    reader = read_text or _read_text
    probe = mtime_probe or _mtime
    nodeids_raw, nodeids_why = reader(tree / NODEIDS)
    if nodeids_raw is None:
        return {"run": "unmeasured",
                "run_reason": f"след прогона не прочитан ({NODEIDS}): {nodeids_why}",
                "run_finished": None, "run_failed": None, "run_failed_examples": []}
    finished = probe(tree / NODEIDS)
    failed_raw, failed_why = reader(tree / LASTFAILED)
    if failed_raw is None:
        # Файла нет ⇒ падений не было: плагин снимает его, когда прогон чист.
        # «Не прочитан по другой причине» от «нет» отличается, и это печатается.
        failed, examples = [], []
        if failed_why != "файла нет":
            return {"run": "unmeasured",
                    "run_reason": f"падения не прочитаны ({LASTFAILED}): {failed_why}",
                    "run_finished": _stamp(finished), "run_failed": None,
                    "run_failed_examples": []}
    else:
        try:
            doc = json.loads(failed_raw) if failed_raw.strip() else {}
        except json.JSONDecodeError as exc:
            return {"run": "unmeasured",
                    "run_reason": f"{LASTFAILED} не разобран как JSON: {exc}",
                    "run_finished": _stamp(finished), "run_failed": None,
                    "run_failed_examples": []}
        failed = sorted(doc) if isinstance(doc, dict) else []
        examples = failed[:3]
    return {"run": "red" if failed else "green",
            "run_reason": None,
            "run_finished": _stamp(finished),
            "run_failed": len(failed),
            "run_failed_examples": examples}


def order_door(run_finished_epoch: Optional[float],
               work_newest_epoch: Optional[float]) -> dict:
    """Прогон завершился ПОСЛЕ последнего байта работы или ДО него.

    Это и есть предмет заказа: «зелёный прогон» ДО последней правки не измерял тех байтов,
    которые остались недоставленными, — он отвечал о ПРЕДЫДУЩЕЙ редакции. Склеить два
    случая значило бы выдать вердикт о чужом содержимом за вердикт об этом.

    Любая из двух отметок не прочитана ⇒ ``unmeasured``: сравнения из одной отметки не
    бывает, а подстановка нуля или «сейчас» дала бы ответ, которого замер не видел.
    """
    if run_finished_epoch is None or work_newest_epoch is None:
        missing = []
        if run_finished_epoch is None:
            missing.append("времени завершения прогона")
        if work_newest_epoch is None:
            missing.append("отметки последнего байта работы")
        return {"order": "unmeasured",
                "order_reason": "нет " + " и ".join(missing),
                "order_gap_s": None}
    gap = run_finished_epoch - work_newest_epoch
    return {"order": "run_covers_work" if gap >= 0 else "run_predates_work",
            "order_reason": None,
            "order_gap_s": round(gap, 1)}


def scope_door(tree: Path, *, read_text=None) -> dict:
    """СКОЛЬКО имён собрал прогон. НАЗЫВАЕТ и НЕ СУДИТ.

    Порога «достаточного охвата» у прибора нет намеренно: замера такого порога нет ни у
    кого, а выдуманный порог превратил бы измерение в суждение (`docs/37`).
    """
    reader = read_text or _read_text
    raw, why = reader(tree / NODEIDS)
    if raw is None:
        return {"scope": "unmeasured", "scope_reason": f"{NODEIDS}: {why}",
                "scope_collected": None}
    try:
        doc = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError as exc:
        return {"scope": "unmeasured", "scope_reason": f"{NODEIDS} не разобран: {exc}",
                "scope_collected": None}
    if not isinstance(doc, list):
        return {"scope": "unmeasured",
                "scope_reason": f"{NODEIDS} не список, а {type(doc).__name__}",
                "scope_collected": None}
    return {"scope": "named", "scope_reason": None, "scope_collected": len(doc)}


def intent_door(tree: str, entries: Optional[Sequence[dict]]) -> dict:
    """Объявляла ли сессия ОТКАЗ доставлять — спрашивается у ПОЛЯ, а не грепом по тексту.

    Поле ``dropped`` `log_session_change.py` и есть объявленный канал «решил не доставлять,
    и вот почему». Его наличие — НАБЛЮДЕНИЕ. Его отсутствие наблюдением НЕ является:
    «умерла» доказать нечем, поэтому второй исход назван ``undeclared``, а не ``died``.

    Вопрос задаётся ПОЛЮ ``files`` (и ``dropped``) записи, а не её тексту: греп по
    ``summary`` ловит упоминания чужих деревьев в резюме — эта ошибка за два цикла дала
    ложный ответ дважды (#1051 «needs-owner 5 против 4», #1052 «три объявления вместо одного»).
    """
    if entries is None:
        return {"intent": "unmeasured", "intent_reason": "журнал объявлений не прочитан",
                "intent_sessions": [], "intent_dropped": []}
    prefix = tree.rstrip("/") + "/"
    mine, dropped = [], []
    for rec in entries:
        if not isinstance(rec, dict):
            continue
        files = rec.get("files") or []
        hit = any(isinstance(f, str) and (f == tree or f.startswith(prefix))
                  for f in files)
        drops = rec.get("dropped") or []
        drop_paths = [d.get("path") for d in drops if isinstance(d, dict)]
        drop_hit = any(isinstance(p, str) and (p == tree or p.startswith(prefix))
                       for p in drop_paths)
        if not (hit or drop_hit):
            continue
        session = rec.get("session")
        if session and session not in mine:
            mine.append(session)
        if drop_hit:
            for d in drops:
                if not isinstance(d, dict):
                    continue
                p = d.get("path")
                if isinstance(p, str) and (p == tree or p.startswith(prefix)):
                    dropped.append({"path": p, "reason": d.get("reason"),
                                    "session": session})
    if dropped:
        return {"intent": "declined", "intent_reason": None,
                "intent_sessions": mine, "intent_dropped": dropped}
    return {"intent": "undeclared",
            "intent_reason": ("объявления отказа нет; «умерла» исходом НЕ является — "
                              "доказать её нечем"),
            "intent_sessions": mine, "intent_dropped": []}


# ── ПЯТАЯ ДВЕРЬ (заказ G926 п. 3, ADR-938) ──────────────────────────────────────
# «Следа нет» (`run_door` → ``unmeasured``) покрывает ДВА мира, и ADR-937 назвал это
# вслух, не разведя: прогона не было ВОВСЕ — и прогон НЕ ДОЕХАЛ до вердикта (кэш
# пишется в ``pytest_sessionfinish``, поэтому убитый прогон следа не оставляет ПО
# ПОСТРОЕНИЮ). Один из двух миров измерим ПРЯМО СЕЙЧАС: если прогон ещё идёт, его
# процесс жив, и о нём можно спросить ОС. Второй мир измерим только задним числом и
# остаётся «не измерено» — поэтому дверь отвечает «live» либо «none», а не «умер».

def _run_tool(argv: Sequence[str], *, timeout: float = 180.0) -> tuple[Optional[int], str, str]:
    """Запустить пробу. ``None`` в первом поле = инструмента НЕТ (отдельный исход)."""
    try:
        done = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "", f"инструмента нет: {argv[0]}"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", f"проба не состоялась ({argv[0]}): {exc}"
    return done.returncode, done.stdout or "", done.stderr or ""


def _probe_argv(run=None, *, canary_pid: Optional[int] = None) -> dict:
    """Процессы и их КОМАНДНЫЕ СТРОКИ — один снимок таблицы процессов.

    Канарейка: СВОЙ номер процесса обязан быть в снимке. Пустая или бессмысленная
    выдача иначе читалась бы как «в деревьях никого» — то есть «не измерено» выдало бы
    себя за «измерено и равно нулю» (инв. #17). Код возврата на этот вопрос не
    отвечает: рабочий прогон может выйти ненулевым и при полной выдаче (дословный урок
    `pyflakes`, `.claude/rules/deployment.md`).
    """
    runner = run or _run_tool
    pid_now = canary_pid if canary_pid is not None else os.getpid()
    code, out, err = runner(["/bin/ps", "-axo", "pid=,command="])
    if code is None:
        return {"ok": False, "reason": err, "rows": []}
    rows: list[tuple[int, str]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        head, _, rest = line.partition(" ")
        try:
            rows.append((int(head), rest.strip()))
        except ValueError:
            continue
    if not any(pid == pid_now for pid, _ in rows):
        return {"ok": False,
                "reason": (f"канарейка не прошла: своего pid {pid_now} нет в снимке "
                           f"(строк разобрано {len(rows)}, код {code})"),
                "rows": []}
    return {"ok": True, "reason": None, "rows": rows}


def _probe_cwd(run=None, *, canary_pid: Optional[int] = None) -> dict:
    """Процессы и их РАБОЧИЕ КАТАЛОГИ: ``lsof -a -d cwd -F pn``.

    Вторая проба нужна потому, что первая отвечает на СВОЙ вопрос: процесс, который
    работает В дереве, свой путь в командной строке называть НЕ ОБЯЗАН (``pytest -q``,
    запущенный из дерева, не содержит имени дерева ни одним символом). Канарейка — та же.
    """
    runner = run or _run_tool
    pid_now = canary_pid if canary_pid is not None else os.getpid()
    code, out, err = runner(["/usr/sbin/lsof", "-a", "-d", "cwd", "-F", "pn"])
    if code is None:
        code2, out2, err2 = runner(["lsof", "-a", "-d", "cwd", "-F", "pn"])
        if code2 is None:
            return {"ok": False, "reason": f"{err}; {err2}", "rows": []}
        code, out = code2, out2
    rows: list[tuple[int, str]] = []
    pid: Optional[int] = None
    for line in out.splitlines():
        if not line:
            continue
        tag, body = line[0], line[1:]
        if tag == "p":
            try:
                pid = int(body)
            except ValueError:
                pid = None
        elif tag == "n" and pid is not None:
            rows.append((pid, body))
    if not any(pid == pid_now for pid, _ in rows):
        return {"ok": False,
                "reason": (f"канарейка не прошла: своего pid {pid_now} нет в выдаче "
                           f"(строк разобрано {len(rows)}, код {code})"),
                "rows": []}
    return {"ok": True, "reason": None, "rows": rows}


def process_snapshot(*, argv_probe=None, cwd_probe=None,
                     canary_pid: Optional[int] = None) -> dict:
    """ОДИН снимок на всю перепись — и это не экономия, а условие согласованности.

    Спрашивать ОС заново у каждого дерева значило бы судить сто деревьев в сто разных
    моментов: процесс, перешедший из дерева A в дерево B между вопросами, попал бы в
    ОБА ответа либо ни в один, и перепись перестала бы описывать какой-либо один мир.
    """
    argv = (argv_probe or _probe_argv)(canary_pid=canary_pid)
    cwd = (cwd_probe or _probe_cwd)(canary_pid=canary_pid)
    # Сводного поля «снимок годен» здесь НЕТ намеренно: у каждой пробы свой вопрос и
    # свой исход, а общее «ок» не смог бы ответить ни на один — дверь спрашивает ровно
    # ту пробу, которая ей нужна. Мутация такого поля вердикта не меняла, и это был не
    # пробел покрытия, а признак, что поле мёртвое (замер ADR-938).
    return {"argv": argv, "cwd": cwd,
            "self_pid": canary_pid if canary_pid is not None else os.getpid()}


def _names_tree(text: str, tree: str) -> bool:
    """Называет ли строка ИМЕННО это дерево — по ГРАНИЦЕ пути, не подстрокой.

    Подстрочное совпадение здесь не «неточно», а НЕВЕРНО в опасную сторону: имя
    ``/private/tmp/spa_c1052`` целиком содержится в ``/private/tmp/spa_c1052_run``, и
    прогон соседнего дерева приписался бы этому — ровно та же ошибка формы имени,
    которая уже дала ложный ответ в соседних заказах.
    """
    base = tree.rstrip("/")
    start = 0
    while True:
        at = text.find(base, start)
        if at < 0:
            return False
        after = text[at + len(base): at + len(base) + 1]
        if after == "" or after in "/ \t:;,\"'\n":
            return True
        start = at + 1


def process_door(tree: str, snapshot: Optional[dict]) -> dict:
    """Держит ли это дерево ЖИВОЙ ПРОЦЕСС прямо сейчас — вердикт держит РАБОЧИЙ КАТАЛОГ.

    **Это НЕ вопрос «идёт ли прогон», и разница ИЗМЕРЕНА.** Замер ADR-938: живых
    держателей нашлось в пяти деревьях, и у трёх дисковых деревьев `_run` все **54**
    держателя оказались безголовым `Google Chrome` (12 из них сироты, ppid 1, старейший
    жив **1 сут 10 ч**) — браузер унаследовал рабочий каталог от прогона, который давно
    кончился. Назвать такой держатель «идущим прогоном» значило бы ответить на СВОЙ
    вопрос вместо нужного. Поэтому дверь НАЗЫВАЕТ команду держателя
    (``process_commands``) и не судит её род.

    Три исхода (инв. #17):

    * ``live``  — процесс, у которого РАБОЧИЙ КАТАЛОГ внутри дерева. Номера названы;
    * ``none``  — проба каталогов ОТВЕТИЛА и никого не нашла;
    * ``unmeasured`` — проба не ответила (инструмента нет либо канарейка не прошла).
      Ноль процессов и «никто не спрашивал» обязаны быть различимы.

    ``none`` НЕ означает «прогона не было»: оно означает «сейчас не идёт». Прогон,
    убитый час назад, не оставил ни кэша, ни процесса, и этой дверью не измеряется
    ВОВСЕ — поэтому дверь СУЖАЕТ ``unmeasured`` первой двери, а не отменяет его.

    **Почему командная строка вердикта НЕ держит, и это ИЗМЕРЕНО, а не предположено.**
    Первая редакция считала ``live`` любой процесс, чья командная строка НАЗЫВАЕТ дерево.
    Проба на живой машине сразу дала ложное срабатывание: о дереве
    ``/private/tmp/spa_c1052`` ответ был ``live`` двумя процессами, и оба были МОИ
    СОБСТВЕННЫЕ — они это дерево только НАЗВАЛИ аргументом, работая в другом. То есть
    ось argv отвечает на вопрос «кто ПРОИЗНОСИТ имя дерева», и МЕРЯЮЩИЙ процесс
    произносит его по построению: прибор ответил бы о СЕБЕ, а не о мире.

    Поэтому argv остаётся ОТДЕЛЬНОЙ осью ``naming`` — список КАНДИДАТОВ, а не вердикт.
    Она не выброшена: прогон вида ``pytest /дерево/spa_core/tests`` из чужого каталога
    ею видно, а каталогом — нет. Склеить две оси значило бы выдать «произносит» за
    «работает».

    Свой процесс из ответа НЕ ВЫЧИТАЕТСЯ — это было бы суждением о том, чей прогон
    считать настоящим. Он НАЗВАН полем ``process_self`` / ``naming_self``.
    """
    snap = snapshot or {}
    cwd_probe = snap.get("cwd") or {}
    argv_probe = snap.get("argv") or {}
    base = tree.rstrip("/")
    prefix = base + "/"
    self_pid = snap.get("self_pid")

    # ось ВЕРДИКТА — рабочий каталог
    if not cwd_probe.get("ok"):
        verdict = {"process": "unmeasured",
                   "process_reason": (cwd_probe.get("reason")
                                      or "снимок рабочих каталогов не снят"),
                   "process_pids": [], "process_self": False,
                   "process_commands": []}
    else:
        pids = sorted({pid for pid, cwd in cwd_probe["rows"]
                       if cwd == base or cwd.startswith(prefix)})
        if pids:
            # Род держателя НАЗЫВАЕТСЯ, и это не украшение. Замер ADR-938: все 54
            # живых держателя трёх деревьев `_run` оказались безголовым Chrome, ни
            # один — прогоном. «Дерево держит живой процесс» ⇒ «прогон идёт» НЕ
            # СЛЕДУЕТ, и без имени команды читатель вывел бы именно это.
            if argv_probe.get("ok"):
                names = {pid: command for pid, command in argv_probe["rows"]}
                commands = [f"{pid}: {names.get(pid, 'команды нет в снимке')[:120]}"
                            for pid in pids[:4]]
            else:
                commands = [f"{pid}: команда НЕ ИЗМЕРЕНА "
                            f"({argv_probe.get('reason')})" for pid in pids[:4]]
            verdict = {"process": "live", "process_reason": None,
                       "process_pids": pids, "process_self": self_pid in pids,
                       "process_commands": commands}
        else:
            verdict = {"process": "none",
                       "process_reason": ("рабочий каталог ни одного процесса не внутри "
                                          "дерева; «дерева никто не держит» ≠ "
                                          "«прогона не было»"),
                       "process_pids": [], "process_self": False,
                       "process_commands": []}

    # ось КАНДИДАТОВ — командная строка. НАЗЫВАЕТ и НЕ СУДИТ.
    if not argv_probe.get("ok"):
        naming = {"naming": "unmeasured",
                  "naming_reason": (argv_probe.get("reason")
                                    or "снимок командных строк не снят"),
                  "naming_pids": [], "naming_self": False, "naming_examples": []}
    else:
        hits = {pid: command for pid, command in argv_probe["rows"]
                if _names_tree(command, base)}
        if hits:
            naming = {"naming": "named",
                      "naming_reason": ("командная строка НАЗЫВАЕТ дерево — это КАНДИДАТ, "
                                        "не вердикт: меряющий процесс произносит имя "
                                        "дерева, работая в другом"),
                      "naming_pids": sorted(hits),
                      "naming_self": self_pid in hits,
                      "naming_examples": [hits[pid][:160] for pid in sorted(hits)[:2]]}
        else:
            naming = {"naming": "none", "naming_reason": None,
                      "naming_pids": [], "naming_self": False, "naming_examples": []}
    return {**verdict, **naming}


def _git_status(tree: Path, timeout: float = 60.0) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "status", "--porcelain"], cwd=str(tree),
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 99, f"{exc}"
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def census(repo_root: str | Path = PROJECT_ROOT, *,
           journal: Optional[str | Path] = None,
           trees: Optional[Sequence[str]] = None,
           status_probe=None, read_text=None, mtime_probe=None,
           process_snapshot_probe=None,
           now: Optional[datetime] = None) -> dict:
    """Перепись. Только ЧИТАЕТ.

    Поверхность деревьев берётся у ``orphan_sweep.discover_trees`` — ОДНА дверь на вопрос
    «какие деревья существуют». Своя копия обхода означала бы второе объявление поверхности,
    расходящееся с первым молча (урок ADR-930).
    """
    moment = now or datetime.now(timezone.utc)
    repo = Path(repo_root).resolve()
    status = status_probe or _git_status
    probe = mtime_probe or _mtime

    if trees is None:
        found = sweep_mod.discover_trees(repo)
        tree_list = [str(t) for t in found.get("trees") or []]
        surface_reason = None if tree_list else "discover_trees не назвал ни одного дерева"
    else:
        tree_list, surface_reason = [str(t) for t in trees], None

    entries, journal_why = None, None
    journal_path = Path(journal) if journal else repo / "data" / "session_changes.jsonl"
    raw, why = _read_text(journal_path)
    if raw is None:
        journal_why = why
    else:
        entries = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Снимок таблицы процессов — ОДИН на всю перепись (см. `process_snapshot`).
    snapshot = (process_snapshot_probe or process_snapshot)()

    rows: list[dict] = []
    for tree in sorted(tree_list):
        path = Path(tree)
        code, out = status(path)
        wt = sweep_mod.worktree_door(code, out, tree=path, mtime_probe=probe)
        row: dict[str, Any] = {"tree": tree, **wt}
        if wt.get("worktree") != "carries":
            rows.append(row)
            continue
        row.update(run_door(path, read_text=read_text, mtime_probe=probe))
        row.update(scope_door(path, read_text=read_text))
        row.update(order_door(probe(path / NODEIDS), wt.get("worktree_newest")))
        row.update(intent_door(tree, entries))
        row.update(process_door(tree, snapshot))
        row["work_newest"] = _stamp(wt.get("worktree_newest"))
        rows.append(row)

    carrying = [r for r in rows if r.get("worktree") == "carries"]
    subject = [r for r in carrying if r.get("run") in ("green", "red")]
    doc = {
        "generated_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo_root": str(repo),
        "surface": {"trees": len(tree_list), "reason": surface_reason},
        "journal": {"path": str(journal_path), "entries":
                    (len(entries) if entries is not None else None),
                    "reason": journal_why},
        "tally": {
            "carries": len(carrying),
            "clean": sum(1 for r in rows if r.get("worktree") == "clean"),
            "worktree_unmeasured": sum(1 for r in rows
                                       if r.get("worktree") == "unmeasured"),
            "run": {k: sum(1 for r in carrying if r.get("run") == k)
                    for k in RUN_OUTCOMES},
            "order": {k: sum(1 for r in subject if r.get("order") == k)
                      for k in ORDER_OUTCOMES},
            "intent": {k: sum(1 for r in subject if r.get("intent") == k)
                       for k in INTENT_OUTCOMES},
            # ПЕРЕКРЁСТНАЯ клетка и есть предмет заказа. «Зелёный прогон без доставки»
            # распадается на ДВА разных утверждения, и склеивать их нельзя:
            #   green × run_covers_work   — прогон измерил ИМЕННО те байты, что не уехали;
            #   green × run_predates_work — зелено было о ПРЕДЫДУЩЕЙ редакции, а последняя
            #                               правка легла ПОСЛЕ прогона и не мерена ничем.
            # Второе «зелёным прогоном недоставленной работы» НЕ является.
            "process": {k: sum(1 for r in carrying if r.get("process") == k)
                        for k in PROCESS_OUTCOMES},
            # Заказ G926 п. 3 и есть ЭТА клетка: «следа прогона нет» разводится на
            # «прогон идёт ПРЯМО СЕЙЧАС» (измеримо) и «сейчас не идёт» (а был ли —
            # этой дверью не измеряется вовсе).
            "trace_absent_by_process": {
                k: sum(1 for r in carrying
                       if r.get("run") == "unmeasured" and r.get("process") == k)
                for k in PROCESS_OUTCOMES},
            "naming": {k: sum(1 for r in carrying if r.get("naming") == k)
                       for k in NAMING_OUTCOMES},
            "cross": {f"{run}×{order}":
                      sum(1 for r in subject
                          if r.get("run") == run and r.get("order") == order)
                      for run in ("green", "red")
                      for order in ORDER_OUTCOMES},
        },
        "process_probes": {
            "argv": {"ok": snapshot["argv"].get("ok"),
                     "reason": snapshot["argv"].get("reason"),
                     "rows": len(snapshot["argv"].get("rows") or [])},
            "cwd": {"ok": snapshot["cwd"].get("ok"),
                    "reason": snapshot["cwd"].get("reason"),
                    "rows": len(snapshot["cwd"].get("rows") or [])},
            "self_pid": snapshot.get("self_pid"),
        },
        "rows": rows,
        # ⚠️ ИМЯ `subject` принадлежит контракту ADR-937 и `exit_code`: это «деревья с
        # ЗАВЕРШЁННЫМ прогоном», то есть знаменатель, а НЕ предмет заказа. Замер 07.11:
        # их 63 против 10 у предмета. Переименовать его тихо нельзя — на нём стоит код
        # возврата; поэтому предмет получает СВОЁ имя ниже, а расхождение названо вслух
        # (ADR-938). Читатель, взявший `subject` за предмет, получил бы 63 вместо 10.
        "subject": sorted((r["tree"] for r in subject)),
        # ПРЕДМЕТ ЗАКАЗА со СВОИМИ ЧЛЕНАМИ. Число без перечня перемерить нельзя: оба
        # наблюдения #1054 опубликовали счёт (11 и 11) без имён, и расхождение
        # 11 → 10 у наблюдения #1055 не удалось отнести НИ К ОДНОМУ дереву (G926 п. 2).
        "order_subject": sorted((r["tree"] for r in subject
                                 if r.get("run") == "green"
                                 and r.get("order") == "run_covers_work")),
        # Члены предмета печатаются ПОИМЁННО: число без своих членов перемерить нельзя —
        # расхождение «11 против 10» между наблюдениями #1054 и #1055 не удалось отнести
        # ни к одному дереву ровно потому, что первое наблюдение опубликовало счёт без
        # перечня (заказ G926 п. 2, ADR-938).
        "trace_absent": sorted((r["tree"] for r in carrying
                                if r.get("run") == "unmeasured")),
        "trace_absent_live": sorted((r["tree"] for r in carrying
                                     if r.get("run") == "unmeasured"
                                     and r.get("process") == "live")),
    }
    return doc


def format_report(doc: dict, max_rows: int = 12) -> list[str]:
    out: list[str] = []
    s = doc["surface"]
    t = doc["tally"]
    if s.get("reason"):
        out.append(f"⚠️ НЕ ИЗМЕРЕНО: {s['reason']}")
        return out
    out.append(f"след прогона у недоставленной работы: деревьев {s['trees']}, "
               f"несут незакоммиченное {t['carries']}, чисто {t['clean']}, "
               f"ось не измерена {t['worktree_unmeasured']}")
    j = doc["journal"]
    out.append(f"   журнал объявлений: "
               + (f"записей {j['entries']}" if j["entries"] is not None
                  else f"НЕ ПРОЧИТАН ({j['reason']})"))
    r = t["run"]
    out.append(f"   завершённый прогон: зелёный {r['green']} · красный {r['red']} · "
               f"НЕ ИЗМЕРЕНО {r['unmeasured']} "
               f"(убитый прогон кэша не пишет — «следа нет» покрывает два мира)")
    o = t["order"]
    out.append(f"   порядок: прогон ПОКРЫВАЕТ последний байт {o['run_covers_work']} · "
               f"прогон СТАРШЕ последнего байта {o['run_predates_work']} · "
               f"НЕ ИЗМЕРЕНО {o['unmeasured']}")
    c = t["cross"]
    out.append(f"   ПРЕДМЕТ ЗАКАЗА (зелёный прогон ИМЕННО по недоставленным байтам): "
               f"{c['green×run_covers_work']}")
    out.append(f"      зелено, но прогон СТАРШЕ последней правки (мерено НЕ то, что "
               f"не уехало): {c['green×run_predates_work']}")
    pr = doc.get("process_probes") or {}
    refused = [f"{name}: {(pr.get(name) or {}).get('reason')}"
               for name in ("argv", "cwd") if not (pr.get(name) or {}).get("ok")]
    pd = t.get("process") or {}
    nm = t.get("naming") or {}
    out.append(f"   держит ли дерево ЖИВОЙ ПРОЦЕСС (вердикт — РАБОЧИЙ КАТАЛОГ): "
               f"держат {pd.get('live')} · никто не держит {pd.get('none')} · "
               f"НЕ ИЗМЕРЕНО {pd.get('unmeasured')} — «держит» НЕ значит «идёт прогон», "
               f"род держателя печатается строкой дерева")
    out.append(f"      ось КАНДИДАТОВ (командная строка НАЗЫВАЕТ дерево, вердиктом НЕ "
               f"является): названо {nm.get('named')} · не названо {nm.get('none')} · "
               f"НЕ ИЗМЕРЕНО {nm.get('unmeasured')} — меряющий процесс произносит имя "
               f"дерева, работая в другом (замер ADR-938)")
    for line in refused:
        out.append(f"      ⚠️ проба не ответила — {line}")
    ta = t.get("trace_absent_by_process") or {}
    out.append(f"   СЛЕДА ПРОГОНА НЕТ ({t['run']['unmeasured']}) разводится: "
               f"дерево ДЕРЖИТ живой процесс {ta.get('live')} · никто не держит "
               f"{ta.get('none')} · НЕ ИЗМЕРЕНО {ta.get('unmeasured')}")
    out.append("      «никто не держит» НЕ значит «прогона не было»: убитый час назад "
               "прогон не оставил ни кэша, ни процесса, и этой дверью не измеряется")
    by_tree = {r["tree"]: r for r in doc.get("rows") or []}
    for tree in (doc.get("trace_absent_live") or [])[:6]:
        out.append(f"      🏃 {tree}")
        for line in ((by_tree.get(tree) or {}).get("process_commands") or [])[:3]:
            out.append(f"         держатель {line}")
    i = t["intent"]
    out.append(f"   объявленный отказ доставить: ОБЪЯВЛЕН {i['declined']} · "
               f"НЕ ОБЪЯВЛЕН {i['undeclared']} · НЕ ИЗМЕРЕНО {i['unmeasured']} "
               f"(«умерла» исходом не является)")
    shown = 0
    for row in sorted((x for x in doc["rows"] if x.get("run") in ("green", "red")),
                      key=lambda x: x.get("run_finished") or "", reverse=True):
        if shown >= max_rows:
            break
        shown += 1
        mark = "🟢" if row["run"] == "green" else "🔴"
        out.append(f"   {mark} {row['tree']}")
        out.append(f"      прогон завершён {row['run_finished']} · собрано имён "
                   f"{row.get('scope_collected')} · падений {row.get('run_failed')}"
                   + (f" ({', '.join(row['run_failed_examples'])})"
                      if row.get("run_failed_examples") else ""))
        out.append(f"      последний байт работы {row.get('work_newest')} · "
                   f"путей вне data/ {row.get('worktree_outside')} · "
                   f"порядок {row['order']}"
                   + (f" (разрыв {row['order_gap_s']} с)"
                      if row.get("order_gap_s") is not None else "")
                   + (f" — {row['order_reason']}" if row.get("order_reason") else ""))
        out.append(f"      держат дерево: {row.get('process')}"
                   + (f" (pid {', '.join(str(x) for x in row.get('process_pids') or [])}"
                      + (", среди них СВОЙ" if row.get("process_self") else "") + ")"
                      if row.get("process_pids") else "")
                   + (f" — {row['process_reason']}" if row.get("process_reason") else "")
                   + f" · имя дерева произносят: {row.get('naming')}"
                   + (f" ({len(row.get('naming_pids') or [])} процесс(а/ов)"
                      + (", среди них СВОЙ" if row.get("naming_self") else "") + ")"
                      if row.get("naming_pids") else ""))
        for line in (row.get("process_commands") or [])[:3]:
            out.append(f"         держатель {line}")
        out.append(f"      отказ доставить: {row['intent']}"
                   + (f" — {row['intent_reason']}" if row.get("intent_reason") else "")
                   + (f" · объявляли: {', '.join(row['intent_sessions'][:4])}"
                      if row.get("intent_sessions") else ""))
    extra = len([x for x in doc["rows"] if x.get("run") in ("green", "red")]) - shown
    if extra > 0:
        out.append(f"   …и ещё {extra} дерев(о/а) с завершённым прогоном")
    out.append("   прибор только ЧИТАЕТ: ни одного байта ни в одно дерево не записано")
    return out


def exit_code(doc: dict) -> int:
    if doc["surface"].get("reason"):
        return 2
    return 1 if doc["subject"] else 0
