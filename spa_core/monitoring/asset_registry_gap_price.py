"""Цена ДВУХ разрывов: ключ без актива и ноль, неотличимый от отсутствия (заказ #610/G23).

Заказ, оставленный в хвосте [ADR-390] по стоячему приказу владельца «Portfolio
CIO», поставлен дословно так:

> **(а) сколько ещё оборота ослеплено ОДНИМ ключом, и почему он не в реестре
> активов?** ``morpho_blue_base`` раздвигает границы на 4 дня из 7. Вопрос не в
> том, чтобы вписать ему актив руками — это была бы догадка того же рода, — а в
> том, ПОЧЕМУ канонический реестр (36 ключей) и реестр активов (22) разошлись на
> 14 ключей и какие из этих 14 встречаются в книге. Измерить по исходу:
> пересечение «ключи, появлявшиеся в ``legs`` за всё окно журнала» × «ключи без
> актива», в долларах оборота. […]
>
> **(б) и в той же валюте — чем ещё судья не отличает ноль от отсутствия.**
> Находка про ``cost_rec > 0.0`` найдена случайно, контролем. Это класс, а не
> случай […] Измерить перебором: для КАЖДОГО числового поля, которое читает
> ``shadow_trigger_eval``, прогнать пару «поле = 0» против «поля нет» на копии
> каталога и сравнить вердикт. Поля, у которых вердикты совпали, и есть
> население класса; сегодня их число неизвестно, а инвариант #17 требует, чтобы
> оно было нулём.

## (а) «Почему разошлись» — это вопрос о ПИСАТЕЛЕ, а не о ключе

Соблазн ответа — перечислить 14 ключей и назвать их «недооформленными». Но у
разрыва есть измеримая причина, и она не в ключах: реестр активов
(``spa_core/adapters/registry.py``) и канонический реестр
(``spa_core/adapters/__init__.py``) — ДВА файла с разной историей. Прибор
спрашивает у истории репозитория, когда каждый из них менялся содержательно, и
печатает **дату последнего изменения состава** у обоих. Если у одного писатель
замолчал, а у другого нет, «разошлись» перестаёт быть свойством ключей и
становится свойством сопровождения — и чинить надо не ключ.

История обязана быть ПОЛНОЙ: на обрезанном клоне (прод-дерево — 443 коммита
против 26 889 в зеркале) ``git log`` назвал бы первым тот коммит, что просто
оказался первым в обрезке. Глубина меряется, и мелкий клон уводит секцию в
``unmeasured`` с названной причиной, а не в чужую дату (урок [ADR-390]).

## (а) Актив ключа берётся тождеством КОДА — прибор не разрешает имена сам

Карту активов даёт сосед ``swap_existence_price.asset_map`` (две независимые
дороги: совпадение ``(module, class)`` с ``ADAPTER_METADATA`` и атрибут класса
``ASSET``). Второй реализации здесь нет НАМЕРЕННО: два ответа об одном активе,
расходящиеся между собой, были бы дефектом, который прибор же и создал бы.

## (б) «Вердикт» у судьи ДВУХЭТАЖНЫЙ, и сравнивать надо оба этажа

Заказ говорит «сравнить вердикт». У ``shadow_trigger_eval`` их два, и они не
сводятся друг к другу:

* **дневной** — исход дня (``outcome``, ``counterfactual``, ``trivial``,
  ``material``, ``unchecked_reason``, ``net_usd``);
* **итоговый** — тот, что читает владелец (``status``, ``ready_to_arm``,
  ``hit_rate``, ``net_usd_if_followed``, ``net_bps_if_followed``, статусы
  критериев взвода).

Поле может не двигать НИ ОДНОГО дня и при этом решать итог: так устроен
``capital_usd`` — он не входит в дневной счёт вовсе, а делит итоговый
``net_bps_if_followed``. Сравнивать только дневной этаж значило бы объявить его
непрочитанным.

## (б) Три исхода, а не два: «совпали» ещё не есть дефект

Заказ просит население «полей, у которых вердикты совпали». Прямое прочтение
даёт ложное население: ``gain_pp`` судья только ПЕРЕПИСЫВАЕТ в отчёт и в счёт
не берёт, поэтому у него вердикты совпадут при любой паре — и назвать это
дефектом ветки значило бы обвинить код, который поля не читает. Поэтому у
каждого поля меряется ещё и **чувствительность**: двигает ли вердикт ХОТЬ КАКОЕ
значение этого поля. Исходов три:

============================  ===============================================
``conflated``                 вердикты совпали И поле вердикт двигает ⇒
                              население класса, инв. #17 требует нуля
``distinguishes``             вердикты разошлись ⇒ поле различает
``not_decisive``              вердикты совпали И ни одно значение вердикт не
                              двинуло ⇒ **не измерено на этой истории**, а не
                              «чисто»
============================  ===============================================

Третий исход — не украшение: он честно говорит, что про поле, которого решение
сегодня не касается, замер ответа НЕ ДАЛ. Выдать его за «различает» значило бы
записать неизмеренное в благополучие, то есть совершить ровно ту подмену, о
которой весь заказ.

## (б) Крупность координаты: контейнер спрашивается ПОЛИСТНО

``current_positions``, ``target_positions`` и ``apy_evidenced_pct`` — словари
чисел. Пара «поле = 0 против поля нет» на ЦЕЛОМ словаре отвечает не на тот
вопрос: у ``target_positions`` пустой словарь ловится отдельной защитой
(«книга без цели — дыра в данных, а не предложение всё продать»), поэтому на
уровне словаря поле «различает», а на уровне КЛЮЧА защиты нет ни одной. Поэтому
координата — лист, а не контейнер; и это расширение заказа, названное вслух.

## (б) Третье значение пары: ``null``

Заказ называет пару «0 против отсутствия». У JSON есть третье представление —
``null``, и по инв. #17 именно оно означает «не наблюдалось». Прибор меряет все
три и печатает их рядом: у позиций ``0``, ``null`` и «ключа нет» оказываются
ОДНИМ, и решающим здесь является ``null``, потому что ноль и отсутствие ключа в
книге позиций и правда значат одно («не держим»), а ``null`` значит «не
измерили». Мерить только заказанную пару значило бы пройти мимо единственного
представления, ради которого инвариант написан.

## Латентность меряется У ВЕТКИ, а не в файле

«Сколько раз ноль встретился в журнале» — не тот вопрос: у ``cost_usd`` нулей
пятнадцать, и НИ ОДИН не доходит до сливающей ветки, потому что все они стоят на
днях без хода, а ветка цены живёт за проверкой существенности. Поэтому прибор
считает вхождения, ДОШЕДШИЕ до решения, и печатает оба числа рядом — иначе
латентный дефект выглядел бы живым, а живой латентным.

ADVISORY, только чтение. Живой каталог данных не открывается на запись ни разу:
пары идут во временной копии тех файлов, которые судья читает.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT = "asset_registry_gap_price.json"
VERSION = "asset-registry-gap-price-v1"

#: Файлы, которые читает судья. Копируются в песочницу; больше ничего.
JUDGE_INPUTS = ("allocation_rationale_history.jsonl", "equity_curve_daily.json")

#: Поля дневного исхода — первый этаж вердикта.
DAY_VERDICT_FIELDS = ("outcome", "counterfactual", "trivial", "material",
                      "unchecked_reason", "net_usd")

#: Канонический реестр и реестр активов — два РАЗНЫХ файла, и вопрос (а) о том,
#: почему их состав разошёлся, есть вопрос об их писателях.
CANONICAL_REGISTRY_FILE = "spa_core/adapters/__init__.py"
ASSET_REGISTRY_FILE = "spa_core/adapters/registry.py"

#: Ниже этой глубины клона археология ОТКАЗЫВАЕТ (урок ADR-390: на обрезке
#: `git log` называет первым тот коммит, что просто оказался первым в обрезке).
MIN_CLONE_DEPTH = 5_000

#: Малая проба чувствительности. Большая берётся ИЗ ДАННЫХ (см. `_probe_values`),
#: а не выдумывается: «миллион» на поле, чьи значения живут в сотнях, доказывал
#: бы чувствительность к невозможному значению.
SMALL_PROBE = 1.0
LARGE_PROBE_FACTOR = 10.0
FALLBACK_LARGE_PROBE = 1_000.0

CRITICAL, WARNING, OK, UNMEASURED = "CRITICAL", "WARNING", "OK", "UNMEASURED"


# ── (а) Разрыв реестров ───────────────────────────────────────────────────────

def _git(repo: Path, *args: str) -> Tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or "").strip()
    except Exception as exc:  # noqa: BLE001 — причина, а не пустая строка
        return 127, f"{type(exc).__name__}: {exc}"


def _clone_depth(repo: Path) -> Optional[int]:
    code, out = _git(repo, "rev-list", "--count", "HEAD")
    if code != 0:
        return None
    try:
        return int(out)
    except ValueError:
        return None


def _symbol_size(tree: ast.Module, symbol: str) -> Optional[Tuple[int, int]]:
    """``(литерал, дописано вызовами)`` — или ``None``, если символа в модуле нет.

    Два слагаемых, а не одно, НАМЕРЕННО. Канонический реестр растёт двумя
    путями: литералом и условными ``ADAPTER_REGISTRY.append(...)`` за
    ``try/except ImportError``. Считать только литерал значило бы объявить
    реестр меньше, чем он есть (замер: 28 против 36), а сложить их молча —
    потерять ровно то различие, из которого и следует ответ «почему разошлись»:
    у второго пути нет двойника в реестре активов.

    Аннотированное присваивание (``X: Dict[...] = {...}``) — ТОЖЕ определение;
    первая редакция этого разбора знала только ``ast.Assign`` и потому не нашла
    ``ADAPTER_METADATA`` ни на одном коммите, выдав «состав не измерен» там, где
    состав есть.
    """
    literal: Optional[int] = None
    for node in ast.walk(tree):
        target_names: List[str] = []
        value = None
        if isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
            value = node.value
        if symbol not in target_names or value is None:
            continue
        if isinstance(value, ast.Dict):
            literal = len(value.keys)
        elif isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            literal = len(value.elts)
    if literal is None:
        return None
    appended = 0
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "extend")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == symbol):
            appended += 1
    return literal, appended


def _composition_at(repo: Path, sha: str, rel: str,
                    symbols: Sequence[str]) -> Optional[dict]:
    """Размер реестра НА ЭТОМ коммите — разбором AST, без исполнения старого кода.

    Имён несколько, потому что символ переименовывали: до цикла #275 реестр
    активов звался ``ADAPTER_REGISTRY`` в том же файле. Спрашивать только
    нынешнее имя значило бы объявить всю историю до переименования пустой.
    """
    code, text = _git(repo, "show", f"{sha}:{rel}")
    if code != 0 or not text:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    for symbol in symbols:
        size = _symbol_size(tree, symbol)
        if size is not None:
            return {"symbol": symbol, "literal": size[0], "appended": size[1],
                    "entries": size[0] + size[1]}
    return None


def composition_history(repo: Path, rel: str, symbols: Sequence[str]) -> dict:
    """Когда состав реестра менялся В ПОСЛЕДНИЙ РАЗ — по РАЗМЕРУ, а не по касанию.

    «Файл менялся 17.08» на вопрос не отвечает: тот коммит переименовал символ и
    состава не тронул (``ADAPTER_REGISTRY`` → ``ADAPTER_METADATA``, цикл #275).
    Спрашивать надо у РАЗМЕРА реестра на каждом коммите, иначе переименование
    читалось бы как живой писатель, и вывод получился бы обратный истине.
    """
    code, log = _git(repo, "log", "--format=%h %ad", "--date=short",
                     "--reverse", "--", rel)
    if code != 0 or not log:
        return {"measured": False,
                "reason": f"git log отказал по {rel}: {log or code}"}
    series: List[dict] = []
    for line in log.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        sha, date = parts[0], parts[1]
        size = _composition_at(repo, sha, rel, symbols)
        row = {"commit": sha, "date": date}
        row.update(size or {"entries": None})
        series.append(row)
    known = [r for r in series if r.get("entries") is not None]
    if not known:
        return {"measured": False, "path": rel, "symbols": list(symbols),
                "commits": len(series),
                "reason": (f"ни одно из имён {list(symbols)} не найдено разбором "
                           f"ни на одном из {len(series)} коммитов файла — "
                           f"состав НЕ ИЗМЕРЕН")}
    last_change = known[0]
    for prev, cur in zip(known, known[1:]):
        if cur["entries"] != prev["entries"]:
            last_change = cur
    tail = known[-1]
    return {"measured": True, "path": rel, "symbols": list(symbols),
            "symbol_now": tail.get("symbol"),
            "commits_touching": len(series),
            "commits_parsed": len(known),
            "entries_now": tail["entries"],
            "literal_now": tail.get("literal"),
            "appended_now": tail.get("appended"),
            "composition_last_changed": last_change["date"],
            "composition_last_commit": last_change["commit"],
            "last_touch_date": series[-1]["date"],
            "series": series}


def registry_divergence(repo: Path) -> dict:
    """Почему составы разошлись — вопрос к ПИСАТЕЛЯМ двух файлов.

    Отказывает (``measured=False``) на мелком клоне: там ответ был бы о глубине
    обрезки, а не о писателе (урок ADR-390).
    """
    depth = _clone_depth(repo)
    if depth is None:
        return {"measured": False,
                "reason": "история репозитория не читается (git не ответил)"}
    if depth < MIN_CLONE_DEPTH:
        return {"measured": False, "clone_depth": depth,
                "reason": (f"клон обрезан ({depth} коммитов < {MIN_CLONE_DEPTH}): "
                           "первая и последняя даты были бы о глубине обрезки, "
                           "а не о писателе — см. ADR-390")}
    out: Dict[str, Any] = {
        "measured": True, "clone_depth": depth,
        "files": {
            "canonical": composition_history(repo, CANONICAL_REGISTRY_FILE,
                                             ("ADAPTER_REGISTRY",)),
            # Имя реестра активов менялось: до цикла #275 он звался
            # ADAPTER_REGISTRY в СВОЁМ файле. Оба имени спрашиваются по порядку.
            "assets": composition_history(repo, ASSET_REGISTRY_FILE,
                                          ("ADAPTER_METADATA",
                                           "ADAPTER_REGISTRY")),
        }}
    a, c = out["files"]["assets"], out["files"]["canonical"]
    if a.get("measured") and c.get("measured"):
        out["assets_composition_frozen_since"] = a["composition_last_changed"]
        out["canonical_composition_last_changed"] = c["composition_last_changed"]
        # Утверждение «писатель замолчал» держится на СРАВНЕНИИ двух дат состава,
        # а не на возрасте одной: законченный реестр выглядел бы так же.
        out["assets_writer_silent"] = bool(
            a["composition_last_changed"] < c["composition_last_changed"])
        out["entries_gap"] = (None if a["entries_now"] is None
                              or c["entries_now"] is None
                              else c["entries_now"] - a["entries_now"])
    return out


def entry_path_of_keys(repo: Path) -> dict:
    """Каким ПУТЁМ ключ попадает в канонический реестр: литералом или дописью.

    Это и есть структурный ответ на «почему разошлись». У канонического реестра
    ДВА пути роста — литерал и условная ``ADAPTER_REGISTRY.append(...)`` за
    ``try/except ImportError``, — а у реестра активов только литерал. Второй
    путь двойника не имеет ни одного, поэтому ключ, пришедший им, в реестр
    активов не попадает НИКОГДА: не по недосмотру автора, а потому, что писать
    его туда нечему.

    Разбор идёт по AST файла, а не по виду имени ключа.
    """
    path = Path(repo) / CANONICAL_REGISTRY_FILE
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return {"measured": False,
                "reason": f"канонический реестр не разобран: {exc}"}

    def first_str(node: ast.AST) -> Optional[str]:
        if isinstance(node, (ast.List, ast.Tuple)) and node.elts:
            head = node.elts[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str):
                return head.value
        return None

    literal: List[str] = []
    appended: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = ([t.id for t in node.targets if isinstance(t, ast.Name)]
                     if isinstance(node, ast.Assign)
                     else ([node.target.id] if isinstance(node.target, ast.Name)
                           else []))
            if "ADAPTER_REGISTRY" in names and isinstance(node.value, ast.List):
                for elt in node.value.elts:
                    key = first_str(elt)
                    if key:
                        literal.append(key)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "extend")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "ADAPTER_REGISTRY" and node.args):
            key = first_str(node.args[0])
            if key:
                appended.append(key)
    return {"measured": True, "literal": sorted(literal),
            "appended": sorted(appended),
            "literal_count": len(literal), "appended_count": len(appended)}


def unresolved_keys(amap: Dict[str, dict]) -> Dict[str, dict]:
    """Ключи канонического реестра без актива — и ПОЧЕМУ, по каждой дороге."""
    out: Dict[str, dict] = {}
    for key, v in sorted(amap.items()):
        if v.get("state") == "resolved":
            continue
        routes = v.get("routes") or {}
        out[key] = {
            "state": v.get("state"),
            "class": v.get("class"),
            # Каждая дорога отвечает СВОЮ причину; «не разрешился» без разбора
            # дорог не сказал бы, чинить метаданные или класс.
            "road_metadata_by_class": (
                "ответила" if "metadata_by_class" in routes
                else ("класса нет в ADAPTER_METADATA ни под одним ключом"
                      if not v.get("metadata_twins")
                      else "близнецы есть, но актив у них не объявлен либо "
                           "различается")),
            "road_class_attribute": (
                "ответила" if "class_attribute" in routes
                else "класс не объявляет атрибут ASSET"),
            "metadata_twins": v.get("metadata_twins") or [],
        }
    return out


# ── (а) Оборот, ослеплённый ключом без актива ─────────────────────────────────

def _history(data_dir: Path) -> Tuple[List[dict], Optional[str]]:
    path = Path(data_dir) / JUDGE_INPUTS[0]
    if not path.exists():
        return [], f"журнала решений нет: {path}"
    recs: List[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("cycle_date"):
                recs.append(obj)
    except OSError as exc:
        return [], f"журнал решений не прочитан: {exc}"
    return recs, None


def _leg_key(leg: dict) -> Optional[str]:
    for name in ("protocol", "key", "name"):
        if leg.get(name):
            return str(leg[name])
    return None


def _leg_usd(leg: dict) -> Optional[float]:
    for name in ("delta_usd", "usd", "amount_usd"):
        if leg.get(name) is not None:
            try:
                return abs(float(leg[name]))
            except (TypeError, ValueError):
                return None
    return None


def blinded_turnover(recs: Sequence[dict], amap: Dict[str, dict]) -> dict:
    """Пересечение «ключи, бывавшие в ``legs``» × «ключи без актива», в долларах.

    Считаются ДВЕ валюты и они не складываются: доллары самих ног (сколько
    двигал ослеплённый ключ) и оборот ДНЕЙ, которых он касается (сколько ответа
    дня зависит от неразрешённого актива). Вторая всегда не меньше первой, и
    путать их значило бы занизить или завысить ответ вдвое.
    """
    days_with_legs = 0
    leg_usd_by_key: Dict[str, float] = {}
    days_by_key: Dict[str, set] = {}
    unpriced_legs = 0
    keyless_legs = 0
    total_leg_usd = 0.0
    day_turnover: Dict[str, float] = {}
    blinded_days: Dict[str, List[str]] = {}

    for rec in recs:
        legs = rec.get("legs")
        if not isinstance(legs, list) or not legs:
            continue
        days_with_legs += 1
        date = str(rec.get("cycle_date"))
        turn = rec.get("turnover_usd")
        try:
            day_turnover[date] = float(turn) if turn is not None else 0.0
        except (TypeError, ValueError):
            day_turnover[date] = 0.0
        for leg in legs:
            if not isinstance(leg, dict):
                continue
            key = _leg_key(leg)
            if key is None:
                keyless_legs += 1
                continue
            usd = _leg_usd(leg)
            if usd is None:
                unpriced_legs += 1
                continue
            leg_usd_by_key[key] = leg_usd_by_key.get(key, 0.0) + usd
            days_by_key.setdefault(key, set()).add(date)
            total_leg_usd += usd
            state = (amap.get(key) or {}).get("state")
            if state != "resolved":
                blinded_days.setdefault(date, [])
                if key not in blinded_days[date]:
                    blinded_days[date].append(key)

    in_book = sorted(leg_usd_by_key)
    blinded_keys = sorted(k for k in in_book
                          if (amap.get(k) or {}).get("state") != "resolved")
    blinded_leg_usd = sum(leg_usd_by_key[k] for k in blinded_keys)
    blinded_day_turnover = sum(day_turnover.get(d, 0.0) for d in blinded_days)
    all_day_turnover = sum(day_turnover.values())
    # Ключ книги, которого в каноническом реестре НЕТ ВОВСЕ, — отдельный исход:
    # «нет актива» и «нет записи о пуле» чинятся в разных местах.
    outside_registry = sorted(k for k in in_book if k not in amap)
    return {
        "measured": True,
        "days_with_legs": days_with_legs,
        "book_keys": in_book,
        "book_keys_count": len(in_book),
        "blinded_keys": blinded_keys,
        "blinded_keys_count": len(blinded_keys),
        "outside_canonical_registry": outside_registry,
        "leg_usd_total": round(total_leg_usd, 2),
        "leg_usd_blinded": round(blinded_leg_usd, 2),
        "leg_usd_blinded_share": (round(blinded_leg_usd / total_leg_usd, 6)
                                  if total_leg_usd else None),
        "day_turnover_total": round(all_day_turnover, 2),
        "day_turnover_touched_by_blinded": round(blinded_day_turnover, 2),
        "day_turnover_blinded_share": (round(blinded_day_turnover / all_day_turnover, 6)
                                       if all_day_turnover else None),
        "blinded_days": {d: sorted(v) for d, v in sorted(blinded_days.items())},
        "per_key_usd": {k: round(leg_usd_by_key[k], 2) for k in in_book},
        "per_key_days": {k: len(days_by_key[k]) for k in in_book},
        "legs_without_key": keyless_legs,
        "legs_without_amount": unpriced_legs,
    }


# ── (б) Население полей — из КОДА судьи, а не из головы ───────────────────────

def judge_record_keys(module_path: Path) -> Tuple[List[str], Optional[str]]:
    """Строковые ключи, которые код судьи снимает с СЛОВАРЯ, — обходом AST.

    Список сознательно ШИРОК: сюда попадают и ключи собственного отчёта судьи.
    Сужает его не догадка о роли переменной, а ЗАМЕР — пересечение с ключами,
    реально встречающимися в журнале решений (см. :func:`numeric_fields`).
    """
    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return [], f"модуль судьи не разобран: {exc}"
    keys: set = set()

    class V(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "get"
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
            # `observed(rec, "x", ...)` — честная форма чтения (инв. #17);
            # пропустить её значило бы потерять ровно те поля, что уже сделаны
            # правильно, и объявить класс шире, чем он есть.
            if (isinstance(fn, ast.Name) and fn.id == "observed"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and isinstance(node.args[1].value, str)):
                keys.add(node.args[1].value)
            self.generic_visit(node)

        def visit_Subscript(self, node: ast.Subscript) -> None:
            if (isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                keys.add(node.slice.value)
            self.generic_visit(node)

    V().visit(tree)
    return sorted(keys), None


def numeric_fields(recs: Sequence[dict], code_keys: Sequence[str]) -> dict:
    """Читаемые судьёй ключи, которые в журнале НЕСУТ ЧИСЛО.

    Род поля берётся у записи, а не у имени: скаляр-число ⇒ координата сам
    ключ; словарь чисел ⇒ координата ЛИСТ (см. шапку модуля).
    """
    scalars: Dict[str, int] = {}
    containers: Dict[str, Dict[str, int]] = {}
    non_numeric: Dict[str, str] = {}
    code = set(code_keys)
    for rec in recs:
        for key, val in rec.items():
            if key not in code:
                continue
            if isinstance(val, bool):
                non_numeric.setdefault(key, "булево")
                continue
            if isinstance(val, (int, float)):
                scalars[key] = scalars.get(key, 0) + 1
            elif isinstance(val, dict):
                leafs = {k: v for k, v in val.items()
                         if isinstance(v, (int, float)) and not isinstance(v, bool)}
                if leafs:
                    slot = containers.setdefault(key, {})
                    for k in leafs:
                        slot[k] = slot.get(k, 0) + 1
                elif val:
                    non_numeric.setdefault(key, "словарь не чисел")
            elif val is not None:
                non_numeric.setdefault(key, type(val).__name__)
    # Поля, которые судья читает у ФОРВАРДНОЙ записи, живут там же (та же схема
    # строки), поэтому отдельного обхода не нужно — но сказать это надо вслух,
    # иначе читатель решит, что forward-поля потеряны.
    return {"scalars": dict(sorted(scalars.items())),
            "containers": {k: dict(sorted(v.items()))
                           for k, v in sorted(containers.items())},
            "read_but_not_numeric": dict(sorted(non_numeric.items())),
            "code_keys_count": len(code)}


# ── (б) Пара «ноль против отсутствия» на копии каталога ───────────────────────

def _sandbox(src: Path, mutate) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="asset_gap_"))
    for name in JUDGE_INPUTS:
        source = Path(src) / name
        if source.exists():
            shutil.copy2(source, tmp / name)
    history = tmp / JUDGE_INPUTS[0]
    if history.exists() and mutate is not None:
        out: List[str] = []
        for line in history.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                out.append(line)      # порченую строку не «чиним»
                continue
            mutate(rec)
            out.append(json.dumps(rec, ensure_ascii=False))
        history.write_text("\n".join(out) + "\n", encoding="utf-8")
    return tmp


def _verdict(data_dir: Path, horizon_days: int) -> Tuple[Any, Any]:
    from spa_core.paper_trading import shadow_trigger_eval as ste
    doc = ste.evaluate_window(data_dir, horizon_days=horizon_days, write=False)
    rows = doc.get("per_verdict") or []
    day = tuple(tuple(r.get(f) for f in DAY_VERDICT_FIELDS) for r in rows)
    top = (doc.get("status"), doc.get("ready_to_arm"), doc.get("hit_rate"),
           doc.get("net_usd_if_followed"), doc.get("net_bps_if_followed"),
           doc.get("hold_missed_usd_total"),
           tuple((c.get("criterion"), c.get("status"), c.get("actual"))
                 for c in doc.get("criteria") or []))
    return day, top


def _run_variant(data_dir: Path, mutate, horizon_days: int) -> Tuple[Any, Any]:
    tmp = _sandbox(Path(data_dir), mutate)
    try:
        return _verdict(tmp, horizon_days)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _scalar_mutators(field: str):
    def to(val):
        def m(rec: dict) -> None:
            rec[field] = val
        return m

    def drop(rec: dict) -> None:
        rec.pop(field, None)
    return to, drop


def _leaf_mutators(field: str, leaf: str):
    def to(val):
        def m(rec: dict) -> None:
            d = rec.get(field)
            if isinstance(d, dict) and leaf in d:
                d[leaf] = val
        return m

    def drop(rec: dict) -> None:
        d = rec.get(field)
        if isinstance(d, dict):
            d.pop(leaf, None)
    return to, drop


def _probe_values(recs: Sequence[dict], field: str,
                  leaf: Optional[str]) -> List[float]:
    """Пробы чувствительности: малая и БОЛЬШАЯ, выведенная из самих данных.

    Большая проба, взятая с потолка, доказывала бы чувствительность к значению,
    которого в этой величине быть не может, — и молча завышала бы население
    класса ``conflated`` за счёт ``not_decisive``.
    """
    seen: List[float] = []
    for rec in recs:
        raw = rec.get(field)
        if leaf is not None:
            raw = raw.get(leaf) if isinstance(raw, dict) else None
        if isinstance(raw, bool) or raw is None:
            continue
        if isinstance(raw, (int, float)):
            seen.append(abs(float(raw)))
    top = max(seen) if seen else None
    large = (top * LARGE_PROBE_FACTOR if top else FALLBACK_LARGE_PROBE)
    if large <= SMALL_PROBE:
        large = FALLBACK_LARGE_PROBE
    return [SMALL_PROBE, round(large, 6)]


def _classify(base: Tuple[Any, Any], zero: Tuple[Any, Any], absent: Tuple[Any, Any],
              null: Tuple[Any, Any], probes: Sequence[Tuple[Any, Any]]) -> dict:
    sensitive = any(p != zero for p in probes)
    same_zero_absent = zero == absent
    if not same_zero_absent:
        state = "distinguishes"
    elif sensitive:
        state = "conflated"
    else:
        state = "not_decisive"
    return {
        "state": state,
        "zero_equals_absent": same_zero_absent,
        "null_equals_absent": null == absent,
        "zero_equals_null": zero == null,
        "sensitive": sensitive,
        "day_verdict_moved_by_zero": zero[0] != base[0],
        "top_verdict_moved_by_zero": zero[1] != base[1],
    }


def zero_vs_absent_census(data_dir: Path, recs: Sequence[dict], fields: dict,
                          *, horizon_days: int) -> dict:
    """Перебор заказа: пара «поле = 0» против «поля нет» по КАЖДОМУ числовому полю."""
    base = _run_variant(Path(data_dir), None, horizon_days)
    rows: List[dict] = []

    def one(field: str, leaf: Optional[str]) -> dict:
        to, drop = (_leaf_mutators(field, leaf) if leaf is not None
                    else _scalar_mutators(field))
        zero = _run_variant(Path(data_dir), to(0.0), horizon_days)
        absent = _run_variant(Path(data_dir), drop, horizon_days)
        null = _run_variant(Path(data_dir), to(None), horizon_days)
        probe_vals = _probe_values(recs, field, leaf)
        probes = [_run_variant(Path(data_dir), to(v), horizon_days)
                  for v in probe_vals]
        row = {"field": field, "leaf": leaf,
               "coordinate": field if leaf is None else f"{field}[{leaf}]",
               "probe_values": probe_vals}
        row.update(_classify(base, zero, absent, null, probes))
        return row

    for field in fields.get("scalars", {}):
        rows.append(one(field, None))
    for field, leafs in (fields.get("containers") or {}).items():
        for leaf in leafs:
            rows.append(one(field, leaf))

    by_state: Dict[str, List[str]] = {}
    for r in rows:
        by_state.setdefault(r["state"], []).append(r["coordinate"])
    return {"measured": True, "rows": rows,
            "counts": {k: len(v) for k, v in sorted(by_state.items())},
            "conflated": sorted(by_state.get("conflated", [])),
            "distinguishes": sorted(by_state.get("distinguishes", [])),
            "not_decisive": sorted(by_state.get("not_decisive", [])),
            # `null` — единственное представление «не наблюдалось» (инв. #17),
            # и его слияние с отсутствием ключа считается ОТДЕЛЬНО от заказанной
            # пары: у позиций ноль и отсутствие значат одно честно, а `null` нет.
            "null_collapsed": sorted(r["coordinate"] for r in rows
                                     if r["null_equals_absent"] and r["sensitive"]),
            "horizon_days": horizon_days}


# ── Латентность: вхождения, ДОШЕДШИЕ до решения ───────────────────────────────

def occurrence_at_branch(data_dir: Path, recs: Sequence[dict], census: dict,
                         *, horizon_days: int) -> dict:
    """Сколько раз сливающее значение ДОШЛО ДО РЕШЕНИЯ — и что им считается.

    Две поправки, без которых число врёт в разные стороны:

    **Вхождения считаются у ветки, а не в файле.** У ``cost_usd`` нулей
    пятнадцать, и ни один не доходит до сливающей ветки: все они стоят на днях
    без хода, а ветка цены живёт за проверкой существенности.

    **«Ключа нет» — вхождение только у СКАЛЯРА.** В книге позиций отсутствие
    ключа значит «не держим» — законное наблюдение, а не пробел; считать его
    сливающим значило бы объявить живым весь класс (замер: 40 «вхождений» у
    ``target_positions[aave_v3_base]``, и все сорок — просто дни, когда ключа в
    книге не было). У листа контейнера сливающим считается ``null`` —
    единственное представление «не наблюдалось» (инв. #17), — и ОТДЕЛЬНО
    печатается явный ноль.
    """
    from spa_core.paper_trading import shadow_trigger_eval as ste
    try:
        doc = ste.evaluate_window(Path(data_dir), horizon_days=horizon_days,
                                  write=False)
    except Exception as exc:  # noqa: BLE001 — причина, а не ноль
        return {"measured": False, "reason": f"судья не отработал: {exc}"}
    material_dates = {str(r.get("cycle_date")) for r in doc.get("per_verdict") or []
                      if r.get("material")}
    rows: List[dict] = []
    MISSING = object()
    for r in census.get("rows", []):
        if r["state"] != "conflated":
            continue
        field, leaf = r["field"], r["leaf"]
        counts = {"null": 0, "zero": 0, "absent": 0}
        reached = {"null": 0, "zero": 0, "absent": 0}
        for rec in recs:
            if leaf is None:
                raw = rec.get(field, MISSING)
            else:
                container = rec.get(field)
                raw = (container.get(leaf, MISSING) if isinstance(container, dict)
                       else MISSING)
            if raw is MISSING:
                kind = "absent"
            elif raw is None:
                kind = "null"
            elif (isinstance(raw, (int, float)) and not isinstance(raw, bool)
                  and float(raw) == 0.0):
                kind = "zero"
            else:
                continue
            counts[kind] += 1
            if str(rec.get("cycle_date")) in material_dates:
                reached[kind] += 1
        # Что именно является сливающим вводом, решает РОД координаты, и правило
        # названо в теле отчёта, а не подразумевается.
        collapsing = (("null", "zero", "absent") if leaf is None
                      else ("null",))
        in_file = sum(counts[k] for k in collapsing)
        at_branch = sum(reached[k] for k in collapsing)
        rows.append({"coordinate": r["coordinate"],
                     "collapsing_kinds": list(collapsing),
                     "counts": counts, "reached": reached,
                     "in_file": in_file, "reached_decision": at_branch,
                     "latent": at_branch == 0})
    return {"measured": True, "rows": rows,
            "material_days": len(material_dates), "days_total": len(recs),
            "live_coordinates": sorted(r["coordinate"] for r in rows
                                       if not r["latent"]),
            "latent_coordinates": sorted(r["coordinate"] for r in rows
                                         if r["latent"])}


# ── Находки, заголовок, отчёт ─────────────────────────────────────────────────

def _findings(div: dict, unres: Dict[str, dict], blind: dict, census: dict,
              occ: dict) -> List[dict]:
    out: List[dict] = []
    if blind.get("measured") and blind.get("blinded_keys"):
        share = blind.get("leg_usd_blinded_share")
        out.append({
            "severity": CRITICAL,
            "code": "book_keys_without_asset",
            "message": (
                f"{blind['blinded_keys_count']} из {blind['book_keys_count']} "
                f"ключей книги не имеют актива ни по одной дороге "
                f"({', '.join(blind['blinded_keys'])}): они двигали "
                f"${blind['leg_usd_blinded']:,.2f} из ${blind['leg_usd_total']:,.2f} "
                f"потока ног"
                + (f" = {100 * share:.2f} %" if share is not None else "")
                + f", и касаются дней с оборотом "
                  f"${blind['day_turnover_touched_by_blinded']:,.2f} из "
                  f"${blind['day_turnover_total']:,.2f}. Ответ (а) ADR-390 "
                  f"занижен по построению ровно на этих долларах")})
    paths_ctx = None
    if isinstance(unres, dict):
        paths_ctx = sorted(k for k, v in unres.items()
                           if v.get("entry_path") == "append_behind_import_guard")
    if paths_ctx:
        out.append({
            "severity": WARNING,
            "code": "second_growth_path_has_no_asset_twin",
            "message": (
                f"{len(paths_ctx)} из {len(unres)} ключей без актива приходят в "
                f"канонический реестр ВТОРЫМ путём — условной "
                f"`ADAPTER_REGISTRY.append(...)` за `try/except ImportError` "
                f"({', '.join(paths_ctx)}). У реестра активов такого пути нет ни "
                f"одного, поэтому эти ключи не попадут в него никогда: разрыв "
                f"СТРУКТУРНЫЙ, а не забывчивость автора")})
    if div.get("measured") and div.get("assets_writer_silent"):
        a = div["files"]["assets"]
        c = div["files"]["canonical"]
        out.append({
            "severity": WARNING,
            "code": "asset_registry_writer_silent",
            "message": (
                f"СОСТАВ реестра активов ({ASSET_REGISTRY_FILE}) не менялся с "
                f"{a['composition_last_changed']} и стои́т на "
                f"{a['entries_now']} записях, а состав канонического "
                f"({CANONICAL_REGISTRY_FILE}) — с "
                f"{c['composition_last_changed']} при {c['entries_now']}. "
                f"«Разошлись на {len(unres)} ключей» есть свойство СОПРОВОЖДЕНИЯ, "
                f"а не ключей: у второго реестра просто нет писателя. Касание "
                f"файла на вопрос не отвечает — последнее было "
                f"{a['last_touch_date']} и состава не тронуло")})
    conflated = census.get("conflated") or []
    if conflated:
        live = (occ.get("live_coordinates") or []) if occ.get("measured") else None
        out.append({
            "severity": CRITICAL,
            "code": "judge_conflates_zero_and_absence",
            "message": (
                f"судья не отличает измеренный ноль от отсутствия на "
                f"{len(conflated)} координат(ах) из "
                f"{sum(census.get('counts', {}).values())}: "
                f"{', '.join(conflated[:8])}"
                + (" …" if len(conflated) > 8 else "")
                + f". Инвариант #17 требует НУЛЯ. "
                + ("дошли до решения: "
                   + (", ".join(live) if live else "НИ ОДНА — класс латентный")
                   if live is not None else "латентность НЕ ИЗМЕРЕНА"))})
    if census.get("not_decisive"):
        out.append({
            "severity": WARNING,
            "code": "fields_not_decisive_on_this_history",
            "message": (
                f"{len(census['not_decisive'])} координат(ы) НЕ ИЗМЕРЕНЫ: на "
                f"этой истории вердикт не двинуло ни одно их значение "
                f"({', '.join(census['not_decisive'][:8])}"
                + (" …" if len(census['not_decisive']) > 8 else "")
                + "). Это «не измерено», а не «различает»")})
    if not div.get("measured"):
        out.append({"severity": WARNING, "code": "registry_archaeology_unmeasured",
                    "message": f"разрыв реестров НЕ ИЗМЕРЕН: {div.get('reason')}"})
    return out


def _headline(blind: dict, census: dict, occ: dict) -> str:
    if not blind.get("measured"):
        return f"НЕ ИЗМЕРЕНО: {blind.get('reason')}"
    share = blind.get("leg_usd_blinded_share")
    a = (f"ослеплено ${blind['leg_usd_blinded']:,.2f} потока ног"
         + (f" ({100 * share:.2f} %)" if share is not None else "")
         + f" на {blind['blinded_keys_count']} ключ(ах) без актива")
    conf = len(census.get("conflated") or [])
    total = sum(census.get("counts", {}).values())
    b = f"судья сливает ноль с отсутствием на {conf} из {total} координат"
    if occ.get("measured"):
        b += (f" (живых {len(occ.get('live_coordinates') or [])}, "
              f"латентных {len(occ.get('latent_coordinates') or [])})")
    return f"{a}; {b}"


def _status(findings: Sequence[dict]) -> str:
    if any(f["severity"] == CRITICAL for f in findings):
        return CRITICAL
    if any(f["severity"] == WARNING for f in findings):
        return WARNING
    return OK


def format_report(doc: dict) -> List[str]:
    """Строки для шага 0-офис. Порядок строк — порядок вопроса заказа."""
    out: List[str] = []
    if doc.get("status") == UNMEASURED:
        out.append(f"   [НЕ ИЗМЕРЕНО] {doc.get('headline')}")
        return out
    # `or {}` здесь был бы ровно тем дефектом, который прибор и меряет: пустой
    # словарь вместо ненаблюдённой секции превращает «секции нет» в «measured
    # False без причины», и отчёт печатает `None` вместо названной причины.
    # Поэтому отсутствие секции несёт СВОЮ причину (инв. #17).
    def _section(key: str) -> dict:
        got = observed(doc, key, kind=dict)
        if got is None:
            return {"measured": False,
                    "reason": f"секции `{key}` нет в артефакте — НЕ ИЗМЕРЕНО"}
        return got

    blind = _section("blinded_turnover")
    census = _section("zero_vs_absent")
    occ = _section("occurrence")
    div = _section("registry_divergence")
    unres = observed(doc, "unresolved_keys", kind=dict)
    if unres is None:
        out.append("   [А/НЕ ИЗМЕРЕНО] секции `unresolved_keys` нет в артефакте")
        unres = {}

    if blind.get("measured"):
        out.append(f"   [А/ОТВЕТ] ключи книги: {blind['book_keys_count']}, "
                   f"из них без актива {blind['blinded_keys_count']} "
                   f"({', '.join(blind['blinded_keys']) or '—'}); "
                   f"поток ног ${blind['leg_usd_blinded']:,.2f} из "
                   f"${blind['leg_usd_total']:,.2f}")
        out.append(f"   [А/ОБОРОТ ДНЕЙ] дни, которых касается ослеплённый ключ, "
                   f"несут ${blind['day_turnover_touched_by_blinded']:,.2f} "
                   f"оборота из ${blind['day_turnover_total']:,.2f} "
                   f"({len(blind.get('blinded_days') or {})} дн. из "
                   f"{blind['days_with_legs']} с ногами)")
        for date, keys in (blind.get("blinded_days") or {}).items():
            out.append(f"   [А/ПО ДНЯМ] {date}: {', '.join(keys)}")
    else:
        out.append(f"   [А/НЕ ИЗМЕРЕНО] {blind.get('reason')}")

    if div.get("measured"):
        a, c = div["files"]["assets"], div["files"]["canonical"]
        out.append(f"   [А/ПОЧЕМУ] СОСТАВ реестра активов последний раз менялся "
                   f"{a.get('composition_last_changed')} "
                   f"({a.get('entries_now')} записей; файл трогали "
                   f"{a.get('last_touch_date')}), состав канонического — "
                   f"{c.get('composition_last_changed')} "
                   f"({c.get('entries_now')} записей; файл трогали "
                   f"{c.get('last_touch_date')}); разрыв "
                   f"{div.get('entries_gap')} ключ(ей), без актива {len(unres)}")
    else:
        out.append(f"   [А/ПОЧЕМУ НЕ ИЗМЕРЕНО] {div.get('reason')}")
    paths = _section("entry_paths")
    if paths.get("measured"):
        out.append(f"   [А/ПУТЬ РОСТА] в канонический реестр ключ попадает двумя "
                   f"путями: литералом {paths['literal_count']}, условной "
                   f"дописью за import-guard {paths['appended_count']}; "
                   f"без актива пришли дописью "
                   f"{len(paths.get('unresolved_via_append') or [])}, "
                   f"литералом {len(paths.get('unresolved_via_literal') or [])}. "
                   f"У реестра активов второго пути нет ни одного")
    for key, row in list(unres.items())[:4]:
        out.append(f"   [А/ДОРОГИ] {key}: метаданные — "
                   f"{row['road_metadata_by_class']}; класс — "
                   f"{row['road_class_attribute']}")

    if census.get("measured"):
        out.append(f"   [Б/ОТВЕТ] координат разобрано "
                   f"{sum(census['counts'].values())}: "
                   f"сливают ноль с отсутствием {len(census['conflated'])} · "
                   f"различают {len(census['distinguishes'])} · "
                   f"не измерено {len(census['not_decisive'])}")
        if census["conflated"]:
            out.append(f"   [Б/КЛАСС] {', '.join(census['conflated'])}")
        if census["distinguishes"]:
            out.append(f"   [Б/РАЗЛИЧАЮТ] {', '.join(census['distinguishes'])}")
        if census.get("null_collapsed"):
            out.append(f"   [Б/NULL] «не наблюдалось» неотличимо от «ключа нет» на "
                       f"{len(census['null_collapsed'])} координат(ах): "
                       f"{', '.join(census['null_collapsed'][:10])}")
    if occ.get("measured"):
        for row in occ.get("rows", []):
            out.append(f"   [Б/ЛАТЕНТНОСТЬ] {row['coordinate']}: сливающий ввод "
                       f"({'/'.join(row['collapsing_kinds'])}) в журнале "
                       f"{row['in_file']} раз, дошло до решения "
                       f"{row['reached_decision']} — "
                       f"{'ЛАТЕНТНО' if row['latent'] else 'ЖИВОЕ'}; "
                       f"рядом: null={row['counts']['null']} "
                       f"zero={row['counts']['zero']} "
                       f"absent={row['counts']['absent']}")
    for f in doc.get("findings", []):
        out.append(f"   [{f['severity']}] {f['message']}")
    out.append("   ADVISORY: пороги RiskPolicy v1.0, стоп-кран, писатель журнала, "
               "ADAPTER_METADATA, судья и живой трек НЕ трогаются — прибор только "
               "читает и называет")
    return out


# ── Сборка ────────────────────────────────────────────────────────────────────

def _unmeasured(now: datetime, reason: str, context: Optional[dict] = None) -> dict:
    return {"generated_at": now.isoformat(), "version": VERSION,
            "status": UNMEASURED, "headline": f"НЕ ИЗМЕРЕНО: {reason}",
            "reason": reason, "context": context or {},
            "findings": [{"severity": WARNING, "code": "unmeasured",
                          "message": reason}]}


def measure(data_dir: Path, *, repo: Optional[Path] = None,
            now: Optional[datetime] = None, horizon_days: int = 7) -> dict:
    now = now or datetime.now(timezone.utc)
    data_dir = Path(data_dir)
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[2]

    recs, err = _history(data_dir)
    if err or not recs:
        return _unmeasured(now, err or "журнал решений пуст",
                           {"data_dir": str(data_dir)})
    try:
        from spa_core.monitoring.swap_existence_price import asset_map
        amap, actx = asset_map()
    except Exception as exc:  # noqa: BLE001
        return _unmeasured(now, f"карта активов не построена: {exc}")
    if not actx.get("measured"):
        return _unmeasured(now, str(actx.get("reason")), {"asset_map": actx})

    div = registry_divergence(repo)
    unres = unresolved_keys(amap)
    paths = entry_path_of_keys(repo)
    if paths.get("measured"):
        appended = set(paths["appended"])
        for key, row in unres.items():
            row["entry_path"] = ("append_behind_import_guard" if key in appended
                                 else "literal")
        paths["unresolved_via_append"] = sorted(k for k in unres
                                                if k in appended)
        paths["unresolved_via_literal"] = sorted(k for k in unres
                                                 if k not in appended)
    blind = blinded_turnover(recs, amap)

    judge_module = (Path(__file__).resolve().parents[1]
                    / "paper_trading" / "shadow_trigger_eval.py")
    code_keys, kerr = judge_record_keys(judge_module)
    if kerr:
        census: dict = {"measured": False, "reason": kerr}
        fields: dict = {"measured": False, "reason": kerr}
        occ: dict = {"measured": False, "reason": kerr}
    else:
        fields = numeric_fields(recs, code_keys)
        census = zero_vs_absent_census(data_dir, recs, fields,
                                       horizon_days=horizon_days)
        occ = occurrence_at_branch(data_dir, recs, census,
                                   horizon_days=horizon_days)

    findings = _findings(div, unres, blind, census, occ)
    return {
        "generated_at": now.isoformat(),
        "version": VERSION,
        "status": _status(findings),
        "headline": _headline(blind, census, occ),
        "journal": str(Path(data_dir) / JUDGE_INPUTS[0]),
        "asset_map_context": actx,
        "registry_divergence": div,
        "entry_paths": paths,
        "unresolved_keys": unres,
        "blinded_turnover": blind,
        "judge_fields": fields,
        "zero_vs_absent": census,
        "occurrence": occ,
        "findings": findings,
        "what_it_does_not_prove": [
            "какой АКТИВ у ослеплённого ключа — прибор его не угадывает и не "
            "вписывает; он называет, что обе дороги молчат, и чинить это правом "
            "владельца реестра, а не догадкой по виду имени",
            "верен ли исход дня — судья не пересчитывается, сравниваются только "
            "его вердикты между двумя представлениями одного входа",
            "что произошло бы при СОВМЕСТНОМ слиянии нескольких координат — "
            "перебор одномерный, и пары берутся по одной координате за раз",
            "поле со статусом not_decisive НЕ объявлено различающим: на этой "
            "истории вердикт не двинуло ни одно его значение, и это отсутствие "
            "замера, а не благополучие",
            "доля ослеплённого потока — ВЕРХНЯЯ граница: знаменатель считан по "
            "`legs`, а писатель `legs` теряет мелкие ноги (замер: $263.16 на "
            "2 днях из 13, то есть 0.066 % знаменателя), поэтому истинная доля "
            "не больше напечатанной. Направление границы названо, а не "
            "умолчано: неназванная граница читалась бы как точное число",
        ],
    }


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        data_dir: Optional[str] = None, write: bool = True,
        horizon_days: int = 7) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    ddir = Path(data_dir) if data_dir else base / "data"
    doc = measure(ddir, repo=base, now=now, horizon_days=horizon_days)
    if write:
        atomic_save(doc, str(ddir / ARTIFACT))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root")
    ap.add_argument("--data-dir")
    ap.add_argument("--horizon-days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    doc = run(root=args.root, data_dir=args.data_dir, write=not args.no_write,
              horizon_days=args.horizon_days)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    else:
        print(f"{doc['status']}: {doc['headline']}")
        for line in format_report(doc):
            print(line)
    # Код возврата — вердикт, а не «сработало ли»: CRITICAL ⇒ 1, НЕ ИЗМЕРЕНО ⇒ 2.
    return {CRITICAL: 1, UNMEASURED: 2}.get(doc["status"], 0)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
