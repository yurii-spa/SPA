#!/usr/bin/env python3
"""Кто и когда ЗАКРЫВАЕТ захват карточки, и чего стоил бы срок годности — заказ **G88 п. 2** (ADR-498).

Заказ поставлен 28.09 и перевыставлялся двадцатью одним заказом (G89…G109) дословно:

    **Захват умершей сессии остаётся открытым НАВСЕГДА.** 12 375 пар — следствие одной
    формы: ``done`` пишет только живая сессия. Мерить надо у ПИСАТЕЛЯ (кто и когда
    закрывает захват), а не по имени поля, и назвать, сколько захватов закрылось бы,
    будь у них срок годности. Поднимать вопрос о сроке по догадке нельзя: слабый
    признак уже дважды запирал очередь.

Прибор отвечает на вопрос заказа и **поправляет его диагноз**. «``done`` пишет только живая
сессия» — верно, но причина вечного захвата не в этом: **освобождение адресовано ДЕРЖАТЕЛЮ,
а не КАРТОЧКЕ**. ``check_card_claim.releases_by_session`` ключует освобождение личностью
писателя, поэтому ``done``, написанный ТЕМ, КТО РАБОТУ ДОДЕЛАЛ, захват предшественника не
снимает — хотя про саму карточку уже сказано «закрыта». Замер: таких захватов **450 из 557**.
Срок годности их бы «закрыл», но закрыл бы ЧУЖОЙ дефект, спрятав его: это ровно та причина,
по которой заказ запретил поднимать вопрос о сроке по догадке.

## Четыре замера, и ни один не заменяет другой

===== ====================================== =========================================
ось   вопрос                                 чем меряется
===== ====================================== =========================================
A     КТО закрывает захват?                  у ПИСАТЕЛЯ: снимает ли запись ``done``
                                              хоть один ПРЕЖНИЙ захват СВОЕЙ личности
                                              — или не снимает ничего
B     КОГДА закрывает?                       распределение задержки «захват →
                                              освобождение» у закрытых пар; это
                                              ЕДИНСТВЕННЫЙ источник цены для оси D
C     почему захват остаётся открытым?       ДВА независимых разреза: живость
                                              держателя у ПИСАТЕЛЯ (жив · измеренно
                                              мёртв · не измерено) И сказано ли про
                                              КАРТОЧКУ «закрыта» кем-то другим
D     сколько закрыл бы срок годности?       лестница сроков, у каждого ЧЕТЫРЕ числа:
                                              закрыл бы мёртвых · закрыл бы
                                              неизмеренных · выгнал бы ЖИВОГО ·
                                              оборвал бы работу, которая закрылась
                                              сама (цена, вход из оси B)
===== ====================================== =========================================

Ось A без оси C назвала бы писателя и промолчала о том, что освобождение не доходит.
Ось C без оси D повторила бы жалобу заказа числом. **Ось D без оси B — догадка**: срок,
названный без распределения задержки, и есть то «по догадке», что заказ запретил.

## Личность — ЯКОРЬ, а не ярлык (иначе замер изготовит дефект из ФОРМЫ записи)

Ярлык (``cycle-6648``, ``pid32079``) выводится из pid однократной CLI-команды, поэтому у
ОДНОЙ сессии их бывает несколько (ADR-498: «считать их разными сессиями значило бы
изготовить столкновение из ФОРМЫ записи» — ровно на этом сгорели три «подтверждённых»
столкновения). Поэтому личность здесь — долгоживущий якорь (``session_pid`` +
``session_pid_start``), и ярлык берётся ТОЛЬКО когда якоря нет; доля такой подмены
объявлена в отчёте (``identity_from_label``), а не спрятана. Разница не теоретическая:
по ярлыку незакрытых захватов 501, по якорю — **557**, и 56 из них ярлык склеил.

## Третий исход обязателен (инв. #17), и здесь он у каждой оси свой

* **журнала нет / не читается** — ``UNMEASURED`` целиком (код 2);
* **захватов ноль** — ``UNMEASURED``: «все захваты закрыты» при нуле захватов верно ПО
  ПОСТРОЕНИЮ, и выдавать это за чистый замер есть fail-OPEN (урок ``pyflakes``,
  ``.claude/rules/deployment.md``);
* **ось B: закрытых пар ноль** — задержки нет, значит цены для оси D нет; лестница
  объявляется, но колонка цены — ``None``, а не нуль;
* **ось C: живость держателя** — ТРИ исхода, и ``holder_unmeasured`` (якоря нет вовсе,
  как у ``cycle-74714``) **не считается мёртвым**. 164 записи именно такие;
* **ось C: ``ps`` не отработал** — тоже ``holder_unmeasured``, и доля названа отдельно:
  при полной недоступности ``ps`` оси C и D нечем мерить, и это говорится вслух.

## Одностороннее названо заранее

* **«Закрыт» здесь значит «освобождение написано», а не «работа сделана».** Прибор читает
  журнал объявлений, а не результат; захват без ``done`` мог быть доделан и не объявлен.
* **Цена оси D — НИЖНЯЯ граница.** Она считается только по парам, которые закрылись САМИ;
  про работу, которую срок оборвал бы ДО объявления, журнал не знает ничего.
* **Прибор НЕ НАЗЫВАЕТ срок и не предлагает его завести.** Он даёт основание — две
  стороны лестницы. Выбор срока есть решение (у заказа сказано: слабый признак дважды
  запирал очередь), и следствием замера он не становится.
* **Живость меряется СЕЙЧАС, а задержка — в прошлом.** Это разные вопросы к одной записи:
  держатель, умерший час назад, был жив все те часы, что захват стоял.
* **Правило освобождения прибор НЕ ПЕРЕПИСЫВАЕТ своим кодом.** Терминальность и ключ
  освобождения берутся у сторожа (``check_card_claim.is_release``), разбор времени и
  личности — у шага 0a (``check_undelivered_work``): второй экземпляр одной мерки
  расходится с первым молча (ADR-220).

## Вердикт

* ``RELEASE_ADDRESSED_TO_HOLDER`` — освобождение адресовано ДЕРЖАТЕЛЮ: есть захваты,
  открытые при закрытой карточке. Код 1 — находка, а не норма;
* ``RELEASE_ADDRESSED_TO_CARD`` — таких захватов нет. Код 0;
* ``UNMEASURED`` — код 2, перебивает всё.

Гейт, срок годности и правку правила освобождения прибор НЕ заводит: он только ЧИТАЕТ.

    python3 -m spa_core.monitoring.claim_release_census
    python3 -m spa_core.monitoring.claim_release_census --json --save
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "claim_release_census.json"
ORDER = ("G88 п. 2 (ADR-498) — кто и когда ЗАКРЫВАЕТ захват, "
         "и сколько закрыл бы срок годности")

JOURNAL_REL = "data/session_changes.jsonl"

STATUS_TO_HOLDER = "RELEASE_ADDRESSED_TO_HOLDER"
STATUS_TO_CARD = "RELEASE_ADDRESSED_TO_CARD"
STATUS_UNMEASURED = "UNMEASURED"

#: Исходы живости держателя (ось C). Имена СВОИ, а не перенос чужих констант:
#: у шага 0a ``active``/``not_confirmed``/``unknown`` отвечают на вопрос «ждать ли
#: доставку», здесь — «держит ли кто-то карточку». Склеить словари значило бы
#: ответить одним именем на два вопроса.
HOLDER_ALIVE = "holder_alive"
HOLDER_DEAD = "holder_dead"
HOLDER_UNMEASURED = "holder_unmeasured"

#: Лестница сроков, в часах. Перечень ЗАКРЫТ и выбран так, чтобы накрыть ОБА
#: распределения замера 02.10 (задержка закрытых пар: p50 0.48 ч, p99 4.92 ч,
#: max 514.48 ч; возраст незакрытых: p50 836.4 ч, max 1517.3 ч) — иначе лестница
#: отвечала бы только на той стороне, где и так всё понятно. Это сетка ОТЧЁТА, а не
#: предложенный срок. Числа здесь — ЗАМЕР С ДАТОЙ, а не константа: перемеряет сам
#: прибор (ось B и ось C), и брать их из этого комментария вместо прибора запрещено.
TTL_LADDER_HOURS = (6, 12, 24, 48, 72, 168, 336, 720)

_HOUR = 3600.0


# ─────────────────────────── чужие мерки: заём, не копия ───────────────────────────

def _load_script(repo_root: Path, rel: str, name: str):
    """Загрузить скрипт-сосед как модуль. ``None`` — не загрузился (это третий исход)."""
    path = repo_root / rel
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception:  # noqa: BLE001 — любая поломка соседа есть «не измерено»
        return None


def load_neighbours(repo_root: Path) -> Dict[str, Any]:
    """Сторож захвата (правило освобождения) и шаг 0a (разбор времени, личности, живости).

    Берутся ЦЕЛИКОМ у соседей намеренно: ``is_release`` — единственное место, где
    читается терминальность, а ``_durable_state`` — единственное, где живость сессии
    отличает мёртвого держателя от неизмеренного. Свой экземпляр любой из этих мерок
    разошёлся бы с оригиналом молча (ADR-220).
    """
    guard = _load_script(repo_root, "scripts/check_card_claim.py", "_crc_guard")
    sibling = _load_script(repo_root, "scripts/check_undelivered_work.py", "_crc_sibling")
    missing = [name for name, mod in (("check_card_claim", guard),
                                      ("check_undelivered_work", sibling)) if mod is None]
    return {"guard": guard, "sibling": sibling, "missing": missing}


# ─────────────────────────── население: журнал объявлений ───────────────────────────

def read_journal(path: Path) -> Dict[str, Any]:
    """Записи журнала объявлений. Форма постоянна; ``records is None`` — не прочитан."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"records": None, "broken_lines": None,
                "reason": f"журнал не прочитан: {type(exc).__name__}: {exc}"}
    records: List[Dict[str, Any]] = []
    broken = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            broken += 1
            continue
        if isinstance(row, dict):
            records.append(row)
        else:
            broken += 1
    return {"records": records, "broken_lines": broken, "reason": None}


def identity_of(record: Dict[str, Any], sibling) -> Tuple[str, Any]:
    """Личность писателя записи: якорь, если объявлен; иначе ЯРЛЫК — и это НАЗВАНО.

    Возврат — пара («откуда взята», значение), чтобы доля подмены была видна в отчёте,
    а не растворилась в равенстве личностей.
    """
    anchor = sibling.anchor_of(record)
    if anchor is not None:
        return ("anchor", anchor)
    return ("label", str(record.get("session") or ""))


def _claim_card(record: Dict[str, Any]) -> Optional[str]:
    """Карточка записи или ``None``. Пустая строка карточкой не является."""
    card = observed(record, "card", kind=str)
    card = (card or "").strip()
    return card or None


def split_population(records: Sequence[Dict[str, Any]], *, guard, sibling) -> Dict[str, Any]:
    """Захваты и освобождения — по правилу СТОРОЖА, а не по имени поля.

    Терминальность спрашивается у ``guard.is_release``; «не ``done``» при наличии карточки
    есть захват (умолчание писателя — ``claim``, ``log_session_change.CARD_STATES``).
    """
    claims: List[Dict[str, Any]] = []
    releases: List[Dict[str, Any]] = []
    unparsed_ts = 0
    without_card = 0
    for record in records:
        card = _claim_card(record)
        if card is None:
            without_card += 1
            continue
        stamp = sibling._parse_ts(record.get("ts"))
        if stamp is None:
            unparsed_ts += 1
            continue
        row = {"record": record, "card": card, "ts": stamp,
               "identity": identity_of(record, sibling)}
        (releases if guard.is_release(record) else claims).append(row)
    return {"claims": claims, "releases": releases,
            "records_without_card": without_card,
            "records_with_card_unparsed_ts": unparsed_ts}


# ───────────────────── ось A: КТО закрывает захват (у писателя) ─────────────────────

def measure_writers(claims: Sequence[Dict[str, Any]],
                    releases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Снимает ли запись ``done`` хоть один ПРЕЖНИЙ захват своей личности.

    Вопрос у ПИСАТЕЛЯ, а не по имени поля: «записей с ``card_state: done``» столько-то —
    это про поле. «Освобождение, которое ничего не освободило» — про писателя.
    """
    if not releases:
        return {"measured": False,
                "reason": "освобождений в журнале нет — чьи захваты они снимают, спросить не у кого"}
    claimed_at: Dict[Tuple[Any, str], List[datetime]] = {}
    for row in claims:
        claimed_at.setdefault((row["identity"], row["card"]), []).append(row["ts"])

    released_own = 0
    released_nothing = 0
    by_identity_source: Dict[str, int] = {"anchor": 0, "label": 0}
    nothing_examples: List[Dict[str, Any]] = []
    for row in releases:
        by_identity_source[row["identity"][0]] += 1
        prior = claimed_at.get((row["identity"], row["card"]), ())
        if any(stamp <= row["ts"] for stamp in prior):
            released_own += 1
            continue
        released_nothing += 1
        if len(nothing_examples) < 5:
            nothing_examples.append({
                "card": row["card"],
                "ts": row["ts"].isoformat().replace("+00:00", "Z"),
                "identity_from": row["identity"][0]})
    return {
        "measured": True,
        "reason": None,
        "releases_total": len(releases),
        "released_own_prior_claim": released_own,
        "released_nothing": released_nothing,
        "identity_from": by_identity_source,
        "released_nothing_examples": nothing_examples,
        "means": ("«освободило ничего» НЕ есть ошибка писателя: карточку мог закрыть тот, "
                  "кто её не брал этим журналом. Это замер АДРЕСАТА освобождения"),
    }


# ───────────────────── ось B: КОГДА закрывает (задержка и её цена) ─────────────────

def _percentile(sorted_values: Sequence[float], share: float) -> float:
    """Процентиль по уже отсортированному ряду. Население пустым здесь не бывает."""
    index = int(share * len(sorted_values))
    return sorted_values[min(len(sorted_values) - 1, max(0, index))]


def measure_latency(claims: Sequence[Dict[str, Any]],
                    releases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Задержка «захват → первое освобождение ТОЙ ЖЕ личности на ТОЙ ЖЕ карточке».

    Это вход цены для оси D: срок короче задержки оборвал бы работу, которая закрылась сама.
    """
    released_at: Dict[Tuple[Any, str], List[datetime]] = {}
    for row in releases:
        released_at.setdefault((row["identity"], row["card"]), []).append(row["ts"])
    for stamps in released_at.values():
        stamps.sort()

    latencies: List[float] = []
    open_claims: List[Dict[str, Any]] = []
    for row in claims:
        later = [s for s in released_at.get((row["identity"], row["card"]), ())
                 if s >= row["ts"]]
        if later:
            latencies.append((later[0] - row["ts"]).total_seconds() / _HOUR)
        else:
            open_claims.append(row)
    if not latencies:
        return {"measured": False,
                "reason": ("ни одна пара «захват → освобождение» не сошлась — задержки нет, "
                           "значит цены для лестницы сроков тоже нет"),
                "closed_pairs": 0, "open_claims": open_claims}
    latencies.sort()
    return {
        "measured": True,
        "reason": None,
        "closed_pairs": len(latencies),
        "open_claims": open_claims,
        "hours": {
            "min": round(latencies[0], 2),
            "p50": round(_percentile(latencies, 0.50), 2),
            "p90": round(_percentile(latencies, 0.90), 2),
            "p99": round(_percentile(latencies, 0.99), 2),
            "max": round(latencies[-1], 2),
        },
        "_latencies": latencies,
    }


# ──────────── ось C: почему захват остаётся открытым (ДВА разреза) ─────────────

def holder_state(row: Dict[str, Any], *, sibling, ps, cmd_probe) -> Tuple[str, str]:
    """(исход, измерение словами) — держит ли карточку кто-то живой.

    Живость спрашивается у ШАГА 0a (``_durable_state``), а не своим ``ps``: правило
    личности процесса (сверка времени старта, отказ таймерам) живёт там одним
    экземпляром. Записи без якоря — ``holder_unmeasured``, и мёртвыми они не
    становятся: «нечем спросить» не есть «поймали».
    """
    state = sibling._durable_state(row["record"], row["ts"], ps, cmd_probe=cmd_probe)
    if state is None:
        return HOLDER_UNMEASURED, ("долгоживущий процесс не объявлен — активность держателя "
                                   "не измерена (ярлык сам о жизни сессии не говорит)")
    verdict, why = state
    if verdict == sibling.ACTIVE:
        return HOLDER_ALIVE, why
    if verdict == sibling.NOT_CONFIRMED:
        return HOLDER_DEAD, why
    return HOLDER_UNMEASURED, why


def measure_open_claims(open_claims: Sequence[Dict[str, Any]],
                        releases: Sequence[Dict[str, Any]], *,
                        sibling, ps, cmd_probe,
                        now: datetime) -> Dict[str, Any]:
    """Незакрытые захваты в ДВУХ разрезах: живость держателя И судьба самой КАРТОЧКИ.

    Второй разрез и есть поправка к диагнозу заказа: захват, у чьей карточки ПОЗЖЕ
    объявлено ``done`` ДРУГОЙ личностью, стои́т открытым не потому, что держатель умер,
    а потому, что освобождение адресовано ДЕРЖАТЕЛЮ, а не КАРТОЧКЕ.
    """
    # ВАЖНО: «незакрытых захватов ноль» есть ИЗМЕРЕННЫЙ НУЛЬ, а не отсутствие замера.
    # Третий исход здесь уже сработал выше — на нуле ЗАХВАТОВ в журнале (там мерить
    # нечего по построению). Поставить его ещё и здесь значило бы вывернуть инвариант
    # #17 наизнанку: из трёх исходов «измерено · измерено и равно нулю · не измерено»
    # склеились бы второй и третий, и честный зелёный контур докладывал бы «НЕ ИЗМЕРЕНО».
    released_card: Dict[str, List[Tuple[datetime, Any]]] = {}
    for row in releases:
        released_card.setdefault(row["card"], []).append((row["ts"], row["identity"]))

    rows: List[Dict[str, Any]] = []
    by_holder: Dict[str, int] = {HOLDER_ALIVE: 0, HOLDER_DEAD: 0, HOLDER_UNMEASURED: 0}
    card_done_elsewhere = 0
    card_never_done = 0
    examples: List[Dict[str, Any]] = []
    for row in open_claims:
        state, why = holder_state(row, sibling=sibling, ps=ps, cmd_probe=cmd_probe)
        by_holder[state] += 1
        elsewhere = [(stamp, who) for stamp, who in released_card.get(row["card"], ())
                     if stamp >= row["ts"] and who != row["identity"]]
        if elsewhere:
            card_done_elsewhere += 1
            if len(examples) < 5:
                examples.append({
                    "card": row["card"],
                    "claimed_at": row["ts"].isoformat().replace("+00:00", "Z"),
                    "card_declared_done_at": elsewhere[0][0].isoformat().replace("+00:00", "Z"),
                    "holder": state})
        else:
            card_never_done += 1
        rows.append({"age_hours": (now - row["ts"]).total_seconds() / _HOUR,
                     "holder": state,
                     "card_done_elsewhere": bool(elsewhere),
                     "why": why})

    ages = sorted(r["age_hours"] for r in rows)
    return {
        "measured": True,
        "reason": None,
        "open_claims": len(rows),
        "by_holder": by_holder,
        "card_declared_done_by_another_identity": card_done_elsewhere,
        "card_never_declared_done": card_never_done,
        # Возраста нет, когда незакрытых захватов нет: `None` — «нечего мерить», а
        # не нулевой возраст. Нуль здесь означал бы «захват взят только что».
        "age_hours": None if not ages else {"min": round(ages[0], 1),
                                            "p50": round(_percentile(ages, 0.50), 1),
                                            "max": round(ages[-1], 1)},
        "examples_done_elsewhere": examples,
        "_rows": rows,
        "means": ("«держатель мёртв» — ИЗМЕРЕННЫЙ факт (процесса нет либо pid занят другим); "
                  "«не измерено» — якоря нет вовсе, и это НЕ обвинение"),
    }


# ──────────── ось D: лестница сроков — ЧЕТЫРЕ числа у каждой ступени ────────────

def measure_expiry_ladder(open_rows: Sequence[Dict[str, Any]],
                          latencies: Optional[Sequence[float]], *,
                          ladder: Sequence[int] = TTL_LADDER_HOURS) -> Dict[str, Any]:
    """Сколько закрыл бы срок годности — и чего бы это стоило. Срок НЕ называется.

    На каждой ступени четыре числа, и смешивать их нельзя: закрытый мёртвый — польза,
    закрытый неизмеренный — польза неизвестного знака, выгнанный живой — вред,
    оборванная работа, закрывшаяся сама, — цена. Отдельно та же лестница по УЗКОМУ
    населению (карточка не объявлена закрытой никем): только для него срок годности
    и есть лекарство, а не маскировка чужого дефекта.
    """
    narrow = [r for r in open_rows if not r["card_done_elsewhere"]]
    steps: List[Dict[str, Any]] = []
    for ttl in ladder:
        def closes(rows: Sequence[Dict[str, Any]], holder: str) -> int:
            return sum(1 for r in rows if r["holder"] == holder and r["age_hours"] >= ttl)
        step = {
            "ttl_hours": ttl,
            "all_open": {
                "would_close_dead_holder": closes(open_rows, HOLDER_DEAD),
                "would_close_unmeasured_holder": closes(open_rows, HOLDER_UNMEASURED),
                "would_evict_live_holder": closes(open_rows, HOLDER_ALIVE),
            },
            "card_never_declared_done": {
                "would_close_dead_holder": closes(narrow, HOLDER_DEAD),
                "would_close_unmeasured_holder": closes(narrow, HOLDER_UNMEASURED),
                "would_evict_live_holder": closes(narrow, HOLDER_ALIVE),
            },
            # Цена: пары, которые закрылись САМИ позже срока. `None` — не нуль:
            # без оси B цены нет вовсе, и нуль здесь читался бы как «цены нет».
            "would_have_cut_self_closing_work": (
                None if latencies is None
                else sum(1 for value in latencies if value > ttl)),
        }
        steps.append(step)
    return {
        "measured": True,
        "reason": None,
        "ladder": steps,
        "narrow_population": len(narrow),
        "cost_population": None if latencies is None else len(latencies),
        "refuses_to_name_a_ttl": (
            "срок прибор НЕ называет и заводить не предлагает: у заказа сказано, что "
            "слабый признак дважды запирал очередь. Лестница — ОСНОВАНИЕ для решения, "
            "а не решение"),
        "lower_bound": (
            "цена есть НИЖНЯЯ граница: она считается только по работе, которая успела "
            "объявить своё закрытие; про оборванную до объявления журнал не знает ничего"),
    }


# ─────────────────────────────── отчёт ───────────────────────────────

def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 journal_path: Optional[Path] = None,
                 ps=None, cmd_probe=None,
                 neighbours: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = now or datetime.now(timezone.utc)
    report: Dict[str, Any] = {
        "generated_at": stamp.isoformat().replace("+00:00", "Z"),
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        "applied": False,
        "population": None,
        "writers": None,
        "latency": None,
        "open_claims": None,
        "expiry_ladder": None,
    }
    kin = neighbours if neighbours is not None else load_neighbours(repo_root)
    if kin["missing"]:
        report["reason"] = ("не загружены соседние мерки: " + ", ".join(kin["missing"])
                            + " — правило освобождения и живость держателя спрашиваются "
                              "у них, своего экземпляра у прибора нет намеренно")
        return report
    guard, sibling = kin["guard"], kin["sibling"]
    ps = ps if ps is not None else sibling._ps_lstart
    cmd_probe = cmd_probe if cmd_probe is not None else sibling._ps_command

    path = journal_path if journal_path is not None else repo_root / JOURNAL_REL
    journal = read_journal(Path(path))
    if journal["records"] is None:
        report["reason"] = journal["reason"]
        return report

    population = split_population(journal["records"], guard=guard, sibling=sibling)
    report["population"] = {
        "journal": str(path),
        "records": len(journal["records"]),
        "broken_lines": journal["broken_lines"],
        "claims": len(population["claims"]),
        "releases": len(population["releases"]),
        "records_without_card": population["records_without_card"],
        "records_with_card_unparsed_ts": population["records_with_card_unparsed_ts"],
    }
    if not population["claims"]:
        report["reason"] = ("захватов в журнале нет: «все захваты закрыты» при нуле "
                            "захватов верно ПО ПОСТРОЕНИЮ и замером не является")
        return report

    report["writers"] = measure_writers(population["claims"], population["releases"])
    latency = measure_latency(population["claims"], population["releases"])
    open_claims = measure_open_claims(latency["open_claims"], population["releases"],
                                      sibling=sibling, ps=ps, cmd_probe=cmd_probe,
                                      now=stamp)
    report["latency"] = {k: v for k, v in latency.items() if not k.startswith("_")
                         and k != "open_claims"}
    report["open_claims"] = {k: v for k, v in open_claims.items() if not k.startswith("_")}

    if not open_claims["measured"]:
        report["reason"] = f"ось C: {open_claims['reason']}"
        return report
    # «Незакрытых захватов ноль» сюда доходит как ИЗМЕРЕННЫЙ нуль (см. measure_open_claims).
    report["expiry_ladder"] = measure_expiry_ladder(
        open_claims["_rows"], latency.get("_latencies") if latency["measured"] else None)

    report["measured"] = True
    report["status"] = (STATUS_TO_HOLDER
                        if open_claims["card_declared_done_by_another_identity"] > 0
                        else STATUS_TO_CARD)
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("кто и когда закрывает захват (заказ G88 п. 2): "
                     f"НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    pop = report["population"]
    writers = report["writers"]
    latency = report["latency"]
    open_claims = report["open_claims"]
    ladder = report["expiry_ladder"]

    lines.append(f"кто и когда закрывает захват (заказ G88 п. 2): {report['status']} · "
                 f"захватов {pop['claims']} · освобождений {pop['releases']} "
                 f"(записей {pop['records']}, битых строк {pop['broken_lines']})")
    if writers.get("measured"):
        lines.append(
            f"[ОСЬ A] у ПИСАТЕЛЯ: освобождений {writers['releases_total']}, из них сняли "
            f"СВОЙ прежний захват {writers['released_own_prior_claim']}, не сняли ничего "
            f"{writers['released_nothing']}; личность по якорю "
            f"{writers['identity_from']['anchor']}, по ярлыку "
            f"{writers['identity_from']['label']}")
    else:
        lines.append(f"[ОСЬ A] НЕ ИЗМЕРЕНО — {writers.get('reason')}")
    if latency.get("measured"):
        h = latency["hours"]
        lines.append(
            f"[ОСЬ B] задержка «захват → освобождение» по {latency['closed_pairs']} парам: "
            f"p50 {h['p50']} ч · p90 {h['p90']} ч · p99 {h['p99']} ч · max {h['max']} ч")
    else:
        lines.append(f"[ОСЬ B] НЕ ИЗМЕРЕНО — {latency.get('reason')} ⇒ цены у лестницы нет")
    bh = open_claims["by_holder"]
    age = observed(open_claims, "age_hours", kind=dict)
    lines.append(
        f"[ОСЬ C] незакрытых захватов {open_claims['open_claims']}: держатель жив "
        f"{bh[HOLDER_ALIVE]} · измеренно МЁРТВ {bh[HOLDER_DEAD]} · НЕ ИЗМЕРЕН "
        f"{bh[HOLDER_UNMEASURED]}; возраст "
        + ("нечего мерить — незакрытых захватов нет" if age is None
           else f"p50 {age['p50']} ч, max {age['max']} ч"))
    lines.append(
        f"[ОСЬ C] из них карточка ПОЗЖЕ объявлена закрытой другой личностью "
        f"{open_claims['card_declared_done_by_another_identity']}, не объявлена никем "
        f"{open_claims['card_never_declared_done']} ⇒ освобождение адресовано ДЕРЖАТЕЛЮ, "
        f"а не КАРТОЧКЕ")
    for step in ladder["ladder"]:
        wide, narrow = step["all_open"], step["card_never_declared_done"]
        cost = step["would_have_cut_self_closing_work"]
        lines.append(
            f"[ОСЬ D] срок {step['ttl_hours']:>4} ч: закрыл бы мёртвых "
            f"{wide['would_close_dead_holder']} + неизмеренных "
            f"{wide['would_close_unmeasured_holder']}, выгнал бы ЖИВОГО "
            f"{wide['would_evict_live_holder']}; по узкому населению "
            f"({ladder['narrow_population']}) — "
            f"{narrow['would_close_dead_holder']} + "
            f"{narrow['would_close_unmeasured_holder']}; оборвал бы работу, "
            f"закрывшуюся саму — {'НЕ ИЗМЕРЕНО' if cost is None else cost}")
    lines.append(f"[ОСЬ D] {ladder['refuses_to_name_a_ttl']}")
    lines.append(f"[ОСЬ D] {ladder['lower_bound']}")
    if report["status"] == STATUS_TO_HOLDER:
        lines.append(
            "ВЫВОД: диагноз заказа («`done` пишет только живая сессия») верен лишь "
            "наполовину. Главная причина вечного захвата — АДРЕСАТ освобождения: "
            f"{open_claims['card_declared_done_by_another_identity']} захватов стоят "
            "открытыми при карточке, про которую уже сказано «закрыта». Срок годности "
            "закрыл бы их, СПРЯТАВ этот дефект; лекарство от него — адресовать "
            "освобождение карточке, и это решение, а не следствие замера")
    lines.append("НЕ ДОКЛАДЫВАЕТ: сделана ли работа (журнал знает объявления, не результат) · "
                 "был ли держатель жив ТОГДА (живость меряется сейчас) · что оборвал бы срок "
                 "до объявления · надо ли заводить срок и какой")
    lines.append("ADVISORY: прибор только ЧИТАЕТ (applied=False) — RiskPolicy v1.0, стоп-кран, "
                 "аллокатор, живой трек и landing/ не трогаются; ни срока, ни гейта, ни правки "
                 "правила освобождения прибор не заводит")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    if not report.get("measured"):
        return 2
    return 0 if report["status"] == STATUS_TO_CARD else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--journal", default=None,
                    help=f"журнал объявлений (по умолчанию — {JOURNAL_REL} своего дерева)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root,
                          journal_path=Path(args.journal) if args.journal else None)
    if args.save:
        save_artifact(report, repo_root / "data")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
