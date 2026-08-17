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

**Контекст-путь ТЕПЕРЬ ИЗМЕРЯЕТСЯ (цикл #142, карточка
`inbox-25-modulei-poluchili-vechnyi-verdikt-pok`).** Отказ был правдив, но
НИКОГДА не менялся: сколько ни перезапускай, движок продолжал брать факты мимо
инструмента. Необратимое «не измерено» морит очередь — его читают дважды, потом
перестают читать вовсе, и в этой же графе однажды окажется модуль, который
действительно надо чинить. Поэтому источник фактов подменяется на записывающий
РОВНО НА ВРЕМЯ ВЫЗОВА движка (`record_facts_path`): ключи, которые движок
спрашивает у СВОЕЙ записи, попадают в тот же учёт, и плечо coverage снова меряет
предмет. Учёт при этом РАЗДЕЛЬНЫЙ (`context_path_*` против `read_keys`) — иначе
«инструмент положил ключ и сам его прочитал» стало бы неотличимо от «движок
спросил ключ», то есть тавтология вернулась бы под другим именем.
`COVERAGE_UNMEASURED` остаётся для того, про кого нечего сказать и после
подмены (например, движок связал `facts_for` при импорте — подмене такой
недоступен): «не измерено» обязано отличаться от «измерен ноль».

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
                   различает, но покрытие не измерено НИ на переданной записи
                   (прочитан только ключ-контекст `protocol`), НИ на контекст-пути
                   (подменённый `_protocol_facts` тоже не спрошен ни о чём сверх
                   него); «пригоден» тут утверждать не на чем (fail-CLOSED);
  NO_SCORE         выход не коэрсится в score (dormant);
  RAISES           движок отверг профиль исключением (контракт не удовлетворён);
  UNCOVERED        различает, но профиль не даёт части ключей — «различается не
                   тем»: проводка дала бы правдоподобное, но не по делу число;
  SHAPE_NOT_PROBED вход объявлен ни списком записей, ни записью — инструмент НЕ
                   измеряет и говорит почему (см. `call_shape`: вызов чужой формы
                   дал бы падение по вине инструмента, а не модуля);
  NO_ENTRY         не нашли entrypoint с позиционным параметром;
  IMPORT_ERR       модуль не импортируется.

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

**`--emit-markup --tier C` (цикл #143).** До него разметки Tier-C не
существовало вовсе, и пять модулей карточки
`inbox-tier-c-pyat-nastoyaschih-otkazov-agregat` числились `failed` — ярлык,
отправляющий следующего исполнителя чинить код, в котором чинить нечего.
Пишет `spa_core/analytics/_tier_c_key_coverage.py`, и требует ВТОРОГО отчёта
(`--blindness`), потому что ни один из двух аудитов сам по себе не отвечает на
нужный вопрос: пригодность говорит «чего не хватает», слепота — «даёт ли
агрегатор от модуля число сегодня». Потребляемый набор = пересечение
(«числа нет» И «недостающее названо») — узко и НАМЕРЕННО: широкое правило
(«все BLIND») погасило бы девять модулей, дающих публикуемый `avg_score`, то
есть разметка молча изменила бы опубликованное число под видом починки ярлыка.

    python3 scripts/audit_protocol_blindness.py --tier C --out /tmp/blind_c.json
    python3 scripts/audit_tier_c_wiring_feasibility.py --tier C \\
        --out /tmp/feas_c.json --emit-markup --blindness /tmp/blind_c.json
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import collections
import contextlib
import inspect
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

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


#: Внутренний признак: подмена источника фактов уже активна. Подмена
#: ГЛОБАЛЬНА (атрибут модуля `_protocol_facts`), поэтому вложенный или
#: параллельный вход перепутал бы чтения двух движков и выдал бы покрытие
#: одного за покрытие другого. Отказ громкий — молчаливое наложение дало бы
#: правдоподобное, но чужое число (тот же класс, что весь этот инструмент ловит).
_FACTS_PATCH_ACTIVE: List[bool] = [False]


@contextlib.contextmanager
def record_facts_path(records: List["RecordingProfile"],
                      source: Any = None) -> Iterator[None]:
    """Подменить источник профиля в `_protocol_facts` на записывающий — НА
    ВРЕМЯ ВЫЗОВА движка, и ни мгновением дольше.

    Зачем (цикл #142, карточка `inbox-25-modulei-poluchili-vechnyi-verdikt-pok`).
    Вердикт ``COVERAGE_UNMEASURED`` правдив, но НИКОГДА не меняется: движок на
    контекст-пути ADR-031 спрашивает у переданной записи только ключ
    ``protocol``, а профиль берёт из `_protocol_facts` САМ, мимо инструмента.
    Fail-CLOSED-вердикт над неизвестным, которое само не рассосётся, морит
    очередь: его читают два раза, а потом перестают читать вовсе — и в этой же
    графе однажды окажется модуль, который действительно надо чинить. Поэтому
    контекст-путь измеряется тем же приёмом, только на другом уровне.

    Две ловушки, обе названы карточкой и обе закрыты здесь:

    1. **Реэнтерабельность.** Настоящий ``generic_profile_for`` сам зовёт
       ``facts_for``. Записать эти чтения — значит записать чтения БАЗЫ ФАКТОВ
       как чтения движка и получить покрытие, посчитанное по чужим вопросам.
       Поэтому вложенный вызов отдаёт сырую запись без учёта (``_depth``).
    2. **Чтения ПОСЛЕ движка не в счёт.** ``extract_protocol_score`` читает
       запись, когда движок уже ответил; к вопросу «что спросил движок» это
       отношения не имеет. Подмена снимается на выходе из блока, а
       ``extract_protocol_score`` вызывается ПОСЛЕ него — структурно, а не по
       договорённости (закреплено тестом).

    *source* — инъекция настоящего источника (тесты); по умолчанию реальный
    ``_pf.generic_profile_for``.
    """
    if _FACTS_PATCH_ACTIVE[0]:
        raise RuntimeError(
            "record_facts_path уже активен: подмена глобальна, вложенный или "
            "параллельный вход смешал бы чтения двух движков — покрытие одного "
            "было бы выдано за покрытие другого")
    real_generic = _pf.generic_profile_for
    real_facts = _pf.facts_for
    under = source if source is not None else real_generic
    depth = [0]

    def _wrap(real: Any) -> Any:
        def inner(protocol: Any) -> Any:
            if depth[0]:
                # Ловушка 1: вложенный вызов внутри самой базы фактов.
                return real(protocol)
            depth[0] += 1
            try:
                raw = real(protocol)
            finally:
                depth[0] -= 1
            if raw is None:
                return None
            rec = RecordingProfile(raw)
            records.append(rec)
            return rec
        return inner

    _pf.generic_profile_for = _wrap(under)
    _pf.facts_for = _wrap(real_facts)
    _FACTS_PATCH_ACTIVE[0] = True
    try:
        yield
    finally:
        _FACTS_PATCH_ACTIVE[0] = False
        _pf.generic_profile_for = real_generic
        _pf.facts_for = real_facts


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


#: Аннотации, при которых движок ждёт СПИСОК записей — форма, которую
#: инструмент зовёт как `fn([profile])`.
_LIST_ANNOTATIONS = ("list", "typing.list", "sequence", "iterable", "tuple")

#: Формы входа, для которых вызов ОПРЕДЕЛЁН контрактом самого движка, а значит
#: инструмент вправе его сделать. Обе зовутся ровно тем, что движок объявил:
#: `list` → `fn([profile])`, `dict` → `fn(profile)`. Всё остальное (`typed`,
#: `unannotated`, `no_param`) остаётся SHAPE_NOT_PROBED — там вызов пришлось бы
#: ВЫДУМАТЬ, а падение от своей же ошибки вызова инструмент записал бы модулю.
_PROBEABLE_SHAPES = ("list", "dict")


def call_shape(fn: Any) -> Tuple[str, Optional[str]]:
    """Какой формой входа движок объявляет свой контракт → (shape, annotation).

    Инструмент зовёт ТОЛЬКО `list`-образные движки. Причина не в удобстве:
    вызвать dict-принимающий движок как `fn([profile])` — значит получить
    исключение от СВОЕЙ ошибки вызова и записать её в отчёт как «модуль
    падает». Кросс-прогон по Tier-B (цикл #133) дал так 268 ложных RAISES —
    ровно тот класс, который инструмент и создан ловить, только в исполнении
    самого инструмента. Поэтому форма выводится из аннотации, а всё, что не
    список, получает ЧЕСТНЫЙ не-пробованный вердикт, а не выдуманное падение.
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
    if ann is inspect.Parameter.empty:
        return "unannotated", None
    text = (getattr(ann, "__name__", None) or str(ann)).lower()
    if any(text.startswith(t) for t in _LIST_ANNOTATIONS):
        return "list", (getattr(ann, "__name__", None) or str(ann))
    if text.startswith("dict") or text.startswith("typing.dict") or text == "any":
        return "dict", (getattr(ann, "__name__", None) or str(ann))
    return "typed", (getattr(ann, "__name__", None) or str(ann))


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
                 profile_for: Any = None,
                 facts_source: Any = None) -> Dict[str, Any]:
    """Сухой прогон движка на профилях протоколов. Ничего не проводит и не чинит.

    `profile_for` — инъекция источника ПЕРЕДАВАЕМОЙ записи (тесты); по умолчанию
    `_protocol_facts.generic_profile_for`.
    `facts_source` — инъекция источника, из которого движок берёт профиль САМ
    (контекст-путь ADR-031); по умолчанию тот же настоящий
    `_protocol_facts.generic_profile_for`. Два разных входа, потому что это два
    разных пути данных, и путать их — ровно та тавтология, из-за которой
    покрытие 25 модулей не измерялось вовсе (см. `record_facts_path`).
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
    if shape not in _PROBEABLE_SHAPES:
        # Не пробуем — и говорим, ПОЧЕМУ. Молчаливая попытка вызвать чужую
        # форму дала бы падение по вине инструмента (см. `call_shape`).
        return {"module": name, "entry": entry, "verdict": "SHAPE_NOT_PROBED",
                "call_shape": shape, "annotation": annotation,
                "detail": f"вход объявлен как `{annotation or shape}` — ни список "
                          "записей, ни запись; пригодность facts-проводки этим "
                          "инструментом не измеряется (не выдумываем вызов)"}

    scores: Dict[str, Any] = {}
    read: Set[Any] = set()
    missing: Set[Any] = set()
    # Отдельный учёт для контекст-пути: ключи, которые движок спросил у СВОЕЙ
    # записи, взятой из `_protocol_facts` мимо инструмента. Держать их в том же
    # множестве нельзя — тогда «инструмент положил ключ и сам его прочитал»
    # станет неотличимо от «движок спросил ключ», а это и была тавтология.
    ctx_read: Set[Any] = set()
    ctx_missing: Set[Any] = set()
    detail = None
    raised = False

    for proto in protocols:
        raw = profile_for(proto)
        if raw is None:            # протокол вне базы фактов — не находка модуля
            continue
        rec = RecordingProfile(raw)
        own: List[RecordingProfile] = []
        try:
            # Форма вызова — та, которую движок объявил сам (см.
            # `_PROBEABLE_SHAPES`), а не удобная инструменту. Подмена источника
            # фактов действует РОВНО на время вызова движка: см. ловушку 2 в
            # `record_facts_path` — `extract_protocol_score` ниже читает запись
            # уже ПОСЛЕ движка и в учёт попадать не имеет права.
            with record_facts_path(own, source=facts_source):
                result = fn([rec]) if shape == "list" else fn(rec)
        except Exception as exc:  # noqa: BLE001 — движок отверг профиль
            raised = True
            detail = f"{type(exc).__name__}: {exc}"
            read |= rec.read
            missing |= rec.missing
            for r in own:
                ctx_read |= r.read
                ctx_missing |= r.missing
            break
        read |= rec.read
        missing |= rec.missing
        for r in own:
            ctx_read |= r.read
            ctx_missing |= r.missing
        # ВНЕ блока подмены — сознательно (ловушка 2).
        extracted = _pf.extract_protocol_score(result, raw)
        scores[proto] = None if extracted is None else float(extracted["risk_score"])

    coverage = None if not read else round((len(read) - len(missing)) / len(read), 4)
    ctx_coverage = (None if not ctx_read else
                    round((len(ctx_read) - len(ctx_missing)) / len(ctx_read), 4))
    out: Dict[str, Any] = {
        "module": name, "entry": entry, "call_shape": shape,
        # Чем именно звали — иначе вердикт нечем перепроверить.
        "call_form": "fn([profile])" if shape == "list" else "fn(profile)",
        "annotation": annotation, "scores": scores,
        "keys_read": len(read), "keys_missing": len(missing),
        # Имена прочитанных ключей, а не только их число: без них вердикт нечем
        # перепроверить — «прочитан 1 ключ» и «прочитан ключ-контекст» это
        # разные утверждения, а различить их по счётчику нельзя.
        "read_keys": sorted(str(k) for k in read),
        "coverage": coverage, "missing_keys": sorted(str(k) for k in missing),
        # Контекст-путь — ОТДЕЛЬНЫЕ поля, а не подмешанные в те же счётчики:
        # иначе «не измерено» стало бы неотличимо от «измерен ноль».
        "context_path_keys_read": len(ctx_read),
        "context_path_keys_missing": len(ctx_missing),
        "context_path_read_keys": sorted(str(k) for k in ctx_read),
        "context_path_missing_keys": sorted(str(k) for k in ctx_missing),
        "context_path_coverage": ctx_coverage,
        # На какой записи посчитано покрытие, определившее вердикт. None —
        # покрытие не измерено ни на одной (COVERAGE_UNMEASURED), и это НЕ ноль.
        "coverage_basis": None,
        # Покрытие, по которому ВЫНЕСЕН вердикт, и поимённый список
        # отсутствующего. Отдельные поля, а не перезапись `coverage`: замер на
        # переданной записи остаётся видимым, иначе вердикт нечем перепроверить.
        # None — не измерено (см. `coverage_basis`).
        "effective_coverage": None,
        "effective_missing_keys": None,
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
    # спросил у неё только ключ-контекст, плечо coverage на ней меряет сам
    # инструмент (единственный спрошенный ключ он же и положил), а факты движок
    # взял мимо него — из `_protocol_facts`. Проверка стоит ДО coverage и ПОСЛЕ
    # variance: одинаковый score — более сильное утверждение, BLIND его и
    # должен назвать.
    #
    # Цикл #142: этот случай больше не тупик. Подменённый на время вызова
    # источник (`record_facts_path`) записал, какие ключи движок спросил у СВОЕЙ
    # записи, и покрытие считается ПО НИМ. Пустой набор — по-прежнему честное
    # «не измерено», а не «измерено ноль» (fail-CLOSED): так остаётся модуль,
    # который берёт факты формой, недоступной подмене (связанный при импорте
    # `from ... import facts_for`), — про него утверждать нечего.
    eff_read, eff_missing, eff_coverage = read, missing, coverage
    basis = "passed_record"
    if read <= {CONTEXT_KEY}:
        if ctx_read - {CONTEXT_KEY}:
            eff_read, eff_missing, eff_coverage = ctx_read, ctx_missing, ctx_coverage
            basis = "context_path"
        else:
            out.update({
                "verdict": "COVERAGE_UNMEASURED",
                "detail": (
                    f"из переданной записи прочитан только ключ-контекст "
                    f"`{CONTEXT_KEY}`, а от подменённого `_protocol_facts` движок "
                    "не спросил ни одного ключа сверх него — покрытие НЕ измерено "
                    "ни на одной записи; coverage=1.0 здесь тавтология, а не "
                    "свидетельство пригодности"),
            })
            return out
    out["coverage_basis"] = basis
    out["effective_coverage"] = eff_coverage
    out["effective_missing_keys"] = sorted(str(k) for k in eff_missing)
    # Различает — но различает ли ТЕМ, о чём модуль? Отвечает покрытие.
    if eff_coverage is None or eff_coverage < min_coverage:
        out.update({"verdict": "UNCOVERED",
                    "detail": "score различается, но профиль не даёт "
                              f"{len(eff_missing)} из {len(eff_read)} читаемых "
                              f"ключей (замер на `{basis}`) — различие пришло из "
                              "побочных полей"})
        return out
    out["verdict"] = "WIRABLE"
    return out


def run_audit(tier: str = "C",
              only_modules: Optional[List[str]] = None,
              min_coverage: float = DEFAULT_MIN_COVERAGE) -> Dict[str, Any]:
    modules = registry.get_tier_modules(tier)
    if only_modules:
        wanted = set(only_modules)
        modules = [m for m in modules if m.get("module") in wanted]
    results = [probe_module(m, min_coverage=min_coverage) for m in modules]
    counts = collections.Counter(r["verdict"] for r in results)
    return {
        "generated_at": _utc_now_iso(),
        "tier": tier,
        "min_coverage": min_coverage,
        "probe_protocols": list(PROBE_PROTOCOLS),
        "module_count": len(results),
        "counts": dict(counts),
        "wirable": sorted(r["module"] for r in results if r["verdict"] == "WIRABLE"),
        "results": results,
        "method": (
            "движок прогоняется на generic_profile_for каждого пробного протокола; "
            "WIRABLE = score различается И профиль покрывает все читаемые ключи "
            f"(>= {min_coverage}) И покрытие ИЗМЕРЕНО — на переданной записи либо "
            "на контекст-пути (источник `_protocol_facts` подменён на записывающий "
            "на время вызова движка, см. `record_facts_path`); если ни там, ни там "
            f"не спрошено ничего сверх ключа-контекста `{CONTEXT_KEY}` — "
            "COVERAGE_UNMEASURED, «не измерено» это НЕ «измерен ноль»; иначе отказ "
            "с поимённым списком отсутствующих ключей. `coverage_basis` в каждой "
            "записи говорит, на какой записи покрытие посчитано"
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
        # `effective_*`, а не `coverage`/`missing_keys`: у модуля контекст-пути
        # покрытие ИЗМЕРЕНО на записи, которую он взял из `_protocol_facts` сам,
        # а на переданной инструментом оно тавтологично (цикл #142). Писать в
        # прод-разметку тавтологичное число — значит вернуть ровно тот дефект,
        # ради поимки которого разметка и заведена.
        cov = r.get("effective_coverage")
        miss = r.get("effective_missing_keys")
        if cov is None or miss is None:   # fail-CLOSED: нечем — не пишем
            raise AssertionError(
                "UNCOVERED без измеренного покрытия: %s (basis=%r) — вердикт и "
                "разметка разошлись" % (r["module"], r.get("coverage_basis")))
        keys = ", ".join(f'"{k}"' for k in miss)
        lines.append(
            f'    "{r["module"]}": {{\n'
            f'        "coverage": {cov},\n'
            f'        "missing_keys": ({keys}{"," if len(miss) == 1 else ""}),\n'
            f'    }},'
        )
    text = _MARKUP_TEMPLATE.format(
        generated_at=report["generated_at"],
        probe_protocols=report["probe_protocols"],
        min_coverage=report["min_coverage"],
        detail_lines="\n".join(lines),
    )
    path.write_text(text, encoding="utf-8")


_TIER_C_MARKUP_TEMPLATE = '''"""
_tier_c_key_coverage.py — разметка Tier-C: что известно про КАЖДЫЙ из {module_count}
модулей тира и какие из них помечены «нечем сорсить».

СГЕНЕРИРОВАНО scripts/audit_tier_c_wiring_feasibility.py — НЕ редактировать
вручную; перегенерация (в sandbox-чекауте, не в живом репо — модули пишут
`data/*`-логи относительно корня репо):

    python3 scripts/audit_protocol_blindness.py --tier C --out /tmp/blind_c.json
    python3 scripts/audit_tier_c_wiring_feasibility.py --tier C \\
        --out /tmp/feas_c.json --emit-markup --blindness /tmp/blind_c.json

Разметка сшита из ДВУХ замеров, потому что ни один из них по отдельности не
отвечает на нужный вопрос (класс #29/#31/#35–#40 — сторож честно отвечает на
свой вопрос и читается как ответ на другой):

* **аудит слепоты** ({blindness_generated_at}) отвечает «даёт ли агрегатор от
  модуля число СЕГОДНЯ» — `blindness` в каждой записи;
* **аудит пригодности** ({generated_at}) отвечает «можно ли НАЗВАТЬ, каких
  фактов не хватает» — `verdict` / `coverage` / `missing_keys`.

## TIER_C_DISPOSITION — запись, а не удаление

Требование родительской карточки `inbox-tier-c-171-iz-180-modulei-ne-otvechayut`
(пункт 4): списание фиксируется ЗАПИСЬЮ, реестр обязан продолжать знать, что
модуль есть и почему он не считается. `TIER_C_DISPOSITION` — эта запись: по
строке на каждый из {module_count} модулей тира, ничего не удалено.

Читать её как приговор нельзя: строка `unchecked` означает «мы НЕ ЗНАЕМ»
(агрегатору нечем построить вход движка), а не «измерен ноль». Решение о
списании — за владельцем, карточка
`own-tier-c-spisat-180-modulei-ili-priznat-chto-ne-znaem`.

## UNSOURCED_MODULES — потребляемый набор, численно инертный

Модуль попадает сюда, только если ОБА условия выполнены:

1. `blindness == "failed"` — агрегатор зовёт его сегодня, и он падает, то есть
   числа от него нет ⇒ не звать его численно ИНЕРТНО (ни `modules_ok`, ни
   `avg_score` не меняются; закреплено тестом в обе стороны);
2. недостающие факты можно НАЗВАТЬ поимённо (замер покрытия либо список полей
   из текста исключения).

Оба условия обязательны — fail-CLOSED. Не смогли назвать, чего не хватает ⇒
модуль остаётся громким `failed`, а не получает успокаивающий ярлык. И
наоборот: модуль, который сегодня ДАЁТ число, сюда не попадает никогда, каким
бы плохим ни было его покрытие, — иначе разметка тихо погасила бы работающий
код (урок цикла #136: аннотация не гарантия, первая версия разделения погасила
рабочий модуль Tier-A).

`signal_aggregator._tier_c_pass` не исполняет помеченный модуль и записывает
статус `"unsourced"` с поимённым списком недостающего — вместо `failed`,
который отправлял следующего исполнителя чинить код, в котором чинить нечего.

Снятие пометки — не правка этого файла (он производный), а появление источника
факта либо решение владельца о списании.

Advisory-слой: Tier-C не влияет на аллокацию, RiskPolicy эту разметку не видит.
"""
from typing import Dict, FrozenSet, Tuple

AUDIT_GENERATED_AT = "{generated_at}"
BLINDNESS_GENERATED_AT = "{blindness_generated_at}"
MIN_COVERAGE = {min_coverage}
MODULE_COUNT = {module_count}

#: Сводка по вердиктам слепоты: {blindness_counts}
#: Сводка по вердиктам пригодности: {feasibility_counts}

#: module_name -> {{"blindness": что даёт агрегатор сегодня,
#:                 "verdict": вердикт пригодности,
#:                 "coverage": доля отданных ключей (None = не измерено),
#:                 "missing_keys": поимённо, чего не хватает}}
TIER_C_DISPOSITION: Dict[str, Dict[str, object]] = {{
{disposition_lines}
}}

#: Потребляемый набор (см. докстринг): агрегатор их НЕ исполняет и пишет
#: honest-статус "unsourced" с поимённым списком недостающих фактов.
UNSOURCED_DETAIL: Dict[str, Dict[str, object]] = {{
{unsourced_lines}
}}

UNSOURCED_MODULES: FrozenSet[str] = frozenset(UNSOURCED_DETAIL)

__all__: Tuple[str, ...] = (
    "AUDIT_GENERATED_AT", "BLINDNESS_GENERATED_AT", "MIN_COVERAGE",
    "MODULE_COUNT", "TIER_C_DISPOSITION", "UNSOURCED_DETAIL",
    "UNSOURCED_MODULES",
)
'''


def named_missing_keys(result: Dict[str, Any]) -> Tuple[str, ...]:
    """Поимённый список недостающих фактов, или пустой кортеж.

    Три источника, в порядке убывания надёжности: измеренное покрытие на
    контекст-пути (`effective_missing_keys`), измеренное на переданной записи
    (`missing_keys`), и — только если движок вообще не дошёл до чтения ключей —
    список полей, который он сам назвал в тексте исключения
    (``ValueError: Missing required fields: ['audit_count', …]``).

    Обрезанный многоточием список НЕ принимается: назвать «и ещё что-то» —
    это не назвать. fail-CLOSED, пустой кортеж означает «сказать нечем».
    """
    for key in ("effective_missing_keys", "missing_keys"):
        val = result.get(key)
        if val:
            return tuple(sorted(str(k) for k in val))
    detail = result.get("detail") or ""
    match = re.search(r"\[([^\]]*)\]", detail)
    if not match or not match.group(1).strip():
        return ()
    raw = [p.strip().strip("'\"") for p in match.group(1).split(",")]
    keys = [p for p in raw if p]
    if not keys or any(p in {"...", "…"} for p in keys):
        return ()
    return tuple(sorted(keys))


def _fmt_keys(keys: Tuple[str, ...]) -> str:
    inner = ", ".join('"%s"' % k for k in keys)
    return "(%s%s)" % (inner, "," if len(keys) == 1 else "")


def emit_tier_c_markup(report: Dict[str, Any], blindness: Dict[str, Any],
                       path: Path) -> None:
    """Записать разметку Tier-C: полную диспозицию + потребляемый набор.

    Потребляемый набор строится по правилу «сегодня числа нет И недостающее
    можно назвать» (см. докстринг шаблона). Правило намеренно узкое: широкое
    (например «все BLIND») погасило бы девять модулей, которые СЕГОДНЯ дают
    публикуемый `avg_score`, — то есть разметка молча изменила бы
    опубликованное число под видом починки ярлыка. Такое решение принимает
    владелец, а не генератор.
    """
    blind_by_module = {r["module"]: r for r in blindness.get("results", [])}
    feas = {r["module"]: r for r in report["results"]}
    missing_from_blindness = sorted(set(feas) - set(blind_by_module))
    if missing_from_blindness:
        raise AssertionError(
            "аудит слепоты не знает %d модулей из реестра (%s…) — отчёты сняты "
            "с разных деревьев, сшивать их нельзя"
            % (len(missing_from_blindness), missing_from_blindness[0]))
    if blindness.get("tier") != report["tier"]:
        raise AssertionError(
            "тиры отчётов не совпадают: слепота=%r пригодность=%r"
            % (blindness.get("tier"), report["tier"]))

    disposition_lines: List[str] = []
    unsourced_lines: List[str] = []
    for name in sorted(feas):
        r = feas[name]
        b = blind_by_module[name]
        keys = named_missing_keys(r)
        cov = r.get("effective_coverage")
        if cov is None:
            cov = r.get("coverage")
        disposition_lines.append(
            '    "%s": {\n'
            '        "blindness": "%s",\n'
            '        "verdict": "%s",\n'
            '        "coverage": %s,\n'
            '        "missing_keys": %s,\n'
            '    },' % (name, b["classification"], r["verdict"], cov,
                        _fmt_keys(keys))
        )
        if b["classification"] == "failed" and keys:
            unsourced_lines.append(
                '    "%s": {\n'
                '        "coverage": %s,\n'
                '        "missing_keys": %s,\n'
                '    },' % (name, cov, _fmt_keys(keys))
            )

    text = _TIER_C_MARKUP_TEMPLATE.format(
        generated_at=report["generated_at"],
        blindness_generated_at=blindness.get("generated_at", "?"),
        min_coverage=report["min_coverage"],
        module_count=report["module_count"],
        blindness_counts=blindness.get("counts", {}),
        feasibility_counts=report["counts"],
        disposition_lines="\n".join(disposition_lines),
        unsourced_lines="\n".join(unsourced_lines),
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
                    help="перегенерировать разметку тира: Tier B → "
                         "spa_core/analytics/_protocol_key_coverage.py, "
                         "Tier C → spa_core/analytics/_tier_c_key_coverage.py "
                         "(для Tier C обязателен --blindness)")
    ap.add_argument("--blindness", default=None,
                    help="JSON-отчёт audit_protocol_blindness.py --tier C; "
                         "нужен для --emit-markup на Tier C: потребляемый "
                         "набор строится по «сегодня числа нет И недостающее "
                         "можно назвать»")
    args = ap.parse_args(argv)

    report = run_audit(args.tier, only_modules=args.only,
                       min_coverage=args.min_coverage)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.emit_markup:
        # Tier-A разметки не потребляет (worst-wins, не weighted) — писать
        # её было бы созданием файла без читателя.
        if args.tier not in ("B", "C"):
            print("--emit-markup поддержан только для Tier B и Tier C",
                  file=sys.stderr)
            return 2
        # Частичный скан не вправе переписывать разметку целиком: не
        # упомянутый модуль молча потерял бы пометку.
        if args.only:
            print("--emit-markup несовместим с --only: частичный скан стёр бы "
                  "пометки у неизмеренных модулей", file=sys.stderr)
            return 2
        if args.tier == "B":
            if args.blindness:
                print("--blindness применим только к Tier C", file=sys.stderr)
                return 2
            emit_markup(report, ROOT / "spa_core" / "analytics"
                        / "_protocol_key_coverage.py")
        else:
            # fail-CLOSED: без ответа на «даёт ли модуль число сегодня»
            # потребляемый набор построить нельзя, а построить его на одном
            # лишь покрытии значило бы погасить работающие модули.
            if not args.blindness:
                print("--emit-markup на Tier C требует --blindness "
                      "<отчёт audit_protocol_blindness.py --tier C>: без него "
                      "нечем доказать, что пометка численно инертна",
                      file=sys.stderr)
                return 2
            blindness = json.loads(
                Path(args.blindness).read_text(encoding="utf-8"))
            emit_tier_c_markup(report, blindness,
                               ROOT / "spa_core" / "analytics"
                               / "_tier_c_key_coverage.py")

    print(f"modules={report['module_count']} counts={report['counts']}")
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
