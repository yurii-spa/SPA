#!/usr/bin/env python3
"""Частота работы §21 приказа владельца: такт наблюдения ОТДЕЛЬНО от такта пересчёта.

Критерий §21 `Частота работы` приказа владельца «Portfolio CIO»
(`inbox-task-portfolio-cio-dynamic-capital-alloc`), заказ G952 п. 1, цикл #1082.

Дословно §21: «Не связывать monitoring frequency и trading frequency.
Monitoring работает часто. Ориентир: 5–10 min или event-driven, если такая
архитектура уже существует. Target allocation recalculation — ориентир hourly и
event-driven при значимых изменениях. События: APY movement · TVL movement ·
utilization · risk score change · new capital · withdrawal · reward expiry ·
gas regime change · liquidity change · Tier change · security alert. Trading не
происходит автоматически после каждого recalculation.»

Прибор НИЧЕГО НЕ ПРАВИТ: ни расписания, ни plist, ни политики, ни гейта, ни
аллокатора, ни такта любого агента. Расписание живого агента — это деплой
(инвариант #12 `CLAUDE.md`), а частота, с которой система трогает деньги, —
предмет №1 ADR-285. Прибор отвечает лишь на вопрос, КАКИЕ такты объявлены,
СВЯЗАНЫ ли они, и сколько из названных владельцем событий вообще способны
поднять пересчёт.

🪤 ЛОВУШКА, из-за которой заказ назвал ВОСЕМЬ событий вместо одиннадцати
------------------------------------------------------------------------------
Заказ G952 п. 1 перечисляет «восемь событий» (`APY movement · TVL movement ·
utilization · risk score change · new capital · withdrawal · reward expiry ·
gas regime change`). В тексте §21 их **ОДИННАДЦАТЬ**: пересказ потерял
`liquidity change`, `Tier change` и `security alert` — и потерял ровно те, у
которых в системе ЕСТЬ живой наблюдатель, то есть пересказ смещал ответ в
сторону «событий не читает никто». Поэтому :data:`OWNER_EVENTS` набран по
ТЕКСТУ ТЗ в карточке приказа, а не по тексту заказа, и число 11 объявлено
константой, которую сверяет тест.

Четыре вопроса, и ни один не выводится из другого
------------------------------------------------------------------------------
Первые три ставит заказ G952 п. 1 дословно, четвёртый — его же условие
(«иначе ответ будет верен СЛУЧАЙНО»).

1. **(а) СКОЛЬКО такта у наблюдения и сколько у пересчёта** (:data:`TACT_KINDS`).
   Спрашивается у ЖИВЫХ объявлений — `architecture/manifest.json` (поле
   ``schedule`` агента и ``produces[].slo_hours``), — а не у памяти автора.
   Агент пересчёта НЕ ЗАШИТ ИМЕНЕМ: он выводится из того, кто ОБЪЯВЛЕН
   производителем артефакта целевой раскладки (:data:`RECALC_ARTIFACTS`).
2. **(б) СВЯЗАНЫ ли два такта** (:data:`COUPLING_KINDS`). Мерится
   ДИФФЕРЕНЦИАЛЬНО, и возмущается РОВНО такт наблюдения: в КОПИИ объявления
   интервал каждого активного наблюдателя делится на :data:`PERTURB_FACTOR`, и
   тот же единственный читатель считает такт пересчёта заново. Род
   присваивается по СМЕНЕ числа, а не по чтению кода глазами. Положительный
   контроль возмущает такт САМОГО пересчёта — он сдвинуться ОБЯЗАН, иначе ответ
   о связи НЕ ВЫДАЁТСЯ.
3. **(в) СКОЛЬКО из названных событий способны поднять пересчёт**
   (:data:`EVENT_KINDS`). «Событие названо» ≠ «событие имеет читателя»: у
   каждого события измеряется НАБЛЮДАТЕЛЬ (активный агент, объявленный
   производителем артефакта, несущего это наблюдение) и ПУТЬ ПОДЪЁМА (читает ли
   этот артефакт хоть одна дверь, которая умеет поднять агента пересчёта).
   Множество дверей подъёма НЕ ОБЪЯВЛЕНО СПИСКОМ, а ИЗМЕРЕНО по дереву
   (:func:`raise_doors`).
4. **(г) ДОСТИЖИМ ли вопрос вообще** (:func:`reachability`). Объявление
   прочитано · агент пересчёта назван · двери подъёма измерены · и отдельно —
   контрапункт §20: событие `new capital` НЕДОСТИЖИМО ПО ПОСТРОЕНИЮ, потому что
   понятия «новые деньги» нет ни у одной из пяти поверхностей решения (ADR-963).
   Без этого «событие не поднимает пересчёт» было бы верно СЛУЧАЙНО.

🪤 ЛОВУШКА ВТОРАЯ: «два срока» — и прибор НЕ ВПРАВЕ выбирать срок сам
------------------------------------------------------------------------------
У агента объявлены ДВА разных числа про одно и то же: ``schedule`` («как часто
запускаюсь») и ``produces[].slo_hours`` («насколько старым разрешено быть моему
выводу»). Это НЕ одно и то же число и не обязаны совпадать — но и не являются
двумя ответами на один вопрос, из которых можно выбрать удобный. Заказ G952
п. 1 требует от прибора третьего исхода, а не выбора, и именно поэтому
:data:`ENFORCEMENT_KINDS` — ОТДЕЛЬНАЯ шкала: такт объявленный и такт
ПРИНУЖДАЕМЫЙ печатаются ОБА, рядом, с названным отношением. Сторож свежести
замечает нарушение только второго; значит «наблюдение каждые 5 минут» может
быть правдой расписания и при этом никем не охраняться.

🪤 ЛОВУШКА ТРЕТЬЯ: событие, читаемое ВНУТРИ пересчёта, событием не является
------------------------------------------------------------------------------
Соблазн — зачесть событию читателя, если его артефакт где-то читают. Но если
единственный читатель события есть САМ пересчёт, то эффективный такт события
РАВЕН такту пересчёта: «событийность» такого события не добавляет ни одного
срабатывания. Для этого в :data:`EVENT_KINDS` есть отдельный род
``read_at_recalc_tact``, и он НЕ засчитывается в ответ на вопрос (в).

🪤 ЛОВУШКА ЧЕТВЁРТАЯ: подъём агента ≠ подъём ПО СОБЫТИЮ
------------------------------------------------------------------------------
Дверь, поднимающая агента пересчёта потому, что он ПРОСТАИВАЕТ (ремонт живости
— разрыв цикла, мёртвая служба), поднимает его не по событию рынка, а по своему
отсутствию. Такая дверь в множество дверей подъёма ВХОДИТ (она действительно
умеет поднять пересчёт), но событию зачтётся только тогда, когда она читает
артефакт ЭТОГО события. Поэтому путь подъёма меряется по ПЕРЕСЕЧЕНИЮ «что
дверь читает» с «чем событие наблюдается», а не по факту существования двери.

Словари ВВЕЗЕНЫ, а не перепечатаны — и ввозится РОВНО то, что читается
------------------------------------------------------------------------------
``UNMEASURED`` — из §13 (``transaction_economics``); ``SURFACES_20`` (само
расширяющее ``SURFACES`` §41) и ``MONEY_PATH_20`` — из §20
(``new_capital_census``). Вторая копия словаря означала бы две шкалы,
расходящиеся молча. Свои здесь четыре, и каждая задаёт ось, которой до §21 не
существовало (:data:`TACT_KINDS`, :data:`ENFORCEMENT_KINDS`,
:data:`COUPLING_KINDS`, :data:`EVENT_KINDS`), либо РАСШИРЯЕТ ввезённое с
названной причиной (:data:`SURFACES_21`).

``EXPRESS_KINDS``/``MONEY_PATH_FILES`` §17 здесь НЕ ввезены намеренно, и это
тоже решение, а не недосмотр: первая редакция ввезла их «за компанию», и ни
один из двух не получил ни одного читателя. Ввезённый словарь без читателя —
это ЛОЖНОЕ УСИЛЕНИЕ (урок ADR-940…944): строка «словари ввезены» читается как
утверждение о связности шкал, а связывать нечего. ``MONEY_PATH_20`` читателя
имеет: им помечается каждая дверь подъёма (:func:`raise_doors`) — вопрос
«поднимает ли пересчёт дверь ДЕНЕЖНОГО пути» §21 задаёт по существу.

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Ввоз словарей. Своих копий здесь нет намеренно.
# ---------------------------------------------------------------------------
_VOCAB_ERRORS: List[str] = []

try:
    from .transaction_economics import UNMEASURED
except Exception as _exc:  # pragma: no cover — ввоз меряется тестом
    UNMEASURED = "unmeasured"
    _VOCAB_ERRORS.append("§13 UNMEASURED: {}: {}".format(type(_exc).__name__, _exc))

try:
    from .new_capital_census import MONEY_PATH_20, SURFACES_20
except Exception as _exc:  # pragma: no cover
    SURFACES_20 = ("allocator", "economics", "gate", "book", "journal")  # type: ignore[assignment]
    MONEY_PATH_20 = ()  # type: ignore[assignment]
    _VOCAB_ERRORS.append("§20 SURFACES_20/MONEY_PATH_20: {}: {}".format(
        type(_exc).__name__, _exc))


#: Поверхности §21. ``SURFACES_20`` несёт пять поверхностей РЕШЕНИЯ (кто считает
#: предложение, цену, допуск, состав книги и запись хода). §21 спрашивает не про
#: решение, а про ЧАСТОТУ — и ни одна из пяти частоту не называет. Расширение
#: названо: ``observation`` (кто смотрит на мир) и ``recalculation`` (кто
#: пересчитывает целевую раскладку). Своего словаря поверхностей прибор не
#: заводит — он РАСШИРЯЕТ ввезённый.
SURFACES_21: Tuple[str, ...] = tuple(SURFACES_20) + ("observation", "recalculation")

#: Ориентиры §21, объявленные ДОСЛОВНО по тексту ТЗ, в секундах. Это НЕ пороги
#: системы и прибор их никуда не записывает: §21 называет их «ориентир», и
#: единственное, что с ними делается, — сравнение с объявленным тактом.
#: «5–10 min» — интервал, поэтому ориентир наблюдения есть ПАРА, а не число:
#: сжать его до одного числа значило бы выдумать владельцу порог.
OBSERVATION_BENCHMARK_S: Tuple[float, float] = (300.0, 600.0)
#: «hourly» — одно число.
RECALC_BENCHMARK_S: float = 3600.0

#: ОДИННАДЦАТЬ событий §21, дословно и в порядке ТЗ. Число объявлено отдельной
#: константой намеренно: заказ G952 п. 1 назвал восемь, и расхождение пересказа
#: с ТЗ обязано краснеть тестом, а не жить в чьей-то памяти.
OWNER_EVENTS: Tuple[str, ...] = (
    "APY movement",
    "TVL movement",
    "utilization",
    "risk score change",
    "new capital",
    "withdrawal",
    "reward expiry",
    "gas regime change",
    "liquidity change",
    "Tier change",
    "security alert",
)
OWNER_EVENTS_DECLARED: int = 11

#: Отношение ОБЪЯВЛЕННОГО такта к ориентиру §21. Шкала ОБЪЯВЛЕНА, а не выведена
#: из сравнений: ветка `else` по построению не может сказать, какие роды
#: существуют (урок ADR-357 п. 3).
TACT_KINDS: Tuple[str, ...] = (
    # такт не грубее ориентира — §21 по этой оси исполняется
    "within_benchmark",
    # такт ГРУБЕЕ ориентира: пересчёт/наблюдение случается реже, чем просит §21
    "coarser_than_benchmark",
    # такт ТОНЬШЕ ориентира (чаще). Для наблюдения это не находка; род нужен,
    # чтобы «чаще» не печаталось как «в пределах» и не прятало расхождение
    "finer_than_benchmark",
    # расписание есть, но такта у него нет: демон, ручной запуск, событийный
    "no_interval_declared",
    UNMEASURED,
)

#: Отношение такта ОБЪЯВЛЕННОГО (``schedule``) к такту ПРИНУЖДАЕМОМУ
#: (минимальный ``slo_hours`` среди ``produces``). Отдельная шкала, и причина
#: названа в ловушке второй: это ДВА разных числа про одно и то же, и выбрать из
#: них прибор не вправе.
ENFORCEMENT_KINDS: Tuple[str, ...] = (
    # принуждаемый срок того же порядка, что такт — простой заметят быстро
    "enforced_at_tact",
    # принуждаемый срок СЛАБЕЕ такта: агент объявлен частым, а остановку его
    # вывода сторож свежести заметит много позже
    "enforced_looser",
    # у агента нет ни одного объявленного срока вывода
    "no_slo_declared",
    UNMEASURED,
)

#: СВЯЗАН ли такт пересчёта с тактом наблюдения. Мерится дифференциально.
COUPLING_KINDS: Tuple[str, ...] = (
    # возмущение такта наблюдения СДВИНУЛО такт пересчёта — §21 запрещает
    "coupled",
    # не сдвинуло: два такта независимы, как §21 и просит
    "decoupled",
    UNMEASURED,
)

#: Способно ли названное владельцем событие поднять пересчёт.
EVENT_KINDS: Tuple[str, ...] = (
    # у события есть наблюдатель, и его наблюдение читает дверь подъёма
    "raises_recalc",
    # событие наблюдает ТОЛЬКО сам пересчёт ⇒ эффективный такт события равен
    # такту пересчёта, и «событийность» не добавляет ни одного срабатывания
    "read_at_recalc_tact",
    # событие кто-то наблюдает, но подъёма от него не бывает ни по одному пути
    "observed_only",
    # событие не наблюдает НИ ОДИН активный производитель артефакта
    "no_reader",
    # понятия нет в системе вовсе — вопрос о подъёме НЕ ЗАДАН (а не отвечен «нет»)
    "unreachable_by_construction",
    UNMEASURED,
)

#: Во СКОЛЬКО раз возмущается такт наблюдения в дифференциальном замере. Число
#: объявлено, а не выбрано на месте: возмущение обязано быть заведомо больше
#: любого округления, иначе «не сдвинулось» было бы свойством арифметики.
PERTURB_FACTOR: float = 12.0

#: Артефакты ЦЕЛЕВОЙ РАСКЛАДКИ. Агент пересчёта НЕ зашит именем: он тот, кого
#: объявление называет ПРОИЗВОДИТЕЛЕМ этих артефактов. Перечень — объявление
#: предмета («что считается целевой раскладкой»), и он один, а не копия.
RECALC_ARTIFACTS: Tuple[str, ...] = (
    "data/allocation_rationale.json",
    "data/allocation_rationale_history.jsonl",
    "data/rebalance_trigger.json",
)

#: Роли агентов, которые §21 называет НАБЛЮДЕНИЕМ. Роль — поле объявления, а не
#: догадка по имени службы.
OBSERVATION_ROLES: Tuple[str, ...] = ("monitoring",)

#: Слово, по которому в дереве узнаётся ПОДЪЁМ службы. Одно, и это слово самой
#: ОС (`launchctl kickstart`), а не наше название приёма.
RAISE_WORD: str = "kickstart"

#: Артефакт стоп-крана (ADR-034/048). Им отличается дверь, поднимающая пересчёт
#: ради СНИЖЕНИЯ риска, от двери, поднимающей его ради улучшения раскладки.
#: Один артефакт, объявленный, а не перечень похожих имён.
KILL_SWITCH_ARTIFACT: str = "data/kill_switch_active.json"

#: ЗАЧЕМ дверь поднимает пересчёт. Шкала ОБЪЯВЛЕНА, и она есть ответ по существу
#: §21: «event-driven при значимых изменениях» просит подъёма ради УЛУЧШЕНИЯ
#: раскладки, а подъём ради снижения риска и подъём ради ремонта простоя — два
#: других предмета, которые §21 не заказывал и которые его не исполняют.
#: Без этой оси «событий, поднимающих пересчёт, двое» читалось бы как частичное
#: исполнение §21, хотя ни одно из двух не поднимает пересчёт ради улучшения.
RAISE_PURPOSES: Tuple[str, ...] = (
    # дверь рядом со подъёмом трогает стоп-кран ⇒ это снижение риска
    "derisk",
    # дверь читает ТОЛЬКО вывод самого пересчёта ⇒ она ремонтирует его простой
    "liveness_repair",
    # ни то, ни другое — подъём ради улучшения раскладки, как просит §21
    "improvement",
    UNMEASURED,
)

#: Где искать двери подъёма. Каталоги объявлены: обход всего дерева затянул бы
#: вложенные рабочие деревья чужих сессий (урок ADR-926…930).
RAISE_SEARCH_DIRS: Tuple[str, ...] = ("spa_core", "scripts")

#: Отношение, при котором принуждаемый срок считается «того же порядка», что
#: такт. Объявлено числом: «того же порядка» на слово не является мерой.
ENFORCEMENT_SAME_ORDER_MAX: float = 4.0

#: Объявление события в словаре СИСТЕМЫ: фрагменты путей артефактов, которыми
#: это наблюдение могло бы быть записано. Перечень — ОБЪЯВЛЕНИЕ с названной
#: причиной, и пустое пересечение есть ИЗМЕРЕННЫЙ НОЛЬ, а не молчание: мерится
#: вхождение фрагмента в путь артефакта `architecture/manifest.json`, и если не
#: совпал ни один — у события нет наблюдателя, и это сказано вслух.
EVENT_ARTIFACT_FRAGMENTS: Dict[str, Tuple[str, ...]] = {
    "APY movement": ("apy_", "_apy", "apy.json", "apy_ranking"),
    "TVL movement": ("tvl", "adapter_status", "adapter_orchestrator_status"),
    "utilization": ("utilization", "utilisation", "capacity"),
    "risk score change": ("risk_score", "risk_scoring", "red_flags",
                          "protocol_risk"),
    # §20 (ADR-963) измерил: понятия «новые деньги» нет ни у одной поверхности
    # решения. Фрагмент объявлен, чтобы ноль был ИЗМЕРЕН, а не предположен.
    "new capital": ("new_capital", "capital_sources", "deposit"),
    "withdrawal": ("withdraw", "exit_liquidity"),
    "reward expiry": ("reward", "incentive", "expiry", "maturity"),
    "gas regime change": ("gas", "base_gas"),
    "liquidity change": ("liquidity", "depth", "slippage"),
    "Tier change": ("tier_curator", "tier1_governance", "tier_", "promotion"),
    "security alert": ("red_flag", "peg_report", "threat", "emergency",
                       "security"),
}

#: События, объявленные НЕДОСТИЖИМЫМИ по построению, с причиной и адресом
#: замера. Это не вкус и не упрощение: у такого события вопрос «поднимает ли
#: оно пересчёт» НЕ ЗАДАН, и ответ «не поднимает» был бы верен СЛУЧАЙНО.
EVENTS_UNREACHABLE: Dict[str, str] = {
    "new capital": ("§20 (ADR-963, цикл #1081) измерил: понятия «новые деньги» "
                    "нет ни у одной из пяти поверхностей решения — род `absent` "
                    "у 5 из 5. Событие НЕВЫРАЗИМО, а не «без читателя»"),
}

#: Объявление, по которому меряются такты. Второй копии перечня агентов прибор
#: не держит.
MANIFEST_REL: str = "architecture/manifest.json"

#: Исход, означающий «агент объявлен, но не включён». Активность — поле
#: объявления (`intent`), а не наличие файла plist.
ACTIVE_INTENT: str = "active"

_INTERVAL_RE = re.compile(r"^interval:(\d+(?:\.\d+)?)s?$")
_CALENDAR_WEEKDAY_RE = re.compile(r"wd\d")
_CALENDAR_MINUTE_RE = re.compile(r"^calendar:minute:\d+$")

_DAY_S = 86_400.0
_WEEK_S = 604_800.0
_HOUR_S = 3_600.0


def _repo_root(root: Optional[Path] = None) -> Path:
    """Корень дерева. Умолчание — дерево ЭТОГО файла, и оно ПЕЧАТАЕТСЯ."""
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# (а) Такт: объявленный и принуждаемый
# ---------------------------------------------------------------------------

def tact_seconds(schedule: Optional[str]) -> Tuple[Optional[float], str]:
    """Такт, объявленный строкой расписания, и ПРИЧИНА, если такта нет.

    Три исхода различимы (инв. #17): такт назван числом · расписание есть, но
    такта у него нет (демон/ручной/событийный) · строка не разобрана.
    Возвращает ``(секунды | None, причина)``; при названном такте причина —
    форма, по которой он разобран.
    """
    if schedule is None:
        return None, "поля `schedule` в объявлении нет"
    s = str(schedule).strip()
    if not s:
        return None, "поле `schedule` пусто"

    m = _INTERVAL_RE.match(s)
    if m:
        return float(m.group(1)), "interval"

    if s in ("daemon",):
        return None, "непрерывный процесс (`daemon`): такт расписанием не объявлен"
    if s in ("manual",):
        return None, "ручной запуск (`manual`): такта нет по построению"
    if s.startswith("event:"):
        return None, "событийный запуск ({}): такта нет по построению".format(s)

    if _CALENDAR_MINUTE_RE.match(s):
        return _HOUR_S, "calendar:minute — раз в час"

    if s.startswith("calendar:"):
        body = s[len("calendar:"):]
        slots = [p for p in body.split(",") if p.strip()]
        if not slots:
            return None, "`calendar:` без ни одной отметки времени"
        weekly = sum(1 for p in slots if _CALENDAR_WEEKDAY_RE.search(p))
        if weekly and weekly == len(slots):
            return _WEEK_S / len(slots), "calendar по дням недели — {} раз(а) в неделю".format(
                len(slots))
        if weekly:
            return None, ("`calendar:` смешивает недельные и суточные отметки "
                          "({}) — одного такта у него нет".format(s))
        return _DAY_S / len(slots), "calendar — {} раз(а) в сутки".format(len(slots))

    return None, "форма расписания не разобрана: {!r}".format(s)


def enforced_seconds(agent: Dict[str, Any]) -> Tuple[Optional[float], List[float]]:
    """Принуждаемый срок агента: минимальный объявленный ``slo_hours``, в секундах.

    Минимум, а не среднее и не максимум: сторож свежести краснеет по САМОМУ
    строгому из объявленных сроков, и именно он есть тот срок, который хоть
    кто-то принуждает. Возвращает ``(секунды | None, все объявленные сроки)``.
    """
    slos: List[float] = []
    for p in (agent.get("produces") or []):
        v = p.get("slo_hours")
        if isinstance(v, (int, float)):
            slos.append(float(v))
    if not slos:
        return None, []
    return min(slos) * 3600.0, sorted(set(slos))


def _tact_kind_vs(tact_s: Optional[float], benchmark: Any,
                  why_no_tact: str) -> Tuple[str, str]:
    """Род такта относительно ориентира §21 и объяснение одной строкой."""
    if tact_s is None:
        return "no_interval_declared", why_no_tact
    if isinstance(benchmark, tuple):
        lo, hi = benchmark
        if tact_s > hi:
            return "coarser_than_benchmark", (
                "такт {:.0f} с ГРУБЕЕ ориентира §21 ({:.0f}–{:.0f} с) в {:.1f}×".format(
                    tact_s, lo, hi, tact_s / hi))
        if tact_s < lo:
            return "finer_than_benchmark", (
                "такт {:.0f} с ТОНЬШЕ ориентира §21 ({:.0f}–{:.0f} с)".format(
                    tact_s, lo, hi))
        return "within_benchmark", (
            "такт {:.0f} с в ориентире §21 ({:.0f}–{:.0f} с)".format(tact_s, lo, hi))
    if tact_s > benchmark:
        return "coarser_than_benchmark", (
            "такт {:.0f} с ГРУБЕЕ ориентира §21 ({:.0f} с) в {:.1f}×".format(
                tact_s, benchmark, tact_s / benchmark))
    if tact_s < benchmark:
        return "finer_than_benchmark", (
            "такт {:.0f} с ТОНЬШЕ ориентира §21 ({:.0f} с)".format(tact_s, benchmark))
    return "within_benchmark", "такт {:.0f} с равен ориентиру §21".format(tact_s)


def _enforcement_kind(tact_s: Optional[float],
                      enf_s: Optional[float]) -> Tuple[str, str]:
    """Отношение объявленного такта к принуждаемому сроку — ОТДЕЛЬНАЯ ось."""
    if enf_s is None:
        return "no_slo_declared", "ни одного объявленного срока вывода"
    if tact_s is None:
        return UNMEASURED, ("срок вывода {:.0f} с объявлен, а такта запуска нет — "
                            "отношение не вычисляется".format(enf_s))
    ratio = enf_s / tact_s if tact_s else None
    if ratio is not None and ratio > ENFORCEMENT_SAME_ORDER_MAX:
        return "enforced_looser", (
            "принуждаемый срок {:.0f} с СЛАБЕЕ такта {:.0f} с в {:.0f}×".format(
                enf_s, tact_s, ratio))
    return "enforced_at_tact", (
        "принуждаемый срок {:.0f} с того же порядка, что такт {:.0f} с".format(
            enf_s, tact_s))


def load_manifest(root: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Объявление агентов и артефактов. Нечитаемое объявление — третий исход."""
    path = root / MANIFEST_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, "{} не прочитан: {}: {}".format(
            MANIFEST_REL, type(exc).__name__, exc)
    if not isinstance(doc.get("agents"), list):
        return None, "{}: ключа `agents` нет или он не список".format(MANIFEST_REL)
    if not isinstance(doc.get("artifacts"), list):
        return None, "{}: ключа `artifacts` нет или он не список".format(MANIFEST_REL)
    return doc, None


def _active_agents(manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [a for a in manifest["agents"]
            if a.get("intent") == ACTIVE_INTENT and a.get("label")]


def recalc_agent(manifest: Dict[str, Any]) -> Tuple[Optional[str], List[str], str]:
    """Агент ПЕРЕСЧЁТА — тот, кого объявление называет производителем целевой раскладки.

    Имя не зашито: оно ИЗМЕРЕНО по объявлению. Два производителя у одного
    предмета — третий исход, а не выбор первого попавшегося.
    """
    found: Dict[str, List[str]] = {}
    # Дверь к объявлению ОДНА (:func:`declared_productions`) — своей копии
    # разбора здесь нет намеренно: разойдись они, прибор мерил бы такт одного
    # агента, а события относил бы к другому.
    for path, producers in declared_productions(manifest).items():
        if path in RECALC_ARTIFACTS:
            for producer in producers:
                found.setdefault(producer, []).append(path)
    if not found:
        return None, [], ("ни один артефакт целевой раскладки ({}) не имеет "
                          "объявленного производителя".format(
                              ", ".join(RECALC_ARTIFACTS)))
    if len(found) > 1:
        return None, sorted(found), (
            "производителей целевой раскладки объявлено {}: {} — единственного "
            "ответа у вопроса «какой такт пересчёта» нет".format(
                len(found), ", ".join(sorted(found))))
    label = next(iter(found))
    return label, sorted(set(found[label])), (
        "объявлен производителем {}".format(", ".join(sorted(set(found[label])))))


def _agent_by_label(manifest: Dict[str, Any], label: str) -> Optional[Dict[str, Any]]:
    for a in manifest["agents"]:
        if a.get("label") == label:
            return a
    return None


def observation_tact(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Такт НАБЛЮДЕНИЯ: самый тонкий объявленный такт среди активных наблюдателей.

    Самый тонкий, а не медиана: §21 про то, как часто система СМОТРИТ, и
    смотрит она так часто, как смотрит её самый частый наблюдатель.
    """
    rows: List[Dict[str, Any]] = []
    for a in _active_agents(manifest):
        if a.get("role") not in OBSERVATION_ROLES:
            continue
        tact_s, why = tact_seconds(a.get("schedule"))
        enf_s, slos = enforced_seconds(a)
        ekind, ewhy = _enforcement_kind(tact_s, enf_s)
        rows.append({
            "label": a["label"], "schedule": a.get("schedule"),
            "tact_s": tact_s, "tact_why": why,
            "enforced_s": enf_s, "slo_hours": slos,
            "enforcement_kind": ekind, "enforcement_why": ewhy,
        })
    with_tact = [r for r in rows if r["tact_s"] is not None]
    if not with_tact:
        return {"surface": "observation", "kind": UNMEASURED,
                "why": "ни у одного активного наблюдателя такт не объявлен числом",
                "agents": rows, "tact_s": None, "finest": None}
    finest = min(with_tact, key=lambda r: r["tact_s"])
    kind, why = _tact_kind_vs(finest["tact_s"], OBSERVATION_BENCHMARK_S,
                              finest["tact_why"])
    return {"surface": "observation", "kind": kind, "why": why,
            "tact_s": finest["tact_s"], "finest": finest["label"],
            "agents": rows,
            "agents_with_tact": len(with_tact), "agents_total": len(rows)}


def recalculation_tact(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Такт ПЕРЕСЧЁТА целевой раскладки — у измеренного агента пересчёта."""
    label, artifacts, why_label = recalc_agent(manifest)
    if label is None:
        return {"surface": "recalculation", "kind": UNMEASURED, "why": why_label,
                "tact_s": None, "label": None, "artifacts": artifacts}
    agent = _agent_by_label(manifest, label)
    if agent is None:
        return {"surface": "recalculation", "kind": UNMEASURED,
                "why": "производитель {} назван артефактом, но самого агента в "
                       "объявлении нет".format(label),
                "tact_s": None, "label": label, "artifacts": artifacts}
    tact_s, why = tact_seconds(agent.get("schedule"))
    enf_s, slos = enforced_seconds(agent)
    ekind, ewhy = _enforcement_kind(tact_s, enf_s)
    kind, why_kind = _tact_kind_vs(tact_s, RECALC_BENCHMARK_S, why)
    return {"surface": "recalculation", "kind": kind, "why": why_kind,
            "tact_s": tact_s, "tact_why": why, "label": label,
            "schedule": agent.get("schedule"), "artifacts": artifacts,
            "why_label": why_label,
            "enforced_s": enf_s, "slo_hours": slos,
            "enforcement_kind": ekind, "enforcement_why": ewhy,
            "intent": agent.get("intent")}


def enforcement_spread(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """«Два срока» по всем активным наблюдателям и агентам раскладки.

    Заказ G952 п. 1 требует от прибора ТРЕТЬЕГО исхода, а не выбора срока.
    Здесь печатаются ОБА числа и их отношение; худшее отношение называется
    поимённо — это и есть цена вопроса «какой такт настоящий».
    """
    rows: List[Dict[str, Any]] = []
    for a in _active_agents(manifest):
        if a.get("role") not in (tuple(OBSERVATION_ROLES) + ("allocation",)):
            continue
        tact_s, why = tact_seconds(a.get("schedule"))
        enf_s, slos = enforced_seconds(a)
        kind, kwhy = _enforcement_kind(tact_s, enf_s)
        rows.append({"label": a["label"], "role": a.get("role"),
                     "schedule": a.get("schedule"), "tact_s": tact_s,
                     "tact_why": why, "enforced_s": enf_s, "slo_hours": slos,
                     "kind": kind, "why": kwhy,
                     "ratio": (enf_s / tact_s) if (tact_s and enf_s) else None})
    looser = [r for r in rows if r["kind"] == "enforced_looser"]
    worst = max(looser, key=lambda r: r["ratio"]) if looser else None
    by_kind: Dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    multi = [r for r in rows if len(r["slo_hours"]) > 1]
    return {"rows": rows, "by_kind": by_kind,
            "looser_count": len(looser),
            "worst": worst,
            "multi_slo_count": len(multi),
            "multi_slo": sorted(r["label"] for r in multi),
            "why": ("у {} агентов объявлено больше одного срока вывода — главным "
                    "не назван ни один, поэтому у вопроса «какой такт настоящий» "
                    "нет единственного ответа и прибор его НЕ ВЫБИРАЕТ".format(
                        len(multi)))}


# ---------------------------------------------------------------------------
# (б) Связаны ли два такта — ДИФФЕРЕНЦИАЛЬНО
# ---------------------------------------------------------------------------

def _perturb_observation(manifest: Dict[str, Any], factor: float) -> Dict[str, Any]:
    """КОПИЯ объявления, в которой возмущён РОВНО такт наблюдения.

    Возмущается только форма ``interval:`` и только у активных наблюдателей:
    переписать `calendar:` значило бы возмутить заодно и ЧИСЛО отметок, то есть
    две величины сразу.
    """
    copy = json.loads(json.dumps(manifest))
    touched: List[str] = []
    for a in copy["agents"]:
        if a.get("intent") != ACTIVE_INTENT:
            continue
        if a.get("role") not in OBSERVATION_ROLES:
            continue
        m = _INTERVAL_RE.match(str(a.get("schedule") or ""))
        if not m:
            continue
        a["schedule"] = "interval:{:.0f}s".format(float(m.group(1)) / factor)
        touched.append(a["label"])
    copy["_perturbed"] = touched
    return copy


def _perturb_recalc(manifest: Dict[str, Any], label: str,
                    seconds: float) -> Dict[str, Any]:
    """КОПИЯ объявления, в которой возмущён такт САМОГО пересчёта.

    Это положительный контроль: величина, которую читатель СВЯЗЫВАЕТ ЗАВЕДОМО.
    Не сдвинулась она ⇒ ответ о связи не выдаётся (дело в приборе, а не в мире).
    """
    copy = json.loads(json.dumps(manifest))
    for a in copy["agents"]:
        if a.get("label") == label:
            a["schedule"] = "interval:{:.0f}s".format(seconds)
    return copy


def coupling(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """СВЯЗАН ли такт пересчёта с тактом наблюдения.

    Возмущается РОВНО такт наблюдения (в ``PERTURB_FACTOR`` раз чаще), и тот же
    единственный читатель :func:`recalculation_tact` считает такт пересчёта
    заново. Род — по СМЕНЕ числа.
    """
    base_obs = observation_tact(manifest)
    base_rec = recalculation_tact(manifest)
    if base_rec["tact_s"] is None:
        return {"kind": UNMEASURED,
                "why": "такт пересчёта не измерен: {}".format(base_rec["why"]),
                "base_recalc_s": None, "base_observation_s": base_obs["tact_s"]}

    perturbed = _perturb_observation(manifest, PERTURB_FACTOR)
    moved_obs = observation_tact(perturbed)
    if not perturbed.get("_perturbed"):
        return {"kind": UNMEASURED,
                "why": ("возмутить такт наблюдения нечем: ни у одного активного "
                        "наблюдателя расписание не имеет формы `interval:`"),
                "base_recalc_s": base_rec["tact_s"],
                "base_observation_s": base_obs["tact_s"]}
    if moved_obs["tact_s"] == base_obs["tact_s"]:
        return {"kind": UNMEASURED,
                "why": ("возмущение не сдвинуло даже такт НАБЛЮДЕНИЯ "
                        "({} → {}) — замер о приборе, а не о мире".format(
                            base_obs["tact_s"], moved_obs["tact_s"])),
                "base_recalc_s": base_rec["tact_s"],
                "base_observation_s": base_obs["tact_s"]}

    after_rec = recalculation_tact(perturbed)

    # Положительный контроль: возмутить такт САМОГО пересчёта.
    control_target_s = base_rec["tact_s"] / PERTURB_FACTOR
    control = recalculation_tact(
        _perturb_recalc(manifest, base_rec["label"], control_target_s))
    control_moved = (control["tact_s"] is not None
                     and control["tact_s"] != base_rec["tact_s"])
    if not control_moved:
        return {"kind": UNMEASURED,
                "why": ("положительный контроль НЕ сменил такт пересчёта "
                        "({} → {}): читатель такта глух к объявлению, и ответ о "
                        "связи не выдаётся".format(base_rec["tact_s"],
                                                   control.get("tact_s"))),
                "base_recalc_s": base_rec["tact_s"],
                "base_observation_s": base_obs["tact_s"],
                "control_moved": False}

    moved = after_rec["tact_s"] != base_rec["tact_s"]
    return {
        "kind": "coupled" if moved else "decoupled",
        "why": ("такт наблюдения {:.0f} → {:.0f} с у {} агент(ов); такт пересчёта "
                "{} {:.0f} с".format(
                    base_obs["tact_s"], moved_obs["tact_s"],
                    len(perturbed["_perturbed"]),
                    "СДВИНУЛСЯ на" if moved else "НЕ сдвинулся:",
                    (after_rec["tact_s"] or 0.0))),
        "base_observation_s": base_obs["tact_s"],
        "perturbed_observation_s": moved_obs["tact_s"],
        "base_recalc_s": base_rec["tact_s"],
        "perturbed_recalc_s": after_rec["tact_s"],
        "perturbed_agents": perturbed["_perturbed"],
        "control_moved": True,
        "control_recalc_s": control["tact_s"],
    }


# ---------------------------------------------------------------------------
# Двери подъёма: ИЗМЕРЕНЫ по дереву, а не объявлены списком
# ---------------------------------------------------------------------------

def _string_literals(node: ast.AST) -> List[str]:
    """Все строковые литералы поддерева, включая части f-строк.

    Части f-строки нужны по замеру: единственная дверь, поднимающая цикл,
    собирает метку службы f-строкой (`f"gui/{uid}/com.spa.daily_cycle"`), и
    разбор, смотрящий только на `ast.Constant` верхнего уровня, её НЕ НАЙДЁТ.
    """
    out: List[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def event_artifact_names(manifest: Dict[str, Any]) -> Dict[str, List[str]]:
    """Имя артефакта → события §21, наблюдение которых он несёт.

    Это тот же единственный разбор объявления и тот же единственный словарь
    фрагментов, которыми меряется ось (в). Второй копии правила «что считается
    наблюдением события» здесь нет намеренно: разойдись она с осью (в), дверь
    получила бы цель по одному словарю, а событие — читателя по другому.
    """
    out: Dict[str, List[str]] = {}
    for event, fragments in EVENT_ARTIFACT_FRAGMENTS.items():
        for row in _artifacts_for_event(manifest, fragments):
            out.setdefault(Path(row["artifact"]).name, []).append(event)
    return {k: sorted(set(v)) for k, v in out.items()}


def _raise_purpose(reads: Sequence[str],
                   event_names: Dict[str, List[str]]) -> Tuple[str, str]:
    """ЗАЧЕМ эта дверь поднимает пересчёт. Порядок проверок значим.

    Снижение риска проверяется ПЕРВЫМ: дверь, трогающая стоп-кран, поднимает
    пересчёт ради него и остаётся таковой, даже если читает что-то ещё — у
    такого подъёма цель названа самим стоп-краном.

    Дальше решает НЕ «что дверь читает вообще», а читает ли она хоть одно
    НАБЛЮДЕНИЕ СОБЫТИЯ §21. Первая редакция спрашивала «читает ли дверь только
    вывод самого пересчёта» и отнесла `self_heal` к подъёму ради улучшения —
    неверно: эта дверь читает `paper_trading_status.json` (разрыв цикла) и
    маячок бота, то есть судит о МОЛЧАНИИ, а не о мире, а «улучшением» её
    сделали её же собственные файлы статуса, не попавшие в вывод пересчёта.
    Мера теперь привязана к предмету §21: подъём РАДИ УЛУЧШЕНИЯ — это подъём от
    наблюдения, которое несёт одно из одиннадцати названных владельцем событий.
    """
    names = {Path(x).name for x in reads}
    if Path(KILL_SWITCH_ARTIFACT).name in names:
        return "derisk", ("дверь трогает стоп-кран ({}) — подъём ради снижения "
                          "риска, а не ради улучшения раскладки".format(
                              KILL_SWITCH_ARTIFACT))
    if not names:
        return UNMEASURED, "у двери не нашлось ни одного имени артефакта"
    carried = sorted({e for n in names for e in event_names.get(n, ())})
    if not carried:
        return "liveness_repair", (
            "ни одно из читаемых дверью наблюдений не несёт события §21 — она "
            "судит о МОЛЧАНИИ пересчёта, а не о событии мира")
    return "improvement", (
        "дверь читает наблюдение событий §21 ({}) и стоп-крана не трогает".format(
            ", ".join(carried)))


def raise_doors(root: Path, recalc_label: Optional[str],
                event_names: Optional[Dict[str, List[str]]] = None,
                ) -> Dict[str, Any]:
    """Файлы, умеющие ПОДНЯТЬ агента пересчёта, и что каждый из них ЧИТАЕТ.

    Дверь узнаётся по вызову, в поддереве аргументов которого есть И слово ОС
    ``kickstart``, И метка агента пересчёта. Обе формы живого дерева этим
    покрыты: список аргументов ``subprocess.run`` с f-строкой метки и вызов
    локального помощника ``_kickstart("<метка>")`` — в первом случае слово лежит
    рядом с меткой в одном списке, во втором слово в ИМЕНИ вызываемого, поэтому
    имя вызываемого тоже участвует в проверке.

    Что дверь ЧИТАЕТ — множество строковых литералов файла, похожих на имя
    артефакта (``*.json``/``*.jsonl``). Третий исход: файл не разобран ⇒ он
    назван в ``unparsed``, а не выброшен молча.
    """
    if not recalc_label:
        return {"doors": [], "unparsed": [], "kind": UNMEASURED,
                "why": "метка агента пересчёта не измерена — искать нечего"}
    doors: List[Dict[str, Any]] = []
    unparsed: List[str] = []
    scanned = 0
    for rel in RAISE_SEARCH_DIRS:
        base = root / rel
        if not base.is_dir():
            unparsed.append("{}: каталога нет в дереве".format(rel))
            continue
        for path in sorted(base.rglob("*.py")):
            if "/tests/" in path.as_posix() or path.name.startswith("test_"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                unparsed.append("{}: {}".format(path, type(exc).__name__))
                continue
            if recalc_label not in text or RAISE_WORD not in text:
                continue
            scanned += 1
            try:
                tree = ast.parse(text)
            except SyntaxError as exc:
                unparsed.append("{}: SyntaxError {}".format(path, exc.lineno))
                continue
            hits: List[int] = []
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                callee = ""
                if isinstance(node.func, ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callee = node.func.attr
                lits = _string_literals(node)
                has_word = (RAISE_WORD in callee
                            or any(RAISE_WORD in s for s in lits))
                has_label = any(recalc_label in s for s in lits)
                if has_word and has_label:
                    hits.append(node.lineno)
            if not hits:
                continue
            reads = sorted({s for s in _string_literals(tree)
                            if s.endswith(".json") or s.endswith(".jsonl")})
            rel_posix = path.relative_to(root).as_posix()
            purpose, purpose_why = _raise_purpose(
                reads, event_names or {})
            doors.append({
                "file": rel_posix,
                "lines": sorted(hits),
                "reads": reads,
                "purpose": purpose,
                "purpose_why": purpose_why,
                # Ввезённый перечень §20 получает здесь своего читателя: §21 по
                # существу спрашивает, поднимает ли пересчёт дверь ДЕНЕЖНОГО
                # пути или советательная.
                "money_path": rel_posix in tuple(MONEY_PATH_20),
            })
    by_purpose: Dict[str, int] = {}
    for d in doors:
        by_purpose[d["purpose"]] = by_purpose.get(d["purpose"], 0) + 1
    return {"doors": doors, "unparsed": unparsed, "candidates_scanned": scanned,
            "by_purpose": by_purpose,
            "improvement_doors": [d["file"] for d in doors
                                  if d["purpose"] == "improvement"],
            "kind": UNMEASURED if (not doors and unparsed) else "measured",
            "why": ("дверей подъёма {}: {}".format(
                len(doors), ", ".join(d["file"] for d in doors) or "НИ ОДНОЙ"))}


# ---------------------------------------------------------------------------
# (в) Сколько из названных событий способны поднять пересчёт
# ---------------------------------------------------------------------------

def declared_productions(manifest: Dict[str, Any]) -> Dict[str, List[str]]:
    """Артефакт → активные производители, по ОБЪЕДИНЕНИЮ двух половин объявления.

    🪤 Половин ДВЕ, и прочитать одну значит ответить не на тот вопрос. Замер
    цикла #1082 на живом объявлении: в списке ``artifacts`` 166 путей, на
    стороне агентов (``produces[]``) — 234, и **73** артефакта объявлены ТОЛЬКО
    на стороне агентов. Первая редакция этого прибора читала список
    ``artifacts`` и выдала шесть «ИЗМЕРЕННЫХ НУЛЕЙ» подряд — в том числе про
    `security alert`, чьё наблюдение (`data/red_flags.json`) ДЕМОНСТРАТИВНО
    читает измеренная дверь подъёма. Ноль был свойством прочитанной половины, а
    не мира; нашёл его не глаз, а собственный вывод прибора, где дверь читала
    артефакт, которого прибор «не находил». Это ровно тот урок, что у переписи
    `delivery_tree_input_census` (ADR-933): поверхность есть ОБЪЕДИНЕНИЕ мест
    объявления, и недоступность любого из них есть НЕ ИЗМЕРЕНО, а не поверхность
    поменьше.
    """
    active = {a["label"]: a for a in _active_agents(manifest)}
    out: Dict[str, List[str]] = {}
    for art in manifest["artifacts"]:
        path = str(art.get("path") or "")
        producer = art.get("producer")
        if path and producer and str(producer) in active:
            out.setdefault(path, []).append(str(producer))
    for label, agent in active.items():
        for p in (agent.get("produces") or []):
            path = str(p.get("artifact") or "")
            if path:
                out.setdefault(path, []).append(label)
    return {k: sorted(set(v)) for k, v in out.items()}


def _artifacts_for_event(manifest: Dict[str, Any], fragments: Sequence[str],
                         ) -> List[Dict[str, Any]]:
    """Активные производители артефактов, чей путь несёт фрагмент события."""
    rows: List[Dict[str, Any]] = []
    for path, producers in sorted(declared_productions(manifest).items()):
        if not any(fr in path for fr in fragments):
            continue
        for producer in producers:
            agent = _agent_by_label(manifest, producer)
            if agent is None:
                continue
            tact_s, why = tact_seconds(agent.get("schedule"))
            rows.append({"artifact": path, "producer": producer,
                         "tact_s": tact_s, "tact_why": why,
                         "schedule": agent.get("schedule")})
    return rows


def events(manifest: Dict[str, Any], doors: Dict[str, Any],
           recalc_label: Optional[str]) -> Dict[str, Any]:
    """Каждое из ОДИННАДЦАТИ событий §21 — поимённо, с родом и причиной."""
    read_by_doors: set = set()
    for d in (doors.get("doors") or []):
        for name in d.get("reads", []):
            read_by_doors.add(name)

    rows: List[Dict[str, Any]] = []
    for event in OWNER_EVENTS:
        if event in EVENTS_UNREACHABLE:
            rows.append({"event": event, "kind": "unreachable_by_construction",
                         "why": EVENTS_UNREACHABLE[event], "observers": []})
            continue
        fragments = EVENT_ARTIFACT_FRAGMENTS.get(event)
        if not fragments:
            rows.append({"event": event, "kind": UNMEASURED,
                         "why": "словарь системы для этого события не объявлен",
                         "observers": []})
            continue
        obs = _artifacts_for_event(manifest, fragments)
        if not obs:
            rows.append({"event": event, "kind": "no_reader",
                         "why": ("ни один активный производитель не объявлен для "
                                 "артефакта с фрагментами {} — ИЗМЕРЕННЫЙ ноль"
                                 .format(", ".join(fragments))),
                         "observers": []})
            continue
        raised = [o for o in obs
                  if Path(o["artifact"]).name in read_by_doors]
        if raised:
            # Печатается ОДНА строка целиком, а не производитель из одной и
            # такт из другой: у `security alert` поднятых наблюдений три
            # (`red_flags` 300 с, `peg_report` 300 с, `emergency_status`
            # 86400 с), и смешать их значило бы приписать такт 300 с агенту,
            # который работает раз в сутки. Первая редакция этого прибора так и
            # сделала. Выбирается САМОЕ ЧАСТОЕ поднятое наблюдение — именно оно
            # отвечает на вопрос «как быстро событие способно поднять пересчёт».
            timed = [o for o in raised if o["tact_s"] is not None]
            finest = min(timed, key=lambda o: o["tact_s"]) if timed else None
            lead = finest or raised[0]
            rows.append({
                "event": event, "kind": "raises_recalc",
                "why": ("наблюдение {} ({}) читает дверь подъёма; такт "
                        "наблюдения {}".format(
                            lead["artifact"], lead["producer"],
                            "{:.0f} с".format(lead["tact_s"])
                            if lead["tact_s"] is not None
                            else "расписанием не объявлен ({})".format(
                                lead["tact_why"]))),
                "observers": obs,
                "raised_by_artifacts": [o["artifact"] for o in raised],
                "fastest_raise_s": finest["tact_s"] if finest else None})
            continue
        producers = {o["producer"] for o in obs}
        if recalc_label and producers == {recalc_label}:
            rows.append({
                "event": event, "kind": "read_at_recalc_tact",
                "why": ("единственный производитель наблюдения — САМ пересчёт "
                        "({}), значит эффективный такт события равен такту "
                        "пересчёта".format(recalc_label)),
                "observers": obs})
            continue
        rows.append({
            "event": event, "kind": "observed_only",
            "why": ("наблюдателей {}, но ни одно их наблюдение не читает дверь "
                    "подъёма".format(len(obs))),
            "observers": obs})

    by_kind: Dict[str, int] = {}
    for r in rows:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    improvement_doors = [d["file"] for d in (doors.get("doors") or [])
                         if d.get("purpose") == "improvement"]
    return {"rows": rows, "by_kind": by_kind,
            "declared": OWNER_EVENTS_DECLARED,
            "raises": by_kind.get("raises_recalc", 0),
            "improvement_doors": improvement_doors,
            # Главное число §21 — НЕ «сколько событий поднимают пересчёт», а
            # «сколько поднимают его РАДИ УЛУЧШЕНИЯ раскладки». Без второго
            # первое читается как частичное исполнение §21, хотя подъём ради
            # снижения риска §21 не заказывал (его заказал ADR-070), а ремонт
            # простоя не является реакцией на мир вовсе.
            "raises_for_improvement": 0 if not improvement_doors else sum(
                1 for r in rows if r["kind"] == "raises_recalc"),
            "why": ("из {} событий §21 пересчёт способны поднять {}, и РАДИ "
                    "УЛУЧШЕНИЯ раскладки — {}".format(
                        OWNER_EVENTS_DECLARED, by_kind.get("raises_recalc", 0),
                        0 if not improvement_doors else by_kind.get(
                            "raises_recalc", 0)))}


# ---------------------------------------------------------------------------
# (г) Достижимость
# ---------------------------------------------------------------------------

def reachability(manifest: Optional[Dict[str, Any]], root: Path,
                 recalc: Dict[str, Any], doors: Dict[str, Any]) -> Dict[str, Any]:
    """ДОСТИЖИМ ли вопрос §21 вообще. Третий исход у каждой половины."""
    out: Dict[str, Any] = {"root": str(root)}
    out["manifest"] = ("прочитано" if manifest else "НЕ ПРОЧИТАНО")
    out["recalc_named"] = bool(recalc.get("label"))
    out["recalc_why"] = recalc.get("why_label") or recalc.get("why")
    out["doors_measured"] = bool(doors.get("doors")) or doors.get("kind") == "measured"
    out["doors_why"] = doors.get("why")
    out["unreachable_events"] = sorted(EVENTS_UNREACHABLE)
    out["why_unreachable"] = (
        "событие `new capital` §21 называет ПЯТЫМ из одиннадцати, а §20 "
        "(ADR-963) измерил, что понятия «новые деньги» в системе нет ни у одной "
        "поверхности решения ⇒ вопрос о его подъёме НЕ ЗАДАН. Без этой оговорки "
        "«событие не поднимает пересчёт» было бы верно СЛУЧАЙНО")
    return out


# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------

def census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Полный замер §21. Только ЧИТАЕТ."""
    rt = _repo_root(root)
    report: Dict[str, Any] = {
        "order": "G952 п. 1",
        "paragraph": "§21 Частота работы",
        "root": str(rt),
        "root_defaulted": root is None,
        "surfaces_declared": list(SURFACES_21),
        "vocab_errors": list(_VOCAB_ERRORS),
        "unmeasured": [],
        "benchmarks": {"observation_s": list(OBSERVATION_BENCHMARK_S),
                       "recalculation_s": RECALC_BENCHMARK_S},
        "advisory": ("прибор только ЧИТАЕТ: ни расписание, ни plist, ни политика, "
                     "ни гейт, ни аллокатор, ни такт любого агента не тронуты. "
                     "Расписание живого агента — деплой (инв. #12), частота "
                     "касания денег — предмет №1 ADR-285"),
    }

    manifest, err = load_manifest(rt)
    if manifest is None:
        report["unmeasured"].append(err or "объявление не прочитано")
        report["observation"] = {"kind": UNMEASURED, "why": err}
        report["recalculation"] = {"kind": UNMEASURED, "why": err, "label": None}
        report["coupling"] = {"kind": UNMEASURED, "why": err}
        report["enforcement"] = {"rows": [], "by_kind": {}, "why": err,
                                 "looser_count": 0, "worst": None,
                                 "multi_slo_count": 0, "multi_slo": []}
        # Ключи те же, что у измеренного ответа: отсутствующий ключ уронил бы
        # РЕНДЕР, а падение рендера прячет «не измерено» так же надёжно, как
        # молчание. Это нашёл собственный тест, а не глаз.
        report["events"] = {"rows": [], "by_kind": {}, "raises": 0,
                            "declared": OWNER_EVENTS_DECLARED,
                            "raises_for_improvement": 0,
                            "improvement_doors": [], "why": err}
        report["reachability"] = reachability(None, rt,
                                              report["recalculation"],
                                              {"doors": [], "why": err})
        return report

    obs = observation_tact(manifest)
    rec = recalculation_tact(manifest)
    event_names = event_artifact_names(manifest)
    doors = raise_doors(rt, rec.get("label"), event_names)
    report["observation"] = obs
    report["recalculation"] = rec
    report["enforcement"] = enforcement_spread(manifest)
    report["coupling"] = coupling(manifest)
    report["raise_doors"] = doors
    report["events"] = events(manifest, doors, rec.get("label"))
    report["reachability"] = reachability(manifest, rt, rec, doors)

    for key in ("observation", "recalculation"):
        if report[key]["kind"] == UNMEASURED:
            report["unmeasured"].append("{}: {}".format(key, report[key]["why"]))
    if report["coupling"]["kind"] == UNMEASURED:
        report["unmeasured"].append("coupling: {}".format(report["coupling"]["why"]))
    if doors.get("kind") == UNMEASURED:
        report["unmeasured"].append("raise_doors: {}".format(doors.get("why")))
    for r in report["events"]["rows"]:
        if r["kind"] == UNMEASURED:
            report["unmeasured"].append("event {}: {}".format(r["event"], r["why"]))
    return report


def verdict_code(report: Dict[str, Any]) -> int:
    """0 — §21 исполняется · 1 — находка НАЗВАНА · 2 — НЕ ИЗМЕРЕНО.

    Порядок проверок значим: «не измерено» НЕ ХУЖЕ и НЕ ЛУЧШЕ находки, это
    отдельный исход (инв. #17), и он решается ПЕРВЫМ — иначе ненадёжный замер
    печатался бы как вердикт о мире.
    """
    if report.get("vocab_errors") or report.get("unmeasured"):
        return 2
    ok_obs = report["observation"]["kind"] in ("within_benchmark",
                                               "finer_than_benchmark")
    ok_rec = report["recalculation"]["kind"] in ("within_benchmark",
                                                 "finer_than_benchmark")
    ok_coupling = report["coupling"]["kind"] == "decoupled"
    # Исполнением §21 считается подъём РАДИ УЛУЧШЕНИЯ: подъём ради снижения
    # риска §21 не заказывал, и зачесть его значило бы объявить §21
    # исполненным тем, что сделано по другому решению (ADR-070).
    ok_events = (report["events"].get("raises_for_improvement", 0)
                 == report["events"]["declared"] - len(EVENTS_UNREACHABLE))
    ok_enforce = report["enforcement"]["looser_count"] == 0
    if ok_obs and ok_rec and ok_coupling and ok_events and ok_enforce:
        return 0
    return 1


def render(report: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append("{} — такт наблюдения ОТДЕЛЬНО от такта пересчёта (заказ {})".format(
        report["paragraph"], report["order"]))
    L.append("  дерево: {}{}".format(
        report["root"], " (УМОЛЧАНИЕ)" if report.get("root_defaulted") else ""))

    o, r = report["observation"], report["recalculation"]
    L.append("")
    L.append("(а) ТАКТ по двум поверхностям §21:")
    L.append("  наблюдение    {:24s} {}".format(o["kind"], o["why"]))
    if o.get("finest"):
        L.append("                самый частый наблюдатель: {} ({} активных, "
                 "такт объявлен у {})".format(
                     o["finest"], o.get("agents_total"), o.get("agents_with_tact")))
    L.append("  пересчёт      {:24s} {}".format(r["kind"], r["why"]))
    if r.get("label"):
        L.append("                агент пересчёта ИЗМЕРЕН: {} ({}) — {}".format(
            r["label"], r.get("schedule"), r.get("why_label")))

    e = report["enforcement"]
    L.append("")
    L.append("    «ДВА СРОКА» — прибор их НЕ СВОДИТ (заказ требует третьего исхода):")
    L.append("      {}".format(e["why"]))
    for kind in ENFORCEMENT_KINDS:
        if kind in e["by_kind"]:
            L.append("      {:18s} {}".format(kind, e["by_kind"][kind]))
    if e.get("worst"):
        w = e["worst"]
        L.append("      худшее отношение: {} — такт {:.0f} с, принуждаемый срок "
                 "{:.0f} с ({:.0f}×)".format(
                     w["label"], w["tact_s"], w["enforced_s"], w["ratio"]))

    c = report["coupling"]
    L.append("")
    L.append("(б) СВЯЗАНЫ ли такты: {}".format(c["kind"]))
    L.append("    {}".format(c["why"]))
    if c.get("control_moved"):
        L.append("    ✅ контроль: возмущение такта САМОГО пересчёта его сдвинуло "
                 "({:.0f} → {:.0f} с)".format(c["base_recalc_s"],
                                              c["control_recalc_s"]))
    elif c.get("control_moved") is False:
        L.append("    ⚠️ контроль НЕ сдвинул такт пересчёта — ответ не выдан")

    ev = report["events"]
    L.append("")
    L.append("(в) СОБЫТИЯ §21 — {} названы владельцем, поднять пересчёт способны {}, "
             "а РАДИ УЛУЧШЕНИЯ раскладки {}:".format(
                 ev["declared"], ev["raises"], ev.get("raises_for_improvement", 0)))
    for row in ev["rows"]:
        L.append("  {:20s} {:28s} {}".format(row["event"], row["kind"], row["why"]))
    L.append("    по родам: {}".format(
        ", ".join("{} {}".format(k, v) for k, v in sorted(ev["by_kind"].items()))))

    d = report.get("raise_doors") or {}
    if d:
        L.append("")
        L.append("    ДВЕРИ ПОДЪЁМА (измерены по дереву, не объявлены списком):")
        L.append("      ПОДЪЁМ РАДИ УЛУЧШЕНИЯ раскладки (то, о чём §21): {}".format(
            ", ".join(d.get("improvement_doors") or []) or "НИ ОДНОЙ ДВЕРИ"))
        for door in d.get("doors", []):
            L.append("      {} {:16s} {}:{}".format(
                "money-path" if door.get("money_path") else "advisory ",
                door["purpose"], door["file"],
                ",".join(str(x) for x in door["lines"])))
            L.append("                   {}".format(door["purpose_why"]))
            L.append("                   читает: {}".format(
                ", ".join(door["reads"]) or "ни одного артефакта"))
        for u in d.get("unparsed", []):
            L.append("      НЕ РАЗОБРАНО: {}".format(u))

    rr = report["reachability"]
    L.append("")
    L.append("(г) ДОСТИЖИМОСТЬ:")
    L.append("    объявление: {} · агент пересчёта назван: {} · двери измерены: {}"
             .format(rr["manifest"], rr["recalc_named"], rr["doors_measured"]))
    L.append("    {}".format(rr["why_unreachable"]))

    L.append("")
    if report.get("vocab_errors"):
        L.append("❌ СЛОВАРИ НЕ ВВЕЗЕНЫ ({}):".format(len(report["vocab_errors"])))
        for x in report["vocab_errors"]:
            L.append("    {}".format(x))
    if report.get("unmeasured"):
        L.append("⚠️ НЕ ИЗМЕРЕНО ({}):".format(len(report["unmeasured"])))
        for u in report["unmeasured"]:
            L.append("    {}".format(u))
    code = verdict_code(report)
    L.append({0: "✅ §21 исполняется", 1: "🔴 НАХОДКА НАЗВАНА",
              2: "⚠️ НЕ ИЗМЕРЕНО"}[code])
    L.append("ADVISORY: {}".format(report["advisory"]))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=(__doc__ or "§21 Частота работы").splitlines()[0])
    ap.add_argument("--root", type=Path, default=None,
                    help="корень дерева (умолчание — дерево этого файла, и оно ПЕЧАТАЕТСЯ)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    args = ap.parse_args(list(argv) if argv is not None else None)
    report = census(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else render(report))
    return verdict_code(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
