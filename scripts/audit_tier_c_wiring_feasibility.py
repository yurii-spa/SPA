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

Любой отказ назван поимённо: `missing_keys` перечисляет, ЧЕГО не хватает, —
чтобы решение «дописать факты / взять живой фид / честно списать» принималось
по фактам, а не по догадке.

**Замер ключей — объединение по всем пробным протоколам.** Движок может уйти в
другую ветку на другом протоколе и спросить там новый ключ; замер по одному
протоколу занизил бы список отсутствующих и подал бы модуль как более
пригодный, чем он есть.

Статусы (`verdict`):
  WIRABLE          различает протоколы И профиль покрывает все читаемые ключи;
  BLIND            score одинаков на всех протоколах — проводка = новая константа;
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
from typing import Any, Dict, List, Optional, Tuple

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
    if shape not in _PROBEABLE_SHAPES:
        # Не пробуем — и говорим, ПОЧЕМУ. Молчаливая попытка вызвать чужую
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

    coverage = None if not read else round((len(read) - len(missing)) / len(read), 4)
    out: Dict[str, Any] = {
        "module": name, "entry": entry, "call_shape": shape,
        # Чем именно звали — иначе вердикт нечем перепроверить.
        "call_form": "fn([profile])" if shape == "list" else "fn(profile)",
        "annotation": annotation, "scores": scores,
        "keys_read": len(read), "keys_missing": len(missing),
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
    # Различает — но различает ли ТЕМ, о чём модуль? Отвечает покрытие.
    if coverage is None or coverage < min_coverage:
        out.update({"verdict": "UNCOVERED",
                    "detail": "score различается, но профиль не даёт "
                              f"{len(missing)} из {len(read)} читаемых ключей — "
                              "различие пришло из побочных полей"})
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
            f"(>= {min_coverage}); иначе отказ с поимённым списком отсутствующих ключей"
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
