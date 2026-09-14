"""Цена ТРЕТЬЕЙ половины рычага — наследников (заказ G17, хвост ADR-384).

Заказ цикла #603 поставлен дословно так:

> Рычаг назван и он ТРОЙНОЙ, а не парный, как считал [ADR-383]: писатель ·
> загрузчик ``load_history`` · двадцать наследников. Заказ G17: **измерить цену
> ТРЕТЬЕЙ половины — наследников.** Если ``load_history`` научить возвращать ВСЕ
> строки дня, сколько из двадцати схлопывающих дадут ДРУГОЙ ответ на сегодняшних
> данных, и у скольких из них этот другой ответ будет ВЕРНЕЕ, а у скольких —
> просто другим (двойной счёт, против которого правило и написано)? Мерить
> дифференциально на копии, по каждому наследнику поимённо; «стало иначе» и
> «стало вернее» — разные величины, и слить их значило бы продать двойной счёт
> как починку. Второй половиной заказа: назвать, у скольких из 62 ``unmeasured``
> отсутствие приводимой точки входа есть свойство модуля, а у скольких —
> свойство прибора.

Прибор только ЧИТАЕТ. Он ничего не чинит, не правит ``load_history`` и не
предлагает править её молча: он называет ЦЕНУ правки, которой ещё не было.

## Почему «стало иначе» нельзя мерить одним стендом

Заказ требует РАЗЛИЧИТЬ две величины, и различие это не стилистическое. Если
научить загрузчик отдавать все строки дня, ответ наследника изменится и в том
случае, когда он ВПЕРВЫЕ УВИДЕЛ стёртое решение, и в том, когда он просто
ПОСЧИТАЛ один день дважды. Первое — починка. Второе — ровно тот двойной счёт,
против которого правило замены и было написано; продать его как починку значит
поменять одну молчаливую ошибку на другую.

Отличить их по величине ответа нельзя: оба выглядят как «ответ изменился».
Поэтому прибор спрашивает у наследника ДРУГОЙ вопрос — вопрос о ПРИРОДЕ его
чувствительности, и спрашивает стендом, на котором правильный ответ известен
заранее.

## Пять стендов, и два из них — контроль по построению

Все пять строятся на КОПИИ ``data/``; живой каталог не открывается на запись
ни разу. День ``D`` выбирается тем же ПРАВИЛОМ, что у соседа [ADR-384], и
горизонт для правила берётся у САМОГО СУДЬИ (``shadow_trigger_eval.
DEFAULT_HORIZON_DAYS``), а не своей константой: позднейший день, за которым в
журнале ещё лежит полный горизонт. ``R`` — настоящая строка дня ``D``.
``R'`` — настоящая строка соседнего дня, перемеченная на ``D`` с вердиктом
``ACT``: настоящий материал вместо правдоподобной подделки.

| стенд | строки дня ``D`` | что им меряется |
|---|---|---|
| ``S_one`` | ``R`` | ответ по ОДНОЙ последней строке |
| ``S_first`` | ``R'`` | ответ по ОДНОЙ ранней строке |
| ``S_true`` | ``R'``, ``R`` | день, в котором стёртое решение ЕСТЬ |
| ``S_dup2`` | ``R``, ``R`` | **контроль:** повтор без новых сведений |
| ``S_dup3`` | ``R``, ``R``, ``R`` | **контроль:** тот же повтор втрое |

Два последних и есть различитель. ``S_dup2`` и ``S_dup3`` несут РОВНО ТУ ЖЕ
информацию, что ``S_one``: строка повторена побайтово, нового в дне не появилось
ничего. Любой ответ о СОСТОЯНИИ дня обязан на них не шелохнуться. Наследник,
чей ответ на них поехал, считает не состояние, а СТРОКИ, — и «все строки дня»
дадут ему не правду, а умножение. Это утверждение о нём верно независимо от
того, что он ответит на ``S_true``, поэтому проверяется первым.

## Пять исходов наследнику, и ни один не есть «ответ изменился»

* ``recovers`` — на ``S_true`` ответ изменился, на повторах НЕ изменился, и
  новый ответ отличается ОТ ОБОИХ однострочных. Наследник впервые увидел вторую
  строку и свёл её с первой. **Это «вернее».**
* ``coincides_with_first_row`` — на ``S_true`` ответ изменился, на повторах не
  изменился, но СОВПАЛ с ответом по одной РАННЕЙ строке. Прочтения два, и этим
  замером они неразличимы: схлопывание переехало с последней строки на первую
  ЛИБО наследник свёл обе строки, и свод совпал. Первая редакция прибора звала
  этот класс ``moved_the_collapse`` — то есть УТВЕРЖДАЛА первое прочтение;
  контроль «множество вердиктов» показал, что честный сводящий читатель попадает
  сюда же, и класс переименован в то, что действительно измерено.
* ``double_counts`` — ответ поехал на ПОВТОРЕ. **Это «иначе», и это хуже.**
* ``unchanged`` — на ``S_true`` ответ тот же. Правка загрузчика этому наследнику
  не стоит ничего и не даёт ничего.
* ``unmeasured`` — с названной причиной.

**Стенд проверяет сам себя.** Наследник ЭТОГО населения день схлопывает,
значит БЕЗ подмены ответ на ``S_true`` обязан совпадать с ответом на ``S_one``.
Прибор это не предполагает, а проверяет перед вердиктом: не совпало — исход
``unmeasured`` с причиной, потому что дальше был бы верный ответ не на тот
вопрос. Из того же равенства следует, что ветка «новый ответ совпал с ответом по
одной ПОСЛЕДНЕЙ строке» НЕДОСТИЖИМА по построению; она была в первой редакции и
снята, а не оставлена украшением.

**Что ``recovers`` НЕ доказывает, и это сказано вслух.** Он доказывает, что
наследник вторую строку УВИДЕЛ и не раздулся на пустом повторе. Он НЕ
доказывает, что получившееся число верно: верность исхода прибор не
пересчитывает и не имеет чем. Граница названа здесь, а не подразумевается.

## Загрузчик подменяется по ТОЖДЕСТВУ, а не по имени

``load_history`` разошлась по дереву копиями ссылки: кто-то зовёт её как
атрибут модуля, кто-то забрал себе через ``from … import``, а
``unobserved_leg_remedy_class`` — через ЧУЖОЙ алиас и имени файла не произносит
вовсе ([ADR-384]). Подменить её по имени в одном модуле значило бы измерить
часть населения и выдать это за целое.

Поэтому подмена идёт обходом ``sys.modules`` по ТОЖДЕСТВУ объекта функции:
переставляется каждый атрибут, который ЕСТЬ исходная функция, и по выходе всё
возвращается на место.

**И этого всё равно недостаточно, поэтому достижимость меряется ОТДЕЛЬНО.**
Ссылка могла уехать в замыкание или в значение по умолчанию, куда обход не
достаёт. Наследник, до которого подмена не дотянулась, ответил бы одинаково в
обоих режимах — и был бы записан в ``unchanged``, то есть «правка ему не стоит
ничего». Это ровно тот дефект, которым этот репозиторий обжигался: не измерено,
выданное за измеренный ноль. Поэтому перед замером каждому наследнику ставится
СЧИТАЮЩАЯ обёртка, и если за прогон она не сработала ни разу — исход
``unmeasured`` с причиной «загрузчик не вызван», а не ``unchanged``.

## Вторая половина заказа: чьё свойство — модуля или прибора

У 59 модулей населения сосед [ADR-384] написал ``нет приводимой точки входа``.
Причина эта — утверждение о ДВОИХ сразу, и заказ верно требует их развести.
Прибор соседа ищет ``measure``/``build``/``evaluate_window`` с первым
параметром из ``(data_dir, base, path)`` либо ``run(root=, write=)``. Модуль
мог иметь исправную точку входа под ДРУГИМ именем — тогда это свойство ПРИБОРА;
а мог не иметь дир-ведомой точки вовсе — тогда свойство МОДУЛЯ.

Разводится это исходом, а не подписью: берутся все верхнеуровневые публичные
функции модуля, чей первый параметр похож на каталог, и они ВЫЗЫВАЮТСЯ на
стенде — в отдельном процессе, с таймаутом, с ``cwd`` и ``SPA_DATA_DIR``,
указывающими в стенд, и с ``write=False`` там, где такой параметр есть.

* ``instrument`` — нашлась, ОТРАБОТАЛА и ДОШЛА ДО ЖУРНАЛА; имя названо. Прибор
  соседа мог бы её водить, если бы знал это имя.
* ``helper_only`` — отработала, но журнала не коснулась. Модуль попал в
  население ПОТОМУ, что читает журнал, значит настоящая его точка входа до
  журнала доходит, а ``resolve_root``/``receipts_path``/``aio_exists`` — нет.
  Первая редакция прибора звала их ``instrument`` и насчитала 15 против
  настоящих; без этого различения счёт «свойство прибора» раздувается
  вспомогательными функциями.
* ``module`` — дир-ведомых функций нет вовсе.
* ``needs_more_than_a_dir`` — кандидаты есть, но ни один не отработал: точке
  входа нужен не каталог, а состояние или аргументы. Это ТРЕТИЙ класс, и он
  назван, а не приписан к одной из двух сторон ради двоичного ответа.

ADVISORY: ``hit_rate``, ``MIN_HIT_RATE``, ``TriggerParams``, писатель журнала и
его правило замены, ``load_history``, ``POLLED_ADAPTERS``, пины, адаптеры,
накопитель ряда, пороги RiskPolicy v1.0, стоп-кран, живой трек и ``landing/``
НЕ трогаются. Капитал не двигается. Прибор только ЧИТАЕТ.

[ADR-383]: docs/decisions/ADR-383-act-day-erased-from-the-journal.md
[ADR-384]: docs/decisions/ADR-384-run-identity-key-price.md
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger(__name__)

VERSION = "heir-all-rows-price-v1"
ARTIFACT = "heir_all_rows_price.json"

HISTORY_FILENAME = "allocation_rationale_history.jsonl"

STATUS_OK = "OK"
STATUS_WARNING = "WARNING"
STATUS_CRITICAL = "CRITICAL"
STATUS_UNMEASURED = "UNMEASURED"

# ── исходы наследнику ────────────────────────────────────────────────────────
HEIR_RECOVERS = "recovers"
HEIR_FIRST_COINCIDES = "coincides_with_first_row"
HEIR_DOUBLE = "double_counts"
HEIR_UNCHANGED = "unchanged"
HEIR_UNMEASURED = "unmeasured"

# ── исходы вопросу «чьё свойство» ────────────────────────────────────────────
WHOSE_INSTRUMENT = "instrument"
WHOSE_MODULE = "module"
WHOSE_NEEDS_MORE = "needs_more_than_a_dir"
WHOSE_HELPER = "helper_only"
WHOSE_UNMEASURED = "unmeasured"

STAND_EXCLUDE = ("backups",)

#: Первые параметры, которые ШИРЕ набора соседа: тем и меряется «свойство прибора».
WIDE_FIRST_PARAMS = (
    "data_dir", "base", "path", "root", "directory", "dirpath", "data",
    "data_path", "base_dir", "dir", "data_root", "repo_root", "tree_root",
)

#: Сколько ждать чужую точку входа, прежде чем назвать её неизмеренной.
ENTRY_TIMEOUT_S = 45.0

_ADVISORY = (
    "hit_rate", "MIN_HIT_RATE", "TriggerParams", "писатель журнала",
    "load_history", "POLLED_ADAPTERS", "пины", "адаптеры", "накопитель ряда",
    "пороги RiskPolicy v1.0", "стоп-кран", "живой трек", "landing/",
)

WHAT_IT_DOES_NOT_PROVE = (
    "исход `recovers` доказывает, что наследник УВИДЕЛ вторую строку и не "
    "раздулся на пустом повторе; он НЕ доказывает, что получившееся число "
    "верно — верность исхода прибор не пересчитывает",
    "исход `unchanged` означает «на СЕГОДНЯШНИХ данных и на ЭТОМ дне ответ не "
    "изменился», а не «не изменится никогда»",
    "класс `instrument` доказывает, что дир-ведомая точка входа ОТРАБОТАЛА на "
    "стенде, а не что она отвечает на тот же вопрос, что искал сосед",
)

#: Второй заслон самоисключения: прибор сам читает журнал, и войти в
#: собственную перепись он обязан не уметь. Первый заслон — по имени модуля.
_SWEEPING = False


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── стенды ───────────────────────────────────────────────────────────────────
def _judge_horizon() -> Optional[int]:
    """Горизонт судьи — у САМОГО судьи, а не своей константой."""
    try:
        from spa_core.paper_trading.shadow_trigger_eval import DEFAULT_HORIZON_DAYS
    except Exception:  # noqa: BLE001
        return None
    try:
        return int(DEFAULT_HORIZON_DAYS)
    except (TypeError, ValueError):
        return None


def read_history(data_dir: Path) -> Tuple[Optional[List[dict]], str]:
    """Строки журнала как они лежат. Не прочитано — ``None`` с причиной."""
    path = Path(data_dir) / HISTORY_FILENAME
    if not path.exists():
        return None, f"{HISTORY_FILENAME} нет в {data_dir}"
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, f"{HISTORY_FILENAME} не прочитан: {exc}"
    rows: List[dict] = []
    for line in raw:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("cycle_date"):
            rows.append(obj)
    if not rows:
        return None, f"{HISTORY_FILENAME} не содержит разбираемых строк"
    return rows, ""


def build_stands(source_data_dir: Path, dest: Path,
                 day: Optional[str] = None) -> Tuple[Optional[dict], str]:
    """Пять стендов на КОПИИ ``data/``; живой каталог не открывается на запись.

    ``S_dup2``/``S_dup3`` — контроль по построению: строка повторена побайтово,
    новых сведений в дне нет, и ответ о СОСТОЯНИИ дня обязан не шелохнуться.
    """
    rows, why = read_history(Path(source_data_dir))
    if rows is None:
        return None, why
    if len(rows) < 2:
        return None, "в журнале меньше двух строк — соседнего дня для стенда нет"

    idx = None
    day_rule = "назван вызовом"
    if day is not None:
        idx = next((i for i, r in enumerate(rows) if r.get("cycle_date") == day), None)
        if idx is None:
            return None, f"дня {day} нет в журнале"
    if idx is None:
        horizon = _judge_horizon()
        idx = max(1, len(rows) - 1 - horizon) if horizon is not None else len(rows) - 1
        day_rule = (f"позднейший день, за которым остаётся горизонт судьи "
                    f"({horizon} дн.)" if horizon is not None
                    else "последний день журнала (горизонт судьи не прочитан)")
    if idx == 0:
        idx = len(rows) - 1
        day_rule += " · сдвинут: у первого дня нет соседа-донора"

    donor = rows[idx - 1]
    target = rows[idx]
    target_day = str(target.get("cycle_date"))
    twin = dict(donor)
    twin["cycle_date"] = target_day
    twin["decision_id"] = f"adr060-shadow-{target_day}"
    twin["generated_at"] = f"{target_day}T06:00:11.000000+00:00"
    twin["verdict"] = "ACT"

    def _write(name: str, day_rows: Sequence[dict]) -> Path:
        stand = Path(dest) / name
        data = stand / "data"
        data.mkdir(parents=True, exist_ok=True)
        for item in sorted(Path(source_data_dir).iterdir()):
            if item.name in STAND_EXCLUDE:
                continue
            dst = data / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
        out: List[dict] = []
        for i, row in enumerate(rows):
            if i == idx:
                out.extend(day_rows)
            else:
                out.append(row)
        (data / HISTORY_FILENAME).write_text(
            "\n".join(json.dumps(r, sort_keys=True, default=str) for r in out) + "\n",
            encoding="utf-8")
        return stand

    return {
        "day": target_day,
        "donor_day": str(donor.get("cycle_date")),
        "day_rule": day_rule,
        "excluded_from_copy": list(STAND_EXCLUDE),
        "s_one": _write("s_one", [target]),
        "s_first": _write("s_first", [twin]),
        "s_true": _write("s_true", [twin, target]),
        "s_dup2": _write("s_dup2", [target, target]),
        "s_dup3": _write("s_dup3", [target, target, target]),
    }, ""


# ── подмена загрузчика по ТОЖДЕСТВУ ──────────────────────────────────────────
def all_rows_loader(data_dir, book_id=None) -> Tuple[List[dict], int]:
    """``load_history``, обученная отдавать ВСЕ строки дня.

    Разбор повторяет исходный построчно; отличие ровно одно — строки дня не
    схлопываются. Сортировка по дате УСТОЙЧИВАЯ, поэтому внутри дня сохраняется
    порядок файла: ранний прогон идёт раньше позднего.
    """
    from spa_core.paper_trading import shadow_trigger_eval as ste
    path = Path(data_dir) / ste._history_filename(book_id)
    rows: List[dict] = []
    bad = 0
    if not path.exists():
        return [], 0
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("shadow history unreadable (%s)", exc)
        return [], 0
    for raw in raw_lines:
        if not raw.strip():
            continue
        try:
            obj = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if not isinstance(obj, dict) or not obj.get("cycle_date"):
            bad += 1
            continue
        rows.append(obj)
    rows.sort(key=lambda r: str(r["cycle_date"]))
    return rows, bad


def rebind_everywhere(original, replacement) -> List[Tuple[object, str]]:
    """Переставить КАЖДЫЙ атрибут дерева, который ЕСТЬ ``original``.

    По тождеству объекта, а не по имени: ссылка на загрузчик разошлась копиями,
    и часть читателей не произносит ни имени файла, ни имени функции.
    """
    sites: List[Tuple[object, str]] = []
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        try:
            items = list(vars(mod).items())
        except Exception:  # noqa: BLE001 — модуль без __dict__
            continue
        for name, value in items:
            if value is original:
                try:
                    setattr(mod, name, replacement)
                except Exception:  # noqa: BLE001 — атрибут только для чтения
                    continue
                sites.append((mod, name))
    return sites


def restore(sites: Sequence[Tuple[object, str]], original) -> None:
    for mod, name in sites:
        try:
            setattr(mod, name, original)
        except Exception:  # noqa: BLE001
            continue


class _CallCounter:
    """Счётчик достижимости: подмена могла не дотянуться до наследника."""

    def __init__(self) -> None:
        self.n = 0

    def wrap(self, original) -> Callable:
        def counting(*args, **kwargs):
            self.n += 1
            return original(*args, **kwargs)
        return counting


# ── замер наследника ─────────────────────────────────────────────────────────
def _answer(call: Callable[[Path], object], stand: Path) -> str:
    from spa_core.monitoring.run_identity_key_price import _strip_clock
    return _strip_clock(call(stand))


def classify_heir(module_name: str, stands: dict, *,
                  patched_loader: Optional[Callable] = None) -> dict:
    """Вердикт одному наследнику — по ИСХОДУ на пяти стендах, в двух режимах.

    ``patched_loader`` — чем подменяется загрузчик; по умолчанию
    :func:`all_rows_loader`. Параметр существует ради НУЛЕВОГО КОНТРОЛЯ:
    подмена на загрузчик с ТЕМ ЖЕ поведением обязана дать всем
    ``unchanged``. Без него «ответ изменился» доказывало бы лишь то, что
    мы что-то подменили, а не то, ЧТО именно мы подменили.
    """
    patched_loader = all_rows_loader if patched_loader is None else patched_loader
    import importlib
    from spa_core.monitoring.run_identity_key_price import module_driver

    row: Dict[str, object] = {"module": module_name}
    if module_name == __name__:
        row.update(outcome=HEIR_UNMEASURED,
                   reason="это сам прибор: он ГОНИТ замер, и гнать его внутри "
                          "замера значило бы войти в него заново")
        return row
    try:
        mod = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001
        row.update(outcome=HEIR_UNMEASURED,
                   reason=f"импорт не удался: {type(exc).__name__}")
        return row
    entry, call = module_driver(mod)
    if call is None:
        row.update(outcome=HEIR_UNMEASURED, reason="нет приводимой точки входа")
        return row
    row["entry"] = entry

    from spa_core.paper_trading import shadow_trigger_eval as ste
    original = ste.load_history

    # 1. Достижимость. Наследник, до которого подмена не дотянулась, ответит
    #    одинаково в обоих режимах — и уехал бы в `unchanged`, то есть в
    #    «правка ему ничего не стоит». Это «не измерено», а не ноль.
    counter = _CallCounter()
    sites = rebind_everywhere(original, counter.wrap(original))
    try:
        call(stands["s_true"])
    except BaseException as exc:  # noqa: BLE001
        restore(sites, original)
        row.update(outcome=HEIR_UNMEASURED,
                   reason=f"{entry}() упал: {type(exc).__name__}")
        return row
    finally:
        restore(sites, original)
    row["loader_calls"] = counter.n
    row["rebound_sites"] = len(sites)
    if counter.n == 0:
        row.update(outcome=HEIR_UNMEASURED,
                   reason="загрузчик не вызван ни разу: подмена до этого "
                          "наследника не дотянулась — про цену правки НЕ "
                          "ИЗМЕРЕНО ничего")
        return row

    # 2. Ответы в обоих режимах.
    keys = ("s_one", "s_first", "s_true", "s_dup2", "s_dup3")
    try:
        as_is = {k: _answer(call, stands[k]) for k in keys}
        again = _answer(call, stands["s_true"])
    except BaseException as exc:  # noqa: BLE001
        row.update(outcome=HEIR_UNMEASURED,
                   reason=f"{entry}() упал в режиме «как есть»: {type(exc).__name__}")
        return row
    if again != as_is["s_true"]:
        row.update(outcome=HEIR_UNMEASURED,
                   reason="ответ не воспроизводится на ОДНОМ И ТОМ ЖЕ стенде")
        return row
    # Встроенный контроль стенда. Наследник ЭТОГО населения схлопывает день,
    # значит без подмены день из двух строк обязан быть для него неотличим от
    # дня из одной ПОСЛЕДНЕЙ. Не так — стенд или население собраны неверно, и
    # дальнейший вердикт был бы верным ответом не на тот вопрос.
    if as_is["s_true"] != as_is["s_one"]:
        row.update(outcome=HEIR_UNMEASURED,
                   reason="без подмены ответ на дне из ДВУХ строк уже отличается "
                          "от ответа по одной ПОСЛЕДНЕЙ: этот наследник день не "
                          "схлопывает, и мерить ему цену схлопывания нечем")
        return row

    sites = rebind_everywhere(original, patched_loader)
    try:
        patched = {k: _answer(call, stands[k]) for k in keys}
    except BaseException as exc:  # noqa: BLE001
        row.update(outcome=HEIR_UNMEASURED,
                   reason=f"{entry}() упал в режиме «все строки»: {type(exc).__name__}")
        return row
    finally:
        restore(sites, original)

    # 3. Классификация. Повтор проверяется ПЕРВЫМ: утверждение «наследник
    #    считает строки, а не состояние» верно независимо от ответа на S_true.
    inflates_2 = patched["s_dup2"] != as_is["s_dup2"]
    inflates_3 = patched["s_dup3"] != patched["s_dup2"]
    row["inflates_on_repeat"] = bool(inflates_2 or inflates_3)
    row["changed_on_true"] = bool(patched["s_true"] != as_is["s_true"])

    if inflates_2 or inflates_3:
        which = []
        if inflates_2:
            which.append("×2")
        if inflates_3:
            which.append("×3")
        row.update(outcome=HEIR_DOUBLE,
                   reason=f"ответ поехал на ПОВТОРЕ побайтово равной строки "
                          f"({', '.join(which)}): наследник считает СТРОКИ, а не "
                          f"состояние дня — «все строки» дадут ему умножение, "
                          f"не правду")
        return row
    if patched["s_true"] == as_is["s_true"]:
        row.update(outcome=HEIR_UNCHANGED,
                   reason="ответ на дне с двумя строками тот же: правка "
                          "загрузчика этому наследнику не стоит ничего и не "
                          "даёт ничего")
        return row
    if patched["s_true"] == as_is["s_first"]:
        row.update(outcome=HEIR_FIRST_COINCIDES,
                   reason="новый ответ СОВПАЛ с ответом по ОДНОЙ РАННЕЙ строке. "
                          "Два прочтения неразличимы этим замером: схлопывание "
                          "переехало с последней строки на первую ЛИБО наследник "
                          "свёл обе, и свод совпал. Двусмысленность названа, а не "
                          "разрешена догадкой")
        return row
    row.update(outcome=HEIR_RECOVERS,
               reason="ответ изменился, на повторах НЕ изменился и отличается ОТ "
                      "ОБОИХ однострочных: наследник впервые увидел вторую "
                      "строку и свёл её с первой")
    return row


# ── вторая половина: чьё свойство — модуля или прибора ───────────────────────
_DRIVER_SNIPPET = r"""
import json, sys
for _root in ({tree!r}, {own!r}):
    if _root not in sys.path:
        sys.path.insert(0, _root)
name, stand = {mod!r}, {stand!r}
out = {{"ran": [], "raised": []}}
try:
    import importlib, inspect
    from pathlib import Path
    mod = importlib.import_module(name)
except BaseException as exc:
    print(json.dumps({{"import_failed": type(exc).__name__}}))
    raise SystemExit(0)
from spa_core.monitoring import heir_all_rows_price as H
from spa_core.paper_trading import shadow_trigger_eval as ste
for fname in {candidates!r}:
    fn = getattr(mod, fname, None)
    if not callable(fn):
        continue
    counter = H._CallCounter()
    original = ste.load_history
    sites = H.rebind_everywhere(original, counter.wrap(original))
    try:
        sig = inspect.signature(fn)
        kwargs = {{"write": False}} if "write" in sig.parameters else {{}}
        fn(Path(stand) / "data", **kwargs)
    except BaseException as exc:
        out["raised"].append([fname, type(exc).__name__])
        continue
    finally:
        H.restore(sites, original)
    out["ran"].append(fname)
    out["loader_calls"] = counter.n
    break
print(json.dumps(out))
"""


def dir_driven_candidates(mod) -> List[str]:
    """Публичные верхнеуровневые функции, чей первый параметр похож на каталог.

    Сеть ШИРЕ набора соседа намеренно: ею и меряется «свойство прибора».
    Остальные параметры обязаны иметь умолчания — иначе каталога мало и по
    подписи, а не по исходу.
    """
    names: List[str] = []
    for name, fn in sorted(vars(mod).items()):
        if name.startswith("_") or not inspect.isfunction(fn):
            continue
        if getattr(fn, "__module__", None) != getattr(mod, "__name__", None):
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        params = list(sig.parameters.values())
        if not params or params[0].name not in WIDE_FIRST_PARAMS:
            continue
        rest_ok = all(
            p.default is not inspect.Parameter.empty
            or p.kind in (inspect.Parameter.VAR_POSITIONAL,
                          inspect.Parameter.VAR_KEYWORD)
            for p in params[1:])
        if rest_ok:
            names.append(name)
    return names


def whose_property(module_name: str, stand: Path, tree_root: Path) -> dict:
    """Чьё свойство — модуля или прибора. По ИСХОДУ, в отдельном процессе.

    Отдельный процесс даёт таймаут (чужая точка входа может ходить в сеть) и
    уводит случайную запись в стенд: ``cwd`` и ``SPA_DATA_DIR`` указывают туда.
    """
    import importlib

    row: Dict[str, object] = {"module": module_name}
    try:
        mod = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001
        row.update(whose=WHOSE_UNMEASURED,
                   reason=f"импорт не удался: {type(exc).__name__}")
        return row
    candidates = dir_driven_candidates(mod)
    row["candidates"] = candidates
    if not candidates:
        row.update(whose=WHOSE_MODULE,
                   reason="дир-ведомых публичных функций нет вовсе: водить "
                          "нечего, и ни одно имя в приборе соседа этого не "
                          "изменило бы")
        return row

    own_root = str(Path(__file__).resolve().parents[2])
    script = _DRIVER_SNIPPET.format(tree=str(tree_root), own=own_root,
                                    mod=module_name, stand=str(stand),
                                    candidates=candidates)
    env = dict(os.environ)
    env["SPA_DATA_DIR"] = str(Path(stand) / "data")
    env["SPA_ENV"] = "ci"
    try:
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True,
                              text=True, timeout=ENTRY_TIMEOUT_S,
                              cwd=str(stand), env=env)
    except subprocess.TimeoutExpired:
        row.update(whose=WHOSE_UNMEASURED,
                   reason=f"кандидаты не уложились в {ENTRY_TIMEOUT_S:.0f} с")
        return row
    line = (proc.stdout or "").strip().splitlines()
    try:
        got = json.loads(line[-1]) if line else {}
    except ValueError:
        got = {}
    if not got:
        row.update(whose=WHOSE_UNMEASURED,
                   reason="водитель не напечатал разбираемого ответа")
        return row
    if got.get("import_failed"):
        row.update(whose=WHOSE_UNMEASURED,
                   reason=f"импорт в отдельном процессе не удался: "
                          f"{got['import_failed']}")
        return row
    ran = got.get("ran") or []
    if ran:
        calls = got.get("loader_calls")
        row["loader_calls"] = calls
        # «Отработала» ещё не значит «это точка входа». Модуль попал в
        # население ПОТОМУ, что читает журнал; значит настоящая точка входа до
        # журнала доходит, а `resolve_root`/`receipts_path` — нет. Без этого
        # различения счёт «свойство прибора» раздувается вспомогательными
        # функциями, и следующий цикл получил бы верный ответ не на тот вопрос.
        if calls:
            row.update(whose=WHOSE_INSTRUMENT, entry=ran[0],
                       reason=f"дир-ведомая точка входа `{ran[0]}` ОТРАБОТАЛА на "
                              f"стенде И дошла до журнала ({calls} вызов(ов) "
                              f"загрузчика): прибор соседа мог бы её водить, "
                              f"если бы знал это имя")
        else:
            row.update(whose=WHOSE_HELPER, entry=ran[0],
                       reason=f"`{ran[0]}` отработала, но журнала НЕ коснулась: "
                              f"это вспомогательная функция, а не точка входа "
                              f"читателя — водить её значило бы мерить не то")
        return row
    raised = got.get("raised") or []
    row["raised"] = raised
    row.update(whose=WHOSE_NEEDS_MORE,
               reason="кандидаты есть, но ни один не отработал: точке входа "
                      "нужен не каталог, а состояние или аргументы — "
                      + ", ".join(f"{n}:{e}" for n, e in raised[:4]))
    return row


# ── сборка замера ────────────────────────────────────────────────────────────
def measure(data_dir: Path, *, now: Optional[datetime] = None,
            stand_root: Optional[Path] = None,
            tree_root: Optional[Path] = None,
            day: Optional[str] = None,
            sweep_entries: bool = True) -> dict:
    """Полный замер G17. Только чтение живого ``data/``; стенды — копии."""
    global _SWEEPING
    stamp = (now or _utcnow()).isoformat()
    doc: Dict[str, object] = {
        "version": VERSION,
        "generated_at": stamp,
        "data_dir": str(data_dir),
        "advisory": list(_ADVISORY),
        "what_it_does_not_prove": list(WHAT_IT_DOES_NOT_PROVE),
    }
    if _SWEEPING:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = (
            "это сам прибор: он уже ГОНИТ замер, и повторный вход в него был бы "
            "входом в перепись изнутри переписи")
        return doc

    tree = Path(tree_root) if tree_root else Path(__file__).resolve().parents[2]
    import tempfile
    tmp = Path(stand_root) if stand_root else Path(tempfile.mkdtemp(prefix="g17_"))
    tmp.mkdir(parents=True, exist_ok=True)

    stands, why = build_stands(Path(data_dir), tmp, day=day)
    if stands is None:
        doc["status"] = STATUS_UNMEASURED
        doc["unmeasured_reason"] = f"стенды не построены: {why}"
        return doc
    doc["stand"] = {k: (str(v) if isinstance(v, Path) else v)
                    for k, v in stands.items()}

    _SWEEPING = True
    try:
        from spa_core.monitoring import run_identity_key_price as g16

        roads, pop_stats = g16.reader_population(tree)
        census: List[dict] = []
        for name in sorted(roads):
            if name in (g16.__name__, __name__):
                census.append({"module": name, "outcome": g16.READER_UNMEASURED,
                               "reason": "прибор переписи / прибор этого замера"})
                continue
            census.append(g16.classify_reader(name, {
                "s1": stands["s_one"], "s2": stands["s_true"],
                "s3": stands["s_first"]}))
        doc["population"] = {"total": len(census), "stats_population":
                             pop_stats.get("population")}

        heirs = [r["module"] for r in census
                 if r.get("outcome") == g16.READER_LAST]
        doc["heirs_population"] = len(heirs)
        heir_rows = [classify_heir(name, stands) for name in heirs]
        doc["heirs"] = heir_rows
        counts: Dict[str, int] = {}
        for r in heir_rows:
            counts[str(r["outcome"])] = counts.get(str(r["outcome"]), 0) + 1
        doc["heir_outcomes"] = counts

        no_entry = [r["module"] for r in census
                    if r.get("outcome") == g16.READER_UNMEASURED
                    and str(r.get("reason", "")).startswith("нет приводимой точки входа")]
        doc["no_entry_population"] = len(no_entry)
        if sweep_entries:
            whose_rows = [whose_property(name, stands["s_one"], tree)
                          for name in no_entry]
            doc["whose"] = whose_rows
            wcounts: Dict[str, int] = {}
            for r in whose_rows:
                wcounts[str(r["whose"])] = wcounts.get(str(r["whose"]), 0) + 1
            doc["whose_outcomes"] = wcounts
        else:
            doc["whose"] = None
            doc["whose_outcomes"] = None
            doc["whose_unmeasured_reason"] = (
                "вторая половина заказа не мерилась: sweep_entries=False")
    finally:
        _SWEEPING = False

    doc.update(_verdict(doc))
    return doc


def _verdict(doc: dict) -> dict:
    """Статус. Нечитаемое — UNMEASURED, а не спокойный ноль."""
    from spa_core.utils.observation import observed

    counts = observed(doc, "heir_outcomes", kind=dict)
    if counts is None:
        return {"status": STATUS_UNMEASURED,
                "unmeasured_reason": "исходы наследников не измерены"}
    pop = observed(doc, "heirs_population", kind=int)
    if pop is None:
        return {"status": STATUS_UNMEASURED,
                "unmeasured_reason": "население наследников не измерено"}
    if pop == 0:
        return {"status": STATUS_UNMEASURED,
                "unmeasured_reason": "схлопывающих наследников не найдено: "
                                     "мерить цену не у кого"}
    double = counts.get(HEIR_DOUBLE, 0)
    recovers = counts.get(HEIR_RECOVERS, 0)
    if double:
        return {"status": STATUS_CRITICAL,
                "headline": f"{double} из {pop} наследников раздуваются на "
                            f"ПОВТОРЕ побайтово равной строки: «все строки дня» "
                            f"дадут им двойной счёт, а не починку"}
    if recovers:
        return {"status": STATUS_WARNING,
                "headline": f"{recovers} из {pop} наследников вернули бы стёртое "
                            f"решение; остальные — цена без выгоды"}
    return {"status": STATUS_OK,
            "headline": f"ни один из {pop} наследников не вернул бы стёртое "
                        f"решение правкой одного загрузчика"}


def format_report(doc: dict) -> List[str]:
    from spa_core.utils.observation import observed

    out: List[str] = []
    status = doc.get("status", STATUS_UNMEASURED)
    if status == STATUS_UNMEASURED:
        out.append(f"[НЕ ИЗМЕРЕНО] {doc.get('unmeasured_reason', 'причина не названа')}")
        return out
    stand = observed(doc, "stand", kind=dict) or {}
    out.append(f"[СТЕНД] день {stand.get('day')} (донор {stand.get('donor_day')}), "
               f"правило дня: {stand.get('day_rule')}")
    counts = observed(doc, "heir_outcomes", kind=dict) or {}
    pop = doc.get("heirs_population")
    out.append(f"[ОТВЕТ] наследников {pop}: "
               + " · ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for row in observed(doc, "heirs", kind=list) or []:
        out.append(f"   [{row.get('outcome')}] {row.get('module')} "
                   f"({row.get('entry', '—')}): {row.get('reason')}")
    wcounts = observed(doc, "whose_outcomes", kind=dict)
    if wcounts is None:
        out.append("[ЧЬЁ СВОЙСТВО] НЕ ИЗМЕРЕНО: "
                   + str(doc.get("whose_unmeasured_reason", "причина не названа")))
    else:
        out.append(f"[ЧЬЁ СВОЙСТВО] из {doc.get('no_entry_population')} без точки "
                   f"входа: " + " · ".join(f"{k}={v}" for k, v in sorted(wcounts.items())))
        for row in observed(doc, "whose", kind=list) or []:
            if row.get("whose") == WHOSE_INSTRUMENT:
                out.append(f"   [ПРИБОР] {row.get('module')} → `{row.get('entry')}`")
    for line in doc.get("what_it_does_not_prove", []):
        out.append(f"[НЕ ДОКАЗЫВАЕТ] {line}")
    out.append("ADVISORY: " + ", ".join(doc.get("advisory", []))
               + " НЕ трогаются — прибор только ЧИТАЕТ")
    return out


def run(root: Optional[str] = None, *, now: Optional[datetime] = None,
        write: bool = True, sweep_entries: bool = True) -> dict:
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    doc = measure(base / "data", now=now, tree_root=base,
                  sweep_entries=sweep_entries)
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(base / "data" / ARTIFACT))
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--stand-root", default=None)
    ap.add_argument("--day", default=None)
    ap.add_argument("--no-entries", action="store_true",
                    help="не мерить вторую половину заказа")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    base = Path(__file__).resolve().parents[2]
    data_dir = Path(args.data_dir) if args.data_dir else base / "data"
    doc = measure(data_dir, stand_root=Path(args.stand_root) if args.stand_root else None,
                  tree_root=base, day=args.day, sweep_entries=not args.no_entries)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    else:
        for line in format_report(doc):
            print(line)
    return {STATUS_OK: 0, STATUS_WARNING: 0, STATUS_CRITICAL: 1,
            STATUS_UNMEASURED: 2}.get(str(doc.get("status")), 2)


if __name__ == "__main__":
    raise SystemExit(main())
