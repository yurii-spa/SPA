"""Сторож: прогон тестов НЕ переписывает живое git-tracked состояние в `data/`.

## Зачем он есть

Три независимых замера одного класса существуют, и **ни один не сходится с
другими**: закрытая карточка `#225/#226` говорит «три файла», замер облачной
сессии 20.08 — «сорок», собственный счёт `main` (`4a98fd7`) — «восемьдесят три».
Мерили в разных деревьях, на разных sha и разными инструментами, поэтому ни один
из трёх не опровергает остальные.

Общее у всех трёх ровно одно и оно же главное: **писателя не мерил никто.**
Какой тест какой файл трогает — было неизвестно, поэтому любое из трёх чисел
оставалось свойством прогона, а не системы. Этот модуль и есть недостающий
замер: он называет ФАЙЛЫ, которые прогон переписал, а по требованию — и ТЕСТ,
который каждый из них переписал.

## Почему существующая изоляция это не ловит

`tests/conftest.py::_isolate_data_dir` подменяет `SPA_DATA_DIR` на tmp-каталог
на каждый тест. Это закрывает всех, кто резолвит каталог данных через эту
переменную, и не закрывает никого, кто считает путь от своего `__file__`, — ровно
та же дыра, ради которой написан `push_state_guard`. Analytics-писатели журналов
во второй группе. Там же и `data/live_execution_log.json` — файл домена
ИСПОЛНЕНИЯ, которого read-only тест не имеет права касаться вовсе (инвариант #6,
`.claude/rules/deployment.md`).

## Чем он отличается от соседа `_package_data_guard`

Тот сторож смотрит на `spa_core/data/` и ловит ПОЯВЛЕНИЕ файла (сравнивает
имена). Этот смотрит на живое состояние и ловит ИЗМЕНЕНИЕ — а именно оно и
описано в карточке: `alert_log.json` не появляется, у него переписывается
`updated_at` и дописываются тестовые тревоги. Сравнение имён такую правку не
видит по построению.

## Почему сторож ПРОГОНА, а не каждого теста — цена измерена

Первая версия снимала состояние вокруг КАЖДОГО теста: так виновник называется
сразу. Замер: один снимок 428 путей — **3.9 мс**, два на тест, 96 492 теста ⇒
**+12,7 минуты** к прогону, который целиком идёт 13,3 минуты. Сторож, удваивающий
CI, будет отключён при первом же неудобном дне — это тот самый «крик волком»,
за который проект уже платил.

Поэтому по умолчанию снимков ДВА на весь прогон (начало и конец сессии, ~8 мс):
падает не тест, а прогон, и в отчёте названы файлы. Приёмка карточки
сформулирована ровно на этой высоте — «после прогона `git status --porcelain --
data/` обязан быть ПУСТ», — и сторож стоит на ней же.

Имя ВИНОВНИКА достаётся отдельным заходом: `SPA_DATA_WRITE_AUDIT=1` включает
снимок вокруг каждого теста и пишет `{nodeid, paths}` в JSONL. Это дороже, зато
даёт карту «файл → тест» целиком за один прогон. Режим НИЧЕГО не гасит: прогон
падает в обоих режимах, замер только ДОБАВЛЯЕТ атрибуцию.

## Что под наблюдением: git-tracked, но по mtime, а не по содержимому

Наблюдаются только пути, которые ЗНАЕТ git (`tracked_paths`): runtime-осадок есть
на машине автора и отсутствует на свежем чекауте CI, и сторож с такой базой краснел
бы у соседа на ровном месте.

А вот сравнение — по mtime, а не по содержимому, и это ловит то, чего приёмка
карточки увидеть НЕ МОЖЕТ. Замер: полный прогон переписывает `data/golive_status.json`
— git-tracked артефакт гейта go-live — тем же самым содержимым. `git status` про него
молчит навсегда, mtime говорит сразу. Тест, который довёл прод-код до записи в артефакт
гейта, опасен независимо от того, совпало ли содержимое в этот раз.

## Почему храповик, а не запрет

Прямой запрет покрасил бы прогон на 76 путях в первый же день — и был бы снят
раньше, чем починен хоть один писатель. Поэтому у сторожа есть КОММИТНУТАЯ база
(`live_data_write_baseline.json`): пути, которые прогон пишет сегодня. Новый путь
= красный прогон немедленно; база может ТОЛЬКО уменьшаться
(`test_live_data_write_ratchet.py`). Дописать путь в базу, чтобы погасить
падение, — запрещено: чинить писателя. Ровно тот же приём и та же причина, что у
`test_frozen_date_ratchet` (346 файлов в классе, запрет в лоб научил бы всех его
отключать).

Нечитаемая база читается как ПУСТАЯ: сломанный файл делает сторожа строже, а не
слепее.

Сторож НАЗЫВАЕТ и НЕ убирает улику: откатить файл значило бы починить отчёт
вместо дефекта — и заодно стереть чужую настоящую правку, если она там была.

## Почему карта «файл → тест» умеет говорить «НЕ ИЗМЕРЕНО»

Замер цикла #353 на одном и том же Маке, в одном и том же дереве `/tmp/spa_c353`,
с единственной разницей — шёл ли рядом второй прогон:

| условие | записей атрибуции |
|---|---|
| в дереве параллельно идёт полный прогон CI | **19** — почти каждый тест файла |
| прогон в дереве ОДИН | **0** (отчёта не создаётся вовсе) |

Среди 19 «писателей» были тесты, которые не могут писать ничего: арифметика над
списком чисел с приписанным `reward_harvesting_log.json`; проверка того, что 3 и
4 не делят 10, с приписанным `yield_farming_roi_log.json`. Механизм называния
автора — разница двух снимков вокруг теста, и в этой разнице нет ни pid, ни
владельца записи: **только совпадение во времени.** Любой параллельный писатель
в том же дереве — второй pytest, агент флота, ручной прогон — красит СЛУЧАЙНЫЙ
тест, и на разных прогонах разный.

Цена — в назначении инструмента. Сторож уровня ПРОГОНА («после набора эти файлы
изменены») верен при любом числе писателей: он ничего не утверждает об авторстве.
А карта авторства утверждает, и по ней уже ведут починку. Ложная карта хуже
отсутствующей: отсутствующая заставляет мерить, ложная — верить.

Поэтому атрибуция теперь **обязана доказать, что писать было некому, кроме
теста**, и у неё есть третий исход. Два независимых признака чужого писателя:

1. **Объявление прогона.** Каждый прогон со сторожем кладёт в общий каталог
   (`/tmp/spa_data_write_audit_runs/<ключ дерева>`) файл-объявление со своим pid и
   отметкой старта процесса. Живое объявление ДРУГОГО прогона в том же дереве ⇒
   назвать автора нельзя. Объявляются ВСЕ прогоны, а не только замеряющие: в
   измеренной аварии соседом был обычный полный прогон CI, и он про режим замера
   ничего не знал.
2. **Окно МЕЖДУ тестами.** Снимок после теста N сравнивается со снимком перед
   тестом N+1. Изменение в этом окне доказывает писателя, которого не объявлял
   никто — на прод-хосте это флот из полусотни агентов, пишущих в `data/`
   непрерывно. Этот признак ловит то, чего объявления не поймают ПО ПОСТРОЕНИЮ.

Найден чужой писатель — отчёт получает строку `attribution: "НЕ ИЗМЕРЕНА"` с
причиной и путями и **не называет ни одного nodeid** до конца прогона. Признак
липкий намеренно: писатель, замеченный однажды, может писать в любой момент, а
карта, честная в половине строк, читается как честная во всех.

**Сторож уровня прогона при этом НЕ ослабляется** (инвариант #16): «эти файлы
изменены» остаётся верным при любом числе писателей, прогон краснеет так же.
Меняется ровно одно — право назвать автора.

Мерить атрибуцию нужно там, где кроме прогона никто не пишет: изолированный
worktree, флот в него не смотрит. Это не обходной путь, а условие, при котором
измерение вообще имеет смысл.

Только stdlib. Импорт без побочных эффектов; хуки сессии и фикстура
регистрируются из ОБОИХ корней conftest одним и тем же модулем (`sys.modules`),
как три сторожа-соседа, иначе у двух корней было бы две независимые базы
прогона — и вторая затёрла бы первую вместе с уликой.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

#: Корень репозитория — этот файл лежит в `<root>/spa_core/tests/`.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Каталоги с живым состоянием. `data/` — трек и журналы тревог;
#: `spa_core/data/` — git-tracked фикстуры пакета (сосед `_package_data_guard`
#: ловит там ПОЯВЛЕНИЕ файла, но не правку существующего, а замер `main`
#: насчитал два таких пути); `spa_core/database/` — sqlite, который оба замера
#: нашли грязным и ни один не считал частью `data/`.
WATCHED = (
    REPO_ROOT / "data",
    REPO_ROOT / "spa_core" / "data",
    REPO_ROOT / "spa_core" / "database",
)

#: Переключатель режима замера и адрес его отчёта.
AUDIT_ENV = "SPA_DATA_WRITE_AUDIT"
AUDIT_OUT_ENV = "SPA_DATA_WRITE_AUDIT_OUT"
#: Отчёт по умолчанию лежит ВНЕ репозитория намеренно: отчёт, записанный в
#: дерево, сам пачкает то, что измеряет.
DEFAULT_AUDIT_OUT = Path("/tmp/spa_data_write_audit.jsonl")

#: Каталог объявлений прогонов, идущих в ЭТОМ дереве. Ключ — само дерево:
#: два worktree на одной машине пишут в разные каталоги данных и соседями друг
#: другу не являются. Лежит в `/tmp` по той же причине, что и отчёт, и ровно
#: там же, где его увидит соседний прогон: `tempfile.gettempdir()` на macOS
#: приватен для пользователя и для сессии, а сосед может идти из-под другой.
DEFAULT_RUNS_ROOT = Path("/tmp/spa_data_write_audit_runs")
RUNS_DIR_ENV = "SPA_DATA_WRITE_AUDIT_RUNS_DIR"

#: Слово третьего исхода. «Не измерено» — не «никто»: сторож обязан отличать
#: «писателя нет» от «назвать писателя нечем».
UNMEASURED = "НЕ ИЗМЕРЕНА"

#: Список путей, которые прогон пишет СЕГОДНЯ. Храповик: он может только
#: уменьшаться (`test_live_data_write_ratchet.py`). Почему список вообще есть —
#: в докстринге раздела «Почему храповик, а не запрет».
BASELINE_PATH = Path(__file__).resolve().parent / "live_data_write_baseline.json"

#: База прогона, набор git-tracked путей и отметка «уже отчитались» — один
#: экземпляр на сессию, потому что модуль общий для обоих корней conftest.
_session_before = None
_tracked = None
_reported = False

#: Атрибуция: причина, по которой называть автора больше нельзя (или None),
#: снимок после предыдущего теста, собственное объявление и кэш вердиктов о
#: живости чужих объявлений. Один экземпляр на сессию — по той же причине, что
#: и база прогона: модуль общий для обоих корней conftest.
_attribution_blocked = None
_last_after = None
_announced = None
_liveness_cache = {}


def tracked_paths(roots=WATCHED):
    """Пути под наблюдением, которые ЗНАЕТ git. Считается один раз за прогон.

    Почему именно git-tracked, а не всё подряд. Замер приёмки цикла #352: полный
    прогон трогает ещё 16 путей, которых git не видит вовсе (`audit_chain.jsonl`,
    `consumption_receipts.jsonl`, `bee/verify_summary.json` …) — это runtime-осадок,
    он есть на Маке и его нет на свежем чекауте CI. Сторож, чья база зависит от
    того, что валялось в каталоге у автора, краснел бы у соседа на ровном месте.
    Git-tracked набор ОДИН И ТОТ ЖЕ везде, и именно про него говорит приёмка
    карточки («`git status --porcelain -- data/` пуст»). Untracked-осадок — предмет
    соседней карточки и соседнего сторожа (`_package_data_guard`).

    Если git недоступен, возвращается None и наблюдение идёт по ВСЕМУ каталогу:
    ошибаться сторож обязан в сторону строгости.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--"] + [str(r) for r in roots],
            cwd=str(REPO_ROOT), capture_output=True, timeout=30, check=True,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    names = frozenset(n for n in out.split("\0") if n)
    return names or None


def load_baseline(path=None):
    """Разрешённые (пока) пути. Нечитаемая база = ПУСТАЯ: сторож строже, а не слепее."""
    try:
        raw = json.loads(Path(path or BASELINE_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    paths = raw.get("paths", []) if isinstance(raw, dict) else raw
    return frozenset(p for p in paths if isinstance(p, str))


def audit_enabled():
    """Режим замера включён? (`SPA_DATA_WRITE_AUDIT=1`)"""
    return os.environ.get(AUDIT_ENV) == "1"


def audit_out_path():
    raw = os.environ.get(AUDIT_OUT_ENV)
    return Path(raw) if raw else DEFAULT_AUDIT_OUT


# ---------------------------------------------------------------------------
# Объявление прогонов: кто ещё пишет в это дерево прямо сейчас
# ---------------------------------------------------------------------------

def runs_dir():
    """Каталог объявлений для ЭТОГО дерева (переопределяется env — ради тестов)."""
    raw = os.environ.get(RUNS_DIR_ENV)
    if raw:
        return Path(raw)
    key = hashlib.sha1(str(REPO_ROOT).encode("utf-8")).hexdigest()[:16]
    return DEFAULT_RUNS_ROOT / key


def pid_start(pid):
    """Отметка старта процесса — защита от ПЕРЕИСПОЛЬЗОВАННОГО номера.

    Голый pid — бомба замедленного действия: ОС выдаёт номер заново, и мёртвое
    объявление начинает читаться как живой сосед (тот же приём, что у шага 0a
    протокола: `session_pid` + `session_pid_start`). `None` означает «измерить
    не удалось», а не «процесса нет».
    """
    try:
        out = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(int(pid))],
            capture_output=True, timeout=10,
        ).stdout.decode("utf-8", "replace").strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out or None


def _is_alive(pid, recorded_start):
    """Жив ли объявивший. Не измерили ⇒ считаем живым: ошибаться в сторону строгости.

    Строгость здесь стоит дёшево (в отчёте появится «не измерено»), а ошибка в
    другую сторону — это ровно та ложная карта, ради которой всё написано.
    """
    now_start = pid_start(pid)
    if now_start is None:
        # Процесса нет ЛИБО `ps` недоступен — эти два случая отсюда неотличимы,
        # и «нечем измерить» не даёт права назвать автора.
        return not _ps_usable()
    if recorded_start and now_start != recorded_start:
        return False          # номер переиспользован: это другой процесс
    return True


def _ps_usable():
    """Отвечает ли `ps` вообще — иначе «процесса нет» неотличимо от «нет ps»."""
    return pid_start(os.getpid()) is not None


#: Через сколько часов объявление считается брошенным. Полный прогон занимает
#: полтора часа в худшем случае, так что сутки — с большим запасом.
STALE_ANNOUNCEMENT_HOURS = 24


def purge_stale_announcements(directory=None, now=None, max_age_hours=STALE_ANNOUNCEMENT_HOURS):
    """Убрать объявления, брошенные больше суток назад. Только `stat`, без `ps`.

    Прогон, снятый `SIGKILL`, своё объявление не снимает, а разбирает объявления
    только режим замера — то есть редко. Без этой уборки каталог рос бы вечно.
    Возраст меряется по отметке в самом объявлении (`started_at`), а при её
    отсутствии — по mtime файла: «не смогли прочитать» не должно означать
    «удалить», но и вечно копить нечитаемое незачем.
    """
    directory = Path(directory) if directory else runs_dir()
    now = time.time() if now is None else now
    cutoff = now - max_age_hours * 3600
    removed = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return ()
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        started = None
        try:
            started = json.loads(Path(entry.path).read_text(encoding="utf-8")).get("started_at")
        except (OSError, ValueError):
            started = None
        if started is None:
            try:
                started = entry.stat().st_mtime
            except OSError:
                continue
        if started < cutoff:
            try:
                Path(entry.path).unlink()
                removed.append(entry.name)
            except OSError:
                pass
    return tuple(sorted(removed))


def announce_run(pid=None, directory=None):
    """Положить объявление «в этом дереве идёт прогон» и вернуть его путь.

    Объявляются ВСЕ прогоны со сторожем, а не только замеряющие: в измеренной
    аварии (#353) соседом был обычный полный прогон CI — он про режим замера не
    знал ничего, но карту испортил целиком.
    """
    pid = os.getpid() if pid is None else pid
    directory = Path(directory) if directory else runs_dir()
    payload = {"pid": pid, "pid_start": pid_start(pid),
               "repo_root": str(REPO_ROOT), "started_at": time.time()}
    try:
        directory.mkdir(parents=True, exist_ok=True)
        marker = directory / f"{pid}.json"
        marker.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        return None           # объявиться не смогли — это не повод ронять прогон
    purge_stale_announcements(directory)
    return marker


def release_run(pid=None, directory=None):
    """Снять СВОЁ объявление. Не снятое подберёт следующий скан по живости."""
    pid = os.getpid() if pid is None else pid
    directory = Path(directory) if directory else runs_dir()
    try:
        (directory / f"{pid}.json").unlink()
    except OSError:
        pass
    return True


def foreign_runs(pid=None, directory=None):
    """Живые объявления ДРУГИХ прогонов в этом дереве (кортеж pid-ов).

    Мёртвое объявление убирается на месте — иначе один упавший прогон навсегда
    объявил бы атрибуцию неизмеримой. Нечитаемое объявление считается ЖИВЫМ
    чужим: файл могли читать посреди записи, и «я не понял» не равно «никого».
    """
    pid = os.getpid() if pid is None else pid
    directory = Path(directory) if directory else runs_dir()
    found = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return ()
    for entry in entries:
        if not entry.name.endswith(".json"):
            continue
        try:
            other = int(entry.name[: -len(".json")])
        except ValueError:
            found.append(entry.name)      # имя не разбирается — строгость
            continue
        if other == pid:
            continue
        cached = _liveness_cache.get(other)
        if cached is None:
            try:
                payload = json.loads(Path(entry.path).read_text(encoding="utf-8"))
                recorded = payload.get("pid_start")
            except (OSError, ValueError):
                found.append(other)       # нечитаемо — строгость, без кэша
                continue
            cached = _is_alive(other, recorded)
            if cached:
                _liveness_cache[other] = True   # живых кэшируем: `ps` дорог
        if cached:
            found.append(other)
        else:
            try:
                Path(entry.path).unlink()
            except OSError:
                pass
    return tuple(found)


# ---------------------------------------------------------------------------
# Третий исход атрибуции
# ---------------------------------------------------------------------------

#: Что делать с «не измерено» — говорится в самом отчёте, а не только в докстринге.
ADVICE = ("Мерить карту авторства нужно в дереве, где кроме прогона никто не "
          "пишет: изолированный worktree, флот в него не смотрит.")


def foreign_run_reason(count):
    """Текст причины для случая «рядом идёт чужой прогон»."""
    return (f"атрибуция {UNMEASURED}: в дереве идёт ещё {count} прогон(а) — "
            "писать мог любой из них, а разница снимков автора не знает. "
            + ADVICE)


def between_tests_reason(paths):
    """Текст причины для случая «писали в окне МЕЖДУ тестами»."""
    return (f"атрибуция {UNMEASURED}: живое состояние изменилось в окне МЕЖДУ "
            f"тестами ({', '.join(paths)}) — писал не тест, а кто-то извне "
            "прогона (агент флота, ручной запуск, второй прогон). " + ADVICE)


def block_attribution(reason):
    """Запретить называние автора до конца прогона и записать это в отчёт.

    Липко намеренно: писатель, замеченный однажды, может писать в любой момент,
    а карта, честная в половине строк, читается как честная во всех.
    """
    global _attribution_blocked
    if _attribution_blocked is None:
        _attribution_blocked = reason
        record_unmeasured(reason)
    return _attribution_blocked


def attribution_blocked():
    """Причина, по которой автор не называется (или None)."""
    return _attribution_blocked


def record_unmeasured(reason, paths=(), out_path=None):
    """Дописать в отчёт строку третьего исхода. `nodeid` — `None`, а не выдумка."""
    line = json.dumps({"nodeid": None, "attribution": UNMEASURED,
                       "reason": reason, "paths": list(paths)}, ensure_ascii=False)
    return _append(line, out_path)


def check_neighbours():
    """Есть ли рядом чужой объявленный прогон — и если да, запретить атрибуцию."""
    if _attribution_blocked is not None:
        return _attribution_blocked            # липко: больше не спрашиваем
    others = foreign_runs()
    if others:
        return block_attribution(foreign_run_reason(len(others)))
    return None


def check_between_tests(before):
    """Сравнить снимок ПЕРЕД тестом со снимком ПОСЛЕ предыдущего.

    Изменение в этом окне доказывает писателя вне прогона: ни один наш тест в
    это время не шёл. Признак ловит того, кого объявления не поймают по
    построению, — флот агентов на прод-хосте.
    """
    if _attribution_blocked is not None or _last_after is None:
        return _attribution_blocked
    gap = changed(_last_after, before)
    if gap:
        return block_attribution(between_tests_reason(gap))
    return None


def _iter_files(root):
    """Все обычные файлы под *root*, `__pycache__` не в счёт.

    `.pyc`, рождённый импортом модуля пакета, — артефакт сборки, а не состояние;
    считать его значило бы краснеть на первом же импорте прогона.
    """
    stack = [Path(root)]
    while stack:
        cur = stack.pop()
        try:
            entries = list(os.scandir(cur))
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for e in entries:
            if e.is_dir(follow_symlinks=False):
                if e.name != "__pycache__":
                    stack.append(Path(e.path))
            elif e.is_file(follow_symlinks=False):
                yield Path(e.path)


def snapshot(roots=WATCHED):
    """`{путь относительно корня: (mtime_ns, размер)}` по всем наблюдаемым файлам.

    Правка на месте той же длины ловится по mtime (`atomic_save` всегда делает
    `os.replace`), удаление — по исчезновению ключа. Хеш содержимого был бы
    строже, но стоил бы ~400 чтений файлов на каждый тест, а авария, ради которой
    сторож написан (проставленный `updated_at`), mtime двигает всегда.
    """
    out = {}
    for root in roots:
        for p in _iter_files(root):
            try:
                st = p.stat()
            except OSError:
                continue
            try:
                rel = str(p.relative_to(REPO_ROOT))
            except ValueError:  # pragma: no cover — WATCHED всегда внутри корня
                rel = str(p)
            out[rel] = (st.st_mtime_ns, st.st_size)
    return out


def changed(before, after):
    """Отсортированные пути, которые появились, исчезли или изменились."""
    seen = {rel for rel, sig in after.items() if before.get(rel) != sig}
    seen.update(rel for rel in before if rel not in after)
    return tuple(sorted(seen))


def failure_message(test_id, paths):
    """Текст отказа: кто, что и почему это не косметика.

    *test_id* — nodeid теста, если он известен (режим замера), иначе слово
    «прогон»: сторож не имеет права называть виновником того, кого не измерил.
    """
    listed = ", ".join(paths)
    return (
        f"{test_id} изменил живое состояние: {listed}.\n"
        "Это git-tracked файлы прода: трек, журналы тревог и журнал исполнения. "
        "Прогон, который их переписывает, (а) подсовывает свежесть, которой в "
        "системе нет — самообновляющаяся фикстура протухнуть не может, и любой "
        "сторож свежести после прогона видит «всё свежее»; (б) делает «чистое "
        "дерево» бессмысленным сигналом перед пушем, и подмену трека можно "
        "закоммитить вместе со своей работой.\n"
        "Починка: подменить каталог/путь состояния на tmp в фикстуре этого "
        "тест-файла (образцы — spa_core/tests/test_protocol_maturity_scorer.py и "
        "соседи), а время передавать входом (`now=`), как велит "
        ".claude/rules/deployment.md.\n"
        "Пометка `live_data` СЮДА НЕ ПОДХОДИТ: она про тесты, которые живое "
        "состояние ЧИТАЮТ (`tests/conftest.py`), и права записывать не даёт "
        "никому — сторож её намеренно не признаёт.\n"
        f"ЧЕЙ ЭТО ТЕСТ — переспросить прогоном с `{AUDIT_ENV}=1`: он пишет "
        f"`{{nodeid, paths}}` в {DEFAULT_AUDIT_OUT} (адрес меняется "
        f"`{AUDIT_OUT_ENV}`). Спрашивать в дереве, где кроме прогона никто не "
        "пишет: увидев чужого писателя, замер честно ответит "
        f"`{UNMEASURED}` вместо имени.\n"
        "Карточка: inbox-progon-testov-perepisyvaet-sorok-otslezhivaemyh-failov-data."
    )


def session_finish(session):
    """Отчитаться за ВЕСЬ прогон и уронить его, если живое состояние поехало.

    Идемпотентна: хук стоит в обоих корнях conftest, и оба его позовут.
    """
    global _reported
    release_self()
    if _reported or _session_before is None:
        return ()
    _reported = True
    if audit_enabled() and _attribution_blocked is not None:
        # Отчёт читают глазами: третий исход обязан быть слышен там же, где
        # называется файл, а не только строкой в JSONL.
        print("\n" + _attribution_blocked, file=sys.stderr)
    allowed = load_baseline()
    touched = tuple(p for p in changed(_session_before, watched_snapshot()) if p not in allowed)
    if not touched:
        return ()
    print("\n" + failure_message("прогон", touched), file=sys.stderr)
    if getattr(session, "exitstatus", 0) == 0:
        session.exitstatus = 1
    return touched


def watched_snapshot():
    """Снимок, суженный до git-tracked путей (или полный, если git недоступен)."""
    snap = snapshot()
    if _tracked is None:
        return snap
    return {rel: sig for rel, sig in snap.items() if rel in _tracked}


def session_start():
    """Снять базу прогона. Идемпотентна по той же причине, что и `session_finish`."""
    global _session_before, _reported, _tracked
    if _session_before is None:
        _tracked = tracked_paths()
        _session_before = watched_snapshot()
        _reported = False
    # Объявление живёт ЗДЕСЬ, а не в хуке модуля: оба корня conftest зовут эту
    # функцию напрямую, и объявиться обязан КАЖДЫЙ прогон — соседом в измеренной
    # аварии был обычный полный прогон, ничего не знавший о режиме замера.
    announce_self()
    return _session_before


def announce_self():
    """Объявиться соседям. Идемпотентна: хук стоит в обоих корнях conftest."""
    global _announced
    if _announced is None:
        _announced = announce_run()
    return _announced


def release_self():
    """Снять своё объявление в конце прогона."""
    global _announced
    if _announced is not None:
        release_run()
        _announced = None
    return None


def _append(line, out_path=None):
    """Дописать строку в JSONL-отчёт. Ошибку записи не поднимает."""
    try:
        out = Path(out_path) if out_path else audit_out_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # замер диагностический; ронять тест из-за его отчёта нельзя
    return line


def record(nodeid, paths, out_path=None):
    """Назвать автора. Зовётся ТОЛЬКО когда доказано, что писать было некому.

    Проверку «а некому ли» делают `check_neighbours` и `check_between_tests`;
    сама запись остаётся глупой — иначе честность зависела бы от того, кто её
    позвал.
    """
    line = json.dumps({"nodeid": nodeid, "paths": list(paths)}, ensure_ascii=False)
    return _append(line, out_path)


@pytest.fixture(autouse=True)
def _live_data_stays_clean(request):
    """Атрибуция: чей это тест. Работает ТОЛЬКО в режиме замера.

    Вне режима замера фикстура не делает НИЧЕГО — ни одного снимка, — и её цена
    равна нулю: сама проверка живёт на уровне прогона (`session_finish`), где
    стоит 8 мс вместо 12,7 минуты.

    Пометки `live_data` здесь нет намеренно. Она означает «этот тест ЧИТАЕТ
    настоящий `data/`» и снимает изоляцию каталога ради чтения; права ПИСАТЬ в
    живое состояние она не даёт, поэтому помеченный писатель называется наравне
    со всеми.
    """
    global _last_after
    if not audit_enabled():
        yield
        return
    before = watched_snapshot()
    # Два независимых признака чужого писателя, оба ДО теста: изменение в окне
    # между тестами (его не объявлял никто) и живое объявление соседа.
    check_between_tests(before)
    check_neighbours()
    yield
    after = watched_snapshot()
    _last_after = after
    # Сосед мог стартовать ПОКА тест шёл — спросить ещё раз, до называния.
    check_neighbours()
    touched = changed(before, after)
    if touched:
        if _attribution_blocked is not None:
            record_unmeasured(_attribution_blocked, touched)
        else:
            record(request.node.nodeid, touched)


# ---------------------------------------------------------------------------
# Хуки сессии. Живут ЗДЕСЬ, а не только в conftest, потому что положительный
# контроль подключает этот модуль плагином (`-p live_data_write_guard`) — тогда
# проверяется тот же код, который работает в настоящем прогоне, а не его копия.
# Оба conftest зовут те же функции; повторный вызов безвреден (`_reported`).
# ---------------------------------------------------------------------------
def pytest_sessionstart(session):                # noqa: D401 — хук pytest
    """База прогона — до первого теста."""
    session_start()


def pytest_sessionfinish(session, exitstatus):   # noqa: D401 — хук pytest
    """Отчёт за прогон; красит его, если живое состояние поехало."""
    session_finish(session)
