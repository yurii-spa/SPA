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
  SHAPE_NOT_PROBED вход объявлен не списком записей — инструмент НЕ измеряет и
                   говорит почему (см. `call_shape`: вызов чужой формы дал бы
                   падение по вине инструмента, а не модуля);
  NO_ENTRY         не нашли entrypoint с позиционным параметром;
  IMPORT_ERR       модуль не импортируется.

**Область применимости.** Инструмент отвечает ровно на один вопрос — «даст ли
`_protocol_facts` честный вход движку, который ждёт СПИСОК записей». Он не
измеряет модули других форм входа и не заменяет `audit_protocol_blindness.py`.

Границы: только stdlib · LLM здесь не участвует · инструмент READ-ONLY по
отношению к прод-состоянию (ничего не пишет, кроме своего --out).

Запуск ТОЛЬКО в sandbox (как и `audit_protocol_blindness.py`): САМИ модули
пишут свои `data/*`-логи относительно корня репо, поэтому прогон из живого
дерева пачкает прод-данные.

    python3 scripts/audit_tier_c_wiring_feasibility.py --tier C --out /tmp/feas.json
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


#: Аннотации, при которых движок ждёт СПИСОК записей — единственная форма,
#: которую этот инструмент вправе позвать как `fn([profile])`.
_LIST_ANNOTATIONS = ("list", "typing.list", "sequence", "iterable", "tuple")


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
    if shape != "list":
        # Не пробуем — и говорим, ПОЧЕМУ. Молчаливая попытка вызвать чужую
        # форму дала бы падение по вине инструмента (см. `call_shape`).
        return {"module": name, "entry": entry, "verdict": "SHAPE_NOT_PROBED",
                "call_shape": shape, "annotation": annotation,
                "detail": f"вход объявлен как `{annotation or shape}` — не список "
                          "записей; пригодность facts-проводки этим инструментом "
                          "не измеряется (не выдумываем вызов)"}

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
            result = fn([rec])
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--out", required=True, help="куда положить JSON-отчёт")
    ap.add_argument("--tier", default="C", choices=["A", "B", "C"])
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                    help="доля читаемых ключей, которые профиль обязан отдать "
                         "(1.0 = ни одного молчаливого дефолта)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="ограничить набор модулей (имена как в реестре)")
    args = ap.parse_args(argv)

    report = run_audit(args.tier, only_modules=args.only,
                       min_coverage=args.min_coverage)
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

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
