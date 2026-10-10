#!/usr/bin/env python3
"""Цена ветви «освобождение по КАРТОЧКЕ» — заказ **G111 п. 1** (ADR-536).

Заказ, дословно:

    **Адресат освобождения — развилка, и обе ветви надо мерить ДО выбора.** Замер назвал
    450 захватов, стоящих открытыми при закрытой карточке. Ветвь «освобождать по карточке»
    (``done`` на карточку снимает захваты ВСЕХ личностей) закрывает их без срока годности,
    но открывает обратный вред: чужой ``done`` снимет ЖИВОЙ захват. Мерить надо **цену
    именно этого вреда** на живом журнале (сколько живых захватов снял бы чужой ``done``
    задним числом), а не выбирать ветвь по тому, что первая звучит чище. Третий исход
    обязателен.

Сосед ADR-536 измерил ПОЛЬЗУ ветви и сам сказал вслух, чего не говорит: «был ли держатель
жив ТОГДА (живость меряется сейчас)». Здесь спрашивается ровно это — и спрашивается НЕ у
ОС, которой прошлое не задать, а у журнала: **свидетельство жизни держателя В МОМЕНТ чужого
``done``**.

## Три оси, и ни одна не заменяет другую

===== ======================================= =========================================
ось   вопрос                                  чем меряется
===== ======================================= =========================================
A     чего ветвь СТОИТ ПОЛЕЗНОГО?             числом СОСЕДА (ADR-536): захваты,
                                               открытые при карточке, закрытой другой
                                               личностью. Своего экземпляра нет
                                               намеренно (ADR-220)
B     чего ветвь стоит ВРЕДНОГО?              перепроигрывание журнала: чей открытый
                                               захват снял бы каждый чужой ``done``, и
                                               что журнал свидетельствует о жизни
                                               держателя В ТОТ момент — три исхода
C     вред ПРИТВОРНЫЙ или настоящий?          вердикт НАСТОЯЩЕЙ двери (``check``) на
                                               одноразовой сцене с ЖИВЫМ держателем:
                                               отдаст ли она карточку постороннему
===== ======================================= =========================================

Ось A без оси B выбрала бы ветвь по одному числу — ровно то, что заказ запретил. Ось B
без оси C осталась бы арифметикой над журналом: «снял бы захват» ещё не значит «дверь
отдала бы карточку», и наоборот. Ось C без оси B измерила бы ОДНУ сцену и промолчала о
том, сколько раз это случилось бы на живом журнале.

## Живость В ПРОШЛОМ меряется журналом, и у неё три исхода (инв. #17)

ОС отвечает только про СЕЙЧАС. Поэтому «был ли держатель жив в момент чужого ``done``»
спрашивается у записей, и ответ бывает трёх видов:

* ``witnessed_working`` — держатель объявил СВОЁ ``card_state: done`` по ЭТОЙ карточке
  **позже** чужого: он работал, и ветвь «по карточке» сняла бы захват ПОД РАБОТОЙ.
  Это не догадка о живости, а её ИСХОД;
* ``witnessed_alive`` — держатель писал в журнал ЧТО-УГОДНО позже чужого ``done``, но
  закрытия этой карточки не объявлял: жив он был, а работал ли ещё над ней — журнал не
  знает. Склеивать с первым исходом нельзя;
* ``no_evidence`` — после чужого ``done`` держатель не сказал НИЧЕГО. Это **«не
  измерено»**, а НЕ «был мёртв»: молчание уликой смерти не является, и именно эта
  подмена сделала бы вред ветви нулём на ровном месте.

**Вред — НИЖНЯЯ граница, и это важнее, чем кажется.** Свидетельством служит только то,
что держатель успел НАПИСАТЬ; работа, оборванная до объявления, журналу неизвестна по
построению (та же оговорка, что у цены оси D соседа). Поэтому вред ветви «по карточке»
может быть только БОЛЬШЕ названного числа, но не меньше.

## Два населения — одно перепроигрывание, и это СВЕРКА СОСТАВА, а не второе мнение

Польза и вред приходят из ОДНОГО и того же события: чужой ``done`` задевает захват,
открытый в тот момент. Поэтому «захваты, которые ветвь закрыла бы полезно» и «захваты,
которые она сняла бы под работой» — две доли одного населения, и их сумма сверяется с
числом соседа. Расхождение есть дефект проводки (один из двух приборов читает не то
население), и прибор его НАЗЫВАЕТ. Совпадение же независимым подтверждением НЕ является:
условие у обоих одно и то же, и равенство тут ожидаемо по построению.

## Правило «снял бы» взято у ДВЕРИ, а не придумано здесь

Освобождение снимает захват, если оно **не раньше** захвата (``done`` в 10:00 при
захвате в 10:05 — повторное взятие живо, ``check_card_claim`` и ось B соседа читают
``>=``). Терминальность — ``is_release`` сторожа; население, карточка, личность и разбор
времени — ``claim_release_census.split_population``. Второй экземпляр любой из этих
мерок разошёлся бы с первым молча (ADR-220).

## Эквивалентность оси C названа, а не подразумевается

Ветви «по карточке» в дереве нет, и прибор её НЕ ПИШЕТ. У двери личность освобождения
служит ТОЛЬКО ключом (``releases_for_card`` → ``latest.pop(session)``), поэтому запись
``done``, несущая ЯРЛЫК ДЕРЖАТЕЛЯ, делает с его захватом ровно то, что сделала бы ветвь
«по карточке». На сцене с ОДНИМ держателем «снять всех» и «снять этого» дают один
вердикт; на сцене с двумя равенство пришлось бы доказывать отдельно, и это сказано
вслух, а не умолчано.

## Вердикт

* ``CARD_BRANCH_STRIPS_LIVE_WORK`` — вред ЗАСВИДЕТЕЛЬСТВОВАН (код 1): на живом журнале
  есть захваты, которые чужой ``done`` снял бы у держателя, работавшего дальше;
* ``CARD_BRANCH_HARM_NOT_WITNESSED`` — задетые захваты есть, свидетельств жизни ни
  одного (код 0). Это ИЗМЕРЕННЫЙ НУЛЬ, а не отсутствие замера;
* ``UNMEASURED`` — код 2, перебивает всё.

Ветвь прибор НЕ ВЫБИРАЕТ и правило освобождения не правит: он только ЧИТАЕТ. Выбор
адресата есть решение (предмет ни одного из трёх ADR-285 — фиксируется журналом), и
следствием замера он не становится.

    python3 -m spa_core.monitoring.foreign_done_cost
    python3 -m spa_core.monitoring.foreign_done_cost --json --save
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring.claim_guard_receipt_readers import (  # noqa: E402
    _ask_guard, _load_guard, _write_sandbox, live_other_anchor,
)
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed  # noqa: E402

ARTIFACT_NAME = "foreign_done_cost.json"
ORDER = ("G111 п. 1 (ADR-536) — цена ветви «освобождение по КАРТОЧКЕ»: "
         "сколько ЖИВЫХ захватов снял бы чужой `done` задним числом")

#: Сосед, у которого берутся население и ПОЛЬЗА ветви. Ввозом по ИМЕНИ МОДУЛЯ, а не по
#: пути: загрузка пакетного модуля через ``spec_from_file_location`` рвёт его
#: относительные импорты и оставляет часть дверей «не измерено» (ADR-682).
CENSUS_MODULE = "spa_core.monitoring.claim_release_census"

STATUS_STRIPS_LIVE = "CARD_BRANCH_STRIPS_LIVE_WORK"
STATUS_NOT_WITNESSED = "CARD_BRANCH_HARM_NOT_WITNESSED"
STATUS_UNMEASURED = "UNMEASURED"

#: Исходы оси B. Имена СВОИ: у соседа ``holder_alive``/``holder_dead`` отвечают на вопрос
#: «держит ли кто-то карточку СЕЙЧАС», здесь вопрос другой — «что журнал свидетельствует
#: о держателе В МОМЕНТ чужого ``done``». Склеить словари значило бы ответить одним
#: именем на два вопроса.
WITNESSED_WORKING = "witnessed_working"
WITNESSED_ALIVE = "witnessed_alive"
NO_EVIDENCE = "no_evidence"
OUTCOMES = (WITNESSED_WORKING, WITNESSED_ALIVE, NO_EVIDENCE)

#: Исходы оси C — что делает НАСТОЯЩАЯ дверь с захватом живого держателя.
DOOR_PROTECTS = "protects_live_holder"
DOOR_HANDS_OVER = "hands_card_to_stranger"

#: Ветви развилки на сцене оси C.
BRANCH_HOLDER = "release_by_holder"
BRANCH_CARD = "release_by_card"
BRANCHES = (BRANCH_HOLDER, BRANCH_CARD)

_SCENE_CARD = "inbox-proba-tsenyi-chuzhogo-done"

_HOUR = 3600.0


# ─────────────────────────── чужие мерки: заём, не копия ───────────────────────────

def load_census(module: str = CENSUS_MODULE):
    """Сосед ADR-536. Ввозом по имени модуля (см. :data:`CENSUS_MODULE`)."""
    return importlib.import_module(module)


# ───────────────── ось A: ПОЛЬЗА ветви — числом СОСЕДА, не своим ─────────────────

def measure_benefit(repo_root: Path, *, census, journal_path: Optional[Path] = None,
                    report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Сколько захватов ветвь «по карточке» закрыла бы ПОЛЕЗНО — ответ соседа.

    Своего экземпляра этой мерки здесь нет намеренно: число пользы уже произведено
    прибором ADR-536 (``open_claims.card_declared_done_by_another_identity``), и второй
    экземпляр расходился бы с первым молча (ADR-220). Сосед не измерил ⇒ польза
    ``None``, а не нуль: нуль читался бы как «ветвь не даёт ничего».
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "useful_claims": None, "neighbour_status": None,
                           "neighbour": CENSUS_MODULE}
    doc = report if report is not None else census.build_report(
        repo_root, journal_path=journal_path)
    out["neighbour_status"] = doc.get("status")
    if not doc.get("measured"):
        out["reason"] = (f"сосед {CENSUS_MODULE} НЕ ИЗМЕРИЛ: {doc.get('reason')} — "
                         "польза ветви берётся у него, своего экземпляра нет (ADR-220)")
        return out
    useful = observed(doc.get("open_claims") or {},
                      "card_declared_done_by_another_identity", kind=int)
    if useful is None:
        out["reason"] = ("у отчёта соседа нет поля "
                         "`open_claims.card_declared_done_by_another_identity` — "
                         "польза ветви НЕ ИЗМЕРЕНА (поле переименовано?)")
        return out
    out["measured"] = True
    out["useful_claims"] = useful
    return out


# ───────────── ось B: ВРЕД ветви — перепроигрывание живого журнала ─────────────

def _own_releases(releases: Sequence[Dict[str, Any]]) -> Dict[Tuple[Any, str], List[datetime]]:
    """(личность, карточка) → отсортированные времена её СОБСТВЕННЫХ освобождений."""
    out: Dict[Tuple[Any, str], List[datetime]] = {}
    for row in releases:
        out.setdefault((row["identity"], row["card"]), []).append(row["ts"])
    for stamps in out.values():
        stamps.sort()
    return out


def _last_voice(records: Sequence[Dict[str, Any]], *, census, sibling) -> Dict[Any, datetime]:
    """Личность → время её ПОСЛЕДНЕЙ записи в журнале, любой.

    Население здесь ШИРЕ, чем у захватов: свидетельством жизни служит ЛЮБАЯ запись, а
    не только относящаяся к карточке. Сузить до карточных значило бы объявить мёртвым
    держателя, который в тот час писал про другую работу.
    """
    out: Dict[Any, datetime] = {}
    for record in records:
        stamp = sibling._parse_ts(record.get("ts"))
        if stamp is None:
            continue
        identity = census.identity_of(record, sibling)
        if identity not in out or stamp > out[identity]:
            out[identity] = stamp
    return out


def measure_harm(records: Sequence[Dict[str, Any]],
                 claims: Sequence[Dict[str, Any]],
                 releases: Sequence[Dict[str, Any]], *,
                 census, sibling) -> Dict[str, Any]:
    """Чей ОТКРЫТЫЙ захват снял бы каждый чужой ``done`` — и что известно о его жизни.

    Порядок ровно такой: сначала «кого задело» (это арифметика над журналом, и она
    точна), потом «что журнал свидетельствует о держателе в ТОТ момент» (и здесь три
    исхода, а не два).

    Захват считается ОТКРЫТЫМ в момент чужого освобождения, если своего ``done`` по той
    же карточке у держателя между захватом и этим моментом не было. Сравнение ``>=``
    взято у двери (``check_card_claim``: ``done`` раньше захвата повторное взятие не
    снимает), а не выбрано здесь.
    """
    if not releases:
        return {"measured": False,
                "reason": ("освобождений в журнале нет — чужого `done` не существует, "
                           "и вред ветви «по карточке» нечем мерить")}
    own = _own_releases(releases)
    voice = _last_voice(records, census=census, sibling=sibling)

    claims_by_card: Dict[str, List[Dict[str, Any]]] = {}
    for row in claims:
        claims_by_card.setdefault(row["card"], []).append(row)

    # Один и тот же захват бывает задет несколькими чужими `done`; вред считается ПО
    # ЗАХВАТУ и по ПЕРВОМУ задевшему его освобождению — именно оно и сняло бы его.
    victims: Dict[int, Dict[str, Any]] = {}
    hits = 0
    stripping_dones = set()
    for release in releases:
        for claim in claims_by_card.get(release["card"], ()):
            if claim["identity"] == release["identity"]:
                continue
            if claim["ts"] > release["ts"]:
                continue
            mine = own.get((claim["identity"], claim["card"]), ())
            if any(claim["ts"] <= stamp <= release["ts"] for stamp in mine):
                continue
            hits += 1
            stripping_dones.add(id(release))
            key = id(claim)
            known = victims.get(key)
            if known is None or release["ts"] < known["done_ts"]:
                victims[key] = {"claim": claim, "done_ts": release["ts"],
                                "by": release["identity"]}

    by_outcome: Dict[str, int] = {name: 0 for name in OUTCOMES}
    identity_from: Dict[str, int] = {"anchor": 0, "label": 0}
    strictly_before = 0
    same_second = 0
    never_closed = 0
    examples: Dict[str, List[Dict[str, Any]]] = {name: [] for name in OUTCOMES}
    for row in victims.values():
        claim, done_ts = row["claim"], row["done_ts"]
        identity_from[claim["identity"][0]] += 1
        later_own = [s for s in own.get((claim["identity"], claim["card"]), ())
                     if s > done_ts]
        if later_own:
            outcome = WITNESSED_WORKING
            evidence = later_own[0]
        else:
            never_closed += 1
            spoke = voice.get(claim["identity"])
            if spoke is not None and spoke > done_ts:
                outcome, evidence = WITNESSED_ALIVE, spoke
            else:
                outcome, evidence = NO_EVIDENCE, None
        by_outcome[outcome] += 1
        if outcome != NO_EVIDENCE:
            if claim["ts"] < done_ts:
                strictly_before += 1
            else:
                same_second += 1
        if len(examples[outcome]) < 5:
            examples[outcome].append({
                "card": claim["card"],
                "identity_from": claim["identity"][0],
                "claimed_at": claim["ts"].isoformat().replace("+00:00", "Z"),
                "foreign_done_at": done_ts.isoformat().replace("+00:00", "Z"),
                "evidence_at": (None if evidence is None
                                else evidence.isoformat().replace("+00:00", "Z")),
                "gap_hours": round((done_ts - claim["ts"]).total_seconds() / _HOUR, 2),
            })

    witnessed = by_outcome[WITNESSED_WORKING] + by_outcome[WITNESSED_ALIVE]
    return {
        "measured": True,
        "reason": None,
        "affected_claims": len(victims),
        "foreign_done_hits": hits,
        "foreign_dones_that_would_strip": len(stripping_dones),
        "by_outcome": by_outcome,
        "witnessed_harm": witnessed,
        "witnessed_strictly_after_claim": strictly_before,
        "witnessed_in_the_same_second": same_second,
        "never_closed_by_holder": never_closed,
        "identity_from": identity_from,
        "examples": examples,
        "lower_bound": ("вред есть НИЖНЯЯ граница: свидетельством служит только то, что "
                        "держатель успел НАПИСАТЬ; работа, оборванная до объявления, "
                        "журналу неизвестна по построению"),
        "means": (f"«{NO_EVIDENCE}» — третий исход инв. #17, а НЕ «держатель был мёртв»: "
                  "молчание после чужого `done` уликой смерти не является"),
    }


def cross_check(benefit: Dict[str, Any], harm: Dict[str, Any]) -> Dict[str, Any]:
    """Сходится ли население соседа с долей «полезного» из перепроигрывания.

    Это сверка СОСТАВА, а не второе мнение: условие у обоих приборов одно и то же
    (захват, который держатель не закрывал, при карточке, закрытой другой личностью),
    поэтому равенство ожидаемо ПО ПОСТРОЕНИЮ. Ценность у него обратная — РАСХОЖДЕНИЕ
    означает, что один из двух читает не то население, и молчать о нём нельзя.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None, "agrees": None,
                           "neighbour_useful": None, "replay_never_closed": None}
    if not benefit.get("measured") or not harm.get("measured"):
        out["reason"] = ("сверка состава невозможна: "
                         + ("польза не измерена" if not benefit.get("measured")
                            else "вред не измерен"))
        return out
    out["measured"] = True
    out["neighbour_useful"] = benefit["useful_claims"]
    out["replay_never_closed"] = harm["never_closed_by_holder"]
    out["agrees"] = benefit["useful_claims"] == harm["never_closed_by_holder"]
    if not out["agrees"]:
        out["reason"] = ("РАСХОЖДЕНИЕ состава: у соседа полезных захватов "
                         f"{benefit['useful_claims']}, у перепроигрывания незакрытых "
                         f"держателем {harm['never_closed_by_holder']} — один из двух "
                         "приборов читает не то население")
    return out


# ──────── ось C: что делает НАСТОЯЩАЯ дверь с захватом ЖИВОГО держателя ────────

def _release_record(announcer, log: Path, *, card: str, session: str) -> None:
    """Дописать в журнал сцены ``card_state: done`` — НАСТОЯЩИМ писателем.

    Личность освобождения подаётся ЯРЛЫКОМ и без якоря: у двери личность освобождения
    служит только ключом, а якорь на чужой записи писатель и так не ставит
    (``log_session_change.record``, «announcing for somebody else yields no anchor»).
    """
    announcer.record(f"сцена прибора: объявление `done` по карточке {card}", [],
                     "сцена развилки адресата освобождения",
                     card=card, card_state="done", log=str(log), session=session)


def measure_door(repo_root: Path, *, guard_loader=None,
                 holder: Optional[Dict[str, Any]] = None,
                 stranger_pid: Optional[int] = None) -> Dict[str, Any]:
    """Отдала бы дверь карточку постороннему — по каждой ветви развилки отдельно.

    Сцена и способ те же, что у оси D ADR-535 и оси C ADR-684: вызывается ровно их
    ``_write_sandbox``/``_ask_guard``, то есть второй копии мерки не появляется. Новое
    здесь — ДОПИСКА освобождения (``_release_record``) и то, что вопрос задаётся ДВАЖДЫ:
    с ярлыком постороннего (ветвь «по держателю», как сегодня) и с ярлыком держателя
    (ветвь «по карточке» — см. «Эквивалентность» в шапке модуля).

    Держатель обязан быть ЧУЖИМ и живым ПО ПОСТРОЕНИЮ: свой захват дверь блокирующим не
    считает, поэтому на своём якоре любая ветвь выглядела бы безвредной. Это проверяется
    ИСХОДОМ (``self_claims`` в отчёте двери), а не доверием к номеру.
    """
    out: Dict[str, Any] = {"measured": False, "reason": None,
                           "verdict_without_done": None, "by_branch": {},
                           "holder": None, "stranger_label": None}
    holder = holder if holder is not None else live_other_anchor()
    out["holder"] = {"pid": holder.get("pid"), "measured": bool(holder.get("measured"))}
    if not holder.get("measured"):
        out["reason"] = (f"личность ЧУЖОЙ ЖИВОЙ сессии НЕ ИЗМЕРЕНА — {holder.get('reason')}; "
                         "судить о том, что дверь отдаёт карточку живого держателя, по "
                         "неизмеренному номеру запрещено")
        return out
    holder_label = f"pid{holder['pid']}"
    # Посторонний — СВОЙ номер: он жив по построению на любом хосте и при этом не равен
    # номеру держателя (``os.getppid()`` ≠ ``os.getpid()``). Освобождению живость не
    # нужна вовсе (у двери это ключ), но литеральный номер здесь был бы той же бомбой,
    # что и литеральная дата (``.claude/rules/deployment.md``, личность процесса).
    stranger_pid = stranger_pid if stranger_pid is not None else os.getpid()
    if stranger_pid == holder["pid"]:
        out["reason"] = (f"номер постороннего совпал с номером держателя ({stranger_pid}) — "
                         "ветви развилки на такой сцене неразличимы")
        return out
    stranger_label = f"pid{stranger_pid}"
    out["stranger_label"] = stranger_label

    scene = Path(tempfile.mkdtemp(prefix="spa_foreign_done_"))
    answers: Dict[str, Dict[str, Any]] = {}
    try:
        guard = (guard_loader or _load_guard)(repo_root)
        announcer = guard.load_announcer()
        tracker, log = _write_sandbox(scene / "base", _SCENE_CARD, announcer=announcer,
                                      receipt_anchor=holder)
        answers["base"] = _ask_guard(guard, tracker, log, _SCENE_CARD)

        tracker, log = _write_sandbox(scene / BRANCH_HOLDER, _SCENE_CARD,
                                      announcer=announcer, receipt_anchor=holder)
        _release_record(announcer, log, card=_SCENE_CARD, session=stranger_label)
        answers[BRANCH_HOLDER] = _ask_guard(guard, tracker, log, _SCENE_CARD)

        tracker, log = _write_sandbox(scene / BRANCH_CARD, _SCENE_CARD,
                                      announcer=announcer, receipt_anchor=holder)
        _release_record(announcer, log, card=_SCENE_CARD, session=holder_label)
        answers[BRANCH_CARD] = _ask_guard(guard, tracker, log, _SCENE_CARD)
    except Exception as exc:  # noqa: BLE001 — сцена могла не собраться как угодно
        out["reason"] = f"сцена пробы не отработала: {type(exc).__name__}: {exc}"
        return out
    finally:
        shutil.rmtree(scene, ignore_errors=True)

    verdicts = {name: observed(row["report"], "verdict", kind=str)
                for name, row in answers.items()}
    missing = sorted(name for name, value in verdicts.items() if value is None)
    if missing:
        out["reason"] = ("вердикт не произведён на сценах: " + ", ".join(missing)
                         + " — о неоткрытой двери прибор не судит")
        return out
    out["verdict_without_done"] = verdicts["base"]
    if verdicts["base"] != "claimed":
        out["reason"] = (f"базовый вердикт сцены `{verdicts['base']}`, а не `claimed` — "
                         "живого держателя дверь на этой сцене не видит, и отдавать "
                         "ей нечего: вред ветви нечем измерить")
        return out
    for branch in BRANCHES:
        if observed(answers[branch]["report"], "self_claims", kind=list):
            out["reason"] = ("якорь держателя опознан дверью как МОЙ — вред мерился бы "
                             "на самозахвате, который дверь блокирующим не считает")
            return out
    if verdicts[BRANCH_HOLDER] == verdicts[BRANCH_CARD]:
        out["reason"] = ("вердикты обеих ветвей равны "
                         f"(`{verdicts[BRANCH_HOLDER]}`) — сцена ветви развилки НЕ "
                         "РАЗЛИЧАЕТ, и «вред есть» было бы утверждением о приборе, "
                         "а не о двери")
        return out

    out["measured"] = True
    for branch in BRANCHES:
        verdict = verdicts[branch]
        out["by_branch"][branch] = {
            "verdict": verdict,
            "exit_code": answers[branch]["code"],
            "outcome": (DOOR_PROTECTS if verdict == "claimed" else DOOR_HANDS_OVER),
        }
    out["one_holder_scene"] = (
        "сцена несёт ОДНОГО держателя, поэтому «снять всех» и «снять этого» дают один "
        "вердикт; на сцене с двумя держателями равенство ветви и ярлыка пришлось бы "
        "доказывать отдельно")
    return out


# ─────────────────────────────── сборка отчёта ───────────────────────────────

def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 journal_path: Optional[Path] = None,
                 census=None, door=None,
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
        "benefit": None,
        "harm": None,
        "cross_check": None,
        "door": None,
    }
    # Имя модуля читается в МОМЕНТ ВЫЗОВА, а не прибивается умолчанием: иначе «соседа
    # не ввезли» было бы ветвью, в которую не попасть ни одной сценой, то есть
    # необлагаемым обещанием (урок `pyflakes`: отсутствие инструмента — третий исход,
    # и у него обязан быть контроль).
    try:
        census = census if census is not None else load_census(CENSUS_MODULE)
    except Exception as exc:  # noqa: BLE001 — сосед не ввезён есть третий исход
        report["reason"] = (f"сосед {CENSUS_MODULE} не ввезён: {type(exc).__name__}: {exc} — "
                            "население и польза берутся у него, своего экземпляра нет")
        return report

    kin = neighbours if neighbours is not None else census.load_neighbours(repo_root)
    if kin["missing"]:
        report["reason"] = ("не загружены соседние мерки: " + ", ".join(kin["missing"])
                            + " — терминальность освобождения и разбор времени "
                              "спрашиваются у них (ADR-220)")
        return report
    guard, sibling = kin["guard"], kin["sibling"]

    path = Path(journal_path) if journal_path is not None else repo_root / census.JOURNAL_REL
    journal = census.read_journal(path)
    if journal["records"] is None:
        report["reason"] = journal["reason"]
        return report

    population = census.split_population(journal["records"], guard=guard, sibling=sibling)
    claims, releases = population["claims"], population["releases"]
    report["population"] = {
        "journal": str(path),
        "records": len(journal["records"]),
        "broken_lines": journal["broken_lines"],
        "claims": len(claims),
        "releases": len(releases),
        "records_without_card": population["records_without_card"],
        "records_with_card_unparsed_ts": population["records_with_card_unparsed_ts"],
    }
    if not claims:
        report["reason"] = ("захватов в журнале нет: «чужой `done` ничего не снял бы» при "
                            "нуле захватов верно ПО ПОСТРОЕНИЮ и замером не является")
        return report

    report["benefit"] = measure_benefit(repo_root, census=census, journal_path=path)
    harm = measure_harm(journal["records"], claims, releases,
                        census=census, sibling=sibling)
    report["harm"] = harm
    report["cross_check"] = cross_check(report["benefit"], harm)
    report["door"] = door if door is not None else measure_door(repo_root)

    if not harm["measured"]:
        report["reason"] = f"ось B: {harm['reason']}"
        return report
    # «Задетых захватов ноль» доходит сюда как ИЗМЕРЕННЫЙ нуль: третий исход уже
    # сработал выше, на нуле захватов и на нуле освобождений, где мерить нечего ПО
    # ПОСТРОЕНИЮ. Поставить его ещё и здесь значило бы склеить второй и третий исходы
    # инв. #17 — здоровый контур докладывал бы «НЕ ИЗМЕРЕНО» (урок соседа ADR-536).
    report["measured"] = True
    report["status"] = (STATUS_STRIPS_LIVE if harm["witnessed_harm"] > 0
                        else STATUS_NOT_WITNESSED)
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if not report.get("measured"):
        lines.append("цена ветви «освобождение по КАРТОЧКЕ» (заказ G111 п. 1): "
                     f"НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    pop, benefit = report["population"], report["benefit"]
    harm, check, door = report["harm"], report["cross_check"], report["door"]

    lines.append(f"цена ветви «освобождение по КАРТОЧКЕ» (заказ G111 п. 1): "
                 f"{report['status']} · захватов {pop['claims']} · освобождений "
                 f"{pop['releases']} (записей {pop['records']}, битых строк "
                 f"{pop['broken_lines']})")
    if benefit.get("measured"):
        lines.append(f"[ОСЬ A] ПОЛЬЗА ветви числом СОСЕДА ({benefit['neighbour']}, "
                     f"{benefit['neighbour_status']}): закрыла бы "
                     f"{benefit['useful_claims']} захватов, стоящих открытыми при "
                     f"закрытой карточке")
    else:
        lines.append(f"[ОСЬ A] НЕ ИЗМЕРЕНО — {benefit.get('reason')}")
    by = harm["by_outcome"]
    lines.append(f"[ОСЬ B] ВРЕД ветви: чужой `done` задел бы {harm['affected_claims']} "
                 f"захватов ({harm['foreign_done_hits']} задеваний у "
                 f"{harm['foreign_dones_that_would_strip']} освобождений); личность по "
                 f"якорю {harm['identity_from']['anchor']}, по ярлыку "
                 f"{harm['identity_from']['label']}")
    lines.append(f"[ОСЬ B] из них держатель РАБОТАЛ дальше (объявил своё `done` позже) "
                 f"{by[WITNESSED_WORKING]} · был ЖИВ, но карточку не закрыл "
                 f"{by[WITNESSED_ALIVE]} · свидетельств НЕТ {by[NO_EVIDENCE]} "
                 f"⇒ засвидетельствованный вред {harm['witnessed_harm']}")
    lines.append(f"[ОСЬ B] у засвидетельствованного вреда захват строго раньше чужого "
                 f"`done` в {harm['witnessed_strictly_after_claim']} случаях, в ту же "
                 f"секунду — {harm['witnessed_in_the_same_second']}")
    lines.append(f"[ОСЬ B] {harm['means']}")
    lines.append(f"[ОСЬ B] {harm['lower_bound']}")
    if check.get("measured"):
        lines.append("[СВЕРКА] состав населений "
                     + ("СОШЁЛСЯ" if check["agrees"] else "РАСОШЁЛСЯ")
                     + f": у соседа полезных {check['neighbour_useful']}, у "
                       f"перепроигрывания незакрытых держателем "
                       f"{check['replay_never_closed']}"
                     + ("" if check["agrees"] else f" — {check['reason']}"))
    else:
        lines.append(f"[СВЕРКА] НЕ ИЗМЕРЕНО — {check.get('reason')}")
    if door.get("measured"):
        lines.append(f"[ОСЬ C] базовый вердикт сцены с ЖИВЫМ держателем "
                     f"`{door['verdict_without_done']}`; держатель pid"
                     f"{door['holder']['pid']}, посторонний {door['stranger_label']}")
        for branch in BRANCHES:
            row = door["by_branch"][branch]
            lines.append(f"[ОСЬ C] ветвь `{branch}`: вердикт `{row['verdict']}` "
                         f"(код {row['exit_code']}) ⇒ {row['outcome']}")
        lines.append(f"[ОСЬ C] {door['one_holder_scene']}")
    else:
        lines.append(f"[ОСЬ C] НЕ ИЗМЕРЕНО — {door.get('reason')}")
    if report["status"] == STATUS_STRIPS_LIVE:
        lines.append(
            "ВЫВОД: развилка ДВУСТОРОННЯЯ, и обе её стороны измерены на ОДНОМ событии. "
            f"Ветвь «по карточке» закрыла бы {benefit.get('useful_claims')} мёртвых "
            f"захватов и сняла бы {harm['witnessed_harm']} таких, у которых держатель "
            "работал дальше — последнее есть НИЖНЯЯ граница. Выбор адресата остаётся "
            "решением: прибор его НЕ делает")
    lines.append("НЕ ДОКЛАДЫВАЕТ: был ли держатель жив, если он молчал (молчание не "
                 "улика) · что оборвала бы ветвь ДО объявления · сделана ли работа "
                 "(журнал знает объявления, не результат) · какую ветвь выбрать")
    lines.append("ADVISORY: прибор только ЧИТАЕТ (applied=False) — RiskPolicy v1.0, "
                 "стоп-кран, аллокатор, живой трек и landing/ не трогаются; ни ветви, "
                 "ни срока, ни правки правила освобождения прибор не заводит")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (``findings_bridge``).

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
    return 1 if report["status"] == STATUS_STRIPS_LIVE else 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--journal", default=None,
                    help="журнал объявлений (по умолчанию — журнал соседа ADR-536)")
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
