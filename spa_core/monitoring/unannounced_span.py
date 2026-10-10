"""Вторая сторона цены оси D: работа, оборванная ДО объявления закрытия.

**Заказ G111 п. 3 (ADR-536), дословно:**

> **Цена оси D — нижняя граница, и у неё есть вторая сторона, которую журнал не знает.**
> Работа, оборванная сроком ДО объявления, в журнал не попадает по построению. Назвать,
> чем её вообще можно померить (например, деревья в `/tmp` без объявленного закрытия),
> или объявить класс неизмеримым — но объявить, а не умолчать.

## Чего именно не знает журнал

Сосед `claim_release_census` (ADR-536) считает цену срока годности так: `latencies` —
задержка «захват → освобождение ТОЙ ЖЕ личности на ТОЙ ЖЕ карточке», и на каждой ступени
лестницы `would_have_cut_self_closing_work` = сколько ЭТИХ задержек длиннее срока. Замер
02.10: 4 пары из 617. Население цены — **только закрытые пары**: работа, которая успела
объявить своё закрытие. Сам сосед это и говорит полем `lower_bound`.

Незакрытых захватов при этом **597** (замер 10.10), и про КАЖДЫЙ журнал знает ровно одно:
когда он был взят. Сколько эта работа шла — не знает НИКТО из журнала, и потому цена
срока по ней не посчитана ни на одну ступень. Это и есть вторая сторона.

## Чем её можно померить: ДВЕ двери, и обе отвечают ИСХОДОМ

| дверь | что читает | почему она отвечает на нужный вопрос |
|---|---|---|
| **живое дерево** | самая свежая отметка записи в дереве, которое запись НАЗВАЛА | запись в дереве позже захвата есть ФАКТ продолжения работы, а не догадка о нём |
| **архив уборщика** | то же, но в копии, снятой `reap_stale_worktrees.archive` | `shutil.copy2` переносит отметку ИСХОДНОГО файла, поэтому архив знает время записи дерева, которого на диске уже нет |

Вторая дверь — единственная, которая переживает снятие дерева, и она же даёт основную
часть замера: деревьев циклов в `/tmp` на диске единицы, а архивов уборщика сотни.
Свойство `copy2` проверено ИСХОДОМ, а не прочитано в документации: у архива
`cartographer-bundle-20261010T034452Z` манифест от 10.10 05:44, а файлы внутри — от
20.09 15:53, то есть отметка пережила копирование (положительный контроль
`test_archive_keeps_the_ORIGINAL_write_time` воспроизводит это на одноразовой сцене).

## Остаток объявлен неизмеримым — ПО ПРИЧИНАМ, а не одним числом

Заказ разрешает вторую ветвь («объявить класс неизмеримым»), но требует объявить. Поэтому
у каждой неизмеренной строки названа СВОЯ причина, и причины эти лечатся разным:

* `unmeasured_tree_unnamed` — запись дерева не называет вовсе (ни путями, ни `cwd`), и
  спросить попросту негде;
* `unmeasured_shared_living_tree` — названо ОБЩЕЕ живое дерево (главное дерево репозитория
  по вердикту самого git). Отметки там пишет флот круглосуточно, поэтому «самая свежая
  запись» о держателе не говорит НИЧЕГО. Это не пробел замера, а отказ атрибуции: взять
  отметку прод-дерева за span значило бы выдать такт дневного цикла за работу сессии;
* `unmeasured_record_without_write_times` — запись о дереве ЕСТЬ (квитанция уборщика,
  регистрация git, архив без файлов), но времени записи она не несёт: квитанция знает
  момент СНЯТИЯ, регистрация — путь и `HEAD`, архив без файлов — что недоставленной
  работы в дереве не было. Все три говорят «дерево существовало», ни одна — «когда в нём
  писали»;
* `unmeasured_no_trace` — следа нет нигде. **Вот для этой доли класс и неизмерим**, и
  объявляется он здесь.

## Направления ошибки названы ОБА, потому что они противоположны

1. **span есть НИЖНЯЯ граница самого span.** Последняя отметка записи — не последний момент
   работы: сессия могла думать, считать, гонять тесты и умереть, ничего больше не записав.
   Вред срока по этой оси ЗАНИЖАЕТСЯ.
2. **Дерево, названное больше чем одной личностью, атрибуцию не даёт.** Самую свежую
   отметку там мог поставить сосед, а не держатель. Вред срока по этой оси ЗАВЫШАЕТСЯ,
   поэтому лестница печатается ДВУМЯ колонками (одна личность / несколько), и доверия
   заслуживает первая.

Ни одно из двух направлений не сводится к другому и складывать их нельзя — поэтому обе
колонки стоят рядом, а не сведены в «оценку».

## Прибор ТОЛЬКО ЧИТАЕТ

`applied=False`, stdlib, сети нет. Журнал, деревья, архив и реестр git читаются; срока
годности прибор не называет и не заводит (это решение, оно идёт заказом), деревьев не
снимает, карточек не двигает. RiskPolicy v1.0, стоп-кран, аллокатор, живой трек и
`landing/` не трогаются.

    python3 -m spa_core.monitoring.unannounced_span
    python3 -m spa_core.monitoring.unannounced_span --json --save
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):  # pragma: no cover — прямой запуск файла
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.monitoring import claim_release_census as census
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

ARTIFACT_NAME = "unannounced_span.json"
ORDER = ("G111 п. 3 (ADR-536) — вторая сторона цены оси D: чем померить работу, "
         "оборванную ДО объявления закрытия, либо объявить класс неизмеримым")

#: Квитанции уборщика деревьев. Своей КОНСТАНТЫ у соседа нет — путь стоит у него
#: умолчанием прямо в теле `record_reap`, поэтому занять нечего, и это сказано вслух,
#: а не выдано за заём. Расхождение двух написаний одного пути поймал бы сам замер:
#: квитанций стало бы ноль при непустом архиве.
LEDGER_REL = "data/worktree_reap_log.jsonl"

#: Каталоги, которые сессия НЕ пишет: `.git` ведёт git, `data/` — живой цикл,
#: `__pycache__` — интерпретатор. Перечень взят у соседа (`reap_stale_worktrees.newest_mtime`,
#: умолчание `skip`) дословно по той же причине, по которой он там и стоит: отметка
#: интерпретатора или дневного цикла работой сессии не является.
SKIP_DIRS = (".git", "data", "__pycache__")

#: Двери замера. Исход «измерено» бывает только через них.
DOOR_TREE = "tree_on_disk"
DOOR_ARCHIVE = "reaper_archive"

#: Исходы «не измерено», каждый со своей причиной (инв. #17).
UNM_TREE_UNNAMED = "unmeasured_tree_unnamed"
UNM_SHARED_LIVING = "unmeasured_shared_living_tree"
UNM_RECORD_NO_TIMES = "unmeasured_record_without_write_times"
UNM_NO_TRACE = "unmeasured_no_trace"

DOORS = (DOOR_TREE, DOOR_ARCHIVE)
UNMEASURED_OUTCOMES = (UNM_TREE_UNNAMED, UNM_SHARED_LIVING,
                       UNM_RECORD_NO_TIMES, UNM_NO_TRACE)

#: Атрибуция отметки. Названа ОТДЕЛЬНО от двери: дверь отвечает «есть ли время записи»,
#: атрибуция — «чья эта запись», и склеить их значило бы ответить одним словом на два
#: вопроса.
ATTR_SOLE = "sole_identity"
ATTR_MULTIPLE = "multiple_identities"

STATUS_MEASURABLE = "SPAN_MEASURABLE"
STATUS_PARTLY = "SPAN_PARTLY_MEASURABLE"
STATUS_CLASS_UNMEASURABLE = "SPAN_CLASS_UNMEASURABLE"
STATUS_UNMEASURED = "UNMEASURED"

_HOUR = 3600.0


# ───────────────────────── чужие мерки: заём, не копия ─────────────────────────

def load_neighbours(repo_root: Path) -> Dict[str, Any]:
    """Соседи, у которых берутся население, разбор дерева и реестр git.

    `claim_release_census` отдаёт РОВНО то население, по которому считается цена оси D
    (и саму лестницу сроков), `check_undelivered_work` — чтение дерева из записи,
    `reap_stale_worktrees` — вердикт git о своём реестре и перечень пропускаемых
    каталогов. Второй экземпляр любой из этих мерок разошёлся бы с первым молча
    (ADR-220), а здесь расхождение было бы особенно тихим: прибор отвечал бы про ДРУГОЕ
    население, чем то, чью цену уточняет.
    """
    kin = census.load_neighbours(repo_root)
    reaper = census._load_script(repo_root, "scripts/reap_stale_worktrees.py", "_uas_reaper")
    missing = list(kin["missing"])
    if reaper is None:
        missing.append("reap_stale_worktrees")
    return {"census": census, "guard": kin["guard"], "sibling": kin["sibling"],
            "reaper": reaper, "missing": missing}


# ───────────────────────── население: незакрытые захваты ─────────────────────────

def open_claims_and_latencies(records: Sequence[Dict[str, Any]], *, guard, sibling
                              ) -> Dict[str, Any]:
    """Незакрытые захваты и задержки закрытых пар — ОДНИМ вызовом соседа.

    Обе величины приходят из `measure_latency`, и это существенно: цена оси D считается
    по `latencies`, а вторая её сторона — по тем же `open_claims`, что сосед из того же
    разбора и отбросил. Спросить их двумя разными способами значило бы уточнять цену
    НЕ ТОГО замера.
    """
    population = census.split_population(records, guard=guard, sibling=sibling)
    latency = census.measure_latency(population["claims"], population["releases"])
    return {"population": population, "latency": latency,
            "open_claims": latency["open_claims"],
            "latencies": latency.get("_latencies") if latency["measured"] else None}


def identities_by_tree(records: Sequence[Dict[str, Any]], *, sibling) -> Dict[str, set]:
    """{дерево: множество личностей, назвавших его в журнале}.

    Считается по ВСЕМ записям, а не только по захватам: сосед, писавший в то же дерево
    без захвата карточки, отметку в нём оставил ровно так же. Личность берётся у
    `census.identity_of` — якорь, если объявлен, иначе ярлык, и подмена НАЗВАНА там же.
    """
    out: Dict[str, set] = {}
    for record in records or ():
        tree = sibling.worktree_of(record)
        if tree:
            out.setdefault(tree, set()).add(census.identity_of(record, sibling))
    return out


# ───────────────────────── дверь 1: живое дерево и архив ─────────────────────────

def newest_write(path: Path, *, skip: Sequence[str] = SKIP_DIRS) -> Tuple[Optional[float], Optional[str]]:
    """(самая свежая отметка записи под ``path``, причина-если-не-измерено).

    ``None`` без причины здесь не бывает: каталог без ни одного файла — это «времени
    записи нет», и причина у него НАЗЫВАЕТСЯ. Нуль не возвращается никогда — нуль
    эпохи читался бы как «писали в 1970», а не как «не писали».
    """
    best: Optional[float] = None
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                try:
                    stamp = os.stat(os.path.join(dirpath, name)).st_mtime
                except OSError:
                    continue      # исчезнувший файл времени записи не даёт
                seen += 1
                if best is None or stamp > best:
                    best = stamp
    except OSError as exc:
        return None, f"обход не удался: {type(exc).__name__}: {exc}"
    if best is None:
        return None, f"ни одного файла вне {list(skip)} — времени записи нет"
    return best, None


def read_archives(archive_root: Path) -> Dict[str, Any]:
    """{дерево: [каталоги архива]} по манифестам уборщика; плюс причина-если-не-прочитано.

    Ключ — дерево, которое уборщик САМ записал в манифест, а не имя каталога архива:
    имя собрано из базового имени и отметки (`<basename>-<stamp>`), и два разных дерева
    с одинаковым базовым именем склеились бы под ним молча.
    """
    out: Dict[str, List[Path]] = {}
    unreadable = 0
    try:
        entries = sorted(p for p in archive_root.iterdir() if p.is_dir())
    except OSError as exc:
        return {"by_tree": None, "reason": f"архив не прочитан ({archive_root}): "
                                           f"{type(exc).__name__}: {exc}",
                "archives": None, "unreadable_manifests": None}
    for entry in entries:
        manifest = entry / "manifest.json"
        try:
            doc = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            unreadable += 1
            continue
        if not isinstance(doc, dict):
            unreadable += 1
            continue
        tree = observed(doc, "worktree", kind=str)
        if not tree:
            unreadable += 1
            continue
        out.setdefault(_same_tree(tree), []).append(entry)
    return {"by_tree": out, "reason": None, "archives": len(entries),
            "unreadable_manifests": unreadable}


def read_ledger(path: Path) -> Dict[str, Any]:
    """{дерево: число квитанций снятия}; ``None`` — журнал квитанций не прочитан.

    Квитанция времени ЗАПИСИ не несёт — только момент снятия, — и потому она здесь не
    дверь замера, а свидетельство существования дерева. Разделение существенно: иначе
    момент снятия (его ставит уборщик) уехал бы в span как работа сессии.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"by_tree": None, "reason": f"квитанции уборщика не прочитаны ({path}): "
                                           f"{type(exc).__name__}: {exc}"}
    out: Dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            continue          # битую строку квитанций разбирает уборщик, не мы
        if not isinstance(row, dict):
            continue
        tree = observed(row, "worktree", kind=str)
        if tree:
            key = _same_tree(tree)
            out[key] = out.get(key, 0) + 1
    return {"by_tree": out, "reason": None}


def _same_tree(path: Any) -> str:
    """Путь к дереву в одном написании — меркой СОСЕДА, чтобы `/tmp` ≡ `/private/tmp`.

    Ввоз отложенный намеренно: модуль соседа грузится по пути (`load_neighbours`), и
    завязывать на него разбор строки значило бы требовать соседа там, где достаточно
    написания. Правило при этом ОДНО — соседское; своей копии нет.
    """
    text = str(path or "").strip()
    if not text:
        return ""
    for prefix in ("/private/tmp/", "/private/var/"):
        if text.startswith(prefix):
            text = "/" + text[len("/private/"):]
            break
    return text.rstrip("/") or "/"


def read_registry(repo_root: Path, *, reaper, git=None) -> Dict[str, Any]:
    """Реестр деревьев git ОДНИМ вопросом: главные деревья и все зарегистрированные.

    Главное дерево — то, в которое круглосуточно пишет флот, поэтому его отметка о
    держателе захвата не говорит НИЧЕГО. Признак берётся у git (`worktree list
    --porcelain` перечисляет главное дерево первым — документированный порядок, сосед
    читает его полем ``main``), а НЕ литералом пути: литерал был бы тем самым
    «напечатанным числом», которое перестаёт быть правдой молча.

    Спрашивается РОВНО один раз намеренно: два вызова одной команды могут разойтись
    между собой (дерево заводят и снимают постоянно), и тогда «главное» и «все»
    отвечали бы о разных реестрах.
    """
    kwargs = {} if git is None else {"git": git}
    regs, why = reaper.list_registrations(str(repo_root), **kwargs)
    if regs is None:
        return {"main": None, "all": None,
                "reason": why or "реестр деревьев git не прочитан"}
    return {"main": {_same_tree(r["path"]) for r in regs if r.get("main")},
            "all": {_same_tree(r["path"]) for r in regs},
            "reason": None}


# ───────────────────────── разбор одного незакрытого захвата ─────────────────────────

def classify(row: Dict[str, Any], *, sibling, shared_main: set, archives: Dict[str, List[Path]],
             ledger: Dict[str, int], registered: set, identities: Dict[str, set]
             ) -> Dict[str, Any]:
    """Исход для ОДНОГО незакрытого захвата: дверь либо названная причина «не измерено».

    Порядок закрыт и существен: «дерево не названо» спрашивается первым (без дерева
    остальные вопросы без предмета), «общее живое дерево» — ВТОРЫМ, до двери живого
    дерева, иначе отметка флота уехала бы в span; дальше живое дерево, архив, и лишь
    затем слабые свидетельства существования.
    """
    record = row["record"]
    tree = sibling.worktree_of(record)
    out: Dict[str, Any] = {
        "card": row["card"],
        "identity_from": row["identity"][0],
        "claimed_at": row["ts"].isoformat().replace("+00:00", "Z"),
        "tree": tree,
        "outcome": None,
        "reason": None,
        "span_hours": None,
        "wrote_after_claim": None,
        "attribution": None,
    }
    if not tree:
        out["outcome"] = UNM_TREE_UNNAMED
        out["reason"] = ("запись не называет дерева ни путями, ни полем `cwd` — "
                         "спросить о времени записи негде")
        return out
    # `.get(...) or set()` склеило бы «дерево в журнале не называл никто» (не бывает:
    # строка пришла ИЗ журнала) с «назвала одна личность». Разные вещи — разный ответ.
    names = identities[tree] if tree in identities else set()
    out["attribution"] = ATTR_MULTIPLE if len(names) > 1 else ATTR_SOLE
    out["identities_naming_tree"] = len(names)

    if tree in shared_main:
        out["outcome"] = UNM_SHARED_LIVING
        out["reason"] = ("названо ОБЩЕЕ живое дерево репозитория (вердикт git): отметки "
                         "там пишет флот, а не держатель, и за span их брать нельзя")
        return out

    stamp: Optional[float] = None
    why: Optional[str] = None
    if Path(tree).is_dir():
        stamp, why = newest_write(Path(tree))
        if stamp is not None:
            out["outcome"] = DOOR_TREE
    if stamp is None and tree in archives:
        best: Optional[float] = None
        reasons: List[str] = []
        for entry in archives[tree]:
            value, note = newest_write(entry / "files")
            if value is not None and (best is None or value > best):
                best = value
            elif value is None and note:
                reasons.append(note)
        if best is not None:
            stamp, why, out["outcome"] = best, None, DOOR_ARCHIVE
        else:
            why = ("архив уборщика есть, но файлов работы в нём нет: "
                   + ("; ".join(reasons[:2]) if reasons else "каталог `files` отсутствует"))

    if stamp is None:
        if tree in archives or tree in ledger or tree in registered:
            where = [name for name, present in (("архив уборщика", tree in archives),
                                                ("квитанция снятия", tree in ledger),
                                                ("регистрация git", tree in registered))
                     if present]
            out["outcome"] = UNM_RECORD_NO_TIMES
            out["reason"] = (f"запись о дереве есть ({', '.join(where)}), времени записи "
                             f"она не несёт" + (f": {why}" if why else ""))
        else:
            out["outcome"] = UNM_NO_TRACE
            out["reason"] = ("дерева нет на диске, и ни архив уборщика, ни квитанция "
                             "снятия, ни реестр git о нём не знают — следа не осталось")
        return out

    span = (stamp - row["ts"].timestamp()) / _HOUR
    out["span_hours"] = round(span, 2)
    # Отрицательный и нулевой span — ИЗМЕРЕННЫЙ НУЛЬ: записей после захвата нет.
    # Это ответ, а не пробел, поэтому `wrote_after_claim` объявлен отдельным полем.
    out["wrote_after_claim"] = span > 0
    return out


# ───────────────────────── лестница: НАСКОЛЬКО поднимается нижняя граница ──────────────

def measure_ladder(rows: Sequence[Dict[str, Any]], latencies: Optional[Sequence[float]], *,
                   ladder: Sequence[int] = census.TTL_LADDER_HOURS) -> Dict[str, Any]:
    """На каждой ступени: что оборвал бы срок по НЕВИДИМОЙ журналу стороне — и что по видимой.

    Сетка сроков и колонка видимой стороны взяты у соседа ЦЕЛИКОМ (`TTL_LADDER_HOURS`,
    `measure_expiry_ladder`): вопрос заказа — «насколько поднимается НИЖНЯЯ ГРАНИЦА
    соседа», и посчитать её своим правилом значило бы сравнивать два разных счёта вместо
    одного и того же.

    Пустой список открытых строк подаётся соседу намеренно: его колонки пользы считаются
    по живости держателя, которую этот прибор не мерит ВОВСЕ, и повторять их здесь было
    бы вторым экземпляром чужого замера. Нужна РОВНО одна его колонка — цена.
    """
    sole = [r["span_hours"] for r in rows
            if r.get("attribution") == ATTR_SOLE and r.get("span_hours") is not None]
    multi = [r["span_hours"] for r in rows
             if r.get("attribution") == ATTR_MULTIPLE and r.get("span_hours") is not None]
    visible = census.measure_expiry_ladder([], latencies, ladder=ladder)
    steps: List[Dict[str, Any]] = []
    for step in visible["ladder"]:
        ttl = step["ttl_hours"]
        steps.append({
            "ttl_hours": ttl,
            "invisible_sole_identity": sum(1 for v in sole if v > ttl),
            "invisible_multiple_identities": sum(1 for v in multi if v > ttl),
            # Колонка СОСЕДА, не своя: то самое число, нижнюю границу которого
            # уточняет весь прибор. `None` — у соседа её нет вовсе.
            "visible_self_closing": step["would_have_cut_self_closing_work"],
        })
    return {
        "measured": True,
        "ladder": steps,
        "population_sole_identity": len(sole),
        "population_multiple_identities": len(multi),
        "visible_population": visible["cost_population"],
        "direction_down": ("span есть НИЖНЯЯ граница самого span: последняя отметка записи "
                           "не есть последний момент работы, поэтому вред срока по этой оси "
                           "ЗАНИЖАЕТСЯ"),
        "direction_up": ("дерево, названное больше чем одной личностью, атрибуции не даёт: "
                         "свежую отметку мог поставить сосед, поэтому вред по колонке "
                         "`multiple_identities` ЗАВЫШАЕТСЯ"),
        "refuses_to_name_a_ttl": ("срок прибор НЕ называет и заводить не предлагает — "
                                  "как и сосед ADR-536: лестница есть ОСНОВАНИЕ для "
                                  "решения, а не решение"),
    }


def _percentiles(values: Sequence[float]) -> Optional[Dict[str, float]]:
    """Распределение span. ``None`` — мерить нечего (это НЕ нули)."""
    if not values:
        return None
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 2),
        "p50": round(census._percentile(ordered, 0.50), 2),
        "p90": round(census._percentile(ordered, 0.90), 2),
        "p99": round(census._percentile(ordered, 0.99), 2),
        "max": round(ordered[-1], 2),
    }


# ───────────────────────────────── отчёт ─────────────────────────────────

def build_report(repo_root: Path, *, now: Optional[datetime] = None,
                 journal_path: Optional[Path] = None,
                 archive_root: Optional[Path] = None,
                 ledger_path: Optional[Path] = None,
                 git=None,
                 neighbours: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Отчёт прибора. Форма ПОСТОЯННА: ключи объявлены всегда, «не вычислено» — ``None``."""
    stamp = now or datetime.now(timezone.utc)
    report: Dict[str, Any] = {
        "generated_at": stamp.isoformat().replace("+00:00", "Z"),
        "order": ORDER,
        "measured": False,
        "status": STATUS_UNMEASURED,
        "reason": None,
        "applied": False,
        "population": None,
        "doors": None,
        "spans": None,
        "ladder": None,
        "sources": None,
    }
    kin = neighbours if neighbours is not None else load_neighbours(repo_root)
    if kin["missing"]:
        report["reason"] = ("не загружены соседние мерки: " + ", ".join(kin["missing"])
                            + " — население, разбор дерева и реестр git спрашиваются у "
                              "них, своего экземпляра у прибора нет намеренно")
        return report
    sibling, reaper = kin["sibling"], kin["reaper"]

    journal = census.read_journal(
        Path(journal_path) if journal_path is not None else repo_root / census.JOURNAL_REL)
    if journal["records"] is None:
        report["reason"] = journal["reason"]
        return report

    found = open_claims_and_latencies(journal["records"], guard=kin["guard"], sibling=sibling)
    rows_in = found["open_claims"]
    report["population"] = {
        "records": len(journal["records"]),
        "broken_lines": journal["broken_lines"],
        "claims": len(found["population"]["claims"]),
        "releases": len(found["population"]["releases"]),
        "closed_pairs": found["latency"]["closed_pairs"],
        "open_claims": len(rows_in),
    }
    if not rows_in:
        # Нуль незакрытых захватов — ИЗМЕРЕННЫЙ нуль у соседа, но для ЭТОГО прибора он
        # означает «предмета нет»: уточнять нижнюю границу нечем и незачем. Это третий
        # исход с названной причиной, а не «класс неизмерим».
        report["reason"] = ("незакрытых захватов нет: вторая сторона цены оси D не имеет "
                            "предмета (это ИЗМЕРЕННЫЙ нуль населения, не отказ замера)")
        return report

    registry = read_registry(repo_root, reaper=reaper, git=git)
    shared = observed(registry, "main", kind=set)
    if shared is None:
        report["reason"] = (f"какое дерево ОБЩЕЕ — не измерено ({registry['reason']}); без "
                            "этого ответа отметки прод-дерева, которые пишет флот, уехали "
                            "бы в span как работа сессии")
        return report
    registered = observed(registry, "all", kind=set)

    archives = read_archives(Path(archive_root) if archive_root is not None
                             else Path(reaper.ARCHIVE_ROOT))
    ledger = read_ledger(Path(ledger_path) if ledger_path is not None
                         else repo_root / LEDGER_REL)
    # Нечитаемый источник свидетельств — ОТКАЗ, а не пустое множество. Подстановка `{}`
    # здесь молча выдавала бы «следа не осталось» за измеренный исход на КАЖДОЙ строке,
    # то есть изготовила бы объявление «класс неизмерим» из собственной слепоты.
    archives_by_tree = observed(archives, "by_tree", kind=dict)
    ledger_by_tree = observed(ledger, "by_tree", kind=dict)
    if archives_by_tree is None or ledger_by_tree is None:
        report["reason"] = ("источник свидетельств не прочитан ⇒ «следа не осталось» было "
                            "бы выдумкой: "
                            + "; ".join(x for x in (archives["reason"], ledger["reason"]) if x))
        return report
    report["sources"] = {
        "journal": str(journal_path if journal_path is not None
                       else repo_root / census.JOURNAL_REL),
        "archive_root": str(archive_root if archive_root is not None
                            else reaper.ARCHIVE_ROOT),
        "archives": archives["archives"],
        "archive_unreadable_manifests": archives["unreadable_manifests"],
        "archive_reason": archives["reason"],
        "ledger": str(ledger_path if ledger_path is not None else repo_root / LEDGER_REL),
        "ledger_reason": ledger["reason"],
        "shared_living_trees": sorted(shared),
        "registered_trees": None if registered is None else len(registered),
    }

    identities = identities_by_tree(journal["records"], sibling=sibling)
    rows = [classify(row, sibling=sibling, shared_main=shared,
                     archives=archives_by_tree, ledger=ledger_by_tree,
                     registered=registered if registered is not None else set(),
                     identities=identities)
            for row in rows_in]

    counts = {name: sum(1 for r in rows if r["outcome"] == name)
              for name in DOORS + UNMEASURED_OUTCOMES}
    measured_rows = [r for r in rows if r["outcome"] in DOORS]
    report["doors"] = {
        "counts": counts,
        "measured": len(measured_rows),
        "unmeasured": len(rows) - len(measured_rows),
        "measurable_share_pct": round(100.0 * len(measured_rows) / len(rows), 2),
    }
    spans = [r["span_hours"] for r in measured_rows if r["span_hours"] is not None]
    wrote = [r for r in measured_rows if r["wrote_after_claim"]]
    report["spans"] = {
        "rows": len(measured_rows),
        "wrote_after_claim": len(wrote),
        "measured_zero_no_write_after_claim": len(measured_rows) - len(wrote),
        "hours": _percentiles([r["span_hours"] for r in wrote
                               if r["span_hours"] is not None]),
        "hours_all_measured": _percentiles(spans),
        "by_attribution": {
            ATTR_SOLE: sum(1 for r in measured_rows if r["attribution"] == ATTR_SOLE),
            ATTR_MULTIPLE: sum(1 for r in measured_rows
                               if r["attribution"] == ATTR_MULTIPLE),
        },
    }
    report["ladder"] = measure_ladder(wrote, found["latencies"])
    report["rows"] = rows

    report["measured"] = True
    if not measured_rows:
        report["status"] = STATUS_CLASS_UNMEASURABLE
    elif report["doors"]["unmeasured"]:
        report["status"] = STATUS_PARTLY
    else:
        report["status"] = STATUS_MEASURABLE
    return report


def save_artifact(report: Dict[str, Any], data_dir: Path) -> Path:
    path = data_dir / ARTIFACT_NAME
    atomic_save(report, str(path))
    return path


def format_report(report: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    head = "вторая сторона цены оси D (заказ G111 п. 3)"
    if not report.get("measured"):
        lines.append(f"{head}: НЕ ИЗМЕРЕНО — {report.get('reason')}")
        return lines
    pop = report["population"]
    doors = observed(report, "doors", kind=dict)
    spans = observed(report, "spans", kind=dict)
    ladder = observed(report, "ladder", kind=dict)
    if doors is None or spans is None or ladder is None:
        lines.append(f"{head}: НЕ ИЗМЕРЕНО — отчёт не несёт разделов "
                     "`doors`/`spans`/`ladder`")
        return lines

    lines.append(
        f"{head}: {report['status']} · незакрытых захватов {pop['open_claims']} "
        f"(закрытых пар у соседа {pop['closed_pairs']}) · span ИЗМЕРЕН у "
        f"{doors['measured']} = {doors['measurable_share_pct']} % · НЕ ИЗМЕРЕНО "
        f"{doors['unmeasured']}")
    counts = doors["counts"]
    lines.append(
        f"[ДВЕРИ] живое дерево {counts[DOOR_TREE]} · архив уборщика "
        f"{counts[DOOR_ARCHIVE]} — архив единственная дверь, переживающая снятие дерева "
        f"(`copy2` несёт ИСХОДНУЮ отметку)")
    lines.append(
        f"[НЕ ИЗМЕРЕНО · ПО ПРИЧИНАМ] дерево не названо {counts[UNM_TREE_UNNAMED]} · "
        f"общее живое дерево {counts[UNM_SHARED_LIVING]} · запись без времени записи "
        f"{counts[UNM_RECORD_NO_TIMES]} · следа нет нигде {counts[UNM_NO_TRACE]} ⇒ "
        f"для последней доли класс НЕИЗМЕРИМ, и это объявлено, а не умолчано")
    hours = observed(spans, "hours", kind=dict)
    lines.append(
        f"[SPAN] записей после захвата {spans['wrote_after_claim']} · ИЗМЕРЕННЫЙ НУЛЬ "
        f"(после захвата не писали) {spans['measured_zero_no_write_after_claim']}; "
        + ("распределения нет — мерить нечего" if hours is None else
           f"span p50 {hours['p50']} ч · p90 {hours['p90']} ч · max {hours['max']} ч"))
    lines.append(
        f"[SPAN · АТРИБУЦИЯ] одна личность "
        f"{spans['by_attribution'][ATTR_SOLE]} · несколько "
        f"{spans['by_attribution'][ATTR_MULTIPLE]} — вторая колонка атрибуции не даёт")
    for step in ladder["ladder"]:
        visible = step["visible_self_closing"]
        lines.append(
            f"[ЛЕСТНИЦА] срок {step['ttl_hours']:>4} ч: НЕВИДИМАЯ сторона оборвала бы "
            f"{step['invisible_sole_identity']} (одна личность) + "
            f"{step['invisible_multiple_identities']} (несколько) · видимая у соседа — "
            f"{'НЕ ИЗМЕРЕНО' if visible is None else visible}")
    lines.append(f"[НАПРАВЛЕНИЕ ↓] {ladder['direction_down']}")
    lines.append(f"[НАПРАВЛЕНИЕ ↑] {ladder['direction_up']}")
    lines.append(f"[ЛЕСТНИЦА] {ladder['refuses_to_name_a_ttl']}")
    lines.append(
        "НЕ ДОКЛАДЫВАЕТ: сделана ли работа (отметка записи говорит о записи, не о "
        "результате) · была ли сессия жива между захватом и последней записью · что "
        "лежало в дереве, не оставившем следа (для этой доли класс НЕИЗМЕРИМ) · надо ли "
        "заводить срок и какой")
    lines.append(
        "ADVISORY: прибор только ЧИТАЕТ (applied=False) — журнал, деревья, архив и реестр "
        "git; деревьев не снимает, карточек не двигает, срока не заводит. RiskPolicy v1.0, "
        "стоп-кран, аллокатор, живой трек и landing/ не трогаются")
    return lines


def run(root: Optional[str] = None, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Точка входа ступени моста (`findings_bridge`).

    Артефакт оставляется ВСЕГДА, включая третий исход: «не измерено» с названной
    причиной обязано доехать до шага 0-офис, иначе отсутствие файла неотличимо от
    «ступень не запускалась».
    """
    repo_root = Path(root) if root else Path(__file__).resolve().parents[2]
    report = build_report(repo_root, now=now)
    try:
        save_artifact(report, repo_root / "data")
    except Exception as exc:  # noqa: BLE001 — прибор не смеет валить мост
        report = dict(report)
        report["artifact_not_written"] = f"{type(exc).__name__}: {exc}"
    return {"measured": bool(report.get("measured")), "doc": report}


def exit_code_for(report: Dict[str, Any]) -> int:
    """0 — весь класс измерим · 1 — часть объявлена неизмеримой · 2 — замера нет вовсе."""
    if not report.get("measured"):
        return 2
    return 0 if report["status"] == STATUS_MEASURABLE else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo-root", default=None, help="корень дерева (по умолчанию — своё)")
    ap.add_argument("--journal", default=None,
                    help=f"журнал объявлений (по умолчанию — {census.JOURNAL_REL})")
    ap.add_argument("--archive-root", default=None,
                    help="каталог архива уборщика (по умолчанию — его же умолчание)")
    ap.add_argument("--ledger", default=None,
                    help=f"квитанции уборщика (по умолчанию — {LEDGER_REL})")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true", help=f"записать data/{ARTIFACT_NAME}")
    args = ap.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[2]
    report = build_report(
        repo_root,
        journal_path=Path(args.journal) if args.journal else None,
        archive_root=Path(args.archive_root) if args.archive_root else None,
        ledger_path=Path(args.ledger) if args.ledger else None)
    if args.save:
        save_artifact(report, repo_root / "data")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for line in format_report(report):
            print(line)
    return exit_code_for(report)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
