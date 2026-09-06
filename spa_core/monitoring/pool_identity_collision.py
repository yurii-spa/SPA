"""pool_identity_collision.py — ДВА ключа протокола, ОДИН контракт.

Вопрос, на который не отвечал ни один сторож
============================================
Потолок концентрации (`per-protocol cap`) считает позиции по КЛЮЧУ ПРОТОКОЛА.
Он молча предполагает, что разные ключи — разные предметы риска. Если два ключа
ранжируются на ОДНОМ пуле DeFiLlama, книга берёт удвоенную долю одного контракта,
а каждый потолок при этом честно доложит, что не нарушен.

Про адаптеры уже спрашивают четырёх сторожей, и каждый отвечает на СВОЙ вопрос:

| вопрос | кто отвечает | чего НЕ проверяет |
|---|---|---|
| фид вообще жив? | ``adapter_watchdog`` | на что он показывает |
| число живое или литерал? | провенанс ``tvl_source`` | тождество пула |
| два артефакта говорят одно? | ``adapter_feed_divergence`` | НЕ РАЗОШЛИСЬ ли они потому, что это ОДИН пул |
| два ПИНА не совпадают? | ``test_no_two_keys_share_a_pool`` | всё, что не запинено |

Последняя строка — ключевая. Тот тест обходит ``_POOL_ID_LOOKUP`` и сравнивает
пины между собой. Ключ, у которого пина НЕТ, в его популяцию не входит вовсе —
и это не оплошность, а прямое следствие принятого решения. Его собственный
докстринг говорит:

    «While wiring feeds on 2026-08-05, ``frax`` resolved to the same SFRAX pool
    as ``sfrax``, and ``fluid_usdc`` to the same pool as ``fluid_fusdc``.
    **Both were left unpinned for this reason.**»

Коллизия была ИЗВЕСТНА, и мерой против неё выбрали «не пинить». Но пин — это не
допуск к капиталу, а всего лишь запись тождества. Незапиненный ключ по-прежнему
резолвится в тот же пул (пином соседа, подсказкой или собственным запросом
адаптера в оркестраторе), по-прежнему получает живой APY, по-прежнему
ранжируется и по-прежнему финансируется. **«Не запинен» означает «не измерен»,
а не «не подвержен».** Ровно этот класс — «не измерено, выданное за ответ».

Замер на живом дереве 2026-09-04 (обе пары проверены по живому фиду DeFiLlama):

    fluid_usdc + fluid_fusdc   → 4438dabc-…  Ethereum/fluid-lending/USDC $150.1M
        fluid_fusdc запинен; fluid_usdc резолвится «best TVL wins» в ТОТ ЖЕ пул.
        В книге на момент замера: fluid_usdc $20 000 = 20 % (свой потолок T2).

    morpho_blue + morpho_steakhouse → 931ea9be-…  Ethereum/morpho-blue/STEAKUSDC $94.7M
        morpho_steakhouse запинен; morpho_blue ищет ``symbol`` в режиме
        "contains" и берёт лучший по TVL USDC-волт — сегодня это STEAKUSDC.
        Оба active, оба T2 по 20 %.

Песочный прогон аллокатора (positive control, живое ``data/`` не тронуто): при
обоих ключах Fluid, наблюдаемых с одинаковой доходностью, аллокатор фондирует
ОБА — $18 947 + $9 474 = **$28 421 в ОДИН пул**, при этом ``fluid_fusdc`` читается
как 18.9 %, ``fluid_usdc`` как 9.5 %, и НИ ОДИН потолок не нарушен. Структурный
предел пары — 20 % + 20 % = 40 % одного контракта под видом двух позиций.

Вторая половина: ОТКАЗ, до которого не доходит исполнение
=========================================================
``data/adapter_registry.json`` объявляет для ключа ``research_only`` и
``status``. Гейт фондирования читает их в ветке слияния реестра
(``allocator._load_adapters``), но ветка начинается со строки

    if name in seen_protocols:   continue   # already handled (orchestrator snapshot)

**Для любого ключа, который опрашивает оркестратор, проверка ``research_only``
недостижима** — до неё не доходит управление. Классовый гейт
(``_adapter_class_gate``) читает ``IS_ADVISORY``/``RESEARCH_ONLY`` с КЛАССА
адаптера, а это ДРУГОЕ объявление того же факта, и оно может молчать, когда
реестр отказывает.

Замер 04.09 по всем 43 ключам: расхождений ровно 2 (``ethena_susde``,
``fluid_usdc``), из них опрашивается 1 — и он же профинансирован на $20 000.
``ethena_susde`` не опрашивается, поэтому для него ветка реестра ДОСТИЖИМА и
отказ работает: разница между «расходится» и «расходится и недостижим»
существенна, и сторож обязан их различать, иначе он кричит о безвредном.

Что этот модуль НЕ делает
=========================
Не выбирает победивший ключ, не двигает капитал, не гейтит исполнение, не
трогает RiskPolicy и ничего не пинит. **Только называет.** Какой из двух ключей
лишний и что делать с уже размещёнными $20 000 — решение владельца (карточка),
а не автономная правка: это money-path.

Почему тождество меряется ДВУМЯ независимыми способами
======================================================
Ни один из них не полон сам по себе, и у них разные слепые пятна.

* ``declared`` — два ключа НАЗЫВАЮТ один UUID (пин в ``_POOL_ID_LOOKUP``,
  ``tvl_pool_id`` наблюдения, ``pool_id`` снимка оркестратора — ADR-233/238 —
  или ``identity_pool_id`` класса — ADR-237). Точно и проверяемо. До 06.09
  четвёртого источника здесь не было, и род видел только запиненное; ключ,
  наблюдение которого приходит от оркестратора, выпадал из него ПО ПОСТРОЕНИЮ —
  а это все одиннадцать опрашиваемых.
* ``observed`` — два ключа в ОДНОМ такте предъявили ОДИНАКОВЫЕ живой TVL и живой
  APY. Это улика, а не подпись: независимые пулы не совпадают до цента. Именно
  она находит незапиненное (обе пары выше найдены ею), и именно она ловит
  «best TVL wins», который может перескочить на соседний волт завтра.

Оба рода считаются ОТДЕЛЬНО и помечаются в находке, потому что чинятся они
по-разному: ``declared`` — снять лишний пин, ``observed`` — закрепить тождество
(запинить) и решить, какой ключ остаётся.

**Сравнение идёт ПО ОБОИМ артефактам сразу.** Пара Fluid живёт в РАЗНЫХ файлах
(``fluid_usdc`` — только в снимке оркестратора, ``fluid_fusdc`` — только в
``adapter_status.json``), поэтому сторож, глядящий внутрь одного артефакта, её
не увидит по построению. Так её и не видели.

Чем измеряется «один такт»
==========================
Разные моменты — разные числа, и совпадение TVL до цента между вчера и сегодня
не значит ничего. Поэтому: разрыв отметок больше ``MAX_SKEW_S`` ⇒ ``UNCHECKED``;
любой вход старше ``MAX_AGE_S`` ⇒ ``UNCHECKED``; возраст не измерен ⇒ это
ГОВОРИТСЯ, а не подразумевается свежим. Время — ВХОД (``now=``), а не окружение
(`.claude/rules/deployment.md`).

Fail-CLOSED
===========
Файла нет / JSON битый / нет секции адаптеров ⇒ ``UNCHECKED`` и код 2.
**Ни одного ключа, пригодного к сверке, ⇒ ``UNCHECKED``, а не чистый зачёт:**
сторож, которому нечего было сравнить, обязан отличаться от сторожа, который
сравнил и не нашёл коллизий (инвариант «третий исход»).

Коды возврата: 0 — коллизий нет · 1 — есть WARN · 2 — CRITICAL или UNCHECKED.
LLM_FORBIDDEN. Только stdlib. Читает read-only, пишет ОДИН свой артефакт.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections import defaultdict
from typing import Any

from spa_core.monitoring.architecture_conformance import REPO_ROOT, _parse_iso
from spa_core.utils.atomic import atomic_save

REPORT_REL = os.path.join("data", "pool_identity_collision.json")
STATUS_REL = os.path.join("data", "adapter_status.json")
ORCH_REL = os.path.join("data", "adapter_orchestrator_status.json")
REGISTRY_REL = os.path.join("data", "adapter_registry.json")
POSITIONS_REL = os.path.join("data", "current_positions.json")

#: Тот же потолок разрыва, что у ``adapter_feed_divergence``: оба артефакта пишет
#: один дневной цикл подряд (замер 26.08 — 0.6 с), запас взят на медленный опрос.
MAX_SKEW_S = 900.0

#: Старше этого — сторож отказывается судить. 26 ч = такт дневного цикла + запас.
MAX_AGE_S = 26 * 3600.0

#: Допуск совпадения APY, процентных пунктов. Обе стороны печатают округлённое до
#: 4 знаков; порог на порядок выше шума округления и на порядки ниже любой
#: осмысленной разницы между двумя РАЗНЫМИ пулами.
APY_TOLERANCE_PP = 0.001

#: Допуск совпадения TVL, доля. Ноль был бы хрупок к округлению при записи, но
#: допуск должен остаться НИЧТОЖНЫМ: смысл улики в том, что два независимых пула
#: не совпадают до цента. 1e-6 от $150M — это $150, то есть всё ещё «до цента»
#: в масштабе, где соседний по величине волт отстоит на миллионы.
TVL_TOLERANCE_FRAC = 1e-6

CRITICAL, WARN, INFO, UNCHECKED = "CRITICAL", "WARN", "INFO", "UNCHECKED"

#: ЧЕМ ключ назвал свой пул. Три источника чинятся по-разному, поэтому в находке
#: они не сливаются: пин — «снять лишний пин»; наблюдение — «закрепить тождество»;
#: объявление класса (ADR-237) — ключ на этот пул НЕ ранжируется вовсе, он им
#: ЯВЛЯЕТСЯ, а ранжируется литералом, и чинится это решением владельца о том,
#: какой из двух ключей остаётся.
NAMED_BY_PIN = "пин"
NAMED_BY_OBSERVATION = "наблюдение"
NAMED_BY_CLASS = "объявление класса"

#: Статусы записи оркестратора, при которых наблюдение считается состоявшимся.
_OK_STATUSES = ("ok", "partial")


def _load(rel: str, root: str, data_dir: str | None = None):
    """Прочитать артефакт. Возвращает ``(doc, error)`` — ошибка ГОВОРИТСЯ, не глотается."""
    if data_dir:
        path = os.path.join(data_dir, os.path.basename(rel))
    else:
        path = os.path.join(root, rel)
    if not os.path.exists(path):
        return None, f"{os.path.basename(path)}: файла нет ({path})"
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh), None
    except Exception as exc:  # noqa: BLE001 — битый JSON обязан быть НАЗВАН
        return None, f"{os.path.basename(path)}: не читается — {exc}"


def _age_s(doc: dict, now: dt.datetime) -> float | None:
    """Возраст артефакта в секундах, или None если отметку разобрать не удалось."""
    for field in ("generated_at", "timestamp", "run_ts"):
        raw = doc.get(field)
        if isinstance(raw, str):
            ts = _parse_iso(raw)
            if ts is not None:
                return (now - ts).total_seconds()
    return None


def _stamp(doc: dict) -> dt.datetime | None:
    for field in ("generated_at", "timestamp", "run_ts"):
        raw = doc.get(field)
        if isinstance(raw, str):
            ts = _parse_iso(raw)
            if ts is not None:
                return ts
    return None


def _num(v: Any) -> float | None:
    """Число или None. ``bool`` — НЕ число (``True`` иначе стало бы 1.0)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and abs(f) != float("inf") else None


def _observations(orch: dict, status: dict) -> tuple[dict[str, dict], list[str]]:
    """Живые наблюдения по ключу протокола, СЛИТЫЕ из ОБОИХ артефактов.

    Пара Fluid живёт в разных файлах — сторож, читающий один артефакт, её не
    увидит по построению. Ключ, объявленный обоими, берётся от оркестратора
    (это первичный опрос); значение второго артефакта не затирает первое, а
    расхождение ЧИСЕЛ между ними — предмет ДРУГОГО сторожа
    (``adapter_feed_divergence``).

    ADR-238 — ПОДПИСЬ ЧИТАЕТСЯ И СО СТОРОНЫ ОРКЕСТРАТОРА. До 06.09 здесь стояло
    жёсткое ``"pool_id": None`` с оговоркой «пул-UUID оттуда не приходит
    никогда». Оговорка была верна ровно до ADR-233 (05.09), который научил
    снимок оркестратора нести ``pool_id`` на всех путях, включая отказные, —
    и перестала быть верной, не изменившись ни на символ. Производитель есть,
    потребитель говорит ``None``: род ``declared`` был слеп ко ВСЕМ одиннадцати
    опрашиваемым ключам, потому что их наблюдение приходит именно отсюда.

    Почему это не косметика. Род ``observed`` — улика, а не подпись: он требует
    совпадения живых TVL и APY с точностью ``1e-6`` / ``0.001`` пп. Два
    производителя опрашивают фид в РАЗНЫЕ моменты, и настоящая коллизия
    становится ему невидима просто оттого, что пул сдвинулся между двумя
    запросами. Подпись этим не сбить — но её выбрасывали здесь.

    Возвращает ``(наблюдения, строки «не измерено»)``. Второе — не украшение:
    если ДВА артефакта называют для одного ключа РАЗНЫЕ пулы, тождество этого
    ключа не установлено, и молча взять первое значило бы выдать «не измерено»
    за ответ. Такой ключ теряет подпись (``pool_id=None``, род ``observed``
    продолжает его видеть) и получает названную строку.
    """
    out: dict[str, dict] = {}
    unchecked: list[str] = []

    rows = orch.get("adapters")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("protocol")
            if not isinstance(key, str) or not key:
                continue
            if str(row.get("status", "ok")) not in _OK_STATUSES:
                continue
            if not row.get("live_data") or row.get("tvl_source") != "live":
                continue
            tvl, apy = _num(row.get("tvl_usd")), _num(row.get("apy_pct"))
            if tvl is None or apy is None or tvl <= 0:
                continue
            pid = row.get("pool_id")
            pid = pid.strip() if isinstance(pid, str) else None
            out[key] = {"tvl_usd": tvl, "apy_pct": apy,
                        "pool_id": pid or None, "source": "orchestrator"}

    rows2 = status.get("adapters")
    if isinstance(rows2, dict):
        for key, row in rows2.items():
            if not isinstance(key, str) or not isinstance(row, dict):
                continue
            if row.get("tvl_source") != "live":
                continue
            tvl, apy = _num(row.get("tvl_usd")), _num(row.get("live_apy"))
            if tvl is None or apy is None or tvl <= 0:
                continue
            pool_id = row.get("tvl_pool_id")
            pool_id = pool_id if isinstance(pool_id, str) and pool_id else None
            if key in out:
                # Ключ уже взят от оркестратора. С ADR-238 подпись может прийти
                # с ОБЕИХ сторон, поэтому здесь три исхода, а не два.
                theirs = out[key]["pool_id"]
                if theirs is None:
                    if pool_id:
                        out[key]["pool_id"] = pool_id      # дополняет
                elif pool_id and pool_id != theirs:
                    # Спор подписей: два артефакта называют РАЗНЫЕ пулы за одним
                    # ключом. Это и есть находка ADR-233 (`aave_v3`), и разрешать
                    # её выбором стороны сторож не вправе — тождество ключа НЕ
                    # УСТАНОВЛЕНО, пока спор не разрешён.
                    out[key]["pool_id"] = None
                    unchecked.append(
                        f"{key}: артефакты называют РАЗНЫЕ пулы — оркестратор "
                        f"{theirs}, adapter_status {pool_id}; подпись тождества "
                        f"НЕ ИЗМЕРЕНА (род `declared` этот ключ не берёт)")
                continue
            out[key] = {"tvl_usd": tvl, "apy_pct": apy,
                        "pool_id": pool_id, "source": "adapter_status"}
    return out, unchecked


def _same_pool(a: dict, b: dict) -> bool:
    """Совпали ли живые TVL и APY двух наблюдений в пределах ничтожного допуска."""
    ta, tb = a["tvl_usd"], b["tvl_usd"]
    if abs(ta - tb) > TVL_TOLERANCE_FRAC * max(abs(ta), abs(tb)):
        return False
    return abs(a["apy_pct"] - b["apy_pct"]) <= APY_TOLERANCE_PP


def _identities(status: dict) -> dict[str, str]:
    """Тождества, объявленные КЛАССОМ ключа (ADR-237) — ``identity_pool_id``.

    Третий источник имени пула, и единственный, который видит ключ, чей путь к
    фиду не разрешился вовсе. Пин и наблюдение оба требуют, чтобы ключ УЖЕ
    резолвился; ключ, ранжируемый литералом, не резолвится по построению — и
    потому в популяцию двух прежних родов не входил (замер 06.09: таких ключей
    12 из 34, на них $200 778 советательного капитала).

    Отсутствие поля — не пустота, а старый артефакт: генератор пишет его с
    ADR-237. Читатель просто не находит тождеств, и это честно видно по
    ``keys_compared``.
    """
    out: dict[str, str] = {}
    rows = status.get("adapters")
    if not isinstance(rows, dict):
        return out
    for key, row in rows.items():
        if not isinstance(key, str) or not isinstance(row, dict):
            continue
        pid = row.get("identity_pool_id")
        if isinstance(pid, str) and pid:
            out[key] = pid
    return out


def _declared_pairs(obs: dict[str, dict], pins: dict[str, str],
                    identities: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Ключи, НАЗЫВАЮЩИЕ один UUID.

    Три источника имени, и они не взаимозаменяемы: пин реестра генератора ·
    наблюдённый ``tvl_pool_id`` · объявленное классом ``identity_pool_id``
    (ADR-237). Третий добавлен потому, что первые два видят только ключ, который
    уже резолвится в пул, — а ``ethena_susde`` не резолвится и при этом означает
    ТОТ ЖЕ контракт, что запинённый ``susde``.
   
    Возвращает ``(пары, чем назвал каждый ключ)``. Второе — не украшение: у трёх
    источников РАЗНЫЕ починки, и находка, не назвавшая источник, отправляет
    чинить не туда.
    """
    by_pool: dict[str, list[str]] = defaultdict(list)
    named_by: dict[str, dict[str, str]] = defaultdict(dict)
    for key, pid in pins.items():
        if isinstance(pid, str) and pid:
            by_pool[pid].append(key)
            named_by[pid][key] = NAMED_BY_PIN
    for key, o in obs.items():
        pid = o.get("pool_id")
        if pid and key not in by_pool[pid]:
            by_pool[pid].append(key)
            named_by[pid].setdefault(key, NAMED_BY_OBSERVATION)
    for key, pid in (identities or {}).items():
        if key not in by_pool[pid]:
            by_pool[pid].append(key)
            named_by[pid].setdefault(key, NAMED_BY_CLASS)
    pairs = {pid: sorted(keys) for pid, keys in by_pool.items() if len(keys) > 1}
    return pairs, {pid: named_by[pid] for pid in pairs}


def _observed_groups(obs: dict[str, dict]) -> list[list[str]]:
    """Группы ключей с ОДИНАКОВЫМИ живыми (TVL, APY) в одном такте."""
    keys = sorted(obs)
    seen: set[str] = set()
    groups: list[list[str]] = []
    for i, k in enumerate(keys):
        if k in seen:
            continue
        group = [k]
        for other in keys[i + 1:]:
            if other not in seen and _same_pool(obs[k], obs[other]):
                group.append(other)
                seen.add(other)
        if len(group) > 1:
            seen.add(k)
            groups.append(group)
    return groups


def _load_pins() -> tuple[dict[str, str], str | None]:
    """Пины генератора. Импорт может не состояться — это ТРЕТИЙ ИСХОД, не пустота."""
    try:
        from spa_core.monitoring import adapter_status_generator as gen
        pins = getattr(gen, "_POOL_ID_LOOKUP", None)
        if not isinstance(pins, dict):
            return {}, "adapter_status_generator._POOL_ID_LOOKUP: не словарь"
        return dict(pins), None
    except Exception as exc:  # noqa: BLE001
        return {}, f"adapter_status_generator не импортируется — {exc}"


def _unreachable_refusals(registry: dict, obs: dict[str, dict],
                          orch_keys: set[str]) -> list[dict]:
    """Ключи, чей отказ в реестре НЕДОСТИЖИМ для гейта фондирования.

    Ветка слияния реестра в аллокаторе начинается с ``if name in seen_protocols:
    continue``, а ``seen_protocols`` наполняется из снимка оркестратора. Значит
    для опрашиваемого ключа ``research_only``/``status`` не читает НИКТО, и
    единственный оставшийся отказ — флаги КЛАССА адаптера, то есть другое
    объявление того же факта.
    """
    rows = registry.get("adapters")
    if not isinstance(rows, dict):
        return []
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        cls_by_key = {e[0]: e[2] for e in ADAPTER_REGISTRY
                      if isinstance(e, (list, tuple)) and len(e) >= 3}
    except Exception:  # noqa: BLE001 — без классов судить о втором объявлении нельзя
        cls_by_key = {}

    out: list[dict] = []
    for key, entry in sorted(rows.items()):
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        refuses = bool(entry.get("research_only")) or (
            status is not None and status != "active")
        if not refuses:
            continue
        cls = cls_by_key.get(key)
        class_refuses = bool(
            getattr(cls, "IS_ADVISORY", False) or getattr(cls, "RESEARCH_ONLY", False)
        ) if cls is not None else False
        if class_refuses:
            continue  # второе объявление говорит то же — отказ состоится
        out.append({
            "key": key,
            "registry_research_only": bool(entry.get("research_only")),
            "registry_status": status,
            "registry_per_protocol_cap": entry.get("per_protocol_cap"),
            "class_declares_refusal": class_refuses,
            "has_class": cls is not None,
            # Достижима ли ветка реестра. Опрашивается ⇒ НЕТ.
            "registry_branch_reachable": key not in orch_keys,
        })
    return out


def _book(positions_doc: dict | None,
          now: dt.datetime | None = None) -> tuple[dict[str, float] | None, str | None]:
    """Книга по протоколам, или ``(None, причина)`` если её измерить нечем.

    Возраст книги проверяется ТАК ЖЕ, как возраст фидов, и по той же причине.
    «В книге $20 000» из вчерашнего снимка — утверждение о вчера, а тяжесть
    находки (CRITICAL против WARN) держится именно на нём. Молча принять
    протухшую книгу значило бы поднять или опустить тревогу по ненаблюдаемому:
    ровно тот класс «не измерено, выданное за ответ», против которого написан
    весь модуль. Отдельно от «книга пуста» — пустая книга ИЗМЕРЕНА.
    """
    if not isinstance(positions_doc, dict):
        return None, "current_positions.json: не прочитан — размер позиций НЕ измерен"
    if now is not None:
        age = _age_s(positions_doc, now)
        if age is None:
            return None, ("current_positions.json: возраст не измерен (нет разбираемой "
                          "отметки) — о размере позиций НЕ сказано ничего")
        if age > MAX_AGE_S:
            return None, (f"current_positions.json: книге {age / 3600:.1f} ч при потолке "
                          f"{MAX_AGE_S / 3600:.0f} ч — размер позиций НЕ измерен, "
                          f"тяжесть находки понижена до WARN")
    pos = positions_doc.get("positions")
    if not isinstance(pos, dict):
        return None, "current_positions.json: нет секции positions — размер НЕ измерен"
    out = {}
    for k, v in pos.items():
        n = _num(v)
        if isinstance(k, str) and n is not None and n > 0:
            out[k] = n
    return out, None


def run(root: str = REPO_ROOT, now: dt.datetime | None = None,
        write: bool = True, data_dir: str | None = None) -> dict:
    """Сверить тождество пулов. Время — ВХОД, не окружение."""
    now = now or dt.datetime.now(dt.timezone.utc)

    findings: list[dict] = []
    unchecked: list[str] = []

    orch, e1 = _load(ORCH_REL, root, data_dir)
    status, e2 = _load(STATUS_REL, root, data_dir)
    registry, e3 = _load(REGISTRY_REL, root, data_dir)
    positions, _e4 = _load(POSITIONS_REL, root, data_dir)  # книга необязательна

    for err in (e1, e2, e3):
        if err:
            unchecked.append(err)

    obs: dict[str, dict] = {}
    orch_keys: set[str] = set()
    collisions: list[dict] = []
    refusals: list[dict] = []

    if orch is not None and status is not None:
        # Один ли это такт? Иначе сравниваются два МОМЕНТА, а не два тождества.
        a_orch, a_st = _age_s(orch, now), _age_s(status, now)
        if a_orch is None or a_st is None:
            unchecked.append(
                "возраст входов не измерен (нет разбираемой отметки) — "
                "о свежести НЕ сказано ничего")
        elif a_orch > MAX_AGE_S or a_st > MAX_AGE_S:
            unchecked.append(
                f"stale_input: снимку оркестратора {a_orch / 3600:.1f} ч, "
                f"adapter_status {a_st / 3600:.1f} ч при потолке "
                f"{MAX_AGE_S / 3600:.0f} ч — сторож не судит в настоящем времени "
                f"о вчерашнем снимке")
        else:
            s_orch, s_st = _stamp(orch), _stamp(status)
            skew = abs((s_orch - s_st).total_seconds()) if s_orch and s_st else None
            if skew is not None and skew > MAX_SKEW_S:
                unchecked.append(
                    f"snapshot_skew: отметки расходятся на {skew:.0f} с при потолке "
                    f"{MAX_SKEW_S:.0f} с — это два РАЗНЫХ такта, тождество по ним "
                    f"не измеряется")
            else:
                obs, obs_unchecked = _observations(orch, status)
                # ADR-238: спор подписей — самостоятельная строка «не измерено»,
                # а не молчание. Ключ при этом остаётся в сверке родом `observed`.
                unchecked.extend(obs_unchecked)
                rows = orch.get("adapters")
                if isinstance(rows, list):
                    orch_keys = {r.get("protocol") for r in rows
                                 if isinstance(r, dict) and isinstance(r.get("protocol"), str)}

                if len(obs) < 2:
                    # Нечего сравнивать — это НЕ «коллизий нет».
                    unchecked.append(
                        f"пригодных к сверке живых наблюдений: {len(obs)} — сравнивать "
                        f"нечего; «коллизий нет» об этом НЕ сказано")
                else:
                    pins, pin_err = _load_pins()
                    if pin_err:
                        unchecked.append(pin_err + " — род `declared` не измерен")
                    book, book_err = _book(positions, now)
                    if book_err:
                        unchecked.append(book_err)
                        book = {}

                    declared, named_by = _declared_pairs(
                        obs, pins, _identities(status))
                    groups = _observed_groups(obs)

                    # Слить оба рода в один список коллизий, помечая, чем найдено.
                    merged: dict[tuple[str, ...], dict] = {}
                    for pid, keys in declared.items():
                        merged[tuple(sorted(keys))] = {
                            "keys": sorted(keys), "kind": "declared", "pool_id": pid,
                            "named_by": dict(named_by.get(pid, {}))}
                    for keys in groups:
                        t = tuple(sorted(keys))
                        if t in merged:
                            merged[t]["kind"] = "declared+observed"
                        else:
                            pid = next((obs[k]["pool_id"] for k in keys
                                        if obs[k].get("pool_id")), None)
                            merged[t] = {"keys": list(t), "kind": "observed",
                                         "pool_id": pid}

                    for t, row in sorted(merged.items()):
                        keys = row["keys"]
                        funded = {k: book[k] for k in keys if k in book}
                        total = sum(funded.values())
                        row["funded_usd"] = funded
                        row["funded_total_usd"] = total
                        ev = {k: {"tvl_usd": obs[k]["tvl_usd"],
                                  "apy_pct": obs[k]["apy_pct"],
                                  "source": obs[k]["source"]}
                              for k in keys if k in obs}
                        row["observations"] = ev
                        sev = CRITICAL if total > 0 else WARN
                        row["severity"] = sev
                        pool = row.get("pool_id") or "не запинен ни одним ключом"
                        if total > 0:
                            msg = (f"{' + '.join(keys)}: ключи ранжируются на ОДНОМ пуле "
                                   f"({pool}), и книга в нём уже стоит — "
                                   f"${total:,.0f}. Потолок концентрации считает их "
                                   f"РАЗНЫМИ предметами риска, поэтому доля одного "
                                   f"контракта занижена; найдено родом `{row['kind']}`")
                        else:
                            msg = (f"{' + '.join(keys)}: ключи ранжируются на ОДНОМ пуле "
                                   f"({pool}); в книге пока ноль, но оба остаются "
                                   f"пригодными к финансированию — структурный предел "
                                   f"пары вдвое выше объявленного потолка; найдено "
                                   f"родом `{row['kind']}`")
                        # Ключ, назвавший пул ОБЪЯВЛЕНИЕМ КЛАССА, на этом пуле
                        # не ранжируется — он им ЯВЛЯЕТСЯ, а ранжируется своим
                        # литералом. Сказать про него «ранжируется на одном пуле»
                        # значило бы соврать в ту же сторону, против которой
                        # написан модуль, поэтому оговорка дописывается ЯВНО.
                        by_class = sorted(k for k, how in row.get("named_by", {}).items()
                                          if how == NAMED_BY_CLASS)
                        if by_class:
                            msg += (f". Оговорка: {', '.join(by_class)} на этот пул НЕ "
                                    f"ранжируется — он его ОБЪЯВЛЯЕТ (константы класса, "
                                    f"ADR-237), а ранжируется собственным литералом. "
                                    f"Тождество от этого не слабее: потолок концентрации "
                                    f"всё равно считает их разными предметами риска")
                        row["message"] = msg
                        collisions.append(row)
                        findings.append({"severity": sev, "kind": "pool_collision",
                                         "keys": keys, "message": msg})

    if registry is not None:
        book, book_err = _book(positions, now)
        if book is None:
            book = {}
            if book_err and book_err not in unchecked:
                unchecked.append(book_err)
        for r in _unreachable_refusals(registry, obs, orch_keys):
            key = r["key"]
            r["funded_usd"] = book.get(key, 0.0)
            reachable = r["registry_branch_reachable"]
            if not reachable:
                sev = CRITICAL if r["funded_usd"] > 0 else WARN
                msg = (f"{key}: реестр отказывает "
                       f"(research_only={r['registry_research_only']}, "
                       f"status={r['registry_status']!r}, "
                       f"cap={r['registry_per_protocol_cap']}), но ключ ОПРАШИВАЕТСЯ "
                       f"оркестратором — ветка реестра в аллокаторе до него не "
                       f"доходит (`if name in seen_protocols: continue`), а класс "
                       f"адаптера отказа НЕ объявляет. Отказ недостижим"
                       + (f"; в книге ${r['funded_usd']:,.0f}" if r["funded_usd"] > 0
                          else "; в книге ноль"))
            else:
                sev = INFO
                msg = (f"{key}: реестр отказывает, класс адаптера — нет; ключ НЕ "
                       f"опрашивается, поэтому ветка реестра достижима и отказ "
                       f"состоится. Расхождение объявлений названо, вреда сегодня нет")
            r["severity"] = sev
            r["message"] = msg
            refusals.append(r)
            findings.append({"severity": sev, "kind": "unreachable_refusal",
                             "keys": [key], "message": msg})

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == CRITICAL),
        "warn": sum(1 for f in findings if f["severity"] == WARN),
        "info": sum(1 for f in findings if f["severity"] == INFO),
        "unchecked": len(unchecked),
    }
    if counts["unchecked"] or counts["critical"]:
        overall = CRITICAL if counts["critical"] else UNCHECKED
    elif counts["warn"]:
        overall = WARN
    elif counts["info"]:
        overall = INFO
    else:
        overall = "OK"

    report = {
        "generated_at": now.isoformat(),
        "generated_by": "spa_core.monitoring.pool_identity_collision",
        "overall": overall,
        "counts": counts,
        "keys_compared": sorted(obs),
        "collisions": collisions,
        "unreachable_refusals": refusals,
        "findings": findings,
        "unchecked": unchecked,
    }

    if write:
        base = data_dir or os.path.join(root, "data")
        atomic_save(report, os.path.join(base, os.path.basename(REPORT_REL)))
    return report


def exit_code(report: dict) -> int:
    c = report["counts"]
    if c["critical"] or c["unchecked"]:
        return 2
    return 1 if c["warn"] else 0


def main(argv=None, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--data-dir", default=None,
                    help="читать артефакты и писать отчёт в ЧУЖОЙ каталог (обычно <прод>/data)")
    ap.add_argument("--no-write", action="store_true", help="только печать, без артефакта")
    ap.add_argument("--json", action="store_true", help="печатать отчёт как JSON")
    args = ap.parse_args(argv)

    report = run(root=args.root, now=now, write=not args.no_write, data_dir=args.data_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return exit_code(report)

    c = report["counts"]
    print(f"тождество пулов: {report['overall']} (critical={c['critical']} "
          f"warn={c['warn']} info={c['info']} unchecked={c['unchecked']}); "
          f"ключей сверено: {len(report['keys_compared'])}")
    for line in report["unchecked"]:
        print(f"   [НЕ ИЗМЕРЕНО] {line}")
    # INFO здесь — «расхождение объявлений названо, но отказ состоится»: состояние
    # стабильное и безвредное. Печатать его построчно каждый цикл значило бы учить
    # читателя пролистывать сторожа (тот же довод, что у tvl_provenance в
    # adapter_feed_divergence) — поэтому оно сворачивается в одну строку, а полный
    # состав остаётся в артефакте.
    infos = [f for f in report["findings"] if f["severity"] == INFO]
    for f in report["findings"]:
        if f["severity"] != INFO:
            print(f"   [{f['severity']}] {f['message']}")
    if infos:
        names = ", ".join(sorted({k for f in infos for k in f["keys"]}))
        print(f"   … и {len(infos)} INFO-строк(и): реестр отказывает, класс молчит, "
              f"но ключ не опрашивается ⇒ отказ достижим и состоится ({names})")
    if report["overall"] == "OK":
        print("   коллизий нет — каждый сверенный ключ стоит на своём пуле")
    return exit_code(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
