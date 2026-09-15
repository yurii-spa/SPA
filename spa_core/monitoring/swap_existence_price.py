"""Цена операции, КОТОРОЙ НЕ БЫЛО (заказ #609/G22).

Заказ, оставленный в хвосте [ADR-389] по стоячему приказу владельца «Portfolio
CIO», поставлен дословно так:

> Замер назвал величину, которая держит знак, и она оказалась **константой без
> провенанса**. Ровно один вопрос следует из этого и ни разу не задавался:
> **(а) существует ли операция, которую эта константа оценивает?**
> ``SLIPPAGE_BPS_STABLE`` называется «stablecoin swap slippage» —
> проскальзывание СВОПА. Но перекладка USDC из Aave в Compound свопа не
> содержит: это вывод и внесение одного и того же актива по номиналу. […]
> **(б) откуда взялось число 8.0** — у константы обязан быть провенанс […]
> **(в) и в той же валюте:** сколько ACT-дней вернулось бы критерию, если бы
> проскальзывание начислялось только на ноги, где актив ДЕЙСТВИТЕЛЬНО меняется.

## Что именно меряется, и почему это не разбор имени константы

Комментарий у литерала («stablecoin swap slippage») — не довод: он говорит, ЧТО
автор имел в виду, а не что происходит с деньгами. Довод даёт только актив пула
у каждой ноги. Поэтому прибор не читает комментарий вовсе, а берёт **актив** и
считает, сколько долларов потока переходит между пулами с ОДНИМ И ТЕМ ЖЕ активом:
на них свопа нет ни при каком прочтении слова «своп», а проскальзывание
начислено.

## Актив ноги: две дороги, и обе ведут от КОДА, а не от вида имени

Денежный путь знает ключ (``aave_v3``), а актив объявлен в другом реестре и под
ДРУГИМИ именами (``aave_usdc``) — 22 записи против 36. Сводить их по виду имени
значило бы воспроизвести ровно тот дефект, из-за которого три месяца врал
``house_view_gap`` (правило ``.claude/rules/adapters.md``, цикл #274). Поэтому
дорог две, и каждая — тождество, а не догадка:

============================  ==========================================
дорога                        чем доказана
============================  ==========================================
``ADAPTER_METADATA`` по КЛАССУ  совпадение ``(module, class)`` с канони-
                              ческим ``ADAPTER_REGISTRY``: один и тот же
                              объект кода наблюдает один и тот же пул
атрибут класса ``ASSET``      адаптер объявил актив о себе сам
============================  ==========================================

Дороги ДОПОЛНЯЮТ друг друга, и это замер, а не предположение: ``fluid_usdc``
первой дорогой НЕ разрешается (в метаданных под этим именем лежит другой модуль),
а второй — разрешается. Разошлись ⇒ третий исход ``asset_disputed``: два
источника об одном пуле, спорящие между собой, — самая дешёвая улика, и
выбирать из них «поудобнее» прибор не вправе.

Ни одна дорога не сработала ⇒ ``asset_unknown`` с НАЗВАННЫМ ключом. Подставить
«наверное USDC, судя по имени» значило бы выдать догадку за запись — и именно от
этого зависит весь ответ.

## Доля свопа: границы, а не одно число

Журнал пишет ноги дня (кто сколько отдал и принял), но НЕ пишет, какой доллар в
какой пул пошёл. Поэтому доля потока, требующая свопа, вообще не есть одно число:
она зависит от сопоставления, которого в записи нет. Прибор даёт **две границы**,
обе выводимые:

* **нижняя** — одинаковые активы сводятся в первую очередь; неизвестный актив
  считается подходящим к чему угодно (ослабление названо: неизвестная нога
  делится свободно, поэтому граница именно НИЖНЯЯ, а не точная);
* **верхняя** — одинаковые активы сводятся только там, где этого нельзя
  избежать; неизвестная нога не подходит ни к чему.

Границы СОВПАЛИ ⇒ ответ точен, и это сказано отдельным признаком: совпадение
границ есть доказательство, что сопоставление предопределено записью дня.

Рядом печатается ВТОРАЯ популяция — дни, где актив известен у КАЖДОЙ ноги. На
ней ответ точен по построению, без всяких ослаблений, и два ответа не
складываются.

## Дисбаланс дня закрывается КЭШЕМ, и у кэша есть владелец

Отток и приток дня не равны: разница уходит в кэш или приходит из него. Актив
кэша берётся у ``data/capital_config.json`` (``capital.currency``) — того самого
git-tracked источника, который читает конституция сайта и который меняется ADR, —
а не из знания, что портфель долларовый. Источник не прочитан ⇒ день уходит в
третий исход целиком: подставленный кэш сводил бы активы, которых никто не
объявлял.

## (б) провенанс константы: прибор ОТКАЗЫВАЕТСЯ мерить на неполной истории

Археология делается ``git log -S`` — и ровно поэтому обязана сперва спросить, та
ли это история. Прод-дерево SPA — НЕПОЛНЫЙ клон (443 коммита против 26 889 в
зеркале), и на нём ``git log -S`` честно называет первым коммитом тот, что просто
оказался первым в обрезке. Это не «нет провенанса», это НЕ ИЗМЕРЕНО, и разница
здесь решает весь ответ. Прибор спрашивает ``git rev-parse
--is-shallow-repository`` ПЕРВЫМ и на обрезанной истории не печатает дату вовсе.

Независимо от глубины истории мерится то, что лежит в дереве: сколько ADR
называют константу, и несёт ли её собственная строка хоть один признак ссылки
(URL, номер ADR, дата). Строка без единого такого признака — литерал с
комментарием, и «комментарий» провенансом не является.

## (в) контрфакт: снять проскальзывание с долларов, которые не менялись

Цена дня пересчитывается ровно одним вычитанием — ``recorded − (поток − своп) ×
bps/10000`` — и ничего больше не трогает: газ и мост остаются записанными, потому
что вопрос заказа именно о проскальзывании. Дни, у которых доля свопа не
измерена, не трогаются ВОВСЕ (их цена идёт как записана), и число таких дней
печатается рядом с ответом: контрфакт, молча пощадивший половину населения,
отвечал бы на свой вопрос.

Проводка контрфакта проверяется отдельным замером: вариант «цена ноль» ОБЯЗАН
менять ответ судьи (по [ADR-389] критерий закрывается уже при ×0.1622). Не
меняет ⇒ весь раздел объявляется НЕ ИЗМЕРЕННЫМ: ноль ACT-дней при мёртвой
проводке говорит о приборе, а не о мире.

## Чего прибор НЕ доказывает

Он не утверждает, что константу следует понизить или убрать: константы стоимости
— вход денежного пути и предмет №1 границы [ADR-285]. Он не измеряет рыночную
цену перекладки — её на бумажной стадии не наблюдал никто. Он ничего не говорит о
днях без записанных ног (до 2026-09-01 писатель ``legs`` не писал) и о том, верен
ли был сам ход. И он не утверждает, что вывод-внесение бесплатны: у них есть газ,
и газ прибор не трогает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

OUTPUT_FILENAME = "swap_existence_price.json"
VERSION = "swap-existence-price-v1"
ORDER = "#609/G22 (хвост ADR-389, стоячий приказ владельца «Portfolio CIO»)"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

#: Доллар считается сведённым в пределах цента: суммы ног записаны с двумя
#: знаками, и требовать точного равенства значило бы объявить расхождением
#: собственное округление журнала.
CENT = 0.005

#: Признаки ССЫЛКИ в строке константы. Список намеренно широк: вопрос «есть ли
#: хоть один признак провенанса», и ложное срабатывание здесь безопаснее
#: пропуска — оно бы ОСЛАБИЛО находку, а не усилило её.
_CITATION_MARKERS = (
    re.compile(r"https?://"),
    re.compile(r"\bADR[-\s]?\d", re.I),
    re.compile(r"\b20\d\d-\d\d-\d\d\b"),
    re.compile(r"\bMP-\d+\b"),
    re.compile(r"\bsource\b|\bисточник\b|\bзамер\b|\bmeasured\b", re.I),
)

#: Владелец константы и её соседа того же рода. Модуль и имя — ЗДЕСЬ, значение —
#: НИКОГДА: число берётся импортом у владельца, иначе прибор сверял бы литерал
#: с копией литерала.
_CONSTANTS: Tuple[Tuple[str, str], ...] = (
    ("spa_core/backtesting/tier1/cost_model.py", "SLIPPAGE_BPS_STABLE"),
    ("spa_core/paper_trading/shadow_trigger_eval.py",
     "ASSUMED_COST_BPS_OF_TURNOVER"),
)


# ───────────────────────── соседи зовутся, а не переписываются ─────────────────
def _neighbour():
    """Прибор G20: доступ к судье, возмущение каталога, перечисление гейтов."""
    from spa_core.monitoring import criterion_sign_price as csp
    return csp


def _judge():
    from spa_core.paper_trading import shadow_trigger_eval as ste
    return ste


def _slippage_bps() -> float:
    """Константа — ИМПОРТОМ у владельца. Литерала 8.0 в этом файле нет."""
    from spa_core.backtesting.tier1.cost_model import SLIPPAGE_BPS_STABLE
    return float(SLIPPAGE_BPS_STABLE)


# ────────────────────────────── актив пула у ноги ──────────────────────────────
def asset_map() -> Tuple[Dict[str, dict], dict]:
    """Актив КАЖДОГО ключа канонического реестра — двумя независимыми дорогами.

    Дороги не «выбираются»: если обе ответили и разошлись, ключ получает
    ``disputed`` и в счёт не идёт ни одной стороной. Ни одна не ответила ⇒
    ``unknown`` с названным ключом; подставить актив по виду имени прибор не
    вправе — на этом три месяца врал ``house_view_gap`` (цикл #274).
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        from spa_core.adapters.registry import ADAPTER_METADATA
    except Exception as exc:  # noqa: BLE001 — причина, а не пустая карта
        return {}, {"measured": False,
                    "reason": f"реестры адаптеров не читаются: {exc}"}

    by_class: Dict[Tuple[str, str], List[str]] = {}
    for key, meta in ADAPTER_METADATA.items():
        by_class.setdefault(
            (str(meta.get("module")), str(meta.get("class"))), []).append(str(key))

    out: Dict[str, dict] = {}
    counts = {"resolved": 0, "unknown": 0, "disputed": 0}
    for name, _tier, cls in ADAPTER_REGISTRY:
        routes: Dict[str, str] = {}
        twins = sorted(by_class.get((cls.__module__, cls.__name__), []))
        metadata_assets = sorted({
            str(ADAPTER_METADATA[t]["asset"]) for t in twins
            if ADAPTER_METADATA[t].get("asset")})
        if len(metadata_assets) == 1:
            routes["metadata_by_class"] = metadata_assets[0]
        declared = getattr(cls, "ASSET", None)
        if declared:
            routes["class_attribute"] = str(declared)
        distinct = sorted(set(routes.values()))
        if len(distinct) == 1:
            state, asset = "resolved", distinct[0]
        elif not distinct:
            state, asset = "unknown", None
        else:
            state, asset = "disputed", None
        counts[state] += 1
        out[str(name)] = {"asset": asset, "state": state, "routes": routes,
                          "metadata_twins": twins,
                          "class": f"{cls.__module__}.{cls.__name__}"}
    ctx = {
        "measured": True,
        "registry_keys": len(out),
        "metadata_keys": len(ADAPTER_METADATA),
        **counts,
        # Дополнительность дорог ИЗМЕРЕНА, а не заявлена: если бы вторая дорога
        # не добавляла ни одного ключа, называть её дорогой было бы украшением.
        "resolved_by_class_attribute_only": sorted(
            k for k, v in out.items()
            if v["state"] == "resolved" and "metadata_by_class" not in v["routes"]),
        "resolved_by_metadata_only": sorted(
            k for k, v in out.items()
            if v["state"] == "resolved" and "class_attribute" not in v["routes"]),
        "disputed_keys": sorted(k for k, v in out.items()
                                if v["state"] == "disputed"),
    }
    return out, ctx


def cash_asset(data_dir: Path) -> Tuple[Optional[str], str]:
    """Актив кэша — у своего владельца, а не из знания, что портфель долларовый.

    ``data/capital_config.json`` git-tracked и меняется ADR (тот же источник, из
    которого генерится конституция сайта). Не прочитан ⇒ ``None`` и причина: без
    актива кэша дисбаланс дня свести нечем, и подставленный кэш сводил бы активы,
    которых никто не объявлял.
    """
    path = Path(data_dir) / "capital_config.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"актив кэша НЕ ПРОЧИТАН ({path.name}: {exc})"
    # `(doc.get("capital") or {}).get(...)` здесь запрещён (инв. #17): пустой
    # словарь слил бы «блока capital нет» с «ключ currency пуст» в один ответ,
    # а причины разные и чинятся по-разному.
    capital = observed(doc, "capital", kind=dict)
    if capital is None:
        return None, f"актив кэша НЕ ОБЪЯВЛЕН ({path.name}: блока capital нет)"
    value = capital.get("currency")
    if not value:
        return None, f"актив кэша НЕ ОБЪЯВЛЕН ({path.name}: capital.currency пуст)"
    return str(value), f"{path.name}: capital.currency = {value}"


# ───────────────────── (а) сколько потока требует смены актива ─────────────────
def swap_share(legs: Sequence[dict], turnover_usd: float, assets: Dict[str, dict],
               cash: Optional[str]) -> dict:
    """Границы доли потока, на которой актив ДЕЙСТВИТЕЛЬНО меняется.

    Возвращает обе границы и признак ``exact`` (границы совпали ⇒ сопоставление
    предопределено записью дня). Неизвестный актив НЕ подставляется: он двигает
    границы врозь, и именно ширина между ними и есть цена незнания.
    """
    if cash is None:
        return {"measured": False, "reason": "cash_asset_unknown"}
    out_known: Dict[str, float] = {}
    in_known: Dict[str, float] = {}
    wild_out = wild_in = 0.0
    unknown_keys: List[str] = []
    disputed_keys: List[str] = []
    for leg in legs:
        key = str(leg.get("protocol"))
        try:
            delta = float(leg.get("delta_usd"))
        except (TypeError, ValueError):
            return {"measured": False, "reason": f"leg_delta_unreadable:{key}"}
        entry = assets.get(key) or {"state": "unknown", "asset": None}
        if entry["state"] == "resolved":
            bucket = out_known if delta < 0 else in_known
            bucket[entry["asset"]] = bucket.get(entry["asset"], 0.0) + abs(delta)
        else:
            (unknown_keys if entry["state"] == "unknown"
             else disputed_keys).append(key)
            if delta < 0:
                wild_out += abs(delta)
            else:
                wild_in += abs(delta)

    gross_out = sum(out_known.values()) + wild_out
    gross_in = sum(in_known.values()) + wild_in
    # Дисбаланс дня — кэш. Он ЗНАЕТ свой актив, поэтому попадает в известные
    # корзины, а не в подстановочные: кэш не «неизвестная нога».
    if gross_out > gross_in:
        in_known[cash] = in_known.get(cash, 0.0) + (gross_out - gross_in)
    elif gross_in > gross_out:
        out_known[cash] = out_known.get(cash, 0.0) + (gross_in - gross_out)
    flow = max(gross_out, gross_in)
    if flow <= 0.0:
        return {"measured": False, "reason": "no_flow"}
    # Поток обязан сойтись с записанным оборотом: расхождение значит, что о ходе
    # спорят два производителя (`legs` против `turnover_usd`), и делить один на
    # другой значило бы взять знаменатель из населения, из которого ноги выпали.
    if abs(flow - float(turnover_usd)) > CENT:
        return {"measured": False,
                "reason": (f"flow_disagrees_with_turnover:"
                           f"{flow:.2f}!={float(turnover_usd):.2f}")}

    names = set(out_known) | set(in_known)
    # НИЖНЯЯ граница: сводим одинаковое в первую очередь, затем подстановочные
    # ноги гасят остатки (ослабление: неизвестная нога делится свободно, поэтому
    # граница НИЖНЯЯ, а не точная — сказано в ответе полем `relaxation`).
    base = sum(min(out_known.get(a, 0.0), in_known.get(a, 0.0)) for a in names)
    rest_out = sum(out_known.get(a, 0.0) - min(out_known.get(a, 0.0),
                                               in_known.get(a, 0.0))
                   for a in names)
    rest_in = sum(in_known.get(a, 0.0) - min(out_known.get(a, 0.0),
                                             in_known.get(a, 0.0))
                  for a in names)
    take_a = min(rest_out, wild_in)
    take_b = min(rest_in, wild_out)
    take_c = min(wild_out - take_b, wild_in - take_a)
    matched_max = base + take_a + take_b + take_c
    swap_min = max(0.0, flow - matched_max)
    # ВЕРХНЯЯ граница: одинаковое сводится только там, где не свести нельзя;
    # подстановочная нога не подходит ни к чему.
    forced = sum(max(0.0, out_known.get(a, 0.0) + in_known.get(a, 0.0) - flow)
                 for a in names)
    swap_max = max(0.0, flow - forced)
    return {
        "measured": True,
        "flow_usd": round(flow, 2),
        "swap_usd_min": round(swap_min, 2),
        "swap_usd_max": round(swap_max, 2),
        "no_swap_usd_min": round(flow - swap_max, 2),
        "no_swap_usd_max": round(flow - swap_min, 2),
        "exact": abs(swap_max - swap_min) <= CENT,
        "all_assets_known": not unknown_keys and not disputed_keys,
        "relaxation": (None if not (wild_out or wild_in) else
                       "неизвестная нога делится свободно ⇒ swap_usd_min есть "
                       "НИЖНЯЯ граница, а не точное число"),
        "assets_out": {k: round(v, 2) for k, v in sorted(out_known.items())},
        "assets_in": {k: round(v, 2) for k, v in sorted(in_known.items())},
        "wildcard_out_usd": round(wild_out, 2),
        "wildcard_in_usd": round(wild_in, 2),
        "unknown_keys": sorted(set(unknown_keys)),
        "disputed_keys": sorted(set(disputed_keys)),
    }


def existence(days: Sequence[dict], rows: Dict[str, dict],
              assets: Dict[str, dict], cash: Optional[str]) -> dict:
    """Сводка (а) по двум популяциям: со всеми известными активами и со всеми днями.

    Два ответа печатаются РЯДОМ и никогда не складываются: на строгой популяции
    ответ точен по построению, на широкой — это границы с названным ослаблением.
    """
    per_day: List[dict] = []
    for d in days:
        rec = rows.get(d["date"]) or {}
        legs = rec.get("legs")
        row = {"date": d["date"], "turnover_usd": round(float(d["turnover_usd"]), 2),
               "cost_usd_recorded": round(float(d["cost_usd"]), 2)}
        if not isinstance(legs, list) or not legs:
            # До 2026-09-01 писатель ног не писал вовсе. Актив ноги, которой нет
            # в записи, не «USDC по умолчанию» — его нет.
            row.update({"measured": False, "reason": "legs_not_recorded"})
        else:
            row.update(swap_share(legs, float(d["turnover_usd"]), assets, cash))
        per_day.append(row)

    good = [r for r in per_day if r.get("measured")]
    strict = [r for r in good if r.get("all_assets_known")]

    def _totals(pop: Sequence[dict]) -> Optional[dict]:
        if not pop:
            return None
        flow = sum(r["flow_usd"] for r in pop)
        smin = sum(r["swap_usd_min"] for r in pop)
        smax = sum(r["swap_usd_max"] for r in pop)
        return {
            "days": len(pop),
            "flow_usd": round(flow, 2),
            "swap_usd_min": round(smin, 2), "swap_usd_max": round(smax, 2),
            "swap_share_min": round(smin / flow, 4) if flow else None,
            "swap_share_max": round(smax / flow, 4) if flow else None,
            "no_swap_share_min": round((flow - smax) / flow, 4) if flow else None,
            "no_swap_share_max": round((flow - smin) / flow, 4) if flow else None,
            "bounds_coincide": abs(smax - smin) <= CENT,
        }

    reasons: Dict[str, List[str]] = {}
    for r in per_day:
        if r.get("measured"):
            continue
        reasons.setdefault(str(r.get("reason")).split(":")[0], []).append(r["date"])
    blocking: Dict[str, List[str]] = {}
    for r in good:
        for key in r.get("unknown_keys", []) + r.get("disputed_keys", []):
            blocking.setdefault(key, []).append(r["date"])
    return {
        "per_day": per_day,
        "days_total": len(per_day),
        "days_measured": len(good),
        "days_all_assets_known": len(strict),
        "unmeasured_reasons": {k: sorted(v) for k, v in sorted(reasons.items())},
        "totals_all_measured_days": _totals(good),
        "totals_strict_days": _totals(strict),
        # Один ключ, ослепляющий половину населения, — находка более
        # действенная, чем сама доля: он называет, что чинить.
        "blocking_keys": {k: sorted(v) for k, v in sorted(
            blocking.items(), key=lambda kv: (-len(kv[1]), kv[0]))},
        "assets_seen": sorted({a for r in good
                               for a in (list(r["assets_out"]) + list(r["assets_in"]))}),
    }


# ─────────────────────── (б) провенанс константы: археология ───────────────────
def _git(repo: Path, *args: str) -> Tuple[int, str]:
    try:
        p = subprocess.run(("git", "-C", str(repo)) + args, capture_output=True,
                           text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        return 127, str(exc)
    return p.returncode, (p.stdout or "").strip()


def provenance(repo: Path) -> dict:
    """Кто и по какому наблюдению выбрал константу — либо честное «не измерено».

    ПЕРВЫМ спрашивается глубина истории. На обрезанном клоне ``git log -S``
    отвечает на свой вопрос («первый в обрезке»), и напечатанная оттуда дата была
    бы не слабым доводом, а неверным: замер 15.09 — прод-дерево называет
    2026-09-12, полное зеркало 2026-06-24. Поэтому на обрезке прибор не печатает
    дату ВОВСЕ.
    """
    repo = Path(repo)
    code, shallow_out = _git(repo, "rev-parse", "--is-shallow-repository")
    if code != 0:
        return {"measured": False,
                "reason": f"git не отвечает в {repo}: {shallow_out[:200]}"}
    shallow = shallow_out.strip().lower() == "true"
    _c, total = _git(repo, "rev-list", "--count", "HEAD")

    entries: List[dict] = []
    for rel, name in _CONSTANTS:
        path = repo / rel
        row: dict = {"constant": name, "file": rel}
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            row.update({"measured": False, "reason": f"файл не прочитан: {exc}"})
            entries.append(row)
            continue
        line = next((l for l in text.splitlines()
                     if l.strip().startswith(name + " ")
                     or l.strip().startswith(name + "=")), None)
        row["declaration_line"] = line
        # Провенанс в самой строке: есть ли ХОТЬ ОДИН признак ссылки. Отсутствие
        # всех — измеримое утверждение, а не впечатление от чтения.
        row["citation_markers_in_line"] = (
            sorted(m.pattern for m in _CITATION_MARKERS if line and m.search(line))
            if line is not None else None)
        row["line_cites_a_source"] = bool(row["citation_markers_in_line"])
        # Сколько ADR называют константу — вопрос к ДЕРЕВУ, а не к истории,
        # поэтому на обрезанном клоне он всё равно измерим.
        adr_dir = repo / "docs" / "decisions"
        named_in: List[str] = []
        if adr_dir.is_dir():
            for adr in sorted(adr_dir.glob("ADR-*.md")):
                try:
                    if name in adr.read_text(encoding="utf-8"):
                        named_in.append(adr.name)
                except Exception:  # noqa: BLE001 — нечитаемый ADR не «чистый»
                    named_in.append(f"{adr.name}:UNREADABLE")
        row["named_in_adr"] = named_in
        row["adr_count"] = len(named_in)
        if shallow:
            row.update({
                "history_measured": False,
                "history_reason": (
                    f"история ОБРЕЗАНА ({total} коммит(ов) в {repo}); "
                    "`git log -S` назвал бы первым тот коммит, что просто "
                    "оказался первым в обрезке — это НЕ «провенанса нет»"),
                "first_commit": None, "first_commit_date": None,
                "commits_touching_line": None})
        else:
            code_l, log = _git(repo, "log", "--reverse",
                               "--format=%H\t%ad\t%s", "--date=short",
                               "-S", name, "--", rel)
            if code_l != 0:
                row.update({"history_measured": False,
                            "history_reason": f"git log -S отказал: {log[:200]}"})
            else:
                lines = [l for l in log.splitlines() if l.strip()]
                first = lines[0].split("\t") if lines else None
                row.update({
                    "history_measured": True,
                    "commits_touching_line": len(lines),
                    "first_commit": first[0][:9] if first else None,
                    "first_commit_date": first[1] if first and len(first) > 1 else None,
                    "first_commit_subject": (first[2] if first and len(first) > 2
                                             else None)})
        entries.append(row)
    return {
        "measured": True,
        "repo": str(repo),
        "history_complete": not shallow,
        "commits_total": int(total) if total.isdigit() else None,
        "constants": entries,
        "constants_without_any_citation": sorted(
            e["constant"] for e in entries
            if e.get("line_cites_a_source") is False),
        "constants_named_by_no_adr": sorted(
            e["constant"] for e in entries if e.get("adr_count") == 0),
    }


# ───────────────── (в) контрфакт: проскальзывание только на своп ───────────────
def _charge_swap_only(relief_by_date: Dict[str, float],
                      refused: Optional[set] = None):
    """Снять с цены дня проскальзывание за доллары, которые актива не меняли.

    Трогается ОДНО слагаемое: газ и мост остаются записанными, потому что вопрос
    заказа именно о проскальзывании. День, которого нет в карте послаблений, не
    трогается вовсе — придуманное послабление было бы ответом на свой вопрос.

    Цена, упавшая до НУЛЯ, не записывается: такой день называется в ``refused``
    и уходит из населения контрфакта, а не подставляет чужое число молча.

    **Основание этой ветки сменилось, и она СОХРАНЕНА намеренно.** Писалась она
    против судьи, у которого ноль и отсутствие шли одной веткой (``cost_rec > 0.0``):
    записанный ноль обернулся бы ЗАВЫШЕНИЕМ цены до ``ASSUMED_COST_BPS_OF_TURNOVER``.
    Ту ветку снял ADR-393, и завышения больше не будет — но снимать отсюда отказ
    прицепом значило бы сдвинуть ЧИСЛА контрфакта ADR-390 правкой, которой владелец
    не давал. Цена сохранения ИЗМЕРЕНА, а не предположена: на журнале 2026-09-15
    ``days_refused_zero_price`` пуст, то есть ветка не срабатывает ни разу и сегодня
    не стои́т нам ни одного дня. Пересмотр — отдельным замером (заказ цикла #611).
    """
    def mutate(rec: dict) -> None:
        date = str(rec.get("cycle_date"))
        relief = relief_by_date.get(date)
        if relief is None:
            return
        # Цены нет ⇒ строка НЕ трогается вовсе. Прочитать её как 0.0 значило бы
        # сделать «не записали» и «бесплатно» одним входом — ровно тот дефект,
        # который этот же прибор нашёл у судьи (инв. #17).
        raw = rec.get("cost_usd")
        if raw is None:
            return
        try:
            new = float(raw) - relief
        except (TypeError, ValueError):
            return
        if new <= 0.0:
            if refused is not None:
                refused.add(date)
            return
        rec["cost_usd"] = new
    return mutate


def zero_is_absent(data_dir: Path, *, horizon_days: int,
                   gates: Sequence[str]) -> dict:
    """Различает ли судья «цена измерена и равна нулю» и «цены не записали»?

    Инвариант #17 CLAUDE.md требует, чтобы отсутствие наблюдения имело СВОЁ
    представление. До 2026-09-15 у судьи обе величины проходили одной веткой
    (``cost_rec > 0.0``), и бесплатный ход оценивался ДОРОЖЕ дешёвого: ноль уводил
    день в ``ASSUMED_COST_BPS_OF_TURNOVER``. Замер печатает оба счёта рядом —
    утверждение о ветке, сделанное чтением кода, здесь подтверждается ИСХОДОМ.

    Ветку снял ADR-393 по явному ответу владельца, и прибор от этого НЕ становится
    украшением: он и есть приёмка той починки (``collides`` обязан быть ложью) и
    сторож её возврата. Замер 15.09 после починки: ноль $80.91 против $80.75 за
    цент — различимы ровно на цену цента, как и требует арифметика.
    """
    csp = _neighbour()
    as_is = csp._variant(Path(data_dir), label="цена как записана",
                         input_name="zero_vs_absent", how="журнал не трогается",
                         mutate=None, horizon_days=horizon_days, gates=gates)
    zero = csp._variant(Path(data_dir), label="цена = 0",
                        input_name="zero_vs_absent",
                        how="`cost_usd` = 0.0 на каждой строке",
                        mutate=lambda rec: rec.__setitem__("cost_usd", 0.0),
                        horizon_days=horizon_days, gates=gates)
    tiny = csp._variant(Path(data_dir), label="цена = цент",
                        input_name="zero_vs_absent",
                        how="`cost_usd` = 0.01 на каждой строке с оборотом",
                        mutate=_flat_cost(0.01),
                        horizon_days=horizon_days, gates=gates)
    # Улика — не «ноль хуже записанного» (это могло бы быть и совпадением), а
    # «ноль хуже ЦЕНТА»: цент дешевле нуля быть не может ни в одной честной
    # модели цены, и расхождение здесь есть утверждение о ветке, а не о мире.
    collides = ((zero.get("best_net_usd") is not None
                 and tiny.get("best_net_usd") is not None
                 and zero["best_net_usd"] < tiny["best_net_usd"] - CENT)
                or (tiny.get("closes_positively") and not zero.get("closes_positively")))
    return {
        "measured": True,
        "collides": bool(collides),
        "best_net_usd_as_is": as_is.get("best_net_usd"),
        "best_net_usd_zero": zero.get("best_net_usd"),
        "best_net_usd_one_cent": tiny.get("best_net_usd"),
        "act_days_zero": zero.get("act_days_to_criterion"),
        "act_days_one_cent": tiny.get("act_days_to_criterion"),
        "closes_zero": zero.get("closes_positively"),
        "closes_one_cent": tiny.get("closes_positively"),
        "rows": [as_is, zero, tiny],
    }


def _flat_cost(level_usd: float):
    """Плоская цена на каждой строке С ОБОРОТОМ; строка без хода не трогается."""
    def mutate(rec: dict) -> None:
        turnover = rec.get("turnover_usd")
        try:
            if turnover is None or float(turnover) <= 0.0:
                return
        except (TypeError, ValueError):
            return
        rec["cost_usd"] = level_usd
    return mutate


def counterfactual(data_dir: Path, ex: dict, *, horizon_days: int,
                   gates: Sequence[str], slippage_bps: float) -> dict:
    """Сколько ACT-дней вернул бы критерию каждый из двух пересчётов цены.

    Уровни названы: цена как записана; проскальзывание только на своп по ВЕРХНЕЙ
    границе свопа (наименьшее послабление) и по НИЖНЕЙ (наибольшее). Границы
    совпали ⇒ два последних совпадут, и это будет видно.

    Проводка проверяется ДО ответа и уровнем, который уже измерен соседом:
    [ADR-389] нашёл перелом критерия при цене ×0.1622, поэтому ×0.1 обязан
    закрывать его. Контроль может провалиться по-настоящему — он не истинен по
    построению, — и провал снимает весь раздел с публикации.

    Уровень «цена ноль» контролем НЕ является и взят быть не может: у судьи ноль
    и отсутствие проходят одной веткой, и бесплатный ход оценивается ДОРОЖЕ
    дешёвого (см. :func:`zero_is_absent`).
    """
    csp = _neighbour()
    good = [r for r in ex["per_day"] if r.get("measured")]

    def _relief(bound: str) -> Dict[str, float]:
        return {r["date"]: (r["flow_usd"] - r[bound]) * slippage_bps / 10_000.0
                for r in good}

    as_is = csp._variant(Path(data_dir), label="цена как записана",
                         input_name="slippage_base", how="журнал не трогается",
                         mutate=None, horizon_days=horizon_days, gates=gates)
    control = csp._variant(
        Path(data_dir), label="контроль проводки: цена ×0.1",
        input_name="wiring_control",
        how="`cost_usd` × 0.1 (ADR-389: перелом критерия при ×0.1622)",
        mutate=csp._scale_cost(0.1), horizon_days=horizon_days, gates=gates,
        factor=0.1)
    wiring_alive = bool(control.get("closes_positively")) and not \
        bool(as_is.get("closes_positively"))
    if not good or not wiring_alive:
        return {
            "measured": False,
            "wiring_alive": wiring_alive,
            "wiring_control": control,
            "reason": (
                "населения нет: ни одного дня с измеренной долей свопа"
                if not good else
                "контроль проводки НЕ ПРОШЁЛ: цена ×0.1 не закрыла критерий, хотя "
                "ADR-389 нашёл перелом при ×0.1622 — расхождение говорит о "
                "приборе или о сдвинувшемся журнале, а не о мире"),
            "rows": [as_is, control],
        }

    rows: List[dict] = [as_is, control]
    refused_least: set = set()
    refused_most: set = set()
    least = csp._variant(
        Path(data_dir), label="своп по ВЕРХНЕЙ границе", input_name="slippage_base",
        how="`cost_usd` −= (поток − swap_max) × bps/10000, газ и мост как записаны",
        mutate=_charge_swap_only(_relief("swap_usd_max"), refused_least),
        horizon_days=horizon_days, gates=gates)
    most = csp._variant(
        Path(data_dir), label="своп по НИЖНЕЙ границе", input_name="slippage_base",
        how="`cost_usd` −= (поток − swap_min) × bps/10000, газ и мост как записаны",
        mutate=_charge_swap_only(_relief("swap_usd_min"), refused_most),
        horizon_days=horizon_days, gates=gates)
    rows.extend([least, most])
    base_act = as_is["act_days_to_criterion"] or 0
    return {
        "measured": True,
        "wiring_alive": True,
        "wiring_control": control,
        "rows": rows,
        "days_repriced": len(good),
        "days_untouched": ex["days_total"] - len(good),
        # Дни, где послабление увело бы цену в ноль, НАЗВАНЫ: их цена осталась
        # записанной, и молчаливой подмены на 15 bps не произошло.
        "days_refused_zero_price": sorted(refused_least | refused_most),
        "slippage_bps": slippage_bps,
        "relief_usd_min": round(sum(_relief("swap_usd_max").values()), 2),
        "relief_usd_max": round(sum(_relief("swap_usd_min").values()), 2),
        "act_days_as_is": as_is["act_days_to_criterion"],
        "act_days_swap_only_least": least["act_days_to_criterion"],
        "act_days_swap_only_most": most["act_days_to_criterion"],
        "closes_as_is": as_is["closes_positively"],
        "closes_swap_only_least": least["closes_positively"],
        "closes_swap_only_most": most["closes_positively"],
        "best_net_usd_as_is": as_is.get("best_net_usd"),
        "best_net_usd_least": least.get("best_net_usd"),
        "best_net_usd_most": most.get("best_net_usd"),
        # Прямой ответ заказа «в той же валюте»: сколько ACT-дней ВЕРНУЛОСЬ.
        "act_days_returned_min": (least["act_days_to_criterion"] or 0) - base_act,
        "act_days_returned_max": (most["act_days_to_criterion"] or 0) - base_act,
    }


# ──────────────────────────────── сборка ответа ────────────────────────────────
def _findings(ex: dict, prov: dict, cf: dict, zero: dict) -> List[dict]:
    out: List[dict] = []
    tot = ex.get("totals_all_measured_days")
    if tot and tot["no_swap_share_min"] and tot["no_swap_share_min"] > 0.0:
        out.append({
            "severity": "critical",
            "code": "slippage_charged_where_no_swap_occurs",
            "text": (
                f"на измеренных днях от {100 * tot['no_swap_share_min']:.2f} % до "
                f"{100 * tot['no_swap_share_max']:.2f} % потока переходит между "
                "пулами с ОДНИМ И ТЕМ ЖЕ активом — свопа там нет, а "
                "проскальзывание начислено на весь оборот безусловно")})
    strict = ex.get("totals_strict_days")
    if strict and strict["bounds_coincide"]:
        out.append({
            "severity": "warning",
            "code": "exact_on_strict_population",
            "text": (
                f"на {strict['days']} дн. с известным активом У КАЖДОЙ ноги "
                "границы совпали ⇒ ответ ТОЧЕН: свопа требует "
                f"{100 * strict['swap_share_min']:.2f} % потока")})
    blocking = ex.get("blocking_keys") or {}
    if blocking:
        key, dates = next(iter(blocking.items()))
        out.append({
            "severity": "warning",
            "code": "one_key_blinds_the_measurement",
            "text": (f"актив не разрешён у {len(blocking)} ключ(ей); хуже всех "
                     f"`{key}` — он расширяет границы на {len(dates)} дн. из "
                     f"{ex['days_measured']}")})
    if prov.get("measured"):
        naked = prov.get("constants_without_any_citation") or []
        if naked:
            out.append({
                "severity": "critical",
                "code": "constant_without_provenance",
                "text": ("ни одного признака ссылки в строке объявления: "
                         + ", ".join(naked))})
        if not prov.get("history_complete"):
            out.append({
                "severity": "warning",
                "code": "history_shallow_archaeology_refused",
                "text": ("история этого дерева ОБРЕЗАНА "
                         f"({prov.get('commits_total')} коммит(ов)) — дата "
                         "рождения константы НЕ ИЗМЕРЕНА, а не «отсутствует»")})
    if zero.get("measured") and zero.get("collides"):
        out.append({
            "severity": "critical",
            "code": "zero_price_is_read_as_absent_price",
            "text": (
                "у судьи «цена измерена и равна нулю» и «цену не записали» — одна "
                f"ветка: при нулевой цене лучший счёт ${zero['best_net_usd_zero']:,.2f}, "
                f"а при цене в ОДИН ЦЕНТ ${zero['best_net_usd_one_cent']:,.2f}. "
                "Бесплатный ход оценивается ДОРОЖЕ дешёвого (инв. #17)")})
    if cf.get("measured") is False and cf.get("wiring_alive") is False:
        out.append({
            "severity": "warning",
            "code": "counterfactual_refused",
            "text": f"контрфакт СНЯТ с публикации: {cf.get('reason')}"})
    if cf.get("measured") and cf.get("wiring_alive"):
        if cf["act_days_returned_max"] == 0:
            out.append({
                "severity": "warning",
                "code": "relief_changes_no_act_day",
                "text": (
                    f"послабление в ${cf['relief_usd_max']:,.2f} не вернуло "
                    "критерию НИ ОДНОГО ACT-дня — счёт за несуществующий своп "
                    "реален, но знак критерия держит не он")})
        else:
            out.append({
                "severity": "critical",
                "code": "act_days_returned_by_removing_phantom_slippage",
                "text": (
                    f"снятие проскальзывания с долларов, не менявших актива, "
                    f"возвращает критерию от {cf['act_days_returned_min']} до "
                    f"{cf['act_days_returned_max']} ACT-дн.")})
    return out


def _headline(ex: dict, prov: dict, cf: dict) -> str:
    tot = ex.get("totals_all_measured_days")
    if not tot:
        return ("НЕ ИЗМЕРЕНО: ни одного дня с записанными ногами и известным "
                "активом — существование свопа проверять не на чем")
    strict = ex.get("totals_strict_days")
    head = (f"из ${tot['flow_usd']:,.2f} потока на {tot['days']} дн. свопа "
            f"требует от {100 * tot['swap_share_min']:.2f} % до "
            f"{100 * tot['swap_share_max']:.2f} %; остальное — вывод и внесение "
            "ОДНОГО актива, за которые начислено проскальзывание")
    if strict:
        head += (f" · на {strict['days']} дн. с полностью известным активом ответ "
                 f"ТОЧЕН: {100 * strict['swap_share_min']:.2f} %")
    if cf.get("measured"):
        head += (f" · ACT-дней возвращается {cf['act_days_returned_min']}"
                 f"…{cf['act_days_returned_max']}")
    if prov.get("measured") and prov.get("constants_without_any_citation"):
        head += (" · провенанса у константы нет ни одного признака")
    return head


def format_report(doc: dict) -> List[str]:
    lines = [f"[ОТВЕТ] {doc.get('headline')}"]
    ex = doc.get("existence") or {}
    for row in ex.get("per_day") or []:
        if row.get("measured"):
            mark = "точно" if row.get("exact") else "границы"
            lines.append(
                f"[ПО ДНЯМ] {row['date']}: поток ${row['flow_usd']:,.2f}, своп "
                f"${row['swap_usd_min']:,.2f}…${row['swap_usd_max']:,.2f} ({mark})"
                f" · отдано {row['assets_out']} · принято {row['assets_in']}")
        else:
            lines.append(f"[ПО ДНЯМ] {row['date']}: НЕ ИЗМЕРЕНО — {row.get('reason')}")
    for key, dates in (ex.get("blocking_keys") or {}).items():
        lines.append(f"[СЛЕПАЯ НОГА] `{key}` — актив не объявлен ни одной дорогой, "
                     f"дн.: {', '.join(dates)}")
    prov = doc.get("provenance") or {}
    if prov.get("measured"):
        for e in prov.get("constants") or []:
            hist = (f"первый коммит {e.get('first_commit')} "
                    f"({e.get('first_commit_date')})" if e.get("history_measured")
                    else f"история НЕ ИЗМЕРЕНА — {e.get('history_reason')}")
            lines.append(
                f"[ПРОВЕНАНС] {e['constant']}: ссылок в строке "
                f"{'ЕСТЬ' if e.get('line_cites_a_source') else 'НЕТ'}, "
                f"ADR называют {e.get('adr_count')}; {hist}")
    else:
        lines.append(f"[ПРОВЕНАНС] НЕ ИЗМЕРЕНО — {prov.get('reason')}")
    zero = doc.get("zero_is_absent") or {}
    if zero.get("measured"):
        lines.append(
            f"[НОЛЬ ПРОТИВ ОТСУТСТВИЯ] лучший счёт: как записано "
            f"${zero['best_net_usd_as_is']:,.2f} · цена ноль "
            f"${zero['best_net_usd_zero']:,.2f} · цена цент "
            f"${zero['best_net_usd_one_cent']:,.2f} ⇒ ветки "
            f"{'СЛИТЫ' if zero.get('collides') else 'различимы'}")
    cf = observed(doc, "counterfactual", kind=dict)
    if cf is None:
        lines.append("[КОНТРФАКТ] НЕ ИЗМЕРЕНО — секции нет в замере")
    elif cf.get("measured"):
        lines.append(
            f"[КОНТРФАКТ] ACT-дней: как записано {cf['act_days_as_is']} → "
            f"{cf['act_days_swap_only_least']}…{cf['act_days_swap_only_most']} "
            f"при послаблении ${cf['relief_usd_min']:,.2f}…"
            f"${cf['relief_usd_max']:,.2f}; лучший счёт "
            f"${cf['best_net_usd_as_is']:,.2f} → ${cf['best_net_usd_least']:,.2f}"
            f"…${cf['best_net_usd_most']:,.2f}; пересчитано дн. "
            f"{cf['days_repriced']}, не тронуто {cf['days_untouched']}")
        if cf.get("days_refused_zero_price"):
            lines.append("[КОНТРФАКТ] цена НЕ обнулена на дн.: "
                         + ", ".join(cf["days_refused_zero_price"])
                         + " — записанный ноль судья прочёл бы как отсутствие")
    else:
        lines.append(f"[КОНТРФАКТ] НЕ ИЗМЕРЕНО — {cf.get('reason')}")
    for f in doc.get("findings") or []:
        lines.append(f"[{f['severity'].upper()}] {f['text']}")
    lines.append("НЕ ДОКЛАДЫВАЕТ: " + " · ".join(doc.get("what_it_does_not_prove") or []))
    lines.append("ADVISORY: константы стоимости, оценщик цены, писатель журнала, "
                 "пороги RiskPolicy v1.0, стоп-кран и живой трек НЕ трогаются — "
                 "прибор только спрашивает, была ли операция, за которую платят")
    return lines


def _unmeasured(now: datetime, reason: str, context: Optional[dict] = None) -> dict:
    return {
        "version": VERSION, "generated_at": now.isoformat(),
        "status": STATUS_UNMEASURED, "mode": "ADVISORY", "order": ORDER,
        "headline": f"НЕ ИЗМЕРЕНО: {reason}", "unmeasured_reason": reason,
        "journal": context or {}, "existence": {}, "provenance": {},
        "counterfactual": {}, "zero_is_absent": {}, "findings": [],
        "what_it_does_not_prove": [
            "«не измерено» не есть «своп был» и не есть «свопа не было»"],
    }


def measure(data_dir: Path, *, now: Optional[datetime] = None,
            repo: Optional[Path] = None, with_counterfactual: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    repo = Path(repo) if repo else Path(__file__).resolve().parents[2]
    csp = _neighbour()
    gates = csp._gate_names()

    try:
        days, ctx = csp.scorable_days(data_dir)
        ste = _judge()
        history, _bad = ste.load_history(data_dir)
        rows = {str(r.get("cycle_date")): r for r in history}
    except Exception as exc:  # noqa: BLE001 — третий исход, а не ноль
        return _unmeasured(now, f"судья не отвечает на этом каталоге: {exc}")

    if not days:
        return _unmeasured(
            now, ("в журнале нет НИ ОДНОГО дня, который критерий №3 считает — "
                  "существование свопа проверять не на чем"), context=ctx)

    assets, asset_ctx = asset_map()
    if not asset_ctx.get("measured"):
        return _unmeasured(now, str(asset_ctx.get("reason")), context=ctx)
    cash, cash_source = cash_asset(data_dir)
    slip = _slippage_bps()
    ex = existence(days, rows, assets, cash)
    prov = provenance(repo)
    if with_counterfactual:
        cf = counterfactual(data_dir, ex, horizon_days=int(ctx["horizon_days"]),
                            gates=gates, slippage_bps=slip)
        zero = zero_is_absent(data_dir, horizon_days=int(ctx["horizon_days"]),
                              gates=gates)
    else:
        cf = {"measured": False, "reason": "--no-counterfactual"}
        zero = {"measured": False, "reason": "--no-counterfactual"}

    findings = _findings(ex, prov, cf, zero)
    status = (STATUS_CRITICAL if any(f["severity"] == "critical" for f in findings)
              else (STATUS_WARNING if findings else STATUS_OK))
    return {
        "version": VERSION,
        "generated_at": now.isoformat(),
        "status": status,
        "mode": "ADVISORY",
        "order": ORDER,
        "headline": _headline(ex, prov, cf),
        "journal": ctx,
        "slippage_bps_constant": slip,
        "cash_asset": cash,
        "cash_asset_source": cash_source,
        "asset_resolution": asset_ctx,
        "existence": ex,
        "provenance": prov,
        "counterfactual": cf,
        "zero_is_absent": zero,
        "findings": findings,
        "what_it_does_not_prove": [
            "не утверждает, что константу следует понизить или убрать: константы "
            "стоимости — вход денежного пути и предмет №1 границы ADR-285",
            "не измеряет РЫНОЧНУЮ цену перекладки: на бумажной стадии исполнения "
            "нет, наблюдать было нечего",
            "не утверждает, что вывод-внесение бесплатны: у них есть газ, и газ "
            "прибор не трогает",
            "ничего не говорит о днях без записанных ног (до 2026-09-01 писатель "
            "`legs` не писал вовсе) и о том, верен ли был сам ход",
            "не сводит актив по виду имени: ключ, не разрешённый ни одной дорогой, "
            "остаётся неизвестным и расширяет границы, а не подставляется",
        ],
    }


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, with_counterfactual: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, repo=base,
                  with_counterfactual=with_counterfactual)
    if write:
        atomic_save(doc, str(base / "data" / OUTPUT_FILENAME))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", help="каталог данных (умолчание — data/ репозитория)")
    ap.add_argument("--repo", help="дерево для археологии константы (умолчание — своё)")
    ap.add_argument("--json", action="store_true", help="печатать замер как JSON")
    ap.add_argument("--no-counterfactual", action="store_true",
                    help="не считать контрфакт (быстро, но ответ НЕПОЛОН)")
    ap.add_argument("--no-write", action="store_true", help="не писать артефакт")
    args = ap.parse_args(argv)

    if args.data_dir:
        doc = measure(Path(args.data_dir),
                      repo=Path(args.repo) if args.repo else None,
                      with_counterfactual=not args.no_counterfactual)
        if not args.no_write:
            atomic_save(doc, str(Path(args.data_dir) / OUTPUT_FILENAME))
    elif args.repo:
        doc = measure(Path(__file__).resolve().parents[2] / "data",
                      repo=Path(args.repo),
                      with_counterfactual=not args.no_counterfactual)
        if not args.no_write:
            atomic_save(doc, str(Path(__file__).resolve().parents[2] / "data"
                                 / OUTPUT_FILENAME))
    else:
        doc = run(write=not args.no_write,
                  with_counterfactual=not args.no_counterfactual)

    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n".join(format_report(doc)))
    return {STATUS_OK: 0, STATUS_WARNING: 0,
            STATUS_CRITICAL: 1}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
