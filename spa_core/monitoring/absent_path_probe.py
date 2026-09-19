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

#: Состояния СОБСТВЕННОГО теста строки в целом дереве (вопрос задаётся только
#: когда исход опыта — `vacuous_pass`, потому что маскироваться пропуск может
#: лишь под него: у всех прочих исходов тест заведомо бежал).
OWN_RAN = "ran"
OWN_SKIPPED = "skipped"
OWN_NOT_ADDRESSABLE = "not_addressable"
OWN_UNKNOWN = "unknown"

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
    entry = _verdict(entry, code, out, base_passed)
    if entry.get("verdict") == VERDICT_VACUOUS:
        # Путь к этому моменту УЖЕ возвращён (блок `finally` выше), поэтому
        # вопрос задаётся о ЦЕЛОМ дереве — что и значит «пропущен здесь».
        state = own_test_state(tree, guard_rel, str(row.get("scope") or ""))
        entry["own_test"] = state
        if state == OWN_SKIPPED:
            entry["verdict"] = VERDICT_ALREADY_SKIPPED
            entry["evidence"] = (
                f"собственный тест строки `{row.get('scope')}` ПРОПУЩЕН в этом "
                f"дереве ещё до опыта — сторож молчал не от слепоты, а потому "
                f"что его не звали; счёт passed у пропущенного теста не "
                f"меняется ни до уноса, ни после")
    return entry


def own_test_state(tree: Path, guard_rel: str, scope: str) -> str:
    """Бежит ли в ЭТОМ дереве собственный тест строки — или он пропущен.

    Вопрос отдельный от прогона сторожа, и он ОБЯЗАН быть отдельным: прогон
    считает `passed` по ВСЕМУ файлу, а пропущенный `skipif`-ом тест не
    прибавляет к этому счёту ни до уноса пути, ни после. Два разных состояния
    («осмотрел ноль и промолчал» и «не звали вовсе») давали один и тот же
    признак, и различить их файловым счётом нельзя в принципе.

    ``scope`` у строки — имя объемлющей функции, и тестом оно бывает не
    всегда (помощник, метод класса). Неадресуемый ``scope`` — третий исход
    (`not_addressable`), а не «бежал»: выдуманное «бежал» вернуло бы ровно ту
    слепоту, ради которой вопрос и задан.
    """
    if not scope:
        return OWN_NOT_ADDRESSABLE
    code, out = base._run(
        [sys.executable, "-m", "pytest", f"{guard_rel}::{scope}",
         "-q", "--tb=no", "-p", "no:randomly"],
        cwd=tree, timeout=RUN_TIMEOUT_S)
    # Коды pytest на селектор `файл::имя`: 5 — собрано ноль, 4 — «не найдено»
    # (ЗАМЕР: `(no match in any of [<Module t.py>])`, код 4). Оба отвечают на
    # НАШ вопрос — имя тестом в этом файле не является; звать это «не
    # измерено» значило бы прятать ответ. Свою ошибку употребления флагов этот
    # разбор не замаскирует: она была бы у КАЖДОЙ строки, включая ту, где тест
    # заведомо есть, и обратная проверка контроля на неё краснеет.
    if code in (4, 5):
        return OWN_NOT_ADDRESSABLE
    if code < 0 or code in vgp._NO_VERDICT_CODES:
        return OWN_UNKNOWN
    passed = vgp.summary_count(out, "passed")
    skipped = vgp.summary_count(out, "skipped")
    if passed is None or skipped is None:
        return OWN_UNKNOWN   # сводка не разобрана — молчать честнее, чем гадать
    if passed:
        return OWN_RAN
    return OWN_SKIPPED if skipped else OWN_NOT_ADDRESSABLE


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
        for row in chosen:
            if base._dirty(root, str(row.get("guard") or "")):
                entries.append({
                    "key": row.get("key"), "guard": row.get("guard"),
                    "path": row.get("path"), "static_door": row.get("door"),
                    "verdict": VERDICT_UNMEASURED,
                    "evidence": ("сторож изменён в рабочем дереве — одноразовое "
                                 "дерево несёт HEAD, то есть НЕ его")})
                continue
            try:
                entries.append(probe_row(tmp, row, baselines=baselines))
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
