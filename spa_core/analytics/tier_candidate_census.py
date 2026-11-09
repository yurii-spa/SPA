#!/usr/bin/env python3
"""Candidate и Tier §19 приказа владельца: сколько определений, и что тир РЕШАЕТ.

Критерий §19 `Candidate и Tier` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G950 п. 1, цикл #1080.

Дословно §19: «Найти существующие canonical definitions. Не придумывать новые.
По умолчанию Candidate должен MONITOR / SCORE / COMPARE, но не получать capital
автоматически, если existing policy этого не разрешает. Tier должен влиять на
допустимый risk/size, а не жёстко фиксировать allocation.»

Прибор НИЧЕГО НЕ ПРАВИТ: ни порога, ни политики, ни гейта, ни аллокатора, ни
ярлыка тира. Сдвинуть ярлык тира — это ADR и, с 2026-10-01, явное разрешение
владельца (ADR-532 §Owner gate); завести отсутствующий потолок — предмет №1
ADR-285. Прибор НАЗЫВАЕТ, он не исполняет.

Четыре вопроса, и ни один не выводится из другого
------------------------------------------------------------------------------
Заказ G950 п. 1 ставит ТРИ дословно; четвёртый (б2) добавлен самопроверкой —
см. ловушку ПЯТУЮ ниже.

1. **(а) где определение объявлено и сколько их** (:func:`definitions`).
   Спрашивается у живых контрактов — ``KNOWN_TIERS``, ``tier_from_registry``,
   ветка выбора потолка в ``policy.py``, ``_cap_for`` аллокатора, кодировка
   поля ``tier`` в живом реестре финансирования, — а не у памяти автора.
2. **(б) отличает ли система Candidate от ДОПУЩЕННОГО** (:func:`candidate_distinction`,
   роды :data:`DISTINCTION_19`). Мерится ДИФФЕРЕНЦИАЛЬНО: у двери, объявленной
   ОДНОЙ на все пути чтения реестра (``declared_ban``, ADR-303/ADR-330),
   возмущается РОВНО admission-status, всё прочее бит в бит.
3. **(б2) какая дверь ДЕЙСТВИТЕЛЬНО отказывает недопущенному ключу**
   (:func:`doors_refusing`). Отдельный вопрос, потому что «ключ не
   финансируется» и «его не пускает дверь ДОПУСКА» — разные утверждения.
4. **(в) тир ОГРАНИЧИВАЕТ размер или ФИКСИРУЕТ его** (:func:`tier_size_role`,
   роды :data:`SIZE_ROLE_KINDS`). Мерится зовом НАСТОЯЩЕГО гейта на одной книге,
   где возмущается РОВНО ярлык тира, на лестнице сумм, ПЕРЕСЕКАЮЩЕЙ порог.

Почему оси раздельны, а не одна
------------------------------------------------------------------------------
Урок ADR-943, повторённый §16, §17 и §18: замкнув их в один перечень, оси
понесли бы ОДИН бит. Состояние «определений тира ровно одно, кандидат от
допущенного отличается, а размер при этом тиром не градуируется» по шкале
«сколько определений» выглядит как лучший исход — и именно оно здесь найдено.

🪤 ЛОВУШКА ПЕРВАЯ: «нормализатор один» НЕ означает «определение одно»
------------------------------------------------------------------------------
ADR-359 свёл РАЗБОР поля ``tier`` в одну функцию (``tier_from_registry``), и
соблазн — прочитать это как закрытый вопрос (а). Но §19 спрашивает не о
разборе, а об ОПРЕДЕЛЕНИИ: сколько РАЗЛИЧНЫХ значений умеет назвать та
величина, которую тир выбирает. Словарь тиров — три члена
(``KNOWN_TIERS``); словарь потолков на протокол — ДВА
(``max_concentration_t1`` / ``max_concentration_t2``, поля
``max_concentration_t3`` в ``RiskConfig`` НЕТ вовсе). Нормализатор один,
а шкала у величины короче шкалы ярлыка — и это ответ (а), не ответ (в).

🪤 ЛОВУШКА ВТОРАЯ: сегодняшняя пустота предмета НЕ есть свойство двери
------------------------------------------------------------------------------
Ось (б) обязана печатать ДВА разных числа и не сливать их: сколько ключей
живого реестра не допущены (``status != active``) и сколько из них дверь
ДЕЙСТВИТЕЛЬНО не пустит. Если ни один недопущенный ключ сегодня не доезжает до
двери, защита есть свойство СОДЕРЖИМОГО снимка, а не гейта, — и завтрашний
снимок её не наследует. Поэтому exposure (``reachable_today``) и слепота двери
(``door_blind``) — отдельные поля, и вердикт стои́т на второй.

🪤 ЛОВУШКА ТРЕТЬЯ: «вердикт не изменился» без контроля — это о приборе, а не о мире
------------------------------------------------------------------------------
У КАЖДОЙ оси свой положительный контроль, и он возмущает ту величину, которую
дверь СВЯЗЫВАЕТ ЗАВЕДОМО (§16/§18/§41): у ``declared_ban`` — ``research_only``
и нулевой ``per_protocol_cap``; у гейта — сумму против потолка и незнакомый
ярлык. Контроль не сменил вердикт ⇒ ответ прибора НЕ ВЫДАЁТСЯ
(``unmeasured`` с названной причиной), а не печатается как находка. Контроль —
не украшение: «не изменился» и «прибор не работает» выглядят одинаково.

🪤 ЛОВУШКА ЧЕТВЁРТАЯ: порог, который НИКОГДА не связывает, — не потолок
------------------------------------------------------------------------------
Урок ADR-959 (порог ёмкости был НЕДОСТИЖИМ, а не warn-only). Достижимость
потолка на протокол для T3 проверяется ОТДЕЛЬНО: доля одного T3-протокола не
может превысить суммарную долю T3, поэтому потолок 20 % за суммарным 15 %
недостижим по построению, и сообщение «exceeds T3 limit 20.0%» называет
число, которое НИ РАЗУ не бывает единственным связывающим. Прибор печатает род
``named_but_unreachable``, а не «потолок есть».

🪤 ЛОВУШКА ПЯТАЯ: вывод о допуске, снятый у ОДНОЙ двери, верен СЛУЧАЙНО
------------------------------------------------------------------------------
Первая редакция замера спрашивала только ``declared_ban`` и уже на этом
утверждала, что недопущенный ключ получит капитал. Рядом стои́т вторая дверь —
``_adapter_class_gate``, — и её отказ по СВОЕЙ причине сделал бы вывод верным
случайно (ровно ошибка, которую §16 и §18 исправляли своим же замером). Поэтому
ось (б2) спрашивает ВСЕ двери поимённо и НАЗЫВАЕТ отказчика. Попутно она мерит
ПРИТЯЗАНИЕ класс-гейта: его docstring заявляет решение владельца «не знаем — не
финансируем» (ADR-357 п. 3, «исполнено ADR-359»), а тело держит
``if cls is None: return True, None``. Притязание меряется НЕВОЗМОЖНЫМ именем, а
не чтением глазами, и сцена гоняется дважды с ПРОТИВОПОЛОЖНЫМИ ответами двери —
иначе константа ``honoured`` неотличима от замера.

Чего прибор НЕ меряет
------------------------------------------------------------------------------
Первую половину §19 — ``MONITOR``/``SCORE``/``COMPARE`` для кандидата.
Прибор мерил ВТОРУЮ (капитал); наблюдается ли недопущенный ключ и попадает ли
он в СРАВНЕНИЕ, остаётся **НЕ ИЗМЕРЕНО**, и нулём это не считается.

«Правильный» тир протокола и «правильный» порог допуска кандидата. Это предмет
владельца: ярлык тира меняется ТОЛЬКО ADR-ом (``docs/tier_criteria.md`` §5,
проверенный факт `CLAUDE.md`), а что считать допуском — решение, а не замер.
Прибор отвечает лишь на вопрос, ЕСТЬ ли в системе место, где такое решение
записано, и спрашивает ли это место хоть одна дверь денежного пути.

Население КОПИЙ ярлыка прибор тоже НЕ мерит заново: это уже сделано
``spa_core.defi_engine.tiers`` (8 копий, ADR-532) и
``spa_core.monitoring.policy_binding_census`` (ADR-173, дрейф ярлыка
``morpho_steakhouse``). Вторая реализация означала бы два ответа об одном
ярлыке, расходящиеся молча (урок ``house_view_gap``, цикл #274).

Словари ВВЕЗЕНЫ, а не перепечатаны
------------------------------------------------------------------------------
``UNMEASURED`` — из §13 (``transaction_economics``), как у §17 и §18; авторитет
ярлыка — из ``defi_engine.tiers`` (ADR-532); нормализатор — из ``risk.policy``
(ADR-359). Вторая копия словаря или правила означала бы две шкалы,
расходящиеся молча. Словарей §17 (``EXPRESS_KINDS``/``OBSERVE_KINDS``) здесь
НЕТ намеренно: §19 ими не пользуется, а ввезти шкалу, которой не меряешь, —
то же украшение, что перепечатать её.

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей. Своих копий здесь нет намеренно.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

#: Третий исход инв. #17: «не измерено» — САМОСТОЯТЕЛЬНОЕ значение, не ноль.
#: Ввезён из §13, как у §17 и §18: вторая копия означала бы две шкалы,
#: расходящиеся молча.
try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

#: Роды ответа оси (б): отличает ли система кандидата от ДОПУЩЕННОГО.
#: Шкала объявлена, а не выведена из ветвей: ветка `else` по построению не может
#: сказать, какие роды существуют (урок ADR-357 п. 3 / KNOWN_TIERS).
DISTINCTION_19: Tuple[str, ...] = (
    # величина допуска объявлена записью И её читает дверь денежного пути
    "declared_and_read",
    # величина допуска объявлена записью, но дверь, объявленная ОДНОЙ на все
    # пути чтения реестра, её не читает — отличие держится на ДРУГОМ поле
    "declared_door_blind",
    # отличия нет вовсе: ни поля, ни двери
    "absent",
    # разобрать не вышло — третий исход, а не ноль
    UNMEASURED,
)

#: Роды ответа оси (в): что тир ДЕЛАЕТ с размером.
SIZE_ROLE_KINDS: Tuple[str, ...] = (
    # тир ОГРАНИЧИВАЕТ: потолок — максимум, и он различен по тирам
    "limits",
    # тир ФИКСИРУЕТ: из ярлыка следует сама доля, а не её граница (запрещено §19)
    "fixes",
    # потолок НАЗВАН в сообщении, но связывающим не бывает НИ ПРИ КАКОЙ сумме
    "named_but_unreachable",
    # у тира нет своего значения — он делит потолок с соседним тиром
    "shared_with_other_tier",
    UNMEASURED,
)

#: Статус записи живого реестра, означающий ДОПУЩЕН. Значение не выдумано:
#: это ровно тот литерал, которым фильтрует реестровый путь загрузки
#: (`allocator.py`, ветка «status not in ("active",) ⇒ continue»).
ADMITTED_STATUS = "active"

_REGISTRY_REL = Path("data") / "adapter_registry.json"


# ---------------------------------------------------------------------------
# Загрузка. Каждая дверь отвечает ТРЕМЯ исходами, а не двумя.
# ---------------------------------------------------------------------------
def load_policy() -> Tuple[Any, Optional[str]]:
    """``(RiskConfig(), None)`` либо ``(None, причина)`` — НЕ ИЗМЕРЕНО."""
    try:
        from spa_core.risk.policy import RiskConfig
        return RiskConfig(), None
    except Exception as exc:  # pragma: no cover — меряется тестом
        return None, "RiskConfig не ввезён: {}".format(exc)


def load_registry(root: Path) -> Tuple[Optional[Dict[str, dict]], Optional[str]]:
    """Живой реестр финансирования, либо причина, почему не прочитан.

    Пустой файл и отсутствующий файл РАЗВЕДЕНЫ: «реестра нет» и «в реестре ноль
    записей» — разные утверждения, и слить их значило бы выдать отсутствие
    наблюдения за наблюдённый ноль (инв. #17).
    """
    path = root / _REGISTRY_REL
    if not path.exists():
        return None, "реестра нет по пути {}".format(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, "реестр не разобран ({}): {}".format(path, exc)
    ads = raw.get("adapters")
    if not isinstance(ads, dict):
        return None, "в реестре {} нет отображения `adapters`".format(path)
    return {str(k): v for k, v in ads.items() if isinstance(v, dict)}, None


def load_doors() -> Tuple[Dict[str, Any], Optional[str]]:
    """Двери, у которых прибор спрашивает. Свои копии правил здесь ЗАПРЕЩЕНЫ."""
    doors: Dict[str, Any] = {}
    try:
        from spa_core.risk.policy import (
            KNOWN_TIERS, PortfolioState, Position, RiskPolicy, tier_from_registry,
        )
        doors.update(
            known_tiers=KNOWN_TIERS, tier_from_registry=tier_from_registry,
            RiskPolicy=RiskPolicy, PortfolioState=PortfolioState, Position=Position,
        )
    except Exception as exc:
        return {}, "двери политики не ввезены: {}".format(exc)
    try:
        from spa_core.allocator.allocator import declared_ban
        doors["declared_ban"] = declared_ban
    except Exception as exc:
        return doors, "дверь `declared_ban` не ввезена: {}".format(exc)
    try:
        # ОДИН авторитет ярлыка (ADR-532). Прибор его НЕ дублирует и население
        # копий заново НЕ мерит — это уже делает `defi_engine.tiers`.
        from spa_core.defi_engine.tiers import authority as tier_authority
        doors["tier_authority"] = tier_authority
    except Exception as exc:
        return doors, "авторитет ярлыка не ввезён: {}".format(exc)
    return doors, None


# ---------------------------------------------------------------------------
# Ось (а): где определение объявлено и СКОЛЬКО их
# ---------------------------------------------------------------------------
def definitions(cfg: Any, doors: Dict[str, Any],
                reg: Optional[Dict[str, dict]]) -> Dict[str, Any]:
    """Сколько РАЗЛИЧНЫХ значений умеет назвать каждая сторона определения тира.

    Вопрос §19 — об ОПРЕДЕЛЕНИИ, а не о разборе: ADR-359 свёл разбор в одну
    функцию, и это закрытый вопрос. Открыт другой: словарь ярлыка и словарь
    величины, которую ярлык выбирает, могут быть РАЗНОЙ длины, и тогда два
    тира неразличимы по этой величине, не породив ни одного расхождения копий.
    """
    out: Dict[str, Any] = {"sides": [], "notes": []}

    known = doors.get("known_tiers")
    label_vocab = sorted(known) if known else None
    out["sides"].append({
        "side": "label", "where": "spa_core/risk/policy.py::KNOWN_TIERS",
        "distinct": len(label_vocab) if label_vocab else UNMEASURED,
        "values": label_vocab if label_vocab else UNMEASURED,
        "declared": True,
    })

    # Величина, которую ярлык выбирает у ГЕЙТА. Ветка `policy.py` читается не
    # глазами: поля RiskConfig перечисляются dataclasses, а не вспоминаются.
    if cfg is None:
        out["sides"].append({"side": "per_protocol_cap", "distinct": UNMEASURED,
                             "where": "RiskConfig не ввезён"})
    else:
        names = {f.name for f in dataclasses.fields(cfg)}
        per_tier = {t: "max_concentration_t{}".format(t[1].lower()) for t in ("T1", "T2", "T3")}
        declared = {t: f for t, f in per_tier.items() if f in names}
        values = sorted({getattr(cfg, f) for f in declared.values()})
        out["sides"].append({
            "side": "per_protocol_cap",
            "where": "spa_core/risk/policy.py::RiskConfig.max_concentration_t*",
            "distinct": len(values), "values": values,
            "declared_fields": sorted(declared.values()),
            "missing_fields": sorted(f for t, f in per_tier.items() if t not in declared),
            "declared": True,
        })
        totals = {t: "max_total_t{}_allocation".format(t[1].lower()) for t in ("T1", "T2", "T3")}
        out["sides"].append({
            "side": "total_cap",
            "where": "spa_core/risk/policy.py::RiskConfig.max_total_t*_allocation",
            "distinct": len([f for f in totals.values() if f in names]),
            "declared_fields": sorted(f for f in totals.values() if f in names),
            "missing_fields": sorted(f for f in totals.values() if f not in names),
            "declared": True,
        })

    # Кодировка ярлыка в ЖИВОМ реестре. Это не «ещё одно определение», а форма
    # хранения — но форм в ОДНОМ файле может быть больше одной, и тогда
    # нормализатор несёт нагрузку, о которой автор записи не знает.
    if reg is None:
        out["sides"].append({"side": "registry_encoding", "distinct": UNMEASURED,
                             "where": "реестр не прочитан"})
    else:
        enc: Dict[str, int] = {}
        for entry in reg.values():
            raw = entry.get("tier")
            enc[type(raw).__name__] = enc.get(type(raw).__name__, 0) + 1
        out["sides"].append({
            "side": "registry_encoding", "where": str(_REGISTRY_REL),
            "distinct": len(enc), "encodings": enc, "declared": False,
        })

    # Согласие ДВУХ существующих определений на ОДНОМ ключе. Это НЕ перепись
    # копий ярлыка (её делает `defi_engine.tiers`, 8 копий, ADR-532): здесь
    # спрашиваются ровно две двери, через которые ярлык попадает на денежный
    # путь, — нормализатор записи реестра (ADR-359, ВХОД гейта) и объявленный
    # ОДИН авторитет (ADR-532). Расходятся ⇒ «сколько определений» больше
    # одного ПО ЗАМЕРУ, а не по памяти автора.
    norm = doors.get("tier_from_registry")
    auth = doors.get("tier_authority")
    if reg is None or norm is None or auth is None:
        out["agreement"] = {"kind": UNMEASURED,
                            "reason": "реестр или одна из двух дверей недоступна"}
    else:
        rows, disagree, silent = [], [], []
        for key, entry in sorted(reg.items()):
            n = norm(entry.get("tier"))
            try:
                a = auth(key)
            except Exception as exc:  # дверь ответила отказом — третий исход
                rows.append({"key": key, "normaliser": n, "authority": UNMEASURED,
                             "why": str(exc)})
                continue
            rows.append({"key": key, "normaliser": n, "authority": a})
            if n is not None and a is not None and n != a:
                disagree.append({"key": key, "normaliser": n, "authority": a})
            elif n is not None and a is None:
                silent.append(key)
        out["agreement"] = {
            "kind": "disagree" if disagree else ("authority_silent" if silent else "agree"),
            "keys": len(rows), "disagreeing": disagree,
            "authority_silent_while_registry_names": sorted(silent),
        }

    return out


# ---------------------------------------------------------------------------
# Ось (б): отличает ли система Candidate от ДОПУЩЕННОГО
# ---------------------------------------------------------------------------
def candidate_distinction(root: Path, doors: Dict[str, Any],
                          reg: Optional[Dict[str, dict]]) -> Dict[str, Any]:
    """Дифференциал на двери ``declared_ban``: возмущается РОВНО admission-status.

    ``declared_ban`` объявлена ОДНОЙ на все пути, читающие реестр (ADR-303
    ввёл её в гейт ``_fundable``, ADR-330 вынес наружу, «чтобы кандидаты книг
    читали ТУ ЖЕ функцию, а не её копию»). Поэтому вопрос §19 задаётся ей, а не
    инлайновой ветке одного из путей: ветка отвечает за свой путь, функция —
    за все.
    """
    out: Dict[str, Any] = {"kind": UNMEASURED, "reason": None, "controls": [],
                           "statuses": {}, "reachable_today": None}
    ban = doors.get("declared_ban")
    if ban is None:
        out["reason"] = "дверь `declared_ban` не ввезена"
        return out
    if reg is None:
        out["reason"] = "реестр не прочитан — сцену не из чего построить"
        return out

    statuses: Dict[str, int] = {}
    for entry in reg.values():
        st = entry["status"] if "status" in entry else "<поля нет>"
        statuses[str(st)] = statuses.get(str(st), 0) + 1
    out["statuses"] = statuses
    out["admission_field_present"] = any("status" in e for e in reg.values())

    # Порядок существенный: поля допуска нет вовсе ⇒ род `absent`, и сцена для
    # этого не нужна. Спросив сначала о сцене, прибор ответил бы «сцена не
    # обеспечена» (НЕ ИЗМЕРЕНО) там, где ответ как раз ИЗВЕСТЕН и равен
    # «отличия нет» — то есть выдал бы незнание за незнание о другом вопросе.
    if not out["admission_field_present"]:
        out["kind"] = "absent"
        reach, reach_reason = _reachable_not_admitted(root, reg, ban)
        out["reachable_today"] = reach
        out["reachable_reason"] = reach_reason
        return out

    # Сцена: ДОПУЩЕННАЯ запись, у которой заведомо нет запрета. Берётся из
    # живого реестра, а не выдумывается: выдуманная запись отвечала бы о
    # приборе. Не нашлось ⇒ громкий третий исход, а не «похоже, не отличает».
    base_key = next((k for k, e in sorted(reg.items())
                     if e.get("status") == ADMITTED_STATUS and ban(e) is None), None)
    if base_key is None:
        out["reason"] = ("в реестре нет ни одной ДОПУЩЕННОЙ записи без запрета — "
                         "сцена не обеспечена")
        return out
    base = dict(reg[base_key])
    out["scene_key"] = base_key
    out["scene_base_verdict"] = ban(base)

    # Возмущение: РОВНО admission-status, всё прочее бит в бит.
    perturbed: List[Dict[str, Any]] = []
    not_admitted = sorted(set(statuses) - {ADMITTED_STATUS})
    # к наблюдённым статусам добавляется дословное слово §19 — владелец называет
    # род «Candidate», и спросить дверь о нём прямо честнее, чем выводить.
    for st in list(not_admitted) + ["candidate"]:
        pert = dict(base)
        pert["status"] = st
        perturbed.append({"status": st, "verdict": ban(pert)})
    out["perturbations"] = perturbed

    # Положительный контроль: возмущаем то, что дверь СВЯЗЫВАЕТ ЗАВЕДОМО.
    for field, value in (("research_only", True), ("per_protocol_cap", 0.0)):
        pert = dict(base)
        pert[field] = value
        out["controls"].append({"field": field, "value": value, "verdict": ban(pert)})
    if any(c["verdict"] is None for c in out["controls"]):
        out["reason"] = ("положительный контроль двери НЕ сменил вердикт — "
                         "ответ об admission-status не выдаётся")
        return out

    blind = all(p["verdict"] == out["scene_base_verdict"] for p in perturbed)
    out["door_blind"] = blind

    # Exposure СЕГОДНЯ — отдельное число, и вердикт на нём НЕ стои́т (ловушка 2).
    reach, reach_reason = _reachable_not_admitted(root, reg, ban)
    out["reachable_today"] = reach
    out["reachable_reason"] = reach_reason

    out["kind"] = "declared_door_blind" if blind else "declared_and_read"
    return out


#: Имя, которого в системе быть не может. Служит контролем притязания класс-гейта
#: «не знаем — не финансируем» (ADR-357 п. 3): если притязание исполнено, такое
#: имя обязано получить ОТКАЗ. Пустую строку брать нельзя — у неё своя ветка.
_IMPOSSIBLE_KEY = "__ключа-с-таким-именем-в-системе-нет__"


def doors_refusing(reg: Optional[Dict[str, dict]]) -> Dict[str, Any]:
    """Какая дверь ДЕЙСТВИТЕЛЬНО отказывает недопущенному ключу — поимённо.

    Вопрос отдельный от слепоты ``declared_ban`` и задаётся ПОТОМУ, что «ключ
    не финансируется» и «его не пускает дверь допуска» — разные утверждения.
    Отказ соседней двери по СВОЕЙ причине делает ответ о допуске верным
    СЛУЧАЙНО (ровно ошибка, исправленная §16 и §18 своим же замером).

    Попутно проверяется ПРИТЯЗАНИЕ класс-гейта. Его docstring заявляет решение
    владельца 12.09 (ADR-357 п. 3, «исполнено ADR-359»): «адаптеры без записи в
    реестре ДОПУСКАЮТСЯ» заменено на **«не знаем — не финансируем»**. В теле,
    однако, стои́т ``if cls is None: return True, None``, то есть правило
    исполнено у двери ТИРА (незнакомый тир ⇒ не финансируем) и НЕ исполнено у
    двери КЛАССА, чей собственный текст его заявляет. Притязание меряется
    невозможным именем, а не чтением глазами.
    """
    out: Dict[str, Any] = {"per_key": [], "class_gate_claim": UNMEASURED}
    try:
        from spa_core.allocator.allocator import _adapter_class_gate, declared_ban
    except Exception as exc:
        out["reason"] = "двери допуска не ввезены: {}".format(exc)
        return out
    try:
        from spa_core.risk.policy import tier_from_registry
    except Exception as exc:
        out["reason"] = "нормализатор тира не ввезён: {}".format(exc)
        return out

    # Притязание класс-гейта: невозможное имя обязано получить ОТКАЗ, если
    # правило «не знаем — не финансируем» у ЭТОЙ двери исполнено.
    allowed, why = _adapter_class_gate(_IMPOSSIBLE_KEY)
    out["class_gate_claim"] = "honoured" if not allowed else "claimed_not_honoured"
    out["class_gate_on_impossible_key"] = {"allowed": bool(allowed), "reason": why}

    if reg is None:
        out["reason"] = "реестр не прочитан — поимённого ответа нет"
        return out

    for key, entry in sorted(reg.items()):
        if entry.get("status") == ADMITTED_STATUS:
            continue
        cls_allowed, cls_why = _adapter_class_gate(key)
        refusers = []
        if not cls_allowed:
            refusers.append("class_gate:{}".format(cls_why))
        if declared_ban(entry):
            refusers.append("declared_ban:{}".format(declared_ban(entry)))
        if tier_from_registry(entry.get("tier")) is None:
            refusers.append("tier_unknown")
        out["per_key"].append({
            "key": key, "status": entry.get("status"),
            "refused_by": refusers,
            # Ни одна дверь не отказала ⇒ недопущенный ключ держится ТОЛЬКО
            # инлайновой веткой ОДНОГО из двух путей загрузки.
            "refused_by_nothing": not refusers,
        })
    out["refused_by_nothing"] = sorted(r["key"] for r in out["per_key"]
                                       if r["refused_by_nothing"])
    return out


def _reachable_not_admitted(root: Path, reg: Dict[str, dict],
                            ban: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Сколько НЕдопущенных ключей сегодня доезжает до двери здоровым.

    Отвечает о СОДЕРЖИМОМ снимка, а не о двери, и печатается отдельно именно
    поэтому: сегодняшний ноль защитой не является и завтра не наследуется.
    """
    snap_path = root / "data" / "adapter_orchestrator_status.json"
    if not snap_path.exists():
        return None, "снимка оркестратора нет по пути {}".format(snap_path)
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, "снимок не разобран: {}".format(exc)
    ads = snap.get("adapters")
    if not isinstance(ads, list):
        return None, "в снимке нет списка `adapters`"
    healthy = [str(a.get("protocol")) for a in ads
               if isinstance(a, dict) and a.get("status") in ("ok", "partial")]
    not_admitted = [k for k in healthy
                    if reg.get(k, {}).get("status") not in (ADMITTED_STATUS, None)]
    unbanned = [k for k in not_admitted if ban(reg.get(k, {})) is None]
    # Отдельно: ключи реестра, НЕ допущенные и НЕ забаненные ничем, — они
    # доедут до двери, как только попадут в снимок здоровыми.
    latent = sorted(k for k, e in reg.items()
                    if e.get("status") not in (ADMITTED_STATUS, None) and ban(e) is None)
    return {
        "healthy_in_snapshot": len(healthy),
        "not_admitted_in_snapshot": sorted(not_admitted),
        "not_admitted_and_unbanned": sorted(unbanned),
        "latent_not_admitted_unbanned": latent,
    }, None


# ---------------------------------------------------------------------------
# Ось (в): тир ОГРАНИЧИВАЕТ размер или ФИКСИРУЕТ его
# ---------------------------------------------------------------------------
#: Лестница сумм (доля книги). Пересекает оба объявленных потолка на протокол
#: (0.20 и 0.40) и суммарный T3 (0.15) — иначе ответ был бы верен СЛУЧАЙНО
#: (урок §16: сцена, не пересёкшая порог, отвечает не на тот вопрос).
_LADDER: Tuple[float, ...] = (0.12, 0.18, 0.25, 0.45)


def tier_size_role(doors: Dict[str, Any], cfg: Any) -> Dict[str, Any]:
    """Зов НАСТОЯЩЕГО гейта на одной книге; возмущается РОВНО ярлык тира."""
    out: Dict[str, Any] = {"kind": UNMEASURED, "reason": None, "ladder": [],
                           "controls": [], "per_tier": {}}
    need = ("RiskPolicy", "PortfolioState", "Position", "known_tiers")
    if any(doors.get(n) is None for n in need):
        out["reason"] = "двери политики не ввезены"
        return out
    if cfg is None:
        out["reason"] = "RiskConfig не ввезён"
        return out

    RiskPolicy = doors["RiskPolicy"]
    PortfolioState = doors["PortfolioState"]
    pol = RiskPolicy(cfg)
    capital = 100_000.0
    tiers = sorted(doors["known_tiers"])

    def ask(tier: str, amount: float) -> Dict[str, Any]:
        state = PortfolioState(total_capital_usd=capital, positions=[])
        res = pol.check_new_position(state, "__scene__", tier, amount,
                                     5.0, 50_000_000.0, "ethereum")
        return {"approved": bool(res.approved),
                "violations": list(getattr(res, "violations", []) or [])}

    for share in _LADDER:
        row: Dict[str, Any] = {"share": share, "amount_usd": capital * share, "by_tier": {}}
        for tier in tiers:
            row["by_tier"][tier] = ask(tier, capital * share)
        out["ladder"].append(row)

    # Контроль: незнакомый ярлык обязан ОТКАЗАТЬ (ADR-357 п. 3). Не отказал ⇒
    # дверь не читает ярлык вовсе, и ответ об ограничении не выдаётся.
    unknown = ask("T9", capital * 0.12)
    out["controls"].append({"control": "unknown_tier", "tier": "T9",
                            "approved": unknown["approved"]})
    if unknown["approved"]:
        out["reason"] = ("контроль незнакомого ярлыка ОДОБРЕН — дверь ярлык не "
                         "читает, ответ об ограничении не выдаётся")
        return out

    # Контроль: сумма против потолка ЗАВЕДОМО связывает (§16/§18).
    small, large = ask(tiers[0], capital * 0.01), ask(tiers[0], capital * 0.95)
    out["controls"].append({"control": "amount_crosses_cap",
                            "small_approved": small["approved"],
                            "large_approved": large["approved"]})
    if not small["approved"] or large["approved"]:
        out["reason"] = ("контроль суммы НЕ сменил вердикт — ответ об "
                         "ограничении не выдаётся")
        return out

    # Порог, с которого ярлык начинает отказывать, — ПО ТИРУ. Разные пороги =
    # тир ОГРАНИЧИВАЕТ; один порог на два тира = тиры по размеру неразличимы.
    first_refusal: Dict[str, Optional[float]] = {}
    for tier in tiers:
        first_refusal[tier] = next(
            (r["share"] for r in out["ladder"] if not r["by_tier"][tier]["approved"]), None)
    per_tier: Dict[str, Any] = {"first_refused_share": first_refusal}
    out["per_tier"] = per_tier

    # Достижимость потолка на протокол для каждого тира: бывает ли он
    # ЕДИНСТВЕННЫМ связывающим хоть на одной ступени (урок ADR-959).
    sole: Dict[str, bool] = {}
    for tier in tiers:
        sole[tier] = any(
            len(r["by_tier"][tier]["violations"]) == 1
            and "oncentration" in r["by_tier"][tier]["violations"][0]
            for r in out["ladder"])
    per_tier["per_protocol_cap_ever_sole_binder"] = sole

    shared = [t for t in tiers
              if not hasattr(cfg, "max_concentration_t{}".format(t[1].lower()))]
    per_tier["tiers_without_own_per_protocol_cap"] = shared

    distinct_thresholds = len({v for v in first_refusal.values() if v is not None})
    if distinct_thresholds <= 1:
        out["kind"] = "fixes" if distinct_thresholds == 0 else "shared_with_other_tier"
    elif shared and not all(sole.get(t, False) for t in shared):
        out["kind"] = "named_but_unreachable"
    else:
        out["kind"] = "limits"
    return out


# ---------------------------------------------------------------------------
# Сборка
# ---------------------------------------------------------------------------
def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Полный ответ §19. Ни одна дверь ничего не правит."""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    report: Dict[str, Any] = {"section": "§19 Candidate и Tier", "root": str(root),
                              "vocab_errors": list(_VOCAB_ERRORS), "unmeasured": []}

    cfg, cfg_err = load_policy()
    reg, reg_err = load_registry(root)
    doors, door_err = load_doors()
    for err in (cfg_err, reg_err, door_err):
        if err:
            report["unmeasured"].append(err)

    report["definitions"] = definitions(cfg, doors, reg)
    report["candidate"] = candidate_distinction(root, doors, reg)
    report["doors"] = doors_refusing(reg)
    report["size_role"] = tier_size_role(doors, cfg)
    if report["candidate"]["kind"] not in DISTINCTION_19:
        report["unmeasured"].append("род оси (б) вне словаря DISTINCTION_19")
    if report["size_role"]["kind"] not in SIZE_ROLE_KINDS:
        report["unmeasured"].append("род оси (в) вне словаря SIZE_ROLE_KINDS")
    return report


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — нечего сказать · 1 — НАХОДКА · 2 — НЕ ИЗМЕРЕНО.

    «Не измерено» СТАРШЕ находки: прибор, не обеспечивший предпосылку, обязан
    сказать это вслух, а не выдать частичный ответ за полный (инв. #17).
    """
    if report.get("vocab_errors") or report.get("unmeasured"):
        return 2
    if report["candidate"]["kind"] == UNMEASURED or report["size_role"]["kind"] == UNMEASURED:
        return 2
    agr = report["definitions"].get("agreement", {})
    if agr.get("kind") == UNMEASURED:
        return 2
    doors = report.get("doors", {})
    if doors.get("class_gate_claim") == UNMEASURED:
        return 2
    findings = (
        report["candidate"]["kind"] in ("declared_door_blind", "absent")
        or report["size_role"]["kind"] != "limits"
        or agr.get("kind") in ("disagree", "authority_silent")
        or doors.get("class_gate_claim") == "claimed_not_honoured"
        or bool(doors.get("refused_by_nothing"))
    )
    return 1 if findings else 0


def render(report: Dict[str, Any]) -> str:
    out: List[str] = ["§19 Candidate и Tier — перепись: (а) определения · (б) допуск · (б2) какая дверь отказывает · (в) размер (ADVISORY, прибор только ЧИТАЕТ)",
                      "дерево: {}".format(report["root"]), ""]

    out.append("(а) СКОЛЬКО ОПРЕДЕЛЕНИЙ И ГДЕ")
    for side in report["definitions"]["sides"]:
        bits = ["  {:18} {:>4} различн.".format(side["side"], str(side.get("distinct")))]
        if side.get("values") is not None:
            bits.append("  значения {}".format(side["values"]))
        if side.get("encodings"):
            bits.append("  кодировки {}".format(side["encodings"]))
        if side.get("missing_fields"):
            bits.append("  ПОЛЯ ОТСУТСТВУЮТ: {}".format(side["missing_fields"]))
        out.append("".join(bits))
        out.append("      где: {}".format(side.get("where")))
    agr = report["definitions"].get("agreement", {})
    if agr:
        out.append("  согласие двух дверей ярлыка (нормализатор ADR-359 ↔ авторитет ADR-532): "
                   "{} на {} ключ(ах)".format(agr.get("kind"), agr.get("keys")))
        for d in agr.get("disagreeing", []):
            out.append("      РАСХОДЯТСЯ {}: нормализатор={} авторитет={}".format(
                d["key"], d["normaliser"], d["authority"]))
        if agr.get("authority_silent_while_registry_names"):
            out.append("      авторитет МОЛЧИТ, а реестр ярлык называет: {}".format(
                agr["authority_silent_while_registry_names"]))
        if agr.get("reason"):
            out.append("      НЕ ИЗМЕРЕНО: {}".format(agr["reason"]))
    out.append("")

    cand = report["candidate"]
    out.append("(б) ОТЛИЧАЕТ ЛИ СИСТЕМА КАНДИДАТА ОТ ДОПУЩЕННОГО: {}".format(cand["kind"]))
    if cand.get("reason"):
        out.append("    НЕ ИЗМЕРЕНО: {}".format(cand["reason"]))
    if cand.get("statuses"):
        out.append("    статусы живого реестра: {}".format(cand["statuses"]))
    if cand.get("scene_key"):
        out.append("    сцена на ключе {} (вердикт базы: {})".format(
            cand["scene_key"], cand["scene_base_verdict"]))
    for p in cand.get("perturbations", []):
        out.append("      status={:16} → declared_ban = {}".format(str(p["status"]), p["verdict"]))
    for c in cand.get("controls", []):
        out.append("      КОНТРОЛЬ {}={} → {}".format(c["field"], c["value"], c["verdict"]))
    reach = cand.get("reachable_today")
    if reach:
        out.append("    СЕГОДНЯ в снимке: здоровых {} · недопущенных {} · из них не забанено {}".format(
            reach["healthy_in_snapshot"], len(reach["not_admitted_in_snapshot"]),
            reach["not_admitted_and_unbanned"]))
        out.append("    ЛАТЕНТНО (недопущен и ничем не забанен в реестре): {}".format(
            reach["latent_not_admitted_unbanned"]))
    elif cand.get("reachable_reason"):
        out.append("    exposure НЕ ИЗМЕРЕНА: {}".format(cand["reachable_reason"]))
    out.append("")

    doors = report.get("doors", {})
    out.append("(б2) КАКАЯ ДВЕРЬ ДЕЙСТВИТЕЛЬНО ОТКАЗЫВАЕТ НЕДОПУЩЕННОМУ КЛЮЧУ")
    out.append("    притязание класс-гейта «не знаем — не финансируем»: {}".format(
        doors.get("class_gate_claim")))
    if doors.get("class_gate_on_impossible_key"):
        out.append("      на НЕВОЗМОЖНОМ имени: {}".format(
            doors["class_gate_on_impossible_key"]))
    for row in doors.get("per_key", []):
        out.append("      {:20} status={:16} отказывают: {}".format(
            row["key"], str(row["status"]), row["refused_by"] or "НИ ОДНА ДВЕРЬ"))
    if doors.get("refused_by_nothing"):
        out.append("    НЕ ОТКАЗЫВАЕТ НИ ОДНА ДВЕРЬ: {}".format(doors["refused_by_nothing"]))
    if doors.get("reason"):
        out.append("    НЕ ИЗМЕРЕНО: {}".format(doors["reason"]))
    out.append("")

    size = report["size_role"]
    out.append("(в) ТИР ОГРАНИЧИВАЕТ РАЗМЕР ИЛИ ФИКСИРУЕТ: {}".format(size["kind"]))
    if size.get("reason"):
        out.append("    НЕ ИЗМЕРЕНО: {}".format(size["reason"]))
    for row in size.get("ladder", []):
        verdicts = " ".join("{}={}".format(t, "OK" if v["approved"] else "ОТКАЗ")
                            for t, v in sorted(row["by_tier"].items()))
        out.append("    доля {:>5.0%} (${:>9,.0f}): {}".format(
            row["share"], row["amount_usd"], verdicts))
    pt = size.get("per_tier", {})
    if pt:
        out.append("    первый отказ по тиру: {}".format(pt.get("first_refused_share")))
        out.append("    потолок на протокол бывает ЕДИНСТВЕННЫМ связывающим: {}".format(
            pt.get("per_protocol_cap_ever_sole_binder")))
        out.append("    тиры БЕЗ своего потолка на протокол: {}".format(
            pt.get("tiers_without_own_per_protocol_cap")))
    for c in size.get("controls", []):
        out.append("    КОНТРОЛЬ {}: {}".format(c["control"],
                   {k: v for k, v in c.items() if k != "control"}))
    out.append("")

    if report.get("vocab_errors"):
        out.append("СЛОВАРИ НЕ ВВЕЗЕНЫ: {}".format(report["vocab_errors"]))
    if report.get("unmeasured"):
        out.append("НЕ ИЗМЕРЕНО: {}".format(report["unmeasured"]))
    out.append("ADVISORY: ни политика, ни гейт, ни аллокатор, ни ярлык тира не тронуты.")
    return "\n".join(out)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Перепись §19 «Candidate и Tier» (read-only)")
    ap.add_argument("--repo-root", default=None,
                    help="дерево, о котором спрашиваем (умолчание — дерево прибора, ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(argv)

    root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    if args.repo_root is None:
        print("[дерево НЕ НАЗВАНО входом — умолчание: {}]".format(root))
    elif not root.exists():
        print("НЕ ИЗМЕРЕНО: названное дерево не существует: {}".format(root))
        return 2

    report = census(root)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str)
          if args.json else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
