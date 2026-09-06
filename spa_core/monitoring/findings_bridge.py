"""findings_bridge.py — мост «находка → карточка» (ADR-066, Фаза 3, C2).

Замыкает петлю: находки сторожа архитектуры и gap-анализа ПРЕВРАЩАЮТСЯ в
карточки бэклога сами, без надежды на то, что кто-то вручную прочитает отчёт.

Дисциплина против спама (каждое правило — против конкретного отказа):
  dedup        одна ОТКРЫТАЯ карточка на ключ находки — и не больше;
  гистерезис   WARN становится карточкой только с REQUIRED_SIGHTINGS-го
               подряд наблюдения (флаппинг не рождает мусор); CRITICAL — сразу;
  rate-limit   ≤ MAX_CARDS_PER_DAY карточек/сутки; излишек — в отчёт с
               пометкой deferred, ГРОМКО, не молча (правило «no silent caps»);
  авто-закрытие исчезнувшая находка закрывает свою карточку, но ТОЛЬКО после
               REQUIRED_ABSENCES прогонов подряд без неё (молчание ОДНОГО
               прогона не есть починка — иначе находка возвращается, и это
               измерено) и ТОЛЬКО если карточка НЕТРОНУТА: `new` для inbox, `needs-owner` без следа
               владельца для owner-decision (цикл #172 — раньше правило знало
               лишь `new`, и вопрос владельца не закрывался никогда); взятую
               в работу не трогаем. Закрытие уведомлённой карточки уходит
               владельцу ОТЗЫВОМ — снимать вопрос молча нельзя;
  эскалация    WARN→CRITICAL по тому же ключу = новая карточка needs-owner.

Маршрутизация: CRITICAL → owner-decision (формат §2.4, 4 секции, по-русски)
+ Telegram-notify; WARN → inbox (agent-backlog). Всё — ТОЛЬКО через
scripts/orchestrator_queue.py (единственный мутационный API очереди).
Инвариант 14 соблюдён по построению: мост никогда не ставит owner-done.

Запуск: агент com.spa.decision_loop (каждые 6ч): сначала пересчёт
house_view_gap, затем мост. Состояние: data/findings_bridge_state.json;
отчёт: data/findings_bridge_report.json. LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT, subject_inputs

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: Объявление, а не вывод из кода — вывести производителя разбором нельзя
#: (замер 28.08: верно 13 из 27, одна ошибка, семья harness недостижима).
#: Сверяется с фактической записью — spa_core/monitoring/artifact_contract.py.
PRODUCES = (
    "data/adapter_feed_divergence.json",
    "data/capital_evidence_coverage.json",
    "data/pool_identity_collision.json",
    "data/decision_reproducibility.json",
    "data/evidence_staleness.json",
    "data/apy_composition.json",
    "data/findings_bridge_report.json",
    "data/house_view_gap.json",
    "data/investment_os/outcomes.jsonl",
    "data/loop_health.json",
    "data/loop_retro.json",
)

# Запись есть, продуктом не является (ADR-154): собственная память моста между
# прогонами (что уже видено, что уже стало карточкой). Её потребитель — сам мост
# на следующем запуске, а не читатель продукта; в коде читателей ноль (замер 29.08).
INTERNAL_WRITES = (
    "data/findings_bridge_state.json",
)

STATE_REL = os.path.join("data", "findings_bridge_state.json")
REPORT_REL = os.path.join("data", "findings_bridge_report.json")

#: ПРЕДМЕТ вердикта моста об отказе доставки — не карточки, а РЕШАТЕЛЬ: именно
#: `card_delivery` решает «переносим правку на origin» или «перенести нечем,
#: сделайте руками». Карточки — живое состояние, их в провенанс объявлять
#: нельзя (комментарий `_SUBJECT` в `scripts/consume_office_reports.py`: тогда
#: находку давал бы каждый прогон); решатель — код, и он меняется редко.
#:
#: Замер цикла #471 (03.09), ADR-220. Отчёт 11:46:08Z объявил PARTIAL и звал
#: перенести ВРУЧНУЮ две карточки `…gas-price-agent…`; в 16:04:31Z коммит
#: 3425bd28 (ADR-219, цикл #470) научил `rebase_onto_ahead_origin` везти ровно
#: этот случай. Перемерено в 17:2xZ: `rebase_card()` строит кандидата для ОБЕИХ.
#: Обязательный шаг 0-офис печатал требование ручной работы 4.3 ч после того,
#: как машина научилась делать её сама, — и отличить «нечем» от «уже есть чем»
#: читателю было НЕЧЕМ: у отчёта есть возраст, но возраст меряет, давно ли
#: ходил мост, а не сменился ли под ним тот, кто выносит вердикт.
DECIDER_REL = "spa_core/monitoring/card_delivery.py"

REQUIRED_SIGHTINGS = 2
#: Столько прогонов ПОДРЯД находка обязана отсутствовать, чтобы её карточка
#: закрылась. Зеркало REQUIRED_SIGHTINGS: рождение карточки уже требовало
#: повтора, а закрытие обходилось ОДНИМ молчаливым прогоном — асимметрия и
#: была механизмом рецидива (замер loop_health 28.08: 4 находки вернулись
#: после закрытия, ВСЕ из класса `gap:opportunity_unnamed`; условие при этом
#: не менялось — менялось лишь то, попал ли протокол в top_opportunities
#: конкретного суточного снимка офиса). Молчание одного прогона — не починка.
REQUIRED_ABSENCES = 2
MAX_CARDS_PER_DAY = 5
SUBPROC_TIMEOUT = 60

# След владельца во frontmatter (кнопки ADR-069). Есть хоть один ⇒ карточку
# владелец уже видел и ответил — авто-закрытие к ней не применяется.
OWNER_TRACE_FIELDS = ("owner_choice", "owner_answered_at", "owner_answered_by")

# Статусы, в которых карточка моста считается ОТКРЫТОЙ (её находка — carded).
# `needs-owner` здесь обязателен: без него потеря состояния приводила бы к
# ДУБЛЮ вопроса владельцу — зеркало того же дефекта, что в авто-закрытии.
OPEN_CARD_STATUSES = ("new", "in-progress", "needs-owner")


# ── сбор находок из источников ───────────────────────────────────────────────

def collect_findings(root: str = REPO_ROOT) -> tuple[list[dict], list[str]]:
    """[{key, severity, message, source}], [источники, которые не прочитались]."""
    findings: list[dict] = []
    unread: list[str] = []

    conf_rel = os.path.join("data", "architecture_conformance.json")
    try:
        conf = json.load(open(os.path.join(root, conf_rel)))
        for f in (conf.get("findings") or []):
            findings.append({"key": f["key"], "severity": f["severity"],
                             "message": f["message"], "source": "architecture_conformance"})
    except Exception:
        unread.append(conf_rel)

    gap_rel = os.path.join("data", "house_view_gap.json")
    try:
        gap = json.load(open(os.path.join(root, gap_rel)))
        for g in (gap.get("gaps") or []):
            if g.get("severity") in ("WARN", "CRITICAL"):
                findings.append({"key": g["key"], "severity": g["severity"],
                                 "message": g["message"], "source": "house_view_gap"})
    except Exception:
        unread.append(gap_rel)

    # Фаза 4: выводы еженедельного ретро — третий источник. Рекомендация не
    # имеет права остаться в отчёте, который никто не обязан открыть.
    retro_rel = os.path.join("data", "loop_retro.json")
    try:
        retro = json.load(open(os.path.join(root, retro_rel)))
        for f in (retro.get("findings") or []):
            if f.get("severity") in ("WARN", "CRITICAL"):
                findings.append({"key": f["key"], "severity": f["severity"],
                                 "message": f["message"], "source": "loop_retro"})
    except Exception:
        unread.append(retro_rel)

    return findings, unread


# ── карточки через единственный мутационный API ──────────────────────────────

def _queue(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, os.path.join(root, "scripts", "orchestrator_queue.py"), *args],
        capture_output=True, text=True, timeout=SUBPROC_TIMEOUT, cwd=root)


def create_card(root: str, finding: dict) -> str | None:
    """Создать карточку; вернуть путь к файлу карточки или None."""
    critical = finding["severity"] == "CRITICAL"
    if critical:
        body = (
            "## Что случилось и почему это важно\n"
            f"Сторож петли ({finding['source']}) нашёл КРИТИЧНОЕ расхождение с архитектурой:\n"
            f"{finding['message']}\n\n"
            "## Что от тебя нужно\n"
            "Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем "
            "решение в манифесте или ADR). Рекомендация агента — чинить: критичные "
            "находки этого класса уже стоили нам молчаливых отказов.\n\n"
            "## Как понять, что готово\n"
            "Находка исчезает из data/architecture_conformance.json при следующем прогоне.\n\n"
            "## Что будет после\n"
            "Мост сам закроет эту карточку, когда находка исчезнет; сторож продолжит "
            "следить, чтобы она не вернулась.\n\n"
            f"_finding_key: `{finding['key']}` · источник: {finding['source']} · ADR-066_\n")
        args = ["create", "--type", "owner-decision", "--status", "needs-owner",
                "--source", "nimbalyst",
                "--title", f"Критичная находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    else:
        body = (f"Находка петли ADR-066 ({finding['source']}, WARN, подтверждена "
                f"{REQUIRED_SIGHTINGS} прогонами подряд):\n\n{finding['message']}\n\n"
                f"Сделано = находка исчезает из отчёта источника при следующем прогоне "
                f"(мост закроет карточку сам).\n\n"
                f"_finding_key: `{finding['key']}` · ADR-066_\n")
        args = ["create", "--type", "inbox", "--status", "new", "--source", "nimbalyst",
                "--title", f"Находка петли: {finding['message'][:70]}",
                "--body", body, "--field", f"finding_key={finding['key']}"]
    try:
        r = _queue(root, *args)
        if r.returncode != 0:
            return None
        path = (r.stdout or "").strip().splitlines()[-1].strip()
        return path if path.endswith(".md") else None
    except Exception:
        return None


def notify_card(root: str, card_path: str) -> bool:
    try:
        return _queue(root, "notify", card_path).returncode == 0
    except Exception:
        return False


def _frontmatter(card_path: str) -> dict:
    """Поля frontmatter карточки (только внутри ограды `---`, без вложенных блоков).

    Читаем именно ограду, а не «первую строку с двоеточием»: тело карточки моста
    заканчивается строкой `_finding_key: ...`, и наивный разбор принял бы её за поле.
    """
    fields: dict = {}
    try:
        with open(card_path, encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return fields
            for line in f:
                if line.strip() == "---":
                    break
                if line.startswith((" ", "\t", "-")):  # вложенный блок (trackerStatus)
                    continue
                if ":" in line:
                    k, v = line.split(":", 1)
                    fields[k.strip()] = v.strip().strip("`'\"")
    except Exception:
        pass
    return fields


def card_status(card_path: str) -> str | None:
    return _frontmatter(card_path).get("status")


def card_is_untouched(card_path: str) -> bool:
    """Карточку моста никто не брал ⇒ исчезнувшая находка вправе её закрыть.

    Два типа карточек — два разных «нетронута», и знать надо ОБА (цикл #172):

    * `inbox` рождается `new` — нетронута, пока `new`;
    * `owner-decision` рождается `needs-owner` — то есть под старым правилом
      («закрываем только `new`») CRITICAL-карточка не закрывалась НИКОГДА, хотя
      её собственный текст обещает владельцу «мост закроет сам». Ложная тревога
      оставалась вечным вопросом в очереди владельца.

    След владельца во frontmatter (кнопки ADR-069: `owner_choice` /
    `owner_answered_at` / `owner_answered_by`) = вопрос УЖЕ увидели и ответили —
    такую не трогаем, как и любую взятую в работу (`in-progress`/`ingested`/
    `owner-done`/`done`). Инвариант #14 не задет: закрытие идёт в `done`,
    отвечать за владельца мост по-прежнему не смеет.
    """
    fm = _frontmatter(card_path)
    status = fm.get("status")
    if status == "new":
        return True
    if status == "needs-owner":
        return not any(fm.get(k) for k in OWNER_TRACE_FIELDS)
    return False


def close_card(root: str, card_path: str) -> bool:
    """Закрыть ТОЛЬКО нетронутую карточку моста. Взятую в работу не трогаем."""
    if not card_is_untouched(card_path):
        return False
    try:
        return _queue(root, "set-status", card_path, "done").returncode == 0
    except Exception:
        return False


def retract_card(root: str, card_path: str) -> bool:
    """Дописать владельцу, что вопрос снят: находка исчезла, тревога была ложной.

    Молчаливое снятие вопроса, о котором владельцу УЖЕ написали, — отдельный дефект,
    а не решение: в чате остаётся висеть «нужно решение», на которое нельзя ответить.
    Заодно гасим кнопки этой карточки (ADR-069), чтобы нажатие через три дня не
    записало «ответ владельца» в уже закрытую карточку.
    """
    try:
        from spa_core.owner_queue.notify import notify_card_withdrawn
        notify_card_withdrawn(card_path)
        return True
    except Exception:  # noqa: BLE001 — отзыв не смеет уронить мост
        return False


# ── ядро моста ───────────────────────────────────────────────────────────────

def _load_state(root: str) -> dict:
    try:
        return json.load(open(os.path.join(root, STATE_REL)))
    except Exception:
        return {"findings": {}, "daily": {}}


def _reconcile_with_tracker(root: str, st_findings: dict) -> int:
    """Самовосстановление состояния из РЕАЛЬНОСТИ (инцидент 2026-08-05 23:55:
    findings_bridge_state.json исчез между прогонами — виновник не установлен,
    файл нетрекаемый). Карточки моста несут `finding_key:` во frontmatter —
    открытая карточка на диске ⇒ находка carded, что бы ни говорило состояние.
    Предотвращает дубли карточек после ЛЮБОЙ потери состояния. Возвращает
    число восстановленных записей."""
    tdir = os.path.join(root, "nimbalyst-local", "tracker")
    if not os.path.isdir(tdir):
        return 0
    restored = 0
    for fn in sorted(os.listdir(tdir)):
        if not fn.endswith(".md"):
            continue
        path = os.path.join(tdir, fn)
        fk = status = None
        try:
            with open(path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if line.startswith("finding_key:"):
                        fk = line.split(":", 1)[1].strip().strip("`'\"")
                    elif line.startswith("status:"):
                        status = line.split(":", 1)[1].strip()
                    if i > 40:
                        break
        except Exception:
            continue
        if not fk or status not in OPEN_CARD_STATUSES:
            continue
        entry = st_findings.get(fk)
        if entry is None or (entry.get("status") != "carded"):
            now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
            prev = entry or {}
            # Тяжесть восстанавливаем ИЗ ТИПА карточки, а не из умолчания «WARN»:
            # `needs-owner` рождает только CRITICAL, а запись с чужой тяжестью на
            # следующем же прогоне сработала бы как эскалация WARN→CRITICAL и
            # создала второй вопрос владельцу — тот самый дубль, от которого
            # это восстановление и защищает.
            owner_card = status == "needs-owner"
            severity = "CRITICAL" if owner_card else prev.get("severity", "WARN")
            st_findings[fk] = {"first_seen": prev.get("first_seen", now_iso),
                               "seen_count": int(prev.get("seen_count", 0)),
                               "severity": severity,
                               # уведомление уже ушло вместе с рождением карточки —
                               # значит и отзыв при закрытии обязан уйти
                               "notified": bool(prev.get("notified", owner_card)),
                               "card": path, "status": "carded",
                               "carded_at": prev.get("carded_at", now_iso),
                               "recurrences": int(prev.get("recurrences", 0)),
                               "reconciled": True}
            restored += 1
    return restored


def _deliver_touched(root: str, created: list, closed: list,
                     now: dt.datetime, deliver=None) -> dict:
    """Довезти до origin карточки, которых мост за прогон КОСНУЛСЯ.

    Закрытые везём наравне с созданными: карточка, закрытая только в прод-дереве,
    остаётся на origin открытой — очередь показывает работу, которой нет
    (тот же класс, что #147).

    Список здесь — ТОЛЬКО тронутое за прогон, и это НЕ полный ответ на вопрос
    «что должно оказаться на origin»: провалившаяся доставка тронутой в следующем
    прогоне уже не будет (карточка помечена `closed` в состоянии моста), а значит
    сюда не попадёт никогда. Повтор живёт этажом ниже — в `card_delivery.deliver`,
    который сам добавляет к пачке свой ДОЛГ (ADR-081). Заводить повтор здесь
    было бы починкой одного вызывающего из нескольких.
    """
    paths = [c["card"] for c in created if c.get("card")]
    paths += [c["card"] for c in closed if c.get("card")]
    try:
        fn = deliver
        if fn is None:
            from spa_core.monitoring.card_delivery import deliver as fn
        return fn(paths, root=root, now=now)
    except Exception as e:  # noqa: BLE001 — доставка не смеет уронить мост,
        # но «не измерено» обязано быть НАЗВАНО, а не выглядеть успехом.
        return {"status": "UNCHECKED", "attempted": paths, "delivered": [],
                "reason": f"доставка не измерена: {type(e).__name__}: {e}",
                "generated_at": now.isoformat()}


def _deliver_owner_answers(root: str, now: dt.datetime, run_answers=None) -> dict:
    """Довезти до origin СЛЕД решения владельца (ADR-086).

    Почему это делает мост, а не отдельный агент: сторожу нужен регулярный
    прогон из ПРОД-дерева (только туда бот пишет ответ) — а это ровно то, чем
    мост уже является. Новый агент означал бы новую точку входа, новый plist и
    новый класс «доставлен, но не включён» (капкан #232), тогда как здесь
    проводка появляется одной строкой в уже работающем такте (6 ч).

    Список сторож строит ЗАНОВО каждый прогон, поэтому долг ему не нужен:
    не доехало — на следующем прогоне находка та же и поедет снова.
    """
    try:
        fn = run_answers
        if fn is None:
            from spa_core.monitoring.owner_answer_delivery import run as fn
        return fn(root=root, now=now)
    except Exception as e:  # noqa: BLE001 — сторож не смеет уронить мост,
        # но «не измерено» обязано быть НАЗВАНО, а не выглядеть успехом.
        return {"status": "UNCHECKED", "delivered": [], "pending": [],
                "reason": f"доставка следа решения владельца не измерена: "
                          f"{type(e).__name__}: {e}",
                "generated_at": now.isoformat()}


def run_bridge(root: str = REPO_ROOT, now: dt.datetime | None = None,
               create=create_card, close=close_card, notify=notify_card,
               deliver=None, retract=retract_card, deliver_answers=None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    state = _load_state(root)
    findings, unread = collect_findings(root)
    current = {f["key"]: f for f in findings}
    st_findings: dict = state.setdefault("findings", {})
    reconciled = _reconcile_with_tracker(root, st_findings)
    daily: dict = state.setdefault("daily", {})
    created_today = int(daily.get(today, 0))

    created, deferred, closed, waiting, escalated = [], [], [], [], []
    closing: list[dict] = []
    withdrawn: list[dict] = []

    for key, f in sorted(current.items()):
        entry = st_findings.get(key)
        if entry is None:
            entry = st_findings[key] = {"first_seen": now.isoformat(), "seen_count": 0,
                                        "severity": f["severity"], "card": None,
                                        "status": "observed"}
        elif entry.get("status") in ("closed", "resolved_untouched"):
            # РЕЦИДИВ: закрытая находка вернулась. Без сброса статуса она никогда
            # больше не родила бы карточку (needs_card требует observed) — молчаливый
            # провал петли, найден при построении loop_health (Фаза 4).
            entry.update(status="observed", seen_count=0, card=None,
                         first_seen=now.isoformat(),
                         recurrences=int(entry.get("recurrences", 0)) + 1)
        entry["seen_count"] = int(entry.get("seen_count", 0)) + 1
        entry["last_seen"] = now.isoformat()
        # Находка на месте ⇒ счётчик отсутствий обнуляется: закрытия требует
        # РЯД молчаливых прогонов подряд, а не их сумма за всю историю.
        entry["absent_count"] = 0

        esc = (f["severity"] == "CRITICAL" and entry.get("severity") != "CRITICAL"
               and entry.get("status") == "carded")
        entry["severity"] = f["severity"]
        needs_card = (entry.get("status") == "observed"
                      and (f["severity"] == "CRITICAL"
                           or entry["seen_count"] >= REQUIRED_SIGHTINGS)) or esc

        if not needs_card:
            if entry.get("status") == "observed":
                waiting.append(key)
            continue
        if created_today >= MAX_CARDS_PER_DAY:
            deferred.append(key)  # ГРОМКО в отчёте — не молчаливое обрезание
            continue
        path = create(root, f)
        if path:
            created_today += 1
            entry.update(status="carded", card=path, carded_at=now.isoformat())
            created.append({"key": key, "card": path, "severity": f["severity"]})
            if esc:
                escalated.append(key)
            if f["severity"] == "CRITICAL":
                # Запоминаем сам ФАКТ уведомления: без него закрытие карточки
                # оставит владельца с вопросом в чате, на который уже никто
                # не ждёт ответа (см. retract_card).
                entry["notified"] = bool(notify(root, path))

    for key in sorted(set(st_findings) - set(current)):
        entry = st_findings[key]
        if entry.get("status") == "carded" and entry.get("card"):
            # Гистерезис закрытия — зеркало гистерезиса рождения. Источник,
            # промолчавший ОДИН раз, ничего не чинит: суточный снимок офиса
            # перетасовывает top_opportunities, находка выпадает из отчёта,
            # карточка закрывается, назавтра находка возвращается дословно.
            # Счётчик виден в отчёте — «жду подтверждения» не должно выглядеть
            # как «ничего не происходит».
            entry["absent_count"] = int(entry.get("absent_count", 0)) + 1
            if entry["absent_count"] < REQUIRED_ABSENCES:
                closing.append({"key": key, "card": entry["card"],
                                "absent_count": entry["absent_count"],
                                "required": REQUIRED_ABSENCES})
                continue
            if close(root, entry["card"]):
                entry["status"] = "closed"
                entry["closed_at"] = now.isoformat()
                closed.append({"key": key, "card": entry["card"]})
                if entry.get("notified"):
                    ok = bool(retract(root, entry["card"]))
                    entry["withdrawn"] = ok
                    withdrawn.append({"key": key, "card": entry["card"], "sent": ok})
            else:
                entry["status"] = "resolved_untouched"  # взята в работу — решит человек
                entry["resolved_at"] = now.isoformat()
        elif entry.get("status") == "observed":
            del st_findings[key]  # мигнула и исчезла — гистерезис отработал

    daily[today] = created_today
    # Последний метр: карточка, рождённая в прод-дереве, на origin не попадает
    # НИКОГДА (замер цикла #170: из рождённых в рантайме доставлено 0 из 4), а
    # `needs-owner` вне origin для очереди владельца не существует. Доставка —
    # отдельный модуль, исключений не бросает и о своём исходе не молчит.
    delivery = _deliver_touched(root, created, closed, now, deliver)
    report = {"generated_at": now.isoformat(), "adr": "ADR-066",
              # Провенанс предмета в ТОЙ ЖЕ форме, что у architecture_conformance
              # (одна функция на обоих) — читает `_subject_drift` шага 0-офис.
              "inputs": subject_inputs(root, (DECIDER_REL,)),
              "delivery": delivery,
              "owner_answer_delivery": _deliver_owner_answers(root, now, deliver_answers),
              "created": created, "deferred": deferred, "closed": closed,
              "withdrawn": withdrawn,
              "waiting_hysteresis": waiting, "escalated": escalated,
              # Карточки, у которых находка пропала, но ряд молчаливых прогонов
              # ещё не набран. Ждать МОЛЧА нельзя: иначе «мост ничего не сделал»
              # неотличимо от «мост ждёт подтверждения» — та же болезнь, что
              # лечится в rate-limit'е словом deferred.
              "closing_hysteresis": closing,
              "sources_unread": unread, "reconciled_from_tracker": reconciled,
              "open_cards": sum(1 for e in st_findings.values() if e.get("status") == "carded"),
              "rate_limit": {"max_per_day": MAX_CARDS_PER_DAY, "used_today": created_today}}

    from spa_core.utils.atomic import atomic_save
    atomic_save(state, os.path.join(root, STATE_REL))
    atomic_save(report, os.path.join(root, REPORT_REL))

    from spa_core.monitoring.consumption_receipts import write_receipt
    for rel in ("data/architecture_conformance.json", "data/house_view_gap.json"):
        if rel not in unread:
            write_receipt(rel, "findings_to_cards", root=root)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--skip-gap", action="store_true",
                    help="не пересчитывать house_view_gap перед мостом")
    args = ap.parse_args(argv)
    if not args.run:
        ap.print_help()
        return 0
    if not args.skip_gap:
        from spa_core.monitoring import house_view_gap
        house_view_gap.run(root=args.root)
    # Сверка двух артефактов адаптеров (D6 ADR-060): считается ЗДЕСЬ, а не отдельным
    # агентом — вопрос «сходятся ли фиды» родствен house_view_gap («сходится ли офис с
    # книгой») и стоит миллисекунды. Новый launchd-агент ради него означал бы деплой,
    # то есть решение владельца, и сторож ушёл бы в очередь вместо того, чтобы работать.
    # Мост находок его пока НЕ читает намеренно: потребитель — шаг 0-офис оркестратора,
    # то есть решение принимает сессия, а не авто-карточка (выбор числа для 20 % книги —
    # money-path, ADR-060 D6 ждёт владельца).
    try:
        from spa_core.monitoring import adapter_feed_divergence
        afd = adapter_feed_divergence.run(root=args.root)
        print(f"adapter_feed_divergence: {afd['overall']} "
              f"(critical={afd['counts']['critical']} warn={afd['counts']['warn']} "
              f"unchecked={afd['counts']['unchecked']}), "
              f"протоколов сверено {len(afd['compared_protocols'])}")
    except Exception as e:  # noqa: BLE001 — сверка фидов не смеет валить мост
        print(f"adapter_feed_divergence: пропущено ({e})")
    # Приёмка §5 ТЗ «Portfolio CIO» (ADR-226): доля КАПИТАЛА, ранжированного по
    # наблюдённым числам. Считается ЗДЕСЬ по той же причине, что и сверка фидов:
    # вопрос родствен («сходится ли то, чем мы объясняем книгу, с самой книгой»),
    # стоит миллисекунды, а отдельный launchd-агент означал бы деплой — решение
    # владельца, — и приёмка ушла бы в очередь вместо того, чтобы работать.
    # Мост находок его НЕ читает намеренно: потребитель — шаг 0-офис, то есть
    # решение принимает сессия. Автокарточка здесь была бы вредна: «не 100 %»
    # почти всегда означает работу над ФИДАМИ, у которой уже есть свои карточки.
    # §49 ТЗ «Portfolio CIO»: воспроизводим ли расчёт вообще. Считается ЗДЕСЬ по
    # той же причине, что соседи выше: отдельный launchd-агент означал бы деплой,
    # то есть решение владельца, и приёмка ушла бы в очередь вместо того, чтобы
    # работать. Цена ИЗМЕРЕНА на живом снимке 06.09 (544 файла): 3 прогона × 2
    # субъекта = 6 полных расчётов за 1.24 с — дороже соседних миллисекунд,
    # поэтому число прогонов держится минимальным (расхождение от соли хеша
    # видно на ЛЮБОЙ паре разных солей, сотни ему не нужны), а дословные 100
    # прогонов владельца доступны командой `--runs 100`.
    # Мост находок его НЕ читает намеренно: потребитель — шаг 0-офис, то есть
    # решение принимает сессия. Невоспроизводимый расчёт — это разбор архитектуры,
    # а не строка в автокарточке.
    try:
        from spa_core.monitoring import decision_reproducibility
        rep = decision_reproducibility.run(root=args.root)
        print(f"decision_reproducibility: {rep['overall']} "
              f"(critical={rep['counts']['critical']} warn={rep['counts']['warn']} "
              f"unchecked={rep['counts']['unchecked']}), прогонов {rep['runs']}")
    except Exception as e:  # noqa: BLE001 — замер воспроизводимости не смеет валить мост
        print(f"decision_reproducibility: пропущено ({e})")
    try:
        from spa_core.monitoring import capital_evidence_coverage
        cec = capital_evidence_coverage.run(root=args.root)
        agg = cec.get("all_books") or {}
        print(f"capital_evidence_coverage: {cec['verdict']} "
              f"(живой трек {cec['capital_coverage_pct']}% по наблюдению, "
              f"развёрнуто {cec['deployed_usd']}, "
              f"не измерено {(cec.get('usd') or {}).get('unmeasured')}; "
              f"ВСЕ книги {agg.get('coverage_pct')}% — "
              f"литералом {(agg.get('usd') or {}).get('literal')}, "
              f"книг померено {len(agg.get('books_measured') or [])}"
              f"/{len(agg.get('books_declared') or [])})")
    except Exception as e:  # noqa: BLE001 — приёмка не смеет валить мост
        print(f"capital_evidence_coverage: пропущено ({e})")
    # Состав ставки (ADR-230): доход операции или раздача токена. Считается тем же
    # прогоном и по той же причине, что сверка фидов: вопрос родствен («чем именно
    # платит пул, число которого ранжирует капитал»), стоит миллисекунды, а новый
    # launchd-агент означал бы деплой — решение владельца, — и сторож ушёл бы в
    # очередь вместо того, чтобы работать. Мост находок его НЕ читает намеренно:
    # считать ли эмиссию доходностью и какой из двух пулов есть `spark_susds` —
    # money-path, то есть решение владельца, а не авто-карточка.
    try:
        from spa_core.monitoring import apy_composition
        apyc = apy_composition.run(root=args.root)
        print(f"apy_composition: {apyc['overall']} "
              f"(critical={apyc['counts']['critical']} warn={apyc['counts']['warn']} "
              f"unchecked={apyc['counts']['unchecked']}), "
              f"ключей с наблюдением {len(apyc['observed_adapters'])}")
    except Exception as e:  # noqa: BLE001 — состав ставки не смеет валить мост
        print(f"apy_composition: пропущено ({e})")
    # Тождество пулов (гэп G1): считается тем же прогоном и по той же причине —
    # вопрос родствен сверке фидов, стоит миллисекунды, новый агент означал бы
    # деплой. Сторож только НАЗЫВАЕТ: снятие ключа с финансирования и правка
    # потолков — money-path, а значит решение владельца, не авто-карточка.
    try:
        from spa_core.monitoring import pool_identity_collision
        pic = pool_identity_collision.run(root=args.root)
        print(f"pool_identity_collision: {pic['overall']} "
              f"(critical={pic['counts']['critical']} warn={pic['counts']['warn']} "
              f"unchecked={pic['counts']['unchecked']}), "
              f"ключей сверено {len(pic['keys_compared'])}")
    except Exception as e:  # noqa: BLE001 — сверка тождества не смеет валить мост
        print(f"pool_identity_collision: пропущено ({e})")
    # Устаревание наблюдения (ADR-167): считается тем же прогоном и по той же
    # причине — вопрос родствен сверке фидов, стоит миллисекунды, новый агент
    # означал бы деплой. До #494 канал `governance/evidence_staleness.py` НИКТО
    # не спрашивал: решение владельца от 29.08 было принято, канал написан и
    # покрыт тестами, а объявленная им тревога по массовой слепоте прозвучать
    # не могла. Сторож только НАЗЫВАЕТ: MASS_BLINDNESS капитал не трогает
    # намеренно, а исполнение де-риска — money-path, то есть решение владельца
    # (карточка `agent-derisk-po-slepote-podklyuchit-k-rebalansu`), не авто-карточка.
    try:
        from spa_core.monitoring import evidence_staleness_monitor
        ev = evidence_staleness_monitor.run(root=args.root)
        c = ev["counts"]
        print(f"evidence_staleness: {ev['overall']} (действие {ev['action']}) — "
              f"свежих {c['fresh']} мягких {c['soft_stale']} жёстких {c['hard_stale']} "
              f"без часов {c['unknown_age']}; без наблюдения ${ev['usd']['unknown_age']:,.0f}")
    except Exception as e:  # noqa: BLE001 — лестница устаревания не смеет валить мост
        print(f"evidence_staleness: пропущено ({e})")
    # Цикл 3 ADR-067: правая половина hit-rate — строка исхода за сегодня
    # (идемпотентно по дате; 4 шанса в день догнать evidenced-бар).
    try:
        from spa_core.monitoring.outcomes_archive import append_daily_outcome
        oc = append_daily_outcome(root=args.root)
        print(f"outcomes: {'записан ' + oc['date'] if oc['appended'] else oc['reason']}")
    except Exception as e:  # noqa: BLE001 — архив исходов не смеет валить мост
        print(f"outcomes: пропущено ({e})")
    # Фаза 4: ретро — раз в неделю, самозапуск внутри 6ч-агента (без нового
    # launchd-агента); loop_health — каждый прогон (дёшево).
    try:
        from spa_core.monitoring import loop_retro
        from spa_core.monitoring.architecture_conformance import _parse_iso
        retro_path = os.path.join(args.root, loop_retro.RETRO_REL)
        prev_ts = None
        try:
            prev_ts = _parse_iso(json.load(open(retro_path)).get("generated_at"))
        except Exception:
            pass
        # Пересчёт при каждом прогоне старше 6ч (стоит миллисекунды): findings
        # ретро кормят мост, и недельная свежесть блокировала бы авто-закрытие
        # исчезнувшей находки на неделю (замечено на verdict_archive_lagging).
        # «Еженедельность» ретро — это КАДЕНЦИЯ ОТЧЁТА владельцу, не свежести.
        if prev_ts is None or (dt.datetime.now(dt.timezone.utc) - prev_ts).total_seconds() >= 6 * 3600:
            rr = loop_retro.run(root=args.root)
            print(f"loop_retro: кандидатов={len(rr['candidates'])} "
                  f"findings={len(rr['findings'])} unchecked={len(rr['unchecked'])}")
    except Exception as e:  # noqa: BLE001 — ретро не смеет валить мост
        print(f"loop_retro: пропущено ({e})")
    r = run_bridge(root=args.root)
    try:
        from spa_core.monitoring import loop_health
        loop_health.run(root=args.root)
    except Exception as e:  # noqa: BLE001
        print(f"loop_health: пропущено ({e})")
    print(f"findings_bridge: created={len(r['created'])} closed={len(r['closed'])} "
          f"deferred={len(r['deferred'])} waiting={len(r['waiting_hysteresis'])} "
          f"closing={len(r.get('closing_hysteresis') or [])} "
          f"open_cards={r['open_cards']} unread={r['sources_unread']}")
    for c in r["created"]:
        print(f"  + [{c['severity']}] {os.path.basename(c['card'])}")
    for c in r["closed"]:
        print(f"  ✓ закрыта {os.path.basename(c['card'])}")
    for c in r.get("withdrawn") or []:
        mark = "отзыв отправлен" if c["sent"] else "⚠️ ОТЗЫВ НЕ УШЁЛ (вопрос висит в чате)"
        print(f"  ↩︎ {os.path.basename(c['card'])}: {mark}")
    try:
        from spa_core.monitoring.card_delivery import render as render_delivery
        print("  " + render_delivery(r.get("delivery") or {}))
    except Exception as e:  # noqa: BLE001
        print(f"  card_delivery: ⚠️ квитанция не прочитана ({e})")
    for c in r.get("closing_hysteresis") or []:
        # Вслух: карточка ЖИВА намеренно, а не по недосмотру.
        print(f"  ⏳ {os.path.basename(c['card'])}: находка пропала "
              f"{c['absent_count']}/{c['required']} прогон(а) подряд — "
              f"закрытия ЖДЁМ (молчание одного прогона не есть починка)")
    if r["deferred"]:
        print(f"  ⚠️ ОТЛОЖЕНО rate-limit'ом ({MAX_CARDS_PER_DAY}/сутки): {r['deferred']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
