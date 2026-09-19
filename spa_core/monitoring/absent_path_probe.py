"""Поведенческий зонд: что сторож ДЕЛАЕТ, когда его входа-пути в дереве нет.

Заказ **G46, п. 1** приказа владельца «Portfolio CIO» — дословный хвост
ADR-421:

    «Поведенческий зонд без правки исходника. Здесь дверь разобрана СТАТИКОЙ,
    а прогоном перемерены 4 строки из населения руками. Зонд обязан делать то
    же машинно: унести путь в одноразовом дереве, прогнать сторожа, вернуть
    путь и сверить по sha. Это ДРУГОЙ механизм, чем у `vacuous_guard_probe`
    (тот правит исходник), и население у него шире: `no_door`-строки с живым
    путём проверяются только так.»

## Чем этот опыт отличается от соседнего зонда

`vacuous_guard_probe` (ADR-420) опустошает вход ПРАВКОЙ ИСХОДНИКА: перечень
записан литералом, и другого способа его опустошить нет. Здесь вход собирается
ВЫЗОВОМ (`ROOT.rglob`, `PATH.read_text`), и правка исходника не нужна вовсе —
достаточно унести путь. Исходник сторожа этот зонд не трогает НИ РАЗУ, и это
не оговорка, а разница в населении: строка `no_door` с живым путём в соседний
зонд не входит по построению.

## Опыт

В ОДНОРАЗОВОМ дереве (`git worktree add --detach` на sha рабочего):

1. база: прогон сторожа как есть. Не зелен или не выполнил ни одного теста ⇒
   `unmeasured` — сдвиг вердикта мерить не от чего;
2. путь УНОСИТСЯ (`rename` в соседнее имя), и унос ПРОВЕРЯЕТСЯ: молча не
   применившийся унос дал бы «вердикт не изменился» и выглядел бы ответом;
3. прогон;
4. путь возвращается и сверяется ПО SHA (у каталога — по манифесту всех его
   файлов). Несовпадение — громкий отказ, а не продолжение: дальнейшие опыты
   в таком дереве недостоверны.

Рабочее дерево на запись не открывается ни разу.

## Четыре исхода опыта, и три из них — вердикты

| исход | что наблюдалось | что значит |
|---|---|---|
| `refuses_absent` | прогон КРАСНЕЕТ | сторож заметил отсутствие |
| `announces_absence` | зелен, но тестов прошло МЕНЬШЕ | сторож СКАЗАЛ, что не смотрел (скип) |
| `vacuous_pass` | зелен, и прошло столько же | осмотрено ноль, и об этом не сказано ничего |
| `scene_destroyed` | сбор тестов сломался | унос сломал СЦЕНУ, а не ослепил сторожа |

`scene_destroyed` — отдельное значение, а не «краснеет». Унести
`spa_core/utils` значит сломать ввоз половине набора: прогон покраснеет, и
приписать эту красноту сторожу значило бы выдумать находку. Различает их
ПРИЧИНА красноты (код возврата pytest и раздел `error` сводки), а не её факт.

## Положительный контроль встроен в население

Зондируются ВСЕ строки с живым путём, а не только `no_door`. Строка, которую
статика назвала `refuses_or_skips`, обязана вести себя как отказ, — и если
ведёт, это контроль прибора на настоящем контуре, а не украшение. Расхождение
статики с прогоном называется поимённо: право на вердикт даёт прогон, статика
же остаётся дешёвым приближением (ровно так ADR-421 опроверг четыре своих
первых вердикта — но руками и на четырёх строках).

## Третий исход (инв. #17)

`unmeasured` с НАЗВАННОЙ причиной: нет pytest (спрошен ОТДЕЛЬНЫМ вопросом —
рабочий прогон выходит ненулевым именно тогда, когда что-то нашёл); сторож
красен на базе; путь есть КОРЕНЬ дерева (унести его нечем); путь СОДЕРЖИТ
самого сторожа (унос убрал бы и предмет, и сцену); пути нет в одноразовом
дереве; унос не применился; прогон не уложился в срок; сторож изменён в
рабочем дереве.
"""

from __future__ import annotations

# --- РАЗЗАТЕНЕНИЕ stdlib. Обязано стоять ВЫШЕ всех ввозов, и это замер ------
# Запуск ПО ПУТИ делает `sys.path[0]` каталогом скрипта, а в
# `spa_core/monitoring/` живёт свой `signal.py` (RTMR, ADR-053). Тогда
# `import signal` внутри `subprocess` достаёт НАШ модуль, а не стандартный, и
# умирает ИМЕННО путь отказа — `subprocess.run(..., timeout=)` по срабатыванию
# срока зовёт `process.kill()` → `signal.SIGKILL`. То есть падает третий исход,
# ради которого срок и поставлен (замер 19.09, цикл #638). Сравнение по
# REALPATH, а не abspath: `sys.path[0]` разыменован, а на macOS `/tmp` есть
# ссылка на `/private/tmp` — версия с abspath не убирала каталог вообще.
import os  # noqa: E402
import sys  # noqa: E402

_HERE = os.path.realpath(os.path.dirname(os.path.abspath(__file__)))
sys.path[:] = [p for p in sys.path
               if os.path.realpath(p or os.getcwd()) != _HERE]
# ---------------------------------------------------------------------------

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import random  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Dict, List, Optional, Tuple  # noqa: E402

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:  # запуск ПО ПУТИ, а не пакетом
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import call_sourced_input_census as census  # noqa: E402
# Проводка опыта (одноразовое дерево, среда прогона, отдельный вопрос о
# наличии pytest, разбор сводки pytest) ВВОЗИТСЯ, а не переписывается: второй
# копии этих правил в репозитории быть не должно (ADR-417/418, и весь этот
# заказ вырос из той переписи).
from spa_core.monitoring import copy_independence_probe as base  # noqa: E402
from spa_core.monitoring import vacuous_guard_probe as vgp  # noqa: E402
from spa_core.monitoring.call_provenance import call_provenance  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402
from spa_core.utils.observation import observed, observed_number  # noqa: E402

#: Имя журнала ВВОЗИТСЯ у переписи: она владеет и координатой строки, и
#: именем своего читателя. Вторая копия имени разошлась бы молча (ADR-418).
ARTIFACT = census.BEHAVIOUR_LEDGER
PRODUCER = "spa_core/monitoring/absent_path_probe.py"
TREE_PREFIX = "spa_absent_probe_"

NotMeasured = base.NotMeasured

VERDICT_VACUOUS = "vacuous_pass"
VERDICT_REFUSES = "refuses_absent"
VERDICT_ANNOUNCES = "announces_absence"
VERDICT_SCENE = "scene_destroyed"
VERDICT_UNMEASURED = "unmeasured"
#: Тест СТРОКИ не бежит в этом дереве вовсе — его пропустил `skipif` ещё ДО
#: опыта. Слепотой это не является и вердиктом о двери тоже: сторож ничего не
#: сказал потому, что его не звали. Исход заведён замером (цикл #642): счёт
#: `passed` у пропущенного теста не меняется ни до уноса, ни после, поэтому
#: пропуск был НЕОТЛИЧИМ от вырожденного прохода — и четыре строки из девяти
#: находок ADR-424 оказались именно им.
VERDICT_ALREADY_SKIPPED = "already_skipped"
VERDICTS = (VERDICT_VACUOUS, VERDICT_REFUSES, VERDICT_ANNOUNCES,
            VERDICT_SCENE, VERDICT_UNMEASURED, VERDICT_ALREADY_SKIPPED)

#: Состояния СОБСТВЕННОГО теста строки в целом дереве. Вопрос задаётся ВСЕМУ
#: населению (заказ G48 п. 2), а не только строкам с исходом `vacuous_pass`.
#: Прежняя редакция спрашивала лениво и обосновывала это рассуждением
#: («маскироваться пропуск может лишь под вырожденный проход: у прочих исходов
#: тест заведомо бежал»). Рассуждение верно ровно наполовину: под `vacuous_pass`
#: пропуск действительно МАСКИРУЕТСЯ, но у соседних исходов он значит другое и
#: не менее существенное — строка, чей тест не звали, получает вердикт,
#: произведённый СОСЕДОМ по файлу. Догадку сменяет число.
OWN_RAN = "ran"
OWN_SKIPPED = "skipped"
OWN_NOT_ADDRESSABLE = "not_addressable"
OWN_UNKNOWN = "unknown"
#: Вопрос не задавался вовсе. Это НЕ «неизвестно»: «спросили и не разобрали
#: ответ» и «не спрашивали» — разные состояния, и слить их значило бы вернуть
#: ровно ту слепоту, против которой заведён сам вопрос (инв. #17).
OWN_NOT_ASKED = "not_asked"
OWN_STATES = (OWN_RAN, OWN_SKIPPED, OWN_NOT_ADDRESSABLE, OWN_UNKNOWN,
              OWN_NOT_ASKED)

#: Вердикты, при которых сторож при отсутствующем входе остаётся ЗЕЛЁНЫМ и об
#: этом не говорит ничего. Это и есть находка зонда.
FINDING_VERDICTS = (VERDICT_VACUOUS,)

#: Срок одного прогона сторожа. Не уложился ⇒ «не измерено», а не «зелено».
RUN_TIMEOUT_S = 420

#: Зерно выборки названо здесь, а не выбирается на бегу: замер обязан
#: воспроизводиться. Умолчание `None` = всё население: живых путей в замере
#: 19.09 сорок шесть, и выборка из такого населения была бы потерей, а не
#: экономией.
SAMPLE_SEED = 20260919
DEFAULT_SAMPLE = None

#: Сколько знаков вывода сбора тестов сохраняется. Умолчание проводки (2000)
#: здесь мало: сбор одного параметризованного теста даёт 81 строку, и
#: обрезание превращало бы «тест есть» в «теста нет» молча.
_COLLECT_KEEP_CHARS = 400_000

#: Хвост имени, под которым путь уносится. Длинный и свой: короткое имя могло
#: бы совпасть с настоящим соседом, и тогда унос был бы перезаписью.
MOVED_SUFFIX = ".__absent_path_probe_moved__"

#: Двери статики, от которых ЖДЁТСЯ отказ в прогоне. Таблица — предмет замера
#: (совпала статика с прогоном или нет), а не правило вердикта: вердикт даёт
#: прогон.
_DOOR_EXPECTS_REFUSAL = census.DOORS_EXPECTING_REFUSAL


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# 1. Отпечаток пути: файл — по содержимому, каталог — по манифесту
# ══════════════════════════════════════════════════════════════════════════════

def fingerprint(path: Path) -> Optional[str]:
    """Отпечаток пути; ``None`` — путь не прочитан.

    У каталога сверять нечего, кроме СОСТАВА: sha одного файла не заметил бы
    ни пропавшего соседа, ни переставленного имени. Поэтому манифест — пары
    «относительное имя → sha» в отсортированном порядке, и уже он хешируется.
    Пустой каталог даёт отпечаток пустого манифеста, а не ``None``: «каталог
    есть и он пуст» и «каталога нет» обязаны быть различимы (инв. #17).
    """
    try:
        if path.is_file():
            return "f:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_dir():
            digest = hashlib.sha256()
            for item in sorted(path.rglob("*")):
                rel = item.relative_to(path).as_posix()
                if item.is_dir():
                    digest.update(f"d {rel}\n".encode())
                    continue
                try:
                    body = hashlib.sha256(item.read_bytes()).hexdigest()
                except OSError:
                    body = "unreadable"
                digest.update(f"f {rel} {body}\n".encode())
            return "d:" + digest.hexdigest()
    except OSError:
        return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 2. Население и выборка
# ══════════════════════════════════════════════════════════════════════════════

def population(rows: List[dict]) -> List[dict]:
    """Строки переписи с ЖИВЫМ путём: только их и можно унести.

    Строка, чьего пути в дереве нет уже сегодня, зондом не проверяется — её
    исход перепись и так называет находкой, а уносить нечего.
    """
    return [r for r in rows if r.get("present_here") == census.PRESENT_YES]


def select(rows: List[dict], *, sample: Optional[int] = DEFAULT_SAMPLE,
           seed: int = SAMPLE_SEED) -> List[dict]:
    """Кого зондировать. Правило выборки названо и воспроизводимо."""
    chosen = population(rows)
    if sample is not None and sample < len(chosen):
        chosen = random.Random(seed).sample(chosen, sample)
    chosen.sort(key=lambda r: r["key"])
    return chosen


# ══════════════════════════════════════════════════════════════════════════════
# 3. Один опыт
# ══════════════════════════════════════════════════════════════════════════════

def _blocking_reason(tree: Path, row: dict) -> Optional[str]:
    """Почему этот путь унести НЕЛЬЗЯ; ``None`` — опыт возможен.

    Причины разные по существу, и сливать их нельзя: «путь есть корень» —
    свойство координаты, «пути нет в дереве» — свойство дерева, «путь содержит
    сторожа» — свойство пары. Каждая печатается своими словами.
    """
    rel = str(row.get("path") or "")
    guard_rel = str(row.get("guard") or "")
    if rel in ("", "."):
        return ("путь есть КОРЕНЬ дерева — унести его нечем, и опыт над ним "
                "был бы опытом над самим прогоном")
    target = tree / rel
    guard = tree / guard_rel
    if target == guard or target in guard.parents:
        return (f"путь `{rel}` СОДЕРЖИТ самого сторожа `{guard_rel}` — унос "
                f"убрал бы вместе со входом и сцену, и краснота ничего не "
                f"сказала бы о слепоте")
    if not target.exists():
        return f"пути `{rel}` нет в одноразовом дереве — уносить нечего"
    if (target.parent / (target.name + MOVED_SUFFIX)).exists():
        return f"имя для уноса `{target.name}{MOVED_SUFFIX}` занято"
    return None


def probe_row(tree: Path, row: dict, *,
              baselines: Dict[str, Tuple[int, str]],
              id_cache: Optional[Dict[str, Optional[List[str]]]] = None) -> dict:
    """Один опыт + вопрос о собственном тесте строки — ВСЕГДА, любому исходу.

    Два вопроса разведены намеренно и задаются в этом порядке: сначала опыт
    (что сторож ДЕЛАЕТ без входа), затем — бежал ли вообще тест ЭТОЙ строки.
    Обратный порядок был бы дешевле, но он же и молчаливее: строку с
    пропущенным тестом он снял бы с опыта, и «сторож слеп» стало бы
    неотличимо от «сторожа не звали» у тех исходов, где пропуск ничего не
    маскирует, зато меняет АВТОРА вердикта.
    """
    entry = _experiment(tree, row, baselines=baselines)
    return _ask_own_test(tree, entry, row, id_cache=id_cache)


def _ask_own_test(tree: Path, entry: dict, row: dict, *,
                  id_cache: Optional[Dict[str, Optional[List[str]]]] = None) -> dict:
    """Записать состояние собственного теста строки и, где надо, сменить вердикт.

    Смена вердикта на `already_skipped` остаётся ТОЛЬКО у `vacuous_pass`, и
    теперь это замер, а не умолчание: у прочих исходов пропуск собственного
    теста наблюдается и НАЗЫВАЕТСЯ отдельным полем, но исход опыта он не
    объясняет — краснота или объявление пришли от соседа по файлу, то есть
    наблюдение о стороже состоялось, просто произвёл его не этот тест.
    """
    entry["own_test"] = own_test_state(
        tree, str(entry.get("guard") or ""), str(row.get("scope") or ""),
        cache=id_cache)
    if (entry.get("verdict") == VERDICT_VACUOUS
            and entry["own_test"] == OWN_SKIPPED):
        entry["verdict"] = VERDICT_ALREADY_SKIPPED
        entry["evidence"] = (
            f"собственный тест строки `{row.get('scope')}` ПРОПУЩЕН в этом "
            f"дереве ещё до опыта — сторож молчал не от слепоты, а потому "
            f"что его не звали; счёт passed у пропущенного теста не "
            f"меняется ни до уноса, ни после")
    return entry


def _experiment(tree: Path, row: dict, *,
                baselines: Dict[str, Tuple[int, str]]) -> dict:
    """Один опыт: до двух прогонов сторожа в ОДНОРАЗОВОМ дереве."""
    guard_rel = str(row.get("guard") or "")
    entry = {
        "key": row.get("key"), "guard": guard_rel, "line": row.get("line"),
        "scope": row.get("scope"), "anchor": row.get("anchor"),
        "path": row.get("path"), "kind": row.get("kind"),
        "static_door": row.get("door"), "guard_sha": row.get("guard_sha"),
        "verdict": VERDICT_UNMEASURED, "evidence": "", "failed_tests": [],
    }

    blocked = _blocking_reason(tree, row)
    if blocked:
        entry["evidence"] = blocked
        return entry

    if guard_rel not in baselines:
        baselines[guard_rel] = vgp.run_guard(tree, guard_rel)
    base_code, base_out = baselines[guard_rel]
    base_passed = vgp.passed_count(base_out)
    entry["baseline_code"] = base_code
    entry["baseline_passed"] = base_passed
    if base_code < 0:
        # Срок — не краснота: «сторож НЕ зелен» о не уложившемся прогоне было
        # бы утверждением о стороже, которого никто не наблюдал.
        entry["evidence"] = (f"прогон сторожа на базе не уложился в "
                             f"{vgp.RUN_TIMEOUT_S} с — НЕ ИЗМЕРЕНО")
        return entry
    if base_code != 0:
        why = vgp._NO_VERDICT_CODES.get(base_code, f"код {base_code}")
        entry["evidence"] = (f"сторож НЕ зелен на базе ({why}) — слепоту мерить "
                             f"не от чего: {base_out.strip()[-200:]}")
        return entry
    if not base_passed:
        entry["evidence"] = ("сторож на базе не выполнил НИ ОДНОГО теста (всё "
                             "пропущено или ничего не собрано) — «зелёный без "
                             "входа» тут ничего не значит")
        return entry

    target = tree / str(row["path"])
    moved = target.parent / (target.name + MOVED_SUFFIX)
    before = fingerprint(target)
    if before is None:
        entry["evidence"] = f"отпечаток пути `{row['path']}` не снят — опыт не ставится"
        return entry

    try:
        target.rename(moved)
    except OSError as exc:
        entry["evidence"] = f"путь не унесён: {exc}"
        return entry
    try:
        if target.exists():
            # Молча не применившийся унос дал бы «вердикт не изменился» и
            # выглядел бы ответом. Поэтому применение ПРОВЕРЯЕТСЯ.
            entry["evidence"] = f"унос `{row['path']}` не применился — путь на месте"
            return entry
        code, out = vgp.run_guard(tree, guard_rel)
    finally:
        # Сторож мог не просто промолчать, а СОЗДАТЬ свой вход заново (замер
        # 19.09: `test_consume_office_reports.py` завёл `data/` сам, и возврат
        # упал на «каталог не пуст»). Это наблюдение о стороже, а не помеха:
        # оно записывается, а созданное прогоном убирается — иначе отпечаток
        # сверял бы чужой каталог с нашим.
        entry["path_recreated_by_run"] = target.exists()
        if entry["path_recreated_by_run"]:
            if tree.resolve() not in target.resolve().parents:
                raise NotMeasured(
                    f"созданный прогоном путь `{row['path']}` лежит ВНЕ "
                    f"одноразового дерева — прибор ничего не удаляет снаружи")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        try:
            moved.rename(target)
        except OSError as exc:
            raise NotMeasured(
                f"путь `{row['path']}` не возвращён после опыта над {guard_rel} "
                f"({exc}) — дальнейшие опыты в этом дереве недостоверны") from exc
        after = fingerprint(target)
        if after != before:
            raise NotMeasured(
                f"одноразовое дерево не восстановлено после опыта над "
                f"{guard_rel}: отпечаток `{row['path']}` до опыта {before}, "
                f"после {after} — дальнейшие опыты недостоверны")

    entry["absent_code"] = code
    entry["absent_passed"] = vgp.passed_count(out)
    # Вопрос о собственном тесте задаёт зовущий (`_ask_own_test`) — и задаёт
    # его ПОСЛЕ возврата пути (блок `finally` выше), то есть о ЦЕЛОМ дереве.
    return _verdict(entry, code, out, base_passed)


def own_test_ids(tree: Path, guard_rel: str, scope: str, *,
                 cache: Optional[Dict[str, Optional[List[str]]]] = None
                 ) -> Optional[List[str]]:
    """Адреса теста ``scope`` в файле — СПРОШЕНЫ У pytest, а не собраны нами.

    ``None`` — сбор не ответил (третий исход). Пустой список — pytest собрал
    файл и такого теста в нём НЕТ; это ответ, а не молчание.

    Почему не селектор `файл::имя` (замер #643, он же находка этого цикла).
    Метод внутри класса им НЕ адресуется: `pytest f.py::test_x` для
    `class C: def test_x` печатает «no tests ran» и выходит КОДОМ 0, и прежняя
    редакция читала это как «имя тестом не является». На живом населении так
    были помечены **29 строк из 47** — среди них
    `test_does_not_use_bsd_unsafe_newermt_epoch`, который в тот же час падал
    в прогоне сторожа под именем
    `TestGateExistsAndParses::test_does_not_use_bsd_unsafe_newermt_epoch`.
    То есть «не тест» выдавалось за ответ там, где тест есть, и весь исход
    `already_skipped` для классовых тестов был недостижим ПО ПОСТРОЕНИЮ.

    Правило адресации при этом не переписывается здесь второй копией
    (ADR-417/418): имена спрашиваются у самого pytest сбором, а наше дело —
    выбрать среди них те, чей ПОСЛЕДНИЙ сегмент равен ``scope`` (или
    начинается с `scope[` — параметризация). Сравнение сегментом, а не
    подстрокой: `test_x` и `test_x_and_more` подстрокой неразличимы.
    """
    key = f"{guard_rel}::{scope}"
    if cache is not None and key in cache:
        collected = cache[key]
    else:
        # `-k` СУЖАЕТ вывод, но ответом не является: подстрокой `test_walks`
        # выбирает и `test_walks_and_more`. Точность даёт сверка СЕГМЕНТА
        # ниже, а `-k` лишь бережёт вывод от обрезания.
        code, out = base._run(
            [sys.executable, "-m", "pytest", guard_rel, "--collect-only",
             "-q", "-p", "no:randomly", "-k", scope],
            cwd=tree, timeout=RUN_TIMEOUT_S, keep=_COLLECT_KEEP_CHARS)
        collected = _collected_ids(out, guard_rel) if code >= 0 else None
        if cache is not None:
            cache[key] = collected
    if collected is None:
        return None
    return [nid for nid in collected
            if nid.split("::")[-1] == scope
            or nid.split("::")[-1].startswith(scope + "[")]


def _collected_ids(out: str, guard_rel: str) -> Optional[List[str]]:
    """Адреса из вывода `--collect-only -q`; ``None`` — вывод не подтверждён.

    Число собранного pytest ОБЪЯВЛЯЕТ сам (`3/160 tests collected`,
    `no tests collected`), и разобранный перечень обязан с этим числом
    сойтись. Не сошёлся — вывод обрезан или не разобран, и это третий исход:
    короткий перечень читался бы как «такого теста нет», то есть «не
    измерено» пришло бы под видом ответа (инв. #17).
    """
    # Сбор, умерший ошибкой, печатает ТУ ЖЕ сводку «no tests collected» —
    # с припиской «, 1 error». Прочесть её как «такого теста нет» значило бы
    # снять строку с учёта поломкой файла. Разбор сводки ВВОЗИТСЯ у соседа:
    # второй копии правила «где живёт сводка» быть не должно (ADR-417).
    if vgp.summary_count(out, "error"):
        return None
    declared = None
    for line in reversed((out or "").splitlines()):
        stripped = line.strip()
        if "tests collected" in stripped or "test collected" in stripped:
            if stripped.startswith("no tests collected"):
                declared = 0
            else:
                match = re.match(r"(\d+)(?:/\d+)? tests? collected", stripped)
                declared = int(match.group(1)) if match else None
            break
    if declared is None:
        return None
    ids = [line.strip() for line in (out or "").splitlines()
           if "::" in line and line.strip().startswith(guard_rel + "::")]
    return ids if len(ids) == declared else None


def own_test_state(tree: Path, guard_rel: str, scope: str, *,
                   cache: Optional[Dict[str, Optional[List[str]]]] = None) -> str:
    """Бежит ли в ЭТОМ дереве собственный тест строки — или он пропущен.

    Вопрос отдельный от прогона сторожа, и он ОБЯЗАН быть отдельным: прогон
    считает `passed` по ВСЕМУ файлу, а пропущенный `skipif`-ом тест не
    прибавляет к этому счёту ни до уноса пути, ни после. Два разных состояния
    («осмотрел ноль и промолчал» и «не звали вовсе») давали один и тот же
    признак, и различить их файловым счётом нельзя в принципе.

    ``scope`` у строки — имя объемлющей функции, и тестом оно бывает не
    всегда (помощник, фикстура). Неадресуемый ``scope`` — третий исход
    (`not_addressable`), а не «бежал»: выдуманное «бежал» вернуло бы ровно ту
    слепоту, ради которой вопрос и задан. Но и «не тест» обязано быть
    ИЗМЕРЕНО, а не выведено из формы селектора — см. `own_test_ids`.
    """
    if not scope:
        return OWN_NOT_ADDRESSABLE
    ids = own_test_ids(tree, guard_rel, scope, cache=cache)
    if ids is None:
        return OWN_UNKNOWN   # сбор не ответил — молчать честнее, чем гадать
    if not ids:
        return OWN_NOT_ADDRESSABLE
    code, out = base._run(
        [sys.executable, "-m", "pytest", *ids, "-q", "--tb=no",
         "-p", "no:randomly"],
        cwd=tree, timeout=RUN_TIMEOUT_S)
    if code < 0 or code in vgp._NO_VERDICT_CODES:
        return OWN_UNKNOWN
    passed = vgp.summary_count(out, "passed")
    skipped = vgp.summary_count(out, "skipped")
    failed = vgp.summary_count(out, "failed")
    if passed is None or skipped is None:
        return OWN_UNKNOWN   # сводка не разобрана — молчать честнее, чем гадать
    if passed or failed:
        return OWN_RAN
    return OWN_SKIPPED if skipped else OWN_NOT_ADDRESSABLE


def own_test_tally(entries: List[dict]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Второе число заказа G48 п. 2: состояние собственного теста у ВСЕГО населения.

    Функция отдельная, потому что её и надо уметь спросить без прогона: в
    замере на настоящем контуре поле есть у каждой строки, и подстановка
    удобного умолчания внутри цикла осталась бы НЕизмеримой (батарея #643,
    мутация 3 выжила именно так). Строка без поля считается ``not_asked``, а
    не «бежал»: удобное умолчание и есть подмена «не измерено» успехом
    (инв. #17). Незнакомое значение — ``unknown``, а не тихо отброшенное.
    """
    own_counts = {st: 0 for st in OWN_STATES}
    by_verdict = {v: 0 for v in VERDICTS}
    for entry in entries:
        state = entry.get("own_test") or OWN_NOT_ASKED
        if state not in own_counts:
            state = OWN_UNKNOWN
        own_counts[state] += 1
        if state == OWN_SKIPPED:
            by_verdict[entry.get("verdict", VERDICT_UNMEASURED)] += 1
    return own_counts, by_verdict


def _verdict(entry: dict, code: int, out: str, base_passed: int) -> dict:
    """Исход прогона без входа → вердикт строки.

    Порядок вопросов существен: сначала спрашивается, ЦЕЛА ли сцена, и только
    потом — что сказал сторож. Обратный порядок записал бы поломку сбора
    тестов в «сторож заметил отсутствие», то есть выдумал бы исправность.
    """
    # Вердикт по умолчанию ставится ЗДЕСЬ, а не предполагается у зовущего:
    # функция, чей исход зависит от того, что поле кто-то заполнил заранее,
    # молча вернула бы запись без вердикта вовсе.
    entry.setdefault("verdict", VERDICT_UNMEASURED)
    if code < 0:
        entry["evidence"] = out.strip()[-200:] or f"прогон не уложился в {RUN_TIMEOUT_S} с"
        return entry
    if code in vgp._NO_VERDICT_CODES:
        entry["verdict"] = VERDICT_SCENE
        entry["evidence"] = (f"{vgp._NO_VERDICT_CODES[code]} без пути "
                             f"`{entry['path']}` — унос сломал СЦЕНУ, а не "
                             f"ослепил сторожа")
        return entry
    errors = vgp.summary_count(out, "error")
    if errors:
        entry["verdict"] = VERDICT_SCENE
        entry["evidence"] = (f"без пути `{entry['path']}` сбор тестов дал "
                             f"{errors} ошибк(и) — унос сломал СЦЕНУ, а не "
                             f"ослепил сторожа")
        return entry
    if code != 0:
        entry["verdict"] = VERDICT_REFUSES
        entry["failed_tests"] = vgp.failed_tests(out)
        scope = str(entry.get("scope") or "")
        entry["consumer_is_red"] = any(
            scope and scope in name for name in entry["failed_tests"])
        entry["evidence"] = (
            f"сторож КРАСНЕЕТ без пути `{entry['path']}` (код {code}); упали "
            f"{', '.join(entry['failed_tests']) or '— имена не разобраны'}")
        return entry
    passed = entry.get("absent_passed")
    if passed is None:
        entry["evidence"] = "сводка pytest не разобрана — «зелено» здесь не вердикт"
        return entry
    if passed < base_passed:
        entry["verdict"] = VERDICT_ANNOUNCES
        entry["evidence"] = (
            f"сторож зелен, но без пути `{entry['path']}` прошло {passed} "
            f"тест(ов) против {base_passed} на базе — он СКАЗАЛ, что не смотрел")
        return entry
    entry["verdict"] = VERDICT_VACUOUS
    entry["evidence"] = (
        f"сторож ЗЕЛЁН без пути `{entry['path']}` и прошло столько же тестов "
        f"({passed}) — осмотрено ноль, и об этом не сказано ничего")
    return entry


# ══════════════════════════════════════════════════════════════════════════════
# 4. Замер
# ══════════════════════════════════════════════════════════════════════════════

def agreement(entry: dict) -> Optional[bool]:
    """Совпал ли вердикт прогона с дверью, разобранной СТАТИКОЙ.

    ``None`` — сравнивать не с чем (опыт не состоялся или сцена сломалась).
    Записывать такой случай согласием значило бы засчитать статике вердикт,
    которого никто не наблюдал.
    """
    verdict = entry.get("verdict")
    if verdict in (VERDICT_UNMEASURED, VERDICT_SCENE,
                   VERDICT_ALREADY_SKIPPED):
        return None
    expects_refusal = entry.get("static_door") in _DOOR_EXPECTS_REFUSAL
    observed_refusal = verdict in (VERDICT_REFUSES, VERDICT_ANNOUNCES)
    return expects_refusal == observed_refusal


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            rows: Optional[List[dict]] = None,
            sample: Optional[int] = DEFAULT_SAMPLE,
            limit: Optional[int] = None) -> dict:
    """Журнал зонда. Одноразовое дерево заводится ЗДЕСЬ и снимается в ``finally``."""
    root = Path(root).resolve()
    if rows is None:
        try:
            rows = census.measure(root).get("rows") or []
        except census.NotMeasured as exc:
            # Отказ ввезённой переписи обязан быть исходом ЭТОГО прибора.
            # Классов `NotMeasured` в связке ДВА (свой — у зонда-основы,
            # чужой — у переписи), и непойманный чужой выходил трассировкой
            # с кодом 1, то есть «не измерено» становилось неотличимо от
            # «нашли находку». Поймано собственным контролем на дереве без
            # каталогов-сторожей.
            raise NotMeasured(str(exc)) from exc
    chosen = select(rows, sample=sample)
    if limit is not None:
        chosen = chosen[:limit]

    code, head = base._run(["git", "rev-parse", "HEAD"], cwd=root, timeout=120)
    if code != 0:
        raise NotMeasured(f"sha рабочего дерева не прочитан: {head.strip()}")
    head = head.strip().splitlines()[-1]

    # Опыт, убитый на полпути, оставляет одноразовое дерево висеть. Прибор его
    # НАЗЫВАЕТ, но не снимает: с тем же префиксом может идти соседний живой
    # опыт, и «прибрался» означало бы «убил чужой замер».
    stale = base.stale_disposable_trees(root, prefix=TREE_PREFIX)

    tmp = Path(tempfile.mkdtemp(prefix=TREE_PREFIX))
    entries: List[dict] = []
    aborted: Optional[str] = None
    try:
        tmp.rmdir()         # git worktree add требует НЕсуществующий путь
        code, out = base._run(
            ["git", "worktree", "add", "--detach", str(tmp), head],
            cwd=root, timeout=RUN_TIMEOUT_S)
        if code != 0:
            raise NotMeasured(f"одноразовое дерево не заведено: {out.strip()[-300:]}")
        available, version = base.pytest_available(tmp)
        if not available:
            raise NotMeasured(f"pytest недоступен в одноразовом дереве: {version}")

        baselines: Dict[str, Tuple[int, str]] = {}
        # Сбор тестов файла спрашивается РАЗ на сторожа: строк у одного файла
        # бывает несколько, а состав его тестов от уноса чужого пути не зависит.
        id_cache: Dict[str, Optional[List[str]]] = {}
        for row in chosen:
            if base._dirty(root, str(row.get("guard") or "")):
                entries.append({
                    "key": row.get("key"), "guard": row.get("guard"),
                    "path": row.get("path"), "static_door": row.get("door"),
                    "verdict": VERDICT_UNMEASURED,
                    # Вопрос о собственном тесте здесь НЕ задаётся, и это
                    # сказано значением: одноразовое дерево несёт HEAD, а
                    # сторож в рабочем дереве другой — ответ был бы о чужом
                    # файле. «Не спрашивали» ≠ «спросили и не поняли».
                    "own_test": OWN_NOT_ASKED,
                    "evidence": ("сторож изменён в рабочем дереве — одноразовое "
                                 "дерево несёт HEAD, то есть НЕ его")})
                continue
            try:
                entries.append(probe_row(tmp, row, baselines=baselines,
                                         id_cache=id_cache))
            except NotMeasured as exc:
                # Невозвращённый путь обрывает ВЕСЬ замер: в таком дереве
                # недостоверны и уже снятые строки, и будущие. Обрыв называется
                # и печатается, а не проглатывается.
                aborted = str(exc)
                break
    finally:
        base._run(["git", "worktree", "remove", "--force", str(tmp)],
                  cwd=root, timeout=RUN_TIMEOUT_S)

    counts = {v: 0 for v in VERDICTS}
    for entry in entries:
        entry["static_agrees"] = agreement(entry)
        counts[entry.get("verdict", VERDICT_UNMEASURED)] += 1
    own_counts, own_skipped_by_verdict = own_test_tally(entries)
    # Строка, чей тест не звали, но чей сторож при уносе пути ЗАГОВОРИЛ:
    # наблюдение состоялось, произвёл его СОСЕД по файлу. Вердикт строки от
    # этого не становится ложным — он перестаёт быть ЕЁ вердиктом, и в дереве,
    # где условие пропуска ложно, отвечать на тот же вопрос будет некому.
    neighbour_credited = [
        e for e in entries
        if (e.get("own_test") == OWN_SKIPPED
            and e.get("verdict") in (VERDICT_REFUSES, VERDICT_ANNOUNCES))]
    compared = [e for e in entries if e.get("static_agrees") is not None]
    disagree = [e for e in compared if e["static_agrees"] is False]
    # Род входа — ось, по которой расхождение статики с прогоном и распалось:
    # отсутствующий каталог даёт ПУСТОЙ обход, отсутствующий файл — ИСКЛЮЧЕНИЕ.
    # Сводить их в одно число значило бы потерять ровно тот ответ, ради
    # которого зонд написан.
    by_kind: Dict[str, Dict[str, int]] = {}
    for entry in compared:
        cell = by_kind.setdefault(str(entry.get("kind")),
                                  {"compared": 0, "disagrees": 0})
        cell["compared"] += 1
        if entry["static_agrees"] is False:
            cell["disagrees"] += 1
    recreated = [e for e in entries if e.get("path_recreated_by_run")]
    return {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": "ABORTED" if aborted else ("MEASURED" if entries else "EMPTY"),
        "aborted_reason": aborted,
        "question": "что сторож ДЕЛАЕТ, когда его входа-пути в дереве нет (ПРОГОНОМ, без правки исходника)",
        "order": "G46 п. 1 (хвост ADR-421)",
        "tree_sha": head,
        "tree": str(root),
        "population": len(population(rows)),
        "probed": len(entries),
        "counts": counts,
        "own_test_counts": own_counts,
        "own_skipped_by_verdict": own_skipped_by_verdict,
        "refusal_credited_to_neighbour": [
            {"key": e.get("key"), "guard": e.get("guard"),
             "line": e.get("line"), "scope": e.get("scope"),
             "verdict": e.get("verdict")} for e in neighbour_credited],
        "findings": counts[VERDICT_VACUOUS],
        "static_compared": len(compared),
        "static_disagrees": len(disagree),
        "static_by_kind": by_kind,
        "path_recreated_by_run": len(recreated),
        "stale_disposable_trees": stale,
        "entries": entries,
        "what_it_does_not_prove": [
            "что `refuses_absent` означает исправного сторожа — он означает лишь, что краснота придёт; верность самого правила сторожа зонд не проверяет",
            "что `vacuous_pass` есть ошибка автора: приём может быть осознанным, но инв. #17 требует ОТДЕЛЬНОГО значения исхода, а не проза в докстроке",
            "что `scene_destroyed` говорит о стороже хоть что-нибудь — он говорит об уносе: сломан сбор тестов, и вердикта о слепоте нет",
            "что строка, до которой зонд не дошёл, исправна — `unmeasured` есть третий исход и строку на учёт ВОЗВРАЩАЕТ",
            "что совпадение статики с прогоном делает статику верной вообще: замерено совпадение на ЭТОМ населении и в ЭТОМ дереве",
            "что унос одного пути равен его отсутствию в чужом дереве: соседние пути на месте, и сторож, читающий два входа, увидит здесь только один пробел",
        "что строка с пропущенным собственным тестом и вердиктом `refuses_absent`/`announces_absence` неисправна: наблюдение состоялось, но произвёл его сосед по файлу — о САМОЙ строке в этом дереве не сказано ничего",
        "что `own_test` есть свойство строки вообще: это свойство ЭТОГО дерева; в дереве, где условие `skipif` ложно, ответ будет другим",
            "что `path_recreated_by_run` безвреден: созданный прогоном путь прибор убирает в СВОЁМ одноразовом дереве, а что этот сторож делает в живом дереве — вопрос не к зонду",
        ],
    }


def report(doc: dict, *, max_rows: int = 25) -> List[str]:
    status = str(doc.get("status"))
    if status == "UNMEASURED":
        return [f"НЕ ИЗМЕРЕНО — {observed(doc, 'reason', kind=str) or 'причина не записана'}"]
    counts = observed(doc, "counts", kind=dict) or {}
    out = [
        f"поведенческий зонд отсутствующего входа (заказ G46 п. 1): {status} · "
        f"население {doc.get('population')} · зондировано {doc.get('probed')} · "
        f"НАХОДОК {doc.get('findings')}",
        f"[ИСХОДЫ] зелен и молчит {counts.get(VERDICT_VACUOUS)} · краснеет "
        f"{counts.get(VERDICT_REFUSES)} · говорит, что не смотрел "
        f"{counts.get(VERDICT_ANNOUNCES)} · СЦЕНА СЛОМАНА "
        f"{counts.get(VERDICT_SCENE)} (вердикта нет) · НЕ ИЗМЕРЕНО "
        f"{counts.get(VERDICT_UNMEASURED)}",
        f"[СТАТИКА ↔ ПРОГОН] сравнимо {doc.get('static_compared')} · "
        f"РАЗОШЛОСЬ {doc.get('static_disagrees')}"
        + ("; по роду входа " + " · ".join(
            f"{k}: {v.get('disagrees')} из {v.get('compared')}"
            for k, v in sorted((observed(doc, 'static_by_kind', kind=dict) or {}).items()))
           if doc.get("static_by_kind") else ""),
        f"[СОЗДАЛ СВОЙ ВХОД] сторожей, заведших унесённый путь заново: "
        f"{doc.get('path_recreated_by_run')}",
    ]
    own = observed(doc, "own_test_counts", kind=dict)
    if own is None:
        out.append("[СВОЙ ТЕСТ] НЕ ИЗМЕРЕНО — журнал не несёт поля "
                   "`own_test_counts`; вопрос всему населению не задавался")
    else:
        by_verdict = observed(doc, "own_skipped_by_verdict", kind=dict) or {}
        other = sum(n for v, n in by_verdict.items()
                    if v != VERDICT_ALREADY_SKIPPED)
        out.append(
            f"[СВОЙ ТЕСТ] (заказ G48 п. 2, спрошено у ВСЕГО населения) бежал "
            f"{own.get(OWN_RAN)} · ПРОПУЩЕН {own.get(OWN_SKIPPED)} · не тест "
            f"{own.get(OWN_NOT_ADDRESSABLE)} · ответ не разобран "
            f"{own.get(OWN_UNKNOWN)} · не спрашивали {own.get(OWN_NOT_ASKED)}")
        out.append(
            f"[ПРОПУЩЕН ПРИ ДРУГОМ ИСХОДЕ] {other} строк(и): "
            + (" · ".join(f"{v}: {n}" for v, n in sorted(by_verdict.items())
                          if n and v != VERDICT_ALREADY_SKIPPED)
               or "ни одной — прежнее ленивое правило совпало с замером"))
    credited = doc.get("refusal_credited_to_neighbour")
    if credited:
        out.append(
            f"[ВЕРДИКТ ПРОИЗВЁЛ СОСЕД] у {len(credited)} строк(и) собственный "
            f"тест ПРОПУЩЕН, а сторож при уносе заговорил — наблюдение есть, "
            f"но о строке оно ничего не говорит: "
            + " · ".join(f"{c.get('guard')}:{c.get('line')} ({c.get('scope')})"
                         for c in credited[:max_rows]))
    if doc.get("aborted_reason"):
        out.append(f"[ОБРЫВ] {doc.get('aborted_reason')}")
    if doc.get("stale_disposable_trees"):
        out.append(f"[ВИСЯТ] одноразовых деревьев прошлых опытов: "
                   f"{len(doc.get('stale_disposable_trees') or [])} — названы, не сняты")
    shown = [e for e in (doc.get("entries") or [])
             if e.get("verdict") in FINDING_VERDICTS or e.get("static_agrees") is False]
    for entry in shown[:max_rows]:
        mark = "РАСХОЖДЕНИЕ" if entry.get("static_agrees") is False else entry.get("verdict")
        out.append(f"[{mark}] {entry.get('guard')}:{entry.get('line')} "
                   f"({entry.get('scope')}) · статика «{entry.get('static_door')}» · "
                   f"{entry.get('evidence')}")
    if len(shown) > max_rows:
        out.append(f"… ещё {len(shown) - max_rows} строк(и) — полный перечень в журнале")
    out.append("НЕ ДОКЛАДЫВАЕТ: верность самого правила сторожа · строки, чей путь "
               "унести нельзя (корень дерева, путь со сторожем внутри) — они НЕ "
               "исправны, а не измерены")
    return out


def format_report(doc: dict, *, max_rows: int = 5) -> List[str]:
    """Короткая форма для шага 0-офис."""
    return report(doc, max_rows=max_rows)


def run(root: str | Path = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        sample: Optional[int] = DEFAULT_SAMPLE,
        limit: Optional[int] = None) -> dict:
    root = Path(root)
    target = Path(dest) if dest is not None else root / ARTIFACT
    try:
        doc = measure(root, now=now, sample=sample, limit=limit)
    except NotMeasured as exc:
        doc = {
            "generated_at": (now or _utcnow()).isoformat(),
            "generated_by": PRODUCER,
            "invoked_by": call_provenance(tree_root=root),
            "status": "UNMEASURED",
            "reason": str(exc),
            "entries": [],
        }
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") not in ("UNMEASURED",),
            "doc": doc, "artifact": str(target)}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="поведенческий зонд отсутствующего входа-пути (G46 п. 1)")
    ap.add_argument("--root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--sample", type=int, default=None,
                    help="случайная выборка населения (зерно — константа модуля)")
    ap.add_argument("--limit", type=int, default=None,
                    help="взять первые N строк выборки (для контроля на малом контуре)")
    ap.add_argument("--max-rows", type=int, default=25)
    args = ap.parse_args(argv)

    outcome = run(Path(args.root), dest=Path(args.out) if args.out else None,
                  write=not args.no_write, sample=args.sample, limit=args.limit)
    doc = outcome["doc"]
    for line in report(doc, max_rows=args.max_rows):
        print(line)
    status = str(doc.get("status"))
    if status in ("UNMEASURED", "ABORTED"):
        return 2
    # Инвариант #17 у САМОГО кода возврата. Прежняя редакция читала
    # `(doc.get("counts") or {}).get(...)`: журнал без поля `counts` давал
    # пусто, пусто давало ложь, ложь давала код 0 — то есть «поля нет» и
    # «находок ноль» выходили ОДНИМ И ТЕМ ЖЕ успехом, а зовущему различить их
    # было нечем. Три исхода обязаны быть различимы, и код возврата — ровно то
    # место, где различие читает вызывающий скрипт. Поймано храповиком
    # `test_absent_observation_ratchet` при доставке (цикл #642); соседние
    # приборы того же класса НЕ тронуты — они красны и на чистом `origin/main`,
    # чинить их прицепом запрещает инв. #16, класс назван карточкой.
    counts = observed(doc, "counts", kind=dict)
    findings = observed_number(doc, "findings")
    if counts is None or findings is None:
        missing = " и ".join(
            n for n, v in (("counts", counts), ("findings", findings)) if v is None)
        print(f"НЕ ИЗМЕРЕНО — в журнале зонда нет пол(я/ей) `{missing}`: "
              f"отсутствие наблюдения кодом 0 не выдаётся")
        return 2
    return 1 if findings or counts.get(VERDICT_UNMEASURED) else 0


if __name__ == "__main__":
    raise SystemExit(main())
