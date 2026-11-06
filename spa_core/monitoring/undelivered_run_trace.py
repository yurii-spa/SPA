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
            "cross": {f"{run}×{order}":
                      sum(1 for r in subject
                          if r.get("run") == run and r.get("order") == order)
                      for run in ("green", "red")
                      for order in ORDER_OUTCOMES},
        },
        "rows": rows,
        "subject": sorted((r["tree"] for r in subject)),
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
