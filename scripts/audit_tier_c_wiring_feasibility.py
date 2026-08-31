#!/usr/bin/env python3
"""
audit_tier_c_wiring_feasibility.py — можно ли ЧЕСТНО провести модуль на
`_protocol_facts`, или проводка сочинит число?

Зачем отдельный инструмент от `audit_protocol_blindness.py`. Тот отвечает на
вопрос «различается ли score между протоколами» (протокол-слепота). Замер
цикла #133 показал, что одного этого критерия НЕДОСТАТОЧНО, и что он
подделываем:

  `defi_lending_rate_spread_analyzer` на профиле `generic_profile_for` даёт
  60 / 51 / 36 для aave_v3 / maple / pendle — по критерию слепоты это
  `sensitive`, «модуль работает». Но профиль не содержит НИ ОДНОГО ключа, о
  котором модуль: `supply_apy_pct`, `borrow_apy_pct`, `reserve_factor_pct`
  отсутствуют и молча становятся 0.0. Спред двух нулей — ноль; всё различие
  пришло из `utilization_rate_pct`, поля ПОБОЧНОГО для анализатора спреда.
  Проводка дала бы число, которое проходит проверку на слепоту и при этом не
  измеряет то, что написано на модуле.

Это тот же класс, что fail-OPEN мониторы (#29/#31/#35–#38/#40), но вывернутый:
не «✅ OK о непроверенном», а правдоподобно РАЗЛИЧАЮЩЕЕСЯ число о неизмеренном.
Различающаяся константа опаснее одинаковой: одинаковую видно глазом.

**Критерий (оба плеча, fail-CLOSED).** Модуль считается пригодным к проводке
(`WIRABLE`), только если ОБА условия выполнены:

  1. **variance** — score различается между протоколами (иначе проводка родит
     новую слепую константу — ровно тот симптом, ради которого всё затевалось);
  2. **coverage** — профиль отдаёт КАЖДЫЙ ключ, который движок у записи
     спрашивает (`--min-coverage`, по умолчанию 1.0). Молчаливый дефолт
     отсутствующего ключа — это и есть сочинение входа.

**Плечо coverage ВЫРОЖДАЕТСЯ, если движок переданную запись не читает
(цикл #141).** Модуль на контекст-пути ADR-031 видит в записи `protocol`,
после чего берёт профиль из `_protocol_facts` САМ:

    if _pf.is_protocol_context(params):
        _p = _pf.generic_profile_for(params["protocol"])   # своя запись, не наша

Переданная инструментом `RecordingProfile` при этом не спрашивается ни разу,
кроме ключа-контекста. Замер честно отвечает «прочитан 1 ключ, отдан 1 из 1,
покрытие 1.0» — и второе плечо удовлетворяется ТАВТОЛОГИЕЙ: единственный
спрошенный ключ инструмент сам же и положил. Замер 2026-08-07: так выглядели
**22 из 25** `WIRABLE` Tier-B и **3 из 3** Tier-A — про них покрытие не измерено
вовсе, а вердикт читался как «пригоден к проводке». Поэтому набор прочитанных
ключей, равный ровно `{CONTEXT_KEY}`, даёт отдельный вердикт
`COVERAGE_UNMEASURED` — не молчание и не `WIRABLE`.

**Плечо coverage судит о ФАКТАХ, а не о проводке (цикл #441).** Движок на
контекст-пути спрашивает у контекста не только протокол: `data_dir` — это
«где лежит состояние», утверждением о протоколе он не является, и в профиле
`_protocol_facts` его нет по построению. Считать такой ключ отсутствующим
значит краснеть на СОБСТВЕННОМ контракте вызова: замер #441 на живой популяции
Tier-B дал ровно это — **18** модулей, сегодня исполняющихся в советующем
сигнале, получили бы `UNCOVERED`, и единственный несошедшийся ключ у всех
восемнадцати — `data_dir`. `UNCOVERED` уезжает в разметку, разметка исключает
модуль из composite ⇒ восемнадцать работающих модулей выключились бы МОЛЧА.
Поэтому ключи из `SERVICE_KEYS` снимаются с обоих плеч покрытия, а снятое
НАЗЫВАЕТСЯ в отчёте полем `service_keys_ignored` — послабление, о котором
отчёт молчит, и есть тот дефект, который инструмент ловит у других.

Любой отказ назван поимённо: `missing_keys` перечисляет, ЧЕГО не хватает, —
чтобы решение «дописать факты / взять живой фид / честно списать» принималось
по фактам, а не по догадке.

**Замер ключей — объединение по всем пробным протоколам.** Движок может уйти в
другую ветку на другом протоколе и спросить там новый ключ; замер по одному
протоколу занизил бы список отсутствующих и подал бы модуль как более
пригодный, чем он есть.

Статусы (`verdict`):
  WIRABLE          различает протоколы И профиль покрывает все читаемые ключи,
                   причём спрошен хотя бы один ключ СВЕРХ ключа-контекста;
  BLIND            score одинаков на всех протоколах — проводка = новая константа;
  COVERAGE_UNMEASURED
                   различает, но из переданной записи не прочитано ни одного
                   ключа-ФАКТА сверх ключа-контекста `protocol` (ключи проводки
                   из `SERVICE_KEYS` в счёт не идут) — движок берёт факты сам,
                   плечо coverage не измерило ничего; «пригоден» тут утверждать
                   не на чем (fail-CLOSED);
  NO_SCORE         выход не коэрсится в score (dormant);
  RAISES           движок отверг профиль исключением (контракт не удовлетворён);
  UNCOVERED        различает, но профиль не даёт части ключей — «различается не
                   тем»: проводка дала бы правдоподобное, но не по делу число;
  DECLARED_INPUT_NOT_A_RECORD
                   вход ОБЪЯВЛЕН и объявлен не записью (`OracleFeed`,
                   `List[float]`, `List[PositionExposure]` …) — вызова нет, но
                   вердикт ЕСТЬ: провести движок ЧЕРЕЗ ЭТОТ ВХОД нельзя.
                   **Это НЕ утверждение, что модуль не читает протокол** —
                   см. `cross_instrument_caveat` (цикл #440);
  SHAPE_NOT_PROBED контракта нет вовсе (`unannotated` / `no_param` / `unknown`) —
                   инструмент НЕ измеряет и говорит почему (см. `call_shape`:
                   вызов выдуманной формы дал бы падение по вине инструмента,
                   а не модуля);
  NO_ENTRY         не нашли entrypoint с позиционным параметром;
  IMPORT_ERR       модуль не импортируется.

**Вердикт ≠ «измерено» — считать это обязан код (цикл #440).** Отчёт печатал
плоский `counts`, и читатель делил статусы на `BLIND` и «прочее = не измерено».
Так 11 модулей из 82 уехали к владельцу как «вердикта нет», хотя у пяти он был:
движок отверг переданную запись (`RAISES`) либо его выход вовсе не несёт оценки
протокола (`NO_SCORE`) — это ответ «нет», а не молчание. Теперь отчёт несёт
`measured` у каждой строки и `measured_count` / `unmeasured` в шапке
(`MEASURED_VERDICTS` — единственное место, где это решается).

**«Измерено» ≠ «можно списывать» — и это тоже в отчёте (ADR-194 + ADR-195).**
Отчёт читают, чтобы решать о списании, а вердикты этого инструмента такого
решения не выдерживают: на эталоне из 115 работающих протокол-различающих
модулей он выносит `BLIND` девяти (7,8 %) и `DECLARED_INPUT_NOT_A_RECORD`
восьми. Причина не в поломке: инструменты кормят движок РАЗНЫМИ входами —
первый контекстом агрегатора (тем, что в проде), этот синтетическим
`generic_profile_for`, — и модуль с объявленным доменным входом вправе брать
факты сам на контекст-пути ADR-031. Поэтому `CROSS_INSTRUMENT_CAVEAT` едет в
шапку каждого отчёта, а списание по вердикту ОДНОГО инструмента запрещено.

**Область применимости.** Инструмент отвечает ровно на один вопрос — «даст ли
`_protocol_facts` честный вход движку», и задаёт его тем движкам, чей вызов
ОПРЕДЕЛЁН их собственным контрактом: `list`-образным (`fn([profile])`) и
`dict`-образным (`fn(profile)`). Он не заменяет `audit_protocol_blindness.py`.

**Почему `dict` пробуется (цикл #137).** До 06.08 инструмент звал ТОЛЬКО
`list`-образные движки, а всё прочее получало `SHAPE_NOT_PROBED`. Формулировка
отказа («не список записей») читалась как принципиальная осторожность, но под
неё попадала форма, для которой никакой выдумки не требуется: движок,
объявивший `analyze(token: dict | None)`, ждёт РОВНО ту запись, которой и
является профиль протокола. В результате 18 модулей Tier-C и 186 Tier-B ни разу
не были измерены — и их непроверенность выглядела как осознанный отказ. Замер
после расширения: из 18 Tier-C `dict`-модулей **wirable = 0** (10 BLIND, 6
RAISES, 1 UNCOVERED, 1 NO_SCORE) — вывод цикла #133 «Tier-C wirable=0» устоял и
на форме, которой он не видел. Граница осталась там же, где была по существу:
`typed` (чужой доменный тип) по-прежнему НЕ зовётся.

Границы: только stdlib · LLM здесь не участвует · инструмент READ-ONLY по
отношению к прод-состоянию (ничего не пишет, кроме своего --out).

Запуск ТОЛЬКО в sandbox (как и `audit_protocol_blindness.py`): САМИ модули
пишут свои `data/*`-логи относительно корня репо, поэтому прогон из живого
дерева пачкает прод-данные.

    python3 scripts/audit_tier_c_wiring_feasibility.py --tier C --out /tmp/feas.json

**`--emit-markup` (только Tier B).** Записывает вердикт `UNCOVERED` в
`spa_core/analytics/_protocol_key_coverage.py` — так же, как
`audit_protocol_blindness.py --emit-markup` записывает слепоту. Разметку
потребляет `signal_aggregator.run_tier_b`: помеченный модуль НЕ исполняется,
получает громкий статус `"unsourced"` и исключается из composite и из
числителя confidence. Причина ровно та же, что у слепых: число, посчитанное
по молчаливым дефолтам, не имеет права складываться в оценку риска
протокола — только теперь оно ещё и различается, поэтому глазом не видно.

    python3 scripts/audit_tier_c_wiring_feasibility.py --tier B \\
        --out /tmp/feas_b.json --emit-markup
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import collections
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spa_core.analytics import _module_registry as registry            # noqa: E402
from spa_core.analytics import _protocol_facts as _pf                  # noqa: E402
from spa_core.analytics.signal_aggregator import (                     # noqa: E402
    _ENTRY_METHODS, _ModuleAdapter,
)

#: Пробные протоколы: разные kind/chain/tier — если различия не проявились
#: здесь, «различает протоколы» утверждать не на чем.
PROBE_PROTOCOLS: Tuple[str, ...] = (
    "aave_v3", "maple", "pendle", "morpho", "spark", "compound_v3",
)

DEFAULT_MIN_COVERAGE = 1.0

#: Ключ, по которому движок опознаёт контекст агрегатора (ADR-031) и уходит
#: брать профиль из `_protocol_facts` САМ. Прочитан только он — значит
#: переданная запись не участвовала, и покрытие не измерено (см. докстринг).
#: Значение обязано совпадать с тем, что смотрит
#: `_protocol_facts.is_protocol_context`; расхождение закреплено тестом —
#: иначе переименование ключа тихо вернуло бы тавтологическое `WIRABLE`.
CONTEXT_KEY = "protocol"

#: Ключи СЛУЖЕБНОЙ ПРОВОДКИ: движок спрашивает их у контекста, но фактом о
#: протоколе они не являются и в профиле `_protocol_facts` их нет и быть не
#: должно. Такой ключ обязан быть исключён из ОБОИХ плеч покрытия — иначе
#: инструмент краснеет на собственном контракте вызова, а не на предмете.
#:
#: **Зачем (решение владельца 2026-08-31 13:32Z, вариант 1; замер цикла #441).**
#: Ответ владельца прямо потребовал «сначала научить проверку отличать факт
#: протокола от служебной проводки, и только потом звать те 29». Замер на всей
#: живой популяции Tier-B (479 модулей) показал цену бездействия точно: у 32
#: модулей вход не аннотирован и назван `context`, при наивном вызове **18**
#: из них получают `UNCOVERED` — и ЕДИНСТВЕННЫЙ ключ, который у них не сходится,
#: это `data_dir`. Все 18 СЕГОДНЯ исполняются в советующем сигнале (ни одного
#: нет ни в `UNSOURCED_MODULES`, ни в `PROTOCOL_BLIND_MODULES` — перемерено),
#: а `UNCOVERED` уезжает в разметку и `signal_aggregator.run_tier_b` исключает
#: модуль из composite. То есть перегенерация разметки выключила бы 18
#: работающих модулей по признаку, который сами мы считаем не относящимся к
#: делу, — и МОЛЧА.
#:
#: **Список узкий по построению, и расширять его дёшево нельзя.** Каждый ключ
#: здесь ослабляет плечо coverage — то самое, ради которого инструмент написан.
#: Условие для внесения: ключ спрашивается у контекста, отсутствует во ВСЕХ
#: пробных профилях и не является утверждением о протоколе. Обратный контроль
#: (`test_wiring_feasibility_service_keys.py`) краснеет, если сюда попадёт
#: ключ, который в профиле протокола ЕСТЬ: тогда это факт, а не проводка.
SERVICE_KEYS: frozenset = frozenset({"data_dir"})

#: Имя первого параметра, которым движок ОБЪЯВЛЯЕТ контекст-контракт ADR-031
#: без аннотации. Прод зовёт такие модули как `fn(context_dict)` каждый цикл —
#: то есть форма здесь НАЗВАНА, просто не типом. Замер #441: таких модулей в
#: Tier-B 32, и у 29 первый параметр называется ровно так.
CONTEXT_PARAM_NAME = "context"


class RecordingProfile(dict):
    """Профиль протокола, запоминающий, какие ключи у него спрашивали.

    Нужен именно подкласс `dict`, а не обёртка: движки передают запись дальше,
    копируют, кладут в списки — прокси развалился бы, а `dict`-наследник ведёт
    себя как обычная запись везде.

    `__contains__` тоже учитывается: `if "k" in rec` — это тоже вопрос к записи,
    и молчаливое «нет» уводит движок в ветку по умолчанию ровно так же, как
    `get(k, 0.0)`.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.read: set = set()
        self.missing: set = set()

    def _note(self, key: Any) -> None:
        self.read.add(key)
        if not dict.__contains__(self, key):
            self.missing.add(key)

    def get(self, key: Any, default: Any = None) -> Any:
        self._note(key)
        return dict.get(self, key, default)

    def __getitem__(self, key: Any) -> Any:
        self._note(key)
        return dict.__getitem__(self, key)

    def __contains__(self, key: Any) -> bool:
        self._note(key)
        return dict.__contains__(self, key)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


#: Аннотации, при которых движок ждёт СПИСОК записей — форма, которую
#: инструмент зовёт как `fn([profile])`.
_LIST_ANNOTATIONS = ("list", "typing.list", "sequence", "iterable", "tuple")

#: Имена ЭЛЕМЕНТА списка, роль которого профиль протокола сыграть может: это
#: запись, а не доменный объект и не скаляр. Смысл тот же, что у
#: `signal_aggregator._MAPPING_ANNOTATION_NAMES`, — расхождение закреплено
#: тестом, иначе два места разошлись бы молча.
_RECORD_ELEMENT_NAMES = frozenset({
    "dict", "mapping", "mutablemapping", "ordereddict", "defaultdict",
    "any", "object",
})

#: Формы входа, для которых вызов ОПРЕДЕЛЁН контрактом самого движка, а значит
#: инструмент вправе его сделать. Обе зовутся ровно тем, что движок объявил:
#: `list` → `fn([profile])`, `dict` → `fn(profile)`. Остаток делится надвое:
#: `typed` / `list_of_nonrecords` — вход ОБЪЯВЛЕН и объявлен НЕ записью
#: протокола (это ЗАМЕР, вердикт `DECLARED_INPUT_NOT_A_RECORD`); `unannotated` /
#: `no_param` / `unknown` — контракта нет вовсе, и это честное «не измерено»
#: (`SHAPE_NOT_PROBED`): там вызов пришлось бы ВЫДУМАТЬ, а падение от своей же
#: ошибки вызова инструмент записал бы модулю.
_PROBEABLE_SHAPES = ("list", "dict")

#: Формы, про которые вердикт ЕСТЬ, хотя вызова не было: движок сам объявил,
#: что берёт не запись протокола.
_DECLARED_NONRECORD_SHAPES = ("typed", "list_of_nonrecords")


def _element_text(annotation: Any) -> Optional[str]:
    """Текст объявленного ЭЛЕМЕНТА списочной аннотации, либо None.

    None означает «элемент не объявлен» (`list`, `List`, `Sequence`) — это НЕ
    то же самое, что «объявлен не записью»: судить там не по чему, и прежнее
    поведение (пробуем как список записей) остаётся.
    """
    text = str(annotation)
    if "[" not in text or not text.rstrip().endswith("]"):
        return None
    inner = text[text.index("[") + 1:text.rstrip().rindex("]")].strip()
    if not inner:
        return None
    # `List[Dict[str, Any]]` — берём голову вложенной аннотации, а не всё нутро.
    head = inner.split("[", 1)[0].split(",", 1)[0].strip()
    return head.rsplit(".", 1)[-1] or None


def call_shape(fn: Any) -> Tuple[str, Optional[str]]:
    """Какой формой входа движок объявляет свой контракт → (shape, annotation).

    Инструмент зовёт ТОЛЬКО те формы, которые движок объявил сам. Причина не в
    удобстве: вызвать dict-принимающий движок как `fn([profile])` — значит
    получить исключение от СВОЕЙ ошибки вызова и записать её в отчёт как
    «модуль падает». Кросс-прогон по Tier-B (цикл #133) дал так 268 ложных
    RAISES — ровно тот класс, который инструмент и создан ловить, только в
    исполнении самого инструмента.

    **Список — это список ЧЕГО (цикл #440).** До 31.08 форма выводилась по
    ГОЛОВЕ аннотации: `List[float]` и `List[PositionExposure]` читались как
    «список записей», инструмент клал туда профиль протокола и записывал
    падение движка как RAISES. Это тот же дефект #133, просто на один уровень
    глубже: `TypeError: type RecordingProfile doesn't define __round__` —
    вина вызова, а не модуля. Элемент, объявленный НЕ записью, даёт отдельную
    форму `list_of_nonrecords`; вызова нет, но вердикт ЕСТЬ — движок сам
    сказал, чего он ждёт.
    """
    try:
        params = [
            p for p in inspect.signature(fn).parameters.values()
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
    except (TypeError, ValueError):
        return "unknown", None
    if not params:
        return "no_param", None
    ann = params[0].annotation
    if ann is inspect.Parameter.empty and params[0].name == CONTEXT_PARAM_NAME:
        # Контракт ADR-031 — НАЗВАННЫЙ, пусть и не аннотированный: прод зовёт
        # эти модули каждый цикл ровно как `fn(context_dict)`, и выдумывать
        # тут нечего. Форму даёт имя параметра, а не аннотация.
        #
        # **Почему это стало можно только теперь (решение владельца 31.08,
        # вариант 1).** Замер #441 до правки: 18 из 32 таких модулей получали
        # `UNCOVERED` — и у всех восемнадцати единственным несошедшимся ключом
        # был служебный `data_dir`. Разметка выключила бы их МОЛЧА. Владелец
        # выбрал порядок «сперва научить проверку отличать факт от проводки,
        # и только потом звать те 29»; `SERVICE_KEYS` — это та наука, и без
        # неё эта ветка обязана оставаться закрытой.
        return "dict", CONTEXT_PARAM_NAME
    if ann is inspect.Parameter.empty:
        # Остаток НАЗВАН, а не закрыт (замер #440). У 29 модулей Tier-B
        # первый параметр называется `context` и по умолчанию `None` — это
        # контракт ADR-031, и прод зовёт их каждый цикл как `fn(context_dict)`
        # (`_annotation_accepts_mapping` неаннотированный параметр пропускает).
        # Звать их отсюда БЫЛО БЫ вернее, но замер показал цену: плечо coverage
        # считает ВСЕ спрошенные ключи, включая служебный `data_dir`, которого
        # в профиле протокола нет и быть не должно, — и 18 модулей, сегодня
        # ИСПОЛНЯЮЩИХСЯ в советующем сигнале, получили бы `UNCOVERED` из-за
        # ключа, не имеющего отношения к фактам протокола. `--emit-markup`
        # исключил бы их молча. Сперва coverage обязан отличать факт от
        # проводки; до тех пор здесь честное «не измерено».
        return "unannotated", None
    shown = getattr(ann, "__name__", None) or str(ann)
    text = shown.lower()
    if any(text.startswith(t) for t in _LIST_ANNOTATIONS):
        element = _element_text(ann)
        if element is not None and element.lower() not in _RECORD_ELEMENT_NAMES:
            # Показываем аннотацию ЦЕЛИКОМ, а не `__name__`: у
            # `typing.List[PositionExposure]` короткое имя — «List», и вердикт
            # «вход объявлен как `List`» нечем перепроверить, хотя вся улика
            # лежит ровно в элементе.
            return "list_of_nonrecords", str(ann)
        return "list", shown
    if text.startswith("dict") or text.startswith("typing.dict") or text == "any":
        return "dict", shown
    return "typed", shown


def resolve_entry(obj: Any) -> Tuple[Optional[str], Optional[Any]]:
    """Первый entrypoint с позиционным параметром — тот же порядок, что у
    `_ModuleAdapter._invoke`: инструмент обязан спрашивать то же, что прод."""
    for meth_name in _ENTRY_METHODS:
        fn = getattr(obj, meth_name, None)
        if not callable(fn):
            continue
        try:
            params = [
                p for p in inspect.signature(fn).parameters.values()
                if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
            ]
        except (TypeError, ValueError):
            continue
        if params:
            return meth_name, fn
    return None, None


def probe_module(module_info: Dict[str, Any],
                 protocols: Tuple[str, ...] = PROBE_PROTOCOLS,
                 min_coverage: float = DEFAULT_MIN_COVERAGE,
                 profile_for: Any = None) -> Dict[str, Any]:
    """Сухой прогон движка на профилях протоколов. Ничего не проводит и не чинит.

    `profile_for` — инъекция источника профиля (тесты); по умолчанию
    `_protocol_facts.generic_profile_for`.
    """
    profile_for = profile_for or _pf.generic_profile_for
    name = module_info.get("module", "")
    adapter = _ModuleAdapter(module_info)
    try:
        obj = adapter._import_callable()
    except Exception as exc:  # noqa: BLE001 — импорт модуля прод-слоя
        return {"module": name, "verdict": "IMPORT_ERR",
                "detail": f"{type(exc).__name__}: {exc}"}

    entry, fn = resolve_entry(obj)
    if fn is None:
        return {"module": name, "verdict": "NO_ENTRY",
                "detail": "нет entrypoint с позиционным параметром"}

    shape, annotation = call_shape(fn)
    if shape in _DECLARED_NONRECORD_SHAPES:
        # Вызова нет — и не надо: движок САМ объявил, чего ждёт, и это не
        # запись протокола. Ответ на вопрос инструмента («даст ли
        # `_protocol_facts` честный вход») получен из контракта: не даст.
        # Это ЗАМЕР, а не пропуск, и путать его с «не измерено» нельзя —
        # именно на этой путанице 9 модулей из 82 три недели числились
        # непроверенными (цикл #440).
        return {"module": name, "entry": entry,
                "verdict": "DECLARED_INPUT_NOT_A_RECORD",
                "call_shape": shape, "annotation": annotation,
                "detail": f"вход объявлен как `{annotation or shape}` — профиль "
                          "протокола такой записью не является, поэтому ЧЕРЕЗ "
                          "ЭТОТ ВХОД провести его нельзя, а вызов пришлось бы "
                          "выдумать. О том, читает ли модуль протокол ИНЫМ "
                          "путём (контекст ADR-031, свой фид), этот инструмент "
                          "НЕ ГОВОРИТ НИЧЕГО — см. cross_instrument_caveat"}
    if shape not in _PROBEABLE_SHAPES:
        # Контракта нет вовсе (`unannotated` / `no_param` / `unknown`). Не
        # пробуем — и говорим, ПОЧЕМУ. Молчаливая попытка вызвать чужую
        # форму дала бы падение по вине инструмента (см. `call_shape`).
        return {"module": name, "entry": entry, "verdict": "SHAPE_NOT_PROBED",
                "call_shape": shape, "annotation": annotation,
                "detail": f"вход объявлен как `{annotation or shape}` — ни список "
                          "записей, ни запись; пригодность facts-проводки этим "
                          "инструментом не измеряется (не выдумываем вызов)"}

    scores: Dict[str, Any] = {}
    read: set = set()
    missing: set = set()
    detail = None
    raised = False

    for proto in protocols:
        raw = profile_for(proto)
        if raw is None:            # протокол вне базы фактов — не находка модуля
            continue
        rec = RecordingProfile(raw)
        try:
            # Форма вызова — та, которую движок объявил сам (см.
            # `_PROBEABLE_SHAPES`), а не удобная инструменту.
            result = fn([rec]) if shape == "list" else fn(rec)
        except Exception as exc:  # noqa: BLE001 — движок отверг профиль
            raised = True
            detail = f"{type(exc).__name__}: {exc}"
            read |= rec.read
            missing |= rec.missing
            break
        read |= rec.read
        missing |= rec.missing
        extracted = _pf.extract_protocol_score(result, raw)
        scores[proto] = None if extracted is None else float(extracted["risk_score"])

    # Факт протокола или служебная проводка? Плечо coverage судит ТОЛЬКО о
    # фактах: ключ проводки движок спрашивает у контекста, профиль его не несёт
    # по построению, и краснеть на нём значит краснеть на собственном контракте
    # вызова. Исключение НАЗЫВАЕТСЯ в отчёте (`service_keys_ignored`), а не
    # применяется молча: молчаливое послабление плеча — ровно тот дефект, ради
    # поимки которого инструмент и написан.
    service_asked = read & SERVICE_KEYS
    read = read - SERVICE_KEYS
    missing = missing - SERVICE_KEYS
    coverage = None if not read else round((len(read) - len(missing)) / len(read), 4)
    out: Dict[str, Any] = {
        "module": name, "entry": entry, "call_shape": shape,
        # Что именно снято с плеча coverage и почему вердикт из-за этого другой.
        # Пусто у подавляющего большинства модулей — и это тоже утверждение.
        "service_keys_ignored": sorted(str(k) for k in service_asked),
        # Чем именно звали — иначе вердикт нечем перепроверить.
        "call_form": "fn([profile])" if shape == "list" else "fn(profile)",
        "annotation": annotation, "scores": scores,
        "keys_read": len(read), "keys_missing": len(missing),
        # Имена прочитанных ключей, а не только их число: без них вердикт нечем
        # перепроверить — «прочитан 1 ключ» и «прочитан ключ-контекст» это
        # разные утверждения, а различить их по счётчику нельзя.
        "read_keys": sorted(str(k) for k in read),
        "coverage": coverage, "missing_keys": sorted(str(k) for k in missing),
    }

    if raised:
        out.update({"verdict": "RAISES", "detail": detail})
        return out
    values = [s for s in scores.values() if s is not None]
    if not values:
        out["verdict"] = "NO_SCORE"
        return out
    if len({round(v, 9) for v in values}) == 1:
        out["verdict"] = "BLIND"
        return out
    # Различает — но участвовала ли в этом ПЕРЕДАННАЯ запись? Если движок
    # спросил у неё только ключ-контекст, плечо coverage меряет сам инструмент
    # (единственный спрошенный ключ он же и положил), а факты движок взял
    # мимо него. Проверка стоит ДО coverage и ПОСЛЕ variance: одинаковый score
    # — более сильное утверждение, BLIND его и должен назвать.
    #
    # Условие — ПОДМНОЖЕСТВО, а не равенство (цикл #441): после снятия ключей
    # проводки набор фактов может остаться и вовсе ПУСТЫМ (движок спросил
    # только `data_dir`). Пустое пересечение с фактами — то же самое
    # утверждение «покрытие не измерено», только сильнее; равенство пропустило
    # бы его ниже, в `coverage is None`, и напечатало бы `UNCOVERED` —
    # измеренный отрицательный вердикт о том, чего не мерили.
    if read <= {CONTEXT_KEY}:
        asked = (f"только ключ-контекст `{CONTEXT_KEY}`" if read
                 else "ни одного ключа-факта")
        via = (f" (ключ(и) проводки сняты с плеча: "
               f"{', '.join(sorted(str(k) for k in service_asked))})"
               if service_asked else "")
        out.update({
            "verdict": "COVERAGE_UNMEASURED",
            "detail": (
                f"из переданной записи прочитан(о) {asked}{via} — движок берёт "
                "профиль из _protocol_facts сам, и покрытие ключей этим "
                "инструментом НЕ измерено; coverage здесь тавтология, "
                "а не свидетельство пригодности"),
        })
        return out
    # Различает — но различает ли ТЕМ, о чём модуль? Отвечает покрытие.
    if coverage is None or coverage < min_coverage:
        out.update({"verdict": "UNCOVERED",
                    "detail": "score различается, но профиль не даёт "
                              f"{len(missing)} из {len(read)} читаемых ключей — "
                              "различие пришло из побочных полей"})
        return out
    out["verdict"] = "WIRABLE"
    return out


#: Вердикты, которые ОТВЕЧАЮТ на вопрос инструмента («даст ли
#: `_protocol_facts` честный вход этому движку»), пусть и отрицательно.
#: Остальные — `COVERAGE_UNMEASURED`, `SHAPE_NOT_PROBED`, `NO_ENTRY`,
#: `IMPORT_ERR` — вопроса не решают, и это надо называть вслух.
#: **Зачем поле (цикл #440).** Отчёт печатал плоский `counts`, и читатель делил
#: вердикты на «BLIND» и «всё остальное = не измерено». Так 11 модулей из 82
#: попали к владельцу как «вердикта нет», хотя у 5 из них ответ был: движок
#: отверг переданную запись (RAISES) либо его выход вовсе не несёт оценки
#: протокола (NO_SCORE). Число «не измерено» обязано считаться кодом, а не
#: глазом по списку статусов.
MEASURED_VERDICTS: FrozenSet[str] = frozenset({
    "WIRABLE", "BLIND", "UNCOVERED", "NO_SCORE", "RAISES", "DECLARED_INPUT_NOT_A_RECORD",
})

#: **Границы вердикта, названные в самом отчёте (ADR-194 + ADR-195).** Отчёт
#: читают, чтобы решать о СПИСАНИИ, а вердикт этого инструмента такого решения
#: не выдерживает — и это ИЗМЕРЕНО, а не осторожность:
#: ADR-194 замерил у `BLIND` собственную цену ошибки 7,8 % (9 из 115 модулей,
#: которые ПЕРВЫЙ инструмент под реальным входом агрегатора видит
#: протокол-различающими); тем же эталоном замерено, что
#: `DECLARED_INPUT_NOT_A_RECORD` получают **8** таких работающих модулей —
#: объявленный доменный вход НЕ означает, что модуль не читает протокол, он
#: берёт факты сам на контекст-пути ADR-031.
#: Строка едет в шапку отчёта, чтобы её нельзя было не прочитать.
CROSS_INSTRUMENT_CAVEAT = (
    "вердикт ЭТОГО инструмента — про проводку ЧЕРЕЗ ОБЪЯВЛЕННЫЙ ВХОД, а не про "
    "способность модуля читать протокол. Замер ADR-194: на эталоне из 115 "
    "работающих протокол-различающих модулей этот инструмент выносит BLIND "
    "девяти (7,8 %) и DECLARED_INPUT_NOT_A_RECORD — восьми. СПИСЫВАТЬ по "
    "вердикту ОДНОГО инструмента запрещено (ADR-194 п.2): нужно согласие двух "
    "на ОДНОМ входе либо ручной разбор."
)


def is_measured(verdict: str) -> bool:
    """Отвечает ли этот вердикт на вопрос инструмента (пусть и «нет»)."""
    return verdict in MEASURED_VERDICTS


def run_audit(tier: str = "C",
              only_modules: Optional[List[str]] = None,
              min_coverage: float = DEFAULT_MIN_COVERAGE) -> Dict[str, Any]:
    modules = registry.get_tier_modules(tier)
    if only_modules:
        wanted = set(only_modules)
        modules = [m for m in modules if m.get("module") in wanted]
    results = [probe_module(m, min_coverage=min_coverage) for m in modules]
    for r in results:
        r["measured"] = is_measured(r["verdict"])
    counts = collections.Counter(r["verdict"] for r in results)
    unmeasured = sorted(r["module"] for r in results if not r["measured"])
    return {
        "generated_at": _utc_now_iso(),
        "tier": tier,
        "min_coverage": min_coverage,
        "probe_protocols": list(PROBE_PROTOCOLS),
        "module_count": len(results),
        "counts": dict(counts),
        "measured_count": sum(1 for r in results if r["measured"]),
        "unmeasured_count": len(unmeasured),
        "unmeasured": unmeasured,
        "cross_instrument_caveat": CROSS_INSTRUMENT_CAVEAT,
        # Послабление плеча coverage названо В ОТЧЁТЕ, а не только в коде:
        # читатель артефакта обязан видеть, какие ключи с плеча сняты, не
        # открывая инструмент. Пофайлово это же лежит в `service_keys_ignored`.
        "service_keys": sorted(SERVICE_KEYS),
        "wirable": sorted(r["module"] for r in results if r["verdict"] == "WIRABLE"),
        "results": results,
        "method": (
            "движок прогоняется на generic_profile_for каждого пробного протокола; "
            "WIRABLE = score различается И профиль покрывает все читаемые ключи "
            f"(>= {min_coverage}) И спрошен хотя бы один ключ-ФАКТ сверх "
            f"ключа-контекста `{CONTEXT_KEY}` (иначе покрытие меряет сам "
            "инструмент — COVERAGE_UNMEASURED); ключи служебной проводки "
            f"({', '.join(sorted(SERVICE_KEYS))}) с обоих плеч покрытия сняты "
            "и названы в `service_keys_ignored` — они не утверждение о "
            "протоколе; иначе отказ с поимённым списком отсутствующих ключей"
        ),
    }


_MARKUP_TEMPLATE = '''"""
_protocol_key_coverage.py — эмпирическая разметка Tier-B модулей, которые
различают протоколы ПОБОЧНЫМИ полями.

СГЕНЕРИРОВАНО scripts/audit_tier_c_wiring_feasibility.py — НЕ редактировать
вручную; перегенерация:
    python3 scripts/audit_tier_c_wiring_feasibility.py --tier B \\
        --out /tmp/feas_b.json --emit-markup
(в sandbox-чекауте, не в живом репо — модули пишут data/*-логи).

Замер {generated_at}: каждый Tier-B модуль прогнан на
`_protocol_facts.generic_profile_for` для {probe_protocols};
запись подменена на `RecordingProfile`, который помнит, какие ключи у неё
спрашивали. Модуль попадает сюда, если его score РАЗЛИЧАЕТСЯ между
протоколами, но профиль не отдаёт часть ключей, которые движок читает
(покрытие < {min_coverage}): отсутствующий ключ молча становится 0.0/False,
и всё различие приходит из побочных полей вроде `utilization_rate_pct`.

**Почему этого мало — «различается»**. Аудит слепоты
(`audit_protocol_blindness.py`) считает такой модуль `sensitive`, «работает».
Одинаковая константа видна глазом; правдоподобно различающееся число — нет.
Это класс fail-OPEN мониторов (#29/#31/#35–#38/#40), вывернутый наизнанку: не
«✅ OK о непроверенном», а РАЗЛИЧАЮЩЕЕСЯ число о неизмеренном.

`signal_aggregator.run_tier_b` исключает эти модули из composite и из
числителя confidence, статус `"unsourced"` — ровно так же, как
`PROTOCOL_BLIND_MODULES`. Advisory-слой; Tier-A разметку не потребляет,
RiskPolicy её не видит.

Снятие пометки — не правка этого файла, а одно из трёх (карточка
`inbox-tier-b-19-modulei-chislyatsya-rabotayusc`): дописать факт в
`_protocol_facts`, подключить живой фид, либо честно списать модуль. После
любого из них разметка перегенерируется и модуль уходит отсюда сам.
"""
from typing import Dict, FrozenSet, Tuple

AUDIT_GENERATED_AT = "{generated_at}"
MIN_COVERAGE = {min_coverage}

#: module_name -> {{"coverage": доля отданных ключей, "missing_keys": чего нет}}
UNSOURCED_DETAIL: Dict[str, Dict[str, object]] = {{
{detail_lines}
}}

UNSOURCED_MODULES: FrozenSet[str] = frozenset(UNSOURCED_DETAIL)

__all__: Tuple[str, ...] = (
    "AUDIT_GENERATED_AT", "MIN_COVERAGE", "UNSOURCED_DETAIL", "UNSOURCED_MODULES",
)
'''


def emit_markup(report: Dict[str, Any], path: Path) -> None:
    """Записать вердикты UNCOVERED в потребляемую прод-слоем разметку.

    Помечаются ВСЕ `UNCOVERED` без исключений — в том числе модуль, который
    разметка слепоты числит `wide_ok` («честный coarse»). Вопросы у двух
    аудитов разные: «различается ли score» и «о том ли он». Модуль, чьё
    различие пришло из побочного поля, не измеряет свой предмет независимо от
    того, грубо он его не измеряет или тонко. Исключение по спискам здесь
    было бы ровно тем молчаливым послаблением, ради поимки которого инструмент
    и написан.
    """
    unc = [r for r in report["results"] if r["verdict"] == "UNCOVERED"]
    lines = []
    for r in sorted(unc, key=lambda x: x["module"]):
        keys = ", ".join(f'"{k}"' for k in r["missing_keys"])
        lines.append(
            f'    "{r["module"]}": {{\n'
            f'        "coverage": {r["coverage"]},\n'
            f'        "missing_keys": ({keys}{"," if len(r["missing_keys"]) == 1 else ""}),\n'
            f'    }},'
        )
    text = _MARKUP_TEMPLATE.format(
        generated_at=report["generated_at"],
        probe_protocols=report["probe_protocols"],
        min_coverage=report["min_coverage"],
        detail_lines="\n".join(lines),
    )
    path.write_text(text, encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", required=True, help="куда положить JSON-отчёт")
    ap.add_argument("--tier", default="C", choices=["A", "B", "C"])
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                    help="доля читаемых ключей, которые профиль обязан отдать "
                         "(1.0 = ни одного молчаливого дефолта)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="ограничить набор модулей (имена как в реестре)")
    ap.add_argument("--emit-markup", action="store_true",
                    help="перегенерировать spa_core/analytics/_protocol_key_coverage.py")
    args = ap.parse_args(argv)

    report = run_audit(args.tier, only_modules=args.only,
                       min_coverage=args.min_coverage)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.emit_markup:
        # Tier-B-only по той же причине, что у аудита слепоты: разметку
        # потребляет run_tier_b, и только он.
        if args.tier != "B":
            print("--emit-markup поддержан только для Tier B", file=sys.stderr)
            return 2
        # Частичный скан не вправе переписывать разметку целиком: не
        # упомянутый модуль молча потерял бы пометку.
        if args.only:
            print("--emit-markup несовместим с --only: частичный скан стёр бы "
                  "пометки у неизмеренных модулей", file=sys.stderr)
            return 2
        emit_markup(report, ROOT / "spa_core" / "analytics"
                    / "_protocol_key_coverage.py")

    print(f"modules={report['module_count']} counts={report['counts']}")
    print(f"измерено={report['measured_count']} · НЕ измерено="
          f"{report['unmeasured_count']}"
          + (f": {', '.join(report['unmeasured'])}" if report['unmeasured'] else ""))
    print(f"wirable={len(report['wirable'])}"
          + (f" → {', '.join(report['wirable'])}" if report["wirable"] else ""))
    print(f"report → {args.out}")

    # Пустой скан — НЕ чистый проход: нечего было мерить, значит вердикта нет.
    if report["module_count"] == 0:
        print("НЕЧЕГО МЕРИТЬ: в тире не найдено ни одного модуля — это находка, "
              "а не успех", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
